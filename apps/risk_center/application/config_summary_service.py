"""Config Center summary for risk center."""

from __future__ import annotations

from typing import Any

from apps.risk_center.application.repository_provider import (
    get_risk_exception_repository,
    get_risk_floor_repository,
    get_risk_policy_repository,
    get_risk_template_repository,
)


def get_risk_center_summary(user: Any) -> dict[str, Any]:
    floor = get_risk_floor_repository().get_active_floor()
    templates = get_risk_template_repository().list_templates()
    policies = get_risk_policy_repository().list_policies(account_ids=None)
    exceptions = get_risk_exception_repository().list_exceptions(account_id=None)
    active_exceptions = [item for item in exceptions if item.is_current]
    return {
        "status": "configured" if floor.is_active and templates else "attention",
        "summary": {
            "floor_active": floor.is_active,
            "template_count": len(templates),
            "account_policy_count": len(policies),
            "active_exception_count": len(active_exceptions),
        },
    }
