from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import requests
from sqlalchemy.orm import Session

from backend.app.services.model_selector_service import is_quota_error
from backend.app.services.wechat_mp_model_service import WechatMpModelContext, resolve_wechat_mp_shotlist_model

if TYPE_CHECKING:
    from backend.app.models.wechat_mp import WechatMpIllustrationCharacter
    from backend.app.services.wechat_mp_content_analysis_service import VisualCandidate


MAX_SEMANTIC_PROMPTS = 6
_SYSTEM_PROMPT = (
    "Return strict JSON only. The complete response must be {\"items\":[...]}. "
    "Each item must contain exactly an input candidate id and one concise Chinese image prompt: "
    "{\"id\":\"...\",\"prompt\":\"...\"}. Do not use Markdown fences or add commentary."
)


@dataclass(frozen=True)
class BatchPromptItem:
    candidate_id: str
    prompt: str


@dataclass(frozen=True)
class BatchPromptResult:
    items: tuple[BatchPromptItem, ...]
    input_tokens: int
    output_tokens: int
    model_name: str | None
    model_calls: int


def _parse_token_count(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("token count must be a non-negative integer")
    return value


def _compact_candidates(candidates: tuple["VisualCandidate", ...] | list["VisualCandidate"]) -> list[dict[str, str]]:
    compact: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for candidate in candidates:
        if candidate.kind != "semantic" or len(compact) >= MAX_SEMANTIC_PROMPTS:
            continue
        candidate_id = str(candidate.source_index)
        if candidate_id in seen_ids:
            continue
        seen_ids.add(candidate_id)
        compact.append({
            "id": candidate_id,
            "heading": " / ".join(candidate.heading_path),
            "text": candidate.block.cleaned_text,
        })
    return compact


def _build_user_payload(
    *, article_title: str, candidates: list[dict[str, str]], character: "WechatMpIllustrationCharacter | None",
) -> str:
    character_summary = ""
    if character is not None:
        character_summary = character.prompt or character.name
    return json.dumps({
        "article_title": article_title,
        "character": character_summary,
        "remaining_slots": len(candidates),
        "candidates": candidates,
    }, ensure_ascii=False, separators=(",", ":"))


def _call_batch_prompt_model(
    *, model: WechatMpModelContext, user_payload: str,
) -> dict[str, Any]:
    base_url = (model.base_url or os.getenv("WECHAT_MP_PROMPT_BASE_URL", "")).rstrip("/")
    api_key = model.api_key or os.getenv("WECHAT_MP_PROMPT_API_KEY", "")
    if not base_url or not api_key:
        raise ValueError("WeChat MP prompt model is not configured")
    try:
        response = requests.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model.model_name,
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_payload},
                ],
            },
            timeout=180,
        )
        response.raise_for_status()
        payload = response.json()
        content = payload["choices"][0]["message"]["content"]
        usage = payload.get("usage") or {}
        if not isinstance(content, str) or not isinstance(usage, dict):
            raise ValueError("WeChat MP batch prompt model returned malformed output")
        return {
            "content": content,
            "input_tokens": _parse_token_count(usage.get("prompt_tokens", 0)),
            "output_tokens": _parse_token_count(usage.get("completion_tokens", 0)),
        }
    except requests.RequestException:
        raise
    except (KeyError, IndexError, TypeError, ValueError, AttributeError) as exc:
        raise ValueError("WeChat MP batch prompt model returned malformed output") from exc


def _parse_items(content: str, allowed_ids: set[str]) -> tuple[BatchPromptItem, ...]:
    try:
        payload = json.loads(content)
    except (TypeError, json.JSONDecodeError):
        return ()
    if not isinstance(payload, dict) or set(payload) != {"items"} or not isinstance(payload["items"], list):
        return ()
    items: list[BatchPromptItem] = []
    seen_ids: set[str] = set()
    for value in payload["items"]:
        if len(items) >= MAX_SEMANTIC_PROMPTS or not isinstance(value, dict) or set(value) != {"id", "prompt"}:
            continue
        candidate_id = value.get("id")
        prompt = value.get("prompt")
        if (
            not isinstance(candidate_id, str)
            or not isinstance(prompt, str)
            or not prompt.strip()
            or candidate_id not in allowed_ids
            or candidate_id in seen_ids
        ):
            continue
        seen_ids.add(candidate_id)
        items.append(BatchPromptItem(candidate_id=candidate_id, prompt=prompt.strip()))
    return tuple(items)


def _empty_result(*, model_name: str | None, model_calls: int, input_tokens: int = 0, output_tokens: int = 0) -> BatchPromptResult:
    return BatchPromptResult((), input_tokens, output_tokens, model_name, model_calls)


def generate_semantic_prompts(
    *, db: Session, user_id: int, article_title: str, candidates: tuple["VisualCandidate", ...] | list["VisualCandidate"],
    character: "WechatMpIllustrationCharacter | None",
) -> BatchPromptResult:
    """Generate all semantic prompts in one request, with one quota-only fallback."""
    compact_candidates = _compact_candidates(candidates)
    if not compact_candidates:
        return _empty_result(model_name=None, model_calls=0)
    user_payload = _build_user_payload(
        article_title=article_title, candidates=compact_candidates, character=character,
    )
    model = resolve_wechat_mp_shotlist_model(db=db, user_id=user_id)
    try:
        response = _call_batch_prompt_model(model=model, user_payload=user_payload)
    except Exception as exc:
        if not is_quota_error(exc):
            return _empty_result(model_name=model.model_name, model_calls=1)
        try:
            fallback = resolve_wechat_mp_shotlist_model(
                db=db, user_id=user_id, excluded_model_names={model.model_name},
            )
        except Exception:
            return _empty_result(model_name=model.model_name, model_calls=1)
        try:
            response = _call_batch_prompt_model(model=fallback, user_payload=user_payload)
            model = fallback
        except Exception:
            return _empty_result(model_name=model.model_name, model_calls=2)
        model_calls = 2
    else:
        model_calls = 1
    return BatchPromptResult(
        items=_parse_items(response["content"], {item["id"] for item in compact_candidates}),
        input_tokens=response["input_tokens"],
        output_tokens=response["output_tokens"],
        model_name=model.model_name,
        model_calls=model_calls,
    )
