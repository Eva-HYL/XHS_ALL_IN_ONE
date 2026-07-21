from __future__ import annotations

from decimal import Decimal

from backend.app.models import WechatMpArticle
from backend.app.services.pricing_service import calculate_image_cost, get_pricing


def add_article_cost(article: WechatMpArticle, cost_yuan: object) -> None:
    current = article.cost_estimate or {}
    total = Decimal(str(current.get("total_yuan", "0"))) + Decimal(str(cost_yuan))
    article.cost_estimate = {
        "currency": "CNY",
        "total_yuan": str(total.quantize(Decimal("0.0001"))),
        "calls": int(current.get("calls", 0)) + 1,
    }


def estimate_image_action(model_name: str) -> dict[str, object]:
    pricing = get_pricing().get("image_models", {}).get(model_name)
    cost = calculate_image_cost(model_name, 1) if pricing else Decimal("0.0000")
    return {
        "model_name": model_name,
        "currency": "CNY",
        "estimated_yuan": str(cost.quantize(Decimal("0.0001"))),
        "pricing_available": pricing is not None,
    }
