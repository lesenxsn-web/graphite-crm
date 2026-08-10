from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any


DEFAULT_STAGE_POINTS = {
    "陌拜线索": 5,
    "已触达": 10,
    "有效接触": 16,
    "需求确认": 22,
    "送样测试": 27,
    "已报价": 30,
    "商务谈判": 33,
    "成交": 35,
    "复购": 35,
    "暂缓": 5,
    "流失": 0,
}


def load_model(path: str | Path = "models/lead_score.json") -> dict[str, Any]:
    model_path = Path(path)
    if not model_path.exists():
        return {
            "weights": {
                "stage": 35,
                "annual_demand": 25,
                "contact_completeness": 15,
                "decision_maker_access": 15,
                "followup_recency": 10,
            },
            "demand_thresholds": [20, 100, 300, 1000],
        }
    return json.loads(model_path.read_text(encoding="utf-8"))


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        return None


def calculate_lead_score(customer: dict[str, Any], model: dict[str, Any] | None = None) -> int:
    model = model or load_model()
    weights = model.get("weights", {})

    stage_max = float(weights.get("stage", 35))
    stage_raw = DEFAULT_STAGE_POINTS.get(str(customer.get("stage", "陌拜线索")), 0)
    stage_score = stage_raw / 35 * stage_max

    demand = float(customer.get("estimated_annual_demand_tons") or 0)
    thresholds = model.get("demand_thresholds", [20, 100, 300, 1000])
    demand_ratio = 0.0
    if demand > 0:
        demand_ratio = 0.2
    if demand >= thresholds[0]:
        demand_ratio = 0.4
    if demand >= thresholds[1]:
        demand_ratio = 0.6
    if demand >= thresholds[2]:
        demand_ratio = 0.8
    if demand >= thresholds[3]:
        demand_ratio = 1.0
    demand_score = demand_ratio * float(weights.get("annual_demand", 25))

    contact_fields = ["contact_name", "phone", "email"]
    completed = sum(bool(customer.get(field)) for field in contact_fields)
    contact_score = completed / len(contact_fields) * float(
        weights.get("contact_completeness", 15)
    )

    role = str(customer.get("contact_role") or "")
    decision_terms = ["采购", "老板", "董事长", "总经理", "负责人", "厂长", "经理"]
    decision_ratio = 1.0 if any(term in role for term in decision_terms) else 0.3 if role else 0.0
    decision_score = decision_ratio * float(weights.get("decision_maker_access", 15))

    last_contact = _parse_date(customer.get("last_contact_date"))
    recency_ratio = 0.0
    if last_contact:
        days = (date.today() - last_contact).days
        if days <= 7:
            recency_ratio = 1.0
        elif days <= 14:
            recency_ratio = 0.8
        elif days <= 30:
            recency_ratio = 0.5
        elif days <= 60:
            recency_ratio = 0.2
    recency_score = recency_ratio * float(weights.get("followup_recency", 10))

    return max(0, min(100, round(stage_score + demand_score + contact_score + decision_score + recency_score)))
