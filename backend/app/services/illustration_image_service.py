from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from typing import Any, Optional

import requests
from sqlalchemy.orm import Session

from backend.app.core.security import decrypt_text
from backend.app.models import IllustrationAsset, ModelConfig, User
from backend.app.services.illustration_size_service import normalize_illustration_size
from backend.app.services.usage_recording_service import record_image_usage


class IllustrationImageClient:
    """Illustration-domain image generation client. Owns its own body assembly
    including the `size` field. Deliberately does NOT inherit from or import
    OpenAICompatibleImageClient — per spec §5.0 isolation, the illustration
    pipeline is a parallel system that must not depend on the legacy generic
    image client.

    The body shape (model, prompt, size, image, response_format, watermark)
    matches the OpenAI-compatible /images/generations contract used by both
    Aliyun DashScope and 火山方舟 doubao.
    """

    def _validate(self, *, model_config: ModelConfig, api_key: str) -> None:
        if not model_config.base_url:
            raise ValueError("Image model base_url is required")
        if not model_config.model_name:
            raise ValueError("Image model_name is required")
        if not api_key:
            raise ValueError("Image model api_key is required")

    def generate_image(
        self,
        *,
        model_config: ModelConfig,
        api_key: str,
        prompt: str,
        size: str,
        reference_urls: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        self._validate(model_config=model_config, api_key=api_key)
        endpoint = f"{model_config.base_url.rstrip('/')}/images/generations"
        body: dict[str, Any] = {
            "model": model_config.model_name,
            "prompt": prompt,
            "size": size,
            "response_format": "url",
        }
        if reference_urls:
            if len(reference_urls) == 1:
                body["image"] = reference_urls[0]
            else:
                body["image"] = reference_urls
                body["sequential_image_generation"] = "disabled"
            body["watermark"] = False
        try:
            response = requests.post(
                endpoint,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=body,
                timeout=180,
            )
            response.raise_for_status()
        except requests.HTTPError as exc:
            detail = ""
            try:
                if exc.response is not None:
                    err = exc.response.json()
                    if isinstance(err, dict):
                        detail = err.get("error", {}).get("message", "") or str(err)[:200]
            except Exception:
                pass
            raise ValueError(f"Illustration image generation failed: {detail or exc}") from exc
        payload = response.json()
        try:
            item = payload["data"][0]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("Image response missing data[0]") from exc
        image_ref = item.get("url") or item.get("b64_json")
        if not isinstance(image_ref, str) or not image_ref:
            raise ValueError("Image response missing url or b64_json")
        return {"url": image_ref, "raw": payload}


def _resolve_reference_urls(db: Session, user_id: int, asset_ids: list[int]) -> list[str]:
    """Map illustration_assets.id list → file_path (URL) list.
    Silently drops ids that don't belong to the user (they're refinement, not required)."""
    if not asset_ids:
        return []
    rows = db.query(IllustrationAsset).filter(
        IllustrationAsset.id.in_(asset_ids),
        IllustrationAsset.user_id == user_id,
    ).all()
    values: list[str] = []
    for row in rows:
        if not row.file_path:
            continue
        path = Path(row.file_path)
        if path.is_file():
            mime = mimetypes.guess_type(path.name)[0] or "image/png"
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
            values.append(f"data:{mime};base64,{encoded}")
        else:
            values.append(row.file_path)
    return values


def generate_and_persist_illustration(
    *,
    db: Session,
    current_user: User,
    model_config: ModelConfig,
    prompt: str,
    size: str,
    reference_asset_ids: list[int],
    character_id: Optional[int],
    role: str,
    pipeline_run_id: Optional[str],
    shot_seq: Optional[int],
    client: Optional[IllustrationImageClient] = None,
) -> IllustrationAsset:
    api_key = decrypt_text(model_config.encrypted_api_key) if model_config.encrypted_api_key else ""
    reference_urls = _resolve_reference_urls(db, current_user.id, reference_asset_ids)

    client = client or IllustrationImageClient()
    provider_size = normalize_illustration_size(model_config.model_name, size)
    result = client.generate_image(
        model_config=model_config,
        api_key=api_key,
        prompt=prompt,
        size=provider_size,
        reference_urls=reference_urls or None,
    )
    file_path = result.get("url") or ""
    raw = result.get("raw")

    asset = IllustrationAsset(
        user_id=current_user.id,
        character_id=character_id,
        role=role,
        pipeline_run_id=pipeline_run_id,
        shot_seq=shot_seq,
        prompt=prompt,
        model=model_config.model_name,
        size=size,
        reference_asset_ids=list(reference_asset_ids),
        file_path=file_path,
        provider_raw=raw if isinstance(raw, dict) else None,
    )
    db.add(asset)
    db.flush()

    record_image_usage(
        db=db,
        user_id=current_user.id,
        pipeline_run_id=pipeline_run_id,
        step="image_gen",
        model=model_config.model_name,
        image_count=1,
    )
    db.commit()
    db.refresh(asset)
    return asset
