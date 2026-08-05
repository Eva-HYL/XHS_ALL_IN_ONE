from __future__ import annotations

from typing import Any


METHOD_VERSION = "v1.3.0"
LAYOUT_STYLE = "article_knowledge_cards_v1"
CHARACTER_ROLE = "边缘单只解说员"

SEMANTIC_PROMPT_CONTRACT = (
    "先判断候选段落是否包含可视化的动作、对象、空间、状态变化或明确关系；"
    "没有有效视觉信息时不要输出该条目。"
    "只提炼文章中需要解释的核心概念，不得复述 Markdown 符号、HTML 标签、编辑器操作、"
    "提示词说明、标题、比例、尺寸、水印或签名。"
    "主角只是单只边缘解说员，不是画面主体；不重复角色外观，不增加无关道具或可见文字。"
)


def apply_method_contract(plan: dict[str, Any]) -> dict[str, Any]:
    """Attach the durable rendering contract to every newly built visual plan."""
    return {
        **plan,
        "method_version": METHOD_VERSION,
        "layout_style": LAYOUT_STYLE,
        "template_copy": [],
        "character_role": CHARACTER_ROLE,
    }


def validate_method_contract(plan: dict[str, Any]) -> dict[str, bool]:
    template_copy = plan.get("template_copy")
    article_only_copy = (
        "title" not in plan
        and isinstance(template_copy, list)
        and not any(str(item).strip() for item in template_copy)
    )
    return {
        "article_only_copy": article_only_copy,
        "layout_valid": plan.get("layout_style") == LAYOUT_STYLE,
        "method_current": plan.get("method_version") == METHOD_VERSION,
    }
