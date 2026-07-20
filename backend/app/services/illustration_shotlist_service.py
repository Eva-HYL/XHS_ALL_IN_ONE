from __future__ import annotations

import json
from typing import Any

import requests

from backend.app.models import ModelConfig

# System prompt is structural — targets JSON output, not marketing copy.
# This is the reason we can't reuse ai_service._complete's 小红书-flavored callers.
SYSTEM_PROMPT_TEMPLATE = """你是"图集配图"助手。基于用户提供的中文文章，产出 shot list JSON。只输出 JSON，不要任何解释文字、markdown 代码块、寒暄。

工作流：先在心里提炼 3-5 个认知锚点（核心判断/断点/前后对比/角色状态/作者不情愿做的那一步/看似简单实际懒得干的环节），再基于锚点生成 4-6 张 shot。每张一个核心结构，不平均配图。

Schema:
{{"core_thesis":"...","cognitive_anchors":["..."],
 "shots":[{{"seq":1,"purpose":"封面|内页","anchor_paragraph":"第N段后",
   "theme":"...","structure_type":"Workflow|系统局部|前后对比|角色状态|概念隐喻|方法分层|地图路线|小漫画分镜",
   "character_action":"拨|扒|蹲|压|翻|叼|卡|蜷|打|躺|偷",
   "elements":["..."],"chinese_labels":["..."]}}]}}

形象定义（严格遵循）：
{ip_definition}

禁止复刻经典构图：传送带断点/判断杆/素材鱼/漏斗分拣/承接路径/常见坑举牌/盖章工具箱/三层信息源拉线。"""


def _call_text_model_json(
    *,
    model_config: ModelConfig,
    api_key: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.5,
) -> tuple[str, dict]:
    """Call an OpenAI-compatible /chat/completions with response_format=json_object.
    Returns (raw_content_string, usage_dict)."""
    endpoint = f"{model_config.base_url.rstrip('/')}/chat/completions"
    body = {
        "model": model_config.model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "response_format": {"type": "json_object"},
    }
    try:
        resp = requests.post(
            endpoint,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=body,
            timeout=180,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        detail = ""
        try:
            if getattr(exc, "response", None) is not None:
                err = exc.response.json()
                if isinstance(err, dict):
                    detail = err.get("error", {}).get("message", "") or str(err)[:200]
        except Exception:
            pass
        raise ValueError(f"Shotlist generation failed: {detail or exc}") from exc
    try:
        payload = resp.json()
        content = payload["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise ValueError("Text response missing choices[0].message.content") from exc
    usage = payload.get("usage", {}) or {}
    return content, usage


def generate_shotlist(
    *,
    model_config: ModelConfig,
    api_key: str,
    essay: str,
    ip_definition: str,
    extra_instruction: str = "",
) -> tuple[dict, dict]:
    """Return (parsed_shotlist_dict, usage_dict). Raises ValueError if the model
    returns text that isn't parseable JSON — caller should surface as 502."""
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(ip_definition=ip_definition.strip() or "(默认形象)")
    user_prompt = f"文章正文：\n\n{essay}\n\n"
    if extra_instruction.strip():
        user_prompt += f"额外指令：{extra_instruction.strip()}\n\n"
    user_prompt += "请直接输出 shot list JSON。"

    content, usage = _call_text_model_json(
        model_config=model_config,
        api_key=api_key,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
    )
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Model returned non-JSON content: {content[:400]}") from exc
    return parsed, usage
