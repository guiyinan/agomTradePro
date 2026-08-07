"""risk_center runtime capability handlers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def _fallback_get_risk_floor() -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.risk_center.get_floor()


def _fallback_list_risk_templates() -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    templates = client.risk_center.list_templates()
    return {
        "templates": templates,
        "total_count": len(templates),
    }


def _fallback_get_effective_risk_policy(account_id: int) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.risk_center.get_effective_policy(account_id)


def _fallback_get_account_risk_policy(account_id: int) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.risk_center.get_account_policy(account_id)


def _fallback_list_risk_exceptions(account_id: int | None = None) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    exceptions = client.risk_center.list_exceptions(account_id=account_id)
    return {
        "exceptions": exceptions,
        "total_count": len(exceptions),
    }


def _fallback_check_pre_trade_risk(
    account_id: int,
    symbol: str,
    side: str,
    quantity: float,
    price: float,
    account_equity: float,
    total_position_value: float,
    cash_balance: float | None = None,
    current_symbol_position_value: float = 0.0,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.risk_center.check_pre_trade(
        {
            "account_id": account_id,
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "price": price,
            "account_equity": account_equity,
            "total_position_value": total_position_value,
            "cash_balance": cash_balance,
            "current_symbol_position_value": current_symbol_position_value,
        }
    )


def _fallback_check_post_investment_risk(
    account_id: int,
    account_equity: float,
    positions: list[dict[str, Any]] | None = None,
    cash_balance: float | None = None,
    total_position_value: float | None = None,
    daily_pnl_pct: float | None = None,
    drawdown_pct: float | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.risk_center.check_post_investment(
        {
            "account_id": account_id,
            "account_equity": account_equity,
            "positions": positions or [],
            "cash_balance": cash_balance,
            "total_position_value": total_position_value,
            "daily_pnl_pct": daily_pnl_pct,
            "drawdown_pct": drawdown_pct,
        }
    )


def _fallback_get_risk_center_daily_report(account_id: int, report_date: str) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.risk_center.get_daily_report(account_id, report_date)


def _fallback_list_risk_center_daily_reports(
    account_id: int | None = None,
    report_date: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    reports = client.risk_center.list_daily_reports(
        account_id=account_id,
        report_date=report_date,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    )
    return {
        "reports": reports,
        "total_count": len(reports),
    }


def _internal_handler_risk_center_create_exception(
    field_name: str,
    allowed_value: Any,
    reason: str,
    expires_at: str,
    account_id: int | None = None,
    is_active: bool = True,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from datetime import datetime

    from agomtradepro import AgomTradeProClient

    parameter_fields = {
        "max_total_position_pct",
        "max_single_position_pct",
        "max_daily_loss_pct",
        "max_drawdown_pct",
        "max_stop_loss_pct",
        "take_profit_pct",
        "min_cash_pct",
        "force_stop_loss",
        "hard_exclusions",
    }
    if account_id is not None and (
        isinstance(account_id, bool) or not isinstance(account_id, int) or account_id <= 0
    ):
        raise ValueError("account_id must be a positive integer or null")

    normalized_field_name = str(field_name or "").strip()
    if normalized_field_name not in parameter_fields:
        raise ValueError(f"unsupported risk exception field_name: {normalized_field_name}")

    normalized_reason = str(reason or "").strip()
    if not normalized_reason:
        raise ValueError("reason must be a non-empty string")

    normalized_expires_at = str(expires_at or "").strip()
    try:
        parsed_expires_at = datetime.fromisoformat(normalized_expires_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("expires_at must be a valid ISO 8601 datetime") from exc
    if parsed_expires_at.tzinfo is None or parsed_expires_at.utcoffset() is None:
        raise ValueError("expires_at must include a timezone offset")
    canonical_expires_at = parsed_expires_at.isoformat()

    payload = {
        "account_id": account_id,
        "field_name": normalized_field_name,
        "allowed_value": allowed_value,
        "reason": normalized_reason,
        "expires_at": canonical_expires_at,
        "is_active": bool(is_active),
    }

    client = AgomTradeProClient()
    if preview_only:
        existing = client.risk_center.list_exceptions(account_id=account_id)
        if not isinstance(existing, list):
            raise ValueError("risk exception list response must be an array")
        scoped_existing = [
            item
            for item in existing
            if isinstance(item, dict) and item.get("account_id") == account_id
        ]
        same_field = [
            item for item in scoped_existing if item.get("field_name") == normalized_field_name
        ]
        return {
            "success": True,
            "preview_only": True,
            "requested_exception": payload,
            "existing_scope_count": len(scoped_existing),
            "same_field_exception_count": len(same_field),
            "same_field_exceptions": [
                {
                    "id": item.get("id"),
                    "allowed_value": item.get("allowed_value"),
                    "reason": item.get("reason"),
                    "expires_at": item.get("expires_at"),
                    "is_active": item.get("is_active"),
                }
                for item in same_field
            ],
            "summary": {
                "account_id": account_id,
                "field_name": normalized_field_name,
                "existing_scope_count": len(scoped_existing),
                "same_field_exception_count": len(same_field),
                "will_create_active_exception": bool(is_active),
            },
            "message": (
                "Preview generated. Confirm to create the persisted risk exception for the "
                "selected account scope and field."
            ),
        }

    return client.risk_center.create_exception(payload)


def _internal_handler_risk_center_update_floor(
    reason: str,
    name: str | None = None,
    max_total_position_pct: float | None = None,
    max_single_position_pct: float | None = None,
    max_daily_loss_pct: float | None = None,
    max_drawdown_pct: float | None = None,
    max_stop_loss_pct: float | None = None,
    take_profit_pct: float | None = None,
    min_cash_pct: float | None = None,
    force_stop_loss: bool | None = None,
    hard_exclusions: list[str] | None = None,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("reason must be a non-empty string")
    normalized_reason = reason.strip()

    updates: dict[str, Any] = {}
    if name is not None:
        if not isinstance(name, str):
            raise ValueError("name must be a string when provided")
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("name must be a non-empty string when provided")
        if len(normalized_name) > 100:
            raise ValueError("name must not exceed 100 characters")
        updates["name"] = normalized_name

    percentage_fields = {
        "max_total_position_pct": max_total_position_pct,
        "max_single_position_pct": max_single_position_pct,
        "max_daily_loss_pct": max_daily_loss_pct,
        "max_drawdown_pct": max_drawdown_pct,
        "max_stop_loss_pct": max_stop_loss_pct,
        "take_profit_pct": take_profit_pct,
        "min_cash_pct": min_cash_pct,
    }
    for field_name, value in percentage_fields.items():
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError(f"{field_name} must be a number between 0 and 1")
        normalized_value = float(value)
        if not 0 <= normalized_value <= 1:
            raise ValueError(f"{field_name} must be between 0 and 1")
        updates[field_name] = normalized_value

    if force_stop_loss is not None:
        if not isinstance(force_stop_loss, bool):
            raise ValueError("force_stop_loss must be a boolean")
        updates["force_stop_loss"] = force_stop_loss

    if hard_exclusions is not None:
        if not isinstance(hard_exclusions, list):
            raise ValueError("hard_exclusions must be an array of strings")
        normalized_exclusions = []
        for item in hard_exclusions:
            if not isinstance(item, str):
                raise ValueError("hard_exclusions must contain only strings")
            normalized_item = item.strip()
            if not normalized_item:
                raise ValueError("hard_exclusions must not contain empty values")
            if len(normalized_item) > 64:
                raise ValueError("hard_exclusions items must not exceed 64 characters")
            normalized_exclusions.append(normalized_item)
        updates["hard_exclusions"] = normalized_exclusions

    if not updates:
        raise ValueError("at least one risk floor field must be provided")

    client = AgomTradeProClient()
    if preview_only:
        current = client.risk_center.get_floor()
        if not isinstance(current, dict):
            raise ValueError("risk floor response must be an object")
        field_changes = {
            field_name: {
                "current": current.get(field_name),
                "requested": requested_value,
            }
            for field_name, requested_value in updates.items()
            if current.get(field_name) != requested_value
        }
        if not field_changes:
            raise ValueError("requested risk floor values do not change the active floor")
        return {
            "success": True,
            "preview_only": True,
            "current_floor": {
                "id": current.get("id"),
                "name": current.get("name"),
                "is_active": current.get("is_active"),
                "updated_at": current.get("updated_at"),
            },
            "field_changes": field_changes,
            "reason": normalized_reason,
            "summary": {
                "floor_id": current.get("id"),
                "changed_field_count": len(field_changes),
                "changed_fields": sorted(field_changes),
                "will_persist_default_floor_if_missing": current.get("id") is None,
            },
            "message": (
                "Preview generated. Confirm to update the persisted global risk floor and "
                "record the canonical risk-policy audit entry."
            ),
        }

    return client.risk_center.update_floor({**updates, "reason": normalized_reason})


def _internal_handler_risk_center_update_account_policy(
    account_id: int,
    reason: str,
    template_id: int | None = None,
    risk_profile: str | None = None,
    max_total_position_pct: float | None = None,
    max_single_position_pct: float | None = None,
    max_daily_loss_pct: float | None = None,
    max_drawdown_pct: float | None = None,
    max_stop_loss_pct: float | None = None,
    take_profit_pct: float | None = None,
    min_cash_pct: float | None = None,
    force_stop_loss: bool | None = None,
    hard_exclusions: list[str] | None = None,
    is_active: bool | None = None,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    if isinstance(account_id, bool) or not isinstance(account_id, int) or account_id <= 0:
        raise ValueError("account_id must be a positive integer")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("reason must be a non-empty string")
    normalized_reason = reason.strip()

    updates: dict[str, Any] = {}
    if template_id is not None:
        if isinstance(template_id, bool) or not isinstance(template_id, int) or template_id <= 0:
            raise ValueError("template_id must be a positive integer when provided")
        updates["template_id"] = template_id

    if risk_profile is not None:
        normalized_profile = str(risk_profile).strip().lower()
        if normalized_profile not in {"conservative", "moderate", "aggressive", "custom"}:
            raise ValueError("risk_profile must be conservative, moderate, aggressive, or custom")
        updates["risk_profile"] = normalized_profile

    percentage_fields = {
        "max_total_position_pct": max_total_position_pct,
        "max_single_position_pct": max_single_position_pct,
        "max_daily_loss_pct": max_daily_loss_pct,
        "max_drawdown_pct": max_drawdown_pct,
        "max_stop_loss_pct": max_stop_loss_pct,
        "take_profit_pct": take_profit_pct,
        "min_cash_pct": min_cash_pct,
    }
    for field_name, value in percentage_fields.items():
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError(f"{field_name} must be a number between 0 and 1")
        normalized_value = float(value)
        if not 0 <= normalized_value <= 1:
            raise ValueError(f"{field_name} must be between 0 and 1")
        updates[field_name] = normalized_value

    if force_stop_loss is not None:
        if not isinstance(force_stop_loss, bool):
            raise ValueError("force_stop_loss must be a boolean")
        updates["force_stop_loss"] = force_stop_loss

    if hard_exclusions is not None:
        if not isinstance(hard_exclusions, list):
            raise ValueError("hard_exclusions must be an array of strings")
        normalized_exclusions = []
        for item in hard_exclusions:
            if not isinstance(item, str):
                raise ValueError("hard_exclusions must contain only strings")
            normalized_item = item.strip()
            if not normalized_item:
                raise ValueError("hard_exclusions must not contain empty values")
            if len(normalized_item) > 64:
                raise ValueError("hard_exclusions items must not exceed 64 characters")
            normalized_exclusions.append(normalized_item)
        updates["hard_exclusions"] = normalized_exclusions

    if is_active is not None:
        if not isinstance(is_active, bool):
            raise ValueError("is_active must be a boolean")
        updates["is_active"] = is_active

    if not updates:
        raise ValueError("at least one account risk policy field must be provided")

    client = AgomTradeProClient()
    if preview_only:
        policies = client.risk_center.list_account_policies()
        if not isinstance(policies, list):
            raise ValueError("account risk policy catalog response must be an array")
        current = next(
            (
                item
                for item in policies
                if isinstance(item, dict) and item.get("account_id") == account_id
            ),
            None,
        )

        template_summary = None
        if template_id is not None:
            templates = client.risk_center.list_templates()
            if not isinstance(templates, list):
                raise ValueError("risk template catalog response must be an array")
            template = next(
                (
                    item
                    for item in templates
                    if isinstance(item, dict) and item.get("id") == template_id
                ),
                None,
            )
            if template is None:
                raise ValueError(f"risk template not found: {template_id}")
            template_summary = {
                "id": template.get("id"),
                "key": template.get("key"),
                "name": template.get("name"),
                "risk_profile": template.get("risk_profile"),
                "is_active": template.get("is_active"),
            }

        current_values = current or {}
        field_changes = {}
        for field_name, requested_value in updates.items():
            current_field_name = "template" if field_name == "template_id" else field_name
            current_value = current_values.get(current_field_name)
            if current_value != requested_value:
                field_changes[field_name] = {
                    "current": current_value,
                    "requested": requested_value,
                }
        if current is not None and not field_changes:
            raise ValueError("requested account risk policy values do not change the stored policy")

        operation = "create" if current is None else "update"
        return {
            "success": True,
            "preview_only": True,
            "operation": operation,
            "account_id": account_id,
            "current_policy": current,
            "template": template_summary,
            "field_changes": field_changes,
            "reason": normalized_reason,
            "summary": {
                "account_id": account_id,
                "operation": operation,
                "policy_id": current_values.get("id"),
                "changed_field_count": len(field_changes),
                "changed_fields": sorted(field_changes),
                "target_is_active": updates.get(
                    "is_active",
                    current_values.get("is_active", True),
                ),
            },
            "message": (
                "Preview generated. Confirm to create or update the account-scoped risk "
                "policy and record the canonical risk-policy audit entry."
            ),
        }

    return client.risk_center.upsert_account_policy(
        {
            "account_id": account_id,
            **updates,
            "reason": normalized_reason,
        }
    )


def _internal_handler_risk_center_generate_daily_report(
    account_id: int,
    report_date: str,
    account_equity: float,
    positions: list[dict[str, Any]] | None = None,
    cash_balance: float | None = None,
    total_position_value: float | None = None,
    daily_pnl_pct: float | None = None,
    drawdown_pct: float | None = None,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from datetime import date

    from agomtradepro import AgomTradeProClient

    if isinstance(account_id, bool) or not isinstance(account_id, int) or account_id <= 0:
        raise ValueError("account_id must be a positive integer")
    if not isinstance(report_date, str) or not report_date.strip():
        raise ValueError("report_date must be an ISO 8601 date")
    try:
        canonical_report_date = date.fromisoformat(report_date.strip()).isoformat()
    except ValueError as exc:
        raise ValueError("report_date must be an ISO 8601 date") from exc

    numeric_values = {
        "account_equity": account_equity,
        "cash_balance": cash_balance,
        "total_position_value": total_position_value,
        "daily_pnl_pct": daily_pnl_pct,
        "drawdown_pct": drawdown_pct,
    }
    normalized_values: dict[str, float | None] = {}
    for field_name, value in numeric_values.items():
        if value is None:
            normalized_values[field_name] = None
            continue
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError(f"{field_name} must be numeric")
        normalized_values[field_name] = float(value)
    for field_name in ("account_equity", "cash_balance", "total_position_value"):
        value = normalized_values[field_name]
        if value is not None and value < 0:
            raise ValueError(f"{field_name} must be non-negative")
    normalized_drawdown = normalized_values["drawdown_pct"]
    if normalized_drawdown is not None and not 0 <= normalized_drawdown <= 1:
        raise ValueError("drawdown_pct must be between 0 and 1")

    normalized_positions = positions or []
    if not isinstance(normalized_positions, list) or any(
        not isinstance(item, dict) for item in normalized_positions
    ):
        raise ValueError("positions must be an array of objects")

    snapshot_payload = {
        "account_id": account_id,
        "account_equity": normalized_values["account_equity"],
        "positions": normalized_positions,
        "cash_balance": normalized_values["cash_balance"],
        "total_position_value": normalized_values["total_position_value"],
        "daily_pnl_pct": normalized_values["daily_pnl_pct"],
        "drawdown_pct": normalized_values["drawdown_pct"],
    }

    client = AgomTradeProClient()
    if preview_only:
        check = client.risk_center.check_post_investment(snapshot_payload)
        if not isinstance(check, dict):
            raise ValueError("post-investment check response must be an object")
        existing_reports = client.risk_center.list_daily_reports(
            account_id=account_id,
            start_date=canonical_report_date,
            end_date=canonical_report_date,
            limit=1,
        )
        if not isinstance(existing_reports, list):
            raise ValueError("daily report history response must be an array")
        existing = next(
            (
                item
                for item in existing_reports
                if isinstance(item, dict) and str(item.get("report_date")) == canonical_report_date
            ),
            None,
        )
        operation = "create" if existing is None else "overwrite"
        return {
            "success": True,
            "preview_only": True,
            "operation": operation,
            "account_id": account_id,
            "report_date": canonical_report_date,
            "projected_check": check,
            "existing_report": existing,
            "summary": {
                "account_id": account_id,
                "report_date": canonical_report_date,
                "operation": operation,
                "existing_report_id": existing.get("id") if existing else None,
                "existing_status": existing.get("status") if existing else None,
                "projected_status": check.get("status"),
                "projected_passed": check.get("passed"),
                "projected_violation_count": len(check.get("violations") or []),
                "position_count": len(normalized_positions),
            },
            "message": (
                "Preview generated. Confirm to persist the selected account/date risk report; "
                "an existing report for the same slot will be overwritten."
            ),
        }

    return client.risk_center.generate_daily_report(
        {
            **snapshot_payload,
            "report_date": canonical_report_date,
        }
    )


def _internal_handler_risk_center_stress_scenario_list(
    include_inactive: bool = False,
) -> dict[str, Any]:
    """List scenarios through the formal SDK."""

    from agomtradepro import AgomTradeProClient

    scenarios = AgomTradeProClient().risk_center.list_scenarios(include_inactive=include_inactive)
    return {"scenarios": scenarios, "total_count": len(scenarios)}


def _internal_handler_risk_center_stress_scenario_read(
    scenario_key: str,
) -> dict[str, Any]:
    """Read one repository-backed scenario through the formal SDK."""

    from agomtradepro import AgomTradeProClient

    normalized_key = str(scenario_key or "").strip()
    if not normalized_key:
        raise ValueError("scenario_key must be a non-empty string")
    return AgomTradeProClient().risk_center.get_scenario(normalized_key)


def _internal_handler_risk_center_stress_scenario_compare(
    scenario_key: str,
    left_version: int,
    right_version: int,
) -> dict[str, Any]:
    """Compare two immutable revision payloads without a write."""

    payload = _internal_handler_risk_center_stress_scenario_read(scenario_key)
    revisions = payload.get("revisions")
    if not isinstance(revisions, list):
        raise ValueError("scenario response must include a revisions array")
    by_version = {item.get("version"): item for item in revisions if isinstance(item, dict)}
    left = by_version.get(left_version)
    right = by_version.get(right_version)
    if left is None or right is None:
        raise ValueError("both requested scenario revisions must exist")
    fields = sorted(set(left).union(right))
    diff = {
        field: {"left": left.get(field), "right": right.get(field)}
        for field in fields
        if left.get(field) != right.get(field)
    }
    return {
        "scenario_key": scenario_key,
        "left_version": left_version,
        "right_version": right_version,
        "diff": diff,
    }


def _internal_handler_risk_center_stress_scenario_validate_revision(
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Validate one revision with zero writes through the canonical API."""

    from agomtradepro import AgomTradeProClient

    return AgomTradeProClient().risk_center.validate_scenario_revision(dict(payload))


def _internal_handler_risk_center_stress_scenario_preview_revision(
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Preview one revision with zero writes through the canonical API."""

    from agomtradepro import AgomTradeProClient

    return AgomTradeProClient().risk_center.preview_scenario_revision(dict(payload))


def _scenario_write_payload(
    *,
    payload: dict[str, Any],
    preview_id: str,
    proposal_id: str | None,
    expected_active_version: int | None,
    expected_active_hash: str | None,
    change_reason: str,
    correlation_id: str,
    idempotency_key: str | None,
) -> dict[str, Any]:
    """Normalize the persisted evidence contract for scenario writes."""

    normalized_preview_id = str(preview_id or "").strip()
    normalized_reason = str(change_reason or "").strip()
    normalized_correlation_id = str(correlation_id or "").strip()
    normalized_idempotency_key = str(idempotency_key or "").strip()
    if not normalized_preview_id:
        raise ValueError("preview_id is required")
    if not normalized_reason:
        raise ValueError("change_reason is required")
    if not normalized_correlation_id:
        raise ValueError("correlation_id is required")
    if not normalized_idempotency_key:
        raise ValueError("idempotency_key is required")
    return {
        **dict(payload),
        "preview_id": normalized_preview_id,
        "proposal_id": str(proposal_id).strip() if proposal_id else None,
        "expected_active_version": expected_active_version,
        "expected_active_hash": (
            str(expected_active_hash).strip() if expected_active_hash else None
        ),
        "change_reason": normalized_reason,
        "correlation_id": normalized_correlation_id,
        "idempotency_key": normalized_idempotency_key,
    }


def _internal_handler_risk_center_stress_scenario_write(
    operation: str,
    *,
    payload: dict[str, Any],
    preview_id: str,
    change_reason: str,
    correlation_id: str,
    idempotency_key: str | None = None,
    proposal_id: str | None = None,
    expected_active_version: int | None = None,
    expected_active_hash: str | None = None,
    preview_only: bool = False,
) -> dict[str, Any]:
    """Execute a preview-first scenario write through formal SDK methods."""

    from agomtradepro import AgomTradeProClient

    request = _scenario_write_payload(
        payload=payload,
        preview_id=preview_id,
        proposal_id=proposal_id,
        expected_active_version=expected_active_version,
        expected_active_hash=expected_active_hash,
        change_reason=change_reason,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
    )
    client = AgomTradeProClient()
    if preview_only:
        target_fields = {
            key: request[key]
            for key in (
                "scenario_key",
                "scenario_set_revision_id",
                "environment",
                "purpose",
                "target_version",
            )
            if request.get(key) is not None
        }
        transport_fields = {
            "preview_id",
            "proposal_id",
            "idempotency_key",
            "expected_active_version",
            "expected_active_hash",
            "change_reason",
            "correlation_id",
        }
        revision_payload = {
            key: value
            for key, value in request.items()
            if key not in transport_fields and (operation == "propose" or key not in target_fields)
        }
        result = client.risk_center.preview_scenario_action(
            operation,
            {
                "payload": revision_payload if operation == "propose" else {},
                **target_fields,
                "expected_active_version": request.get("expected_active_version"),
                "expected_active_hash": request.get("expected_active_hash"),
                "change_reason": request["change_reason"],
                "correlation_id": request["correlation_id"],
            },
        )
        return {
            **result,
            "preview_only": True,
            "operation": operation,
            "correlation_id": correlation_id,
        }
    if operation == "propose":
        return client.risk_center.propose_scenario_revision(request)
    if operation == "activate":
        return client.risk_center.activate_scenario_revision(request)
    if operation == "rollback":
        return client.risk_center.rollback_scenario_revision(request)
    if operation == "retire":
        scenario_key = str(request.get("scenario_key") or "").strip()
        if not scenario_key:
            raise ValueError("scenario_key is required for retirement")
        return client.risk_center.retire_scenario(scenario_key, request)
    raise ValueError(f"unsupported scenario write operation: {operation}")


def _internal_handler_risk_center_stress_scenario_propose_revision(
    preview_only: bool = False,
    **kwargs: Any,
) -> dict[str, Any]:
    """Preview or create a persistent scenario revision proposal."""

    return _internal_handler_risk_center_stress_scenario_write(
        "propose", preview_only=preview_only, **kwargs
    )


def _internal_handler_risk_center_stress_scenario_activate_revision(
    preview_only: bool = False,
    **kwargs: Any,
) -> dict[str, Any]:
    """Preview or activate a human-approved scenario revision."""

    return _internal_handler_risk_center_stress_scenario_write(
        "activate", preview_only=preview_only, **kwargs
    )


def _internal_handler_risk_center_stress_scenario_rollback_revision(
    preview_only: bool = False,
    **kwargs: Any,
) -> dict[str, Any]:
    """Preview or create-and-activate a rollback revision."""

    return _internal_handler_risk_center_stress_scenario_write(
        "rollback", preview_only=preview_only, **kwargs
    )


def _internal_handler_risk_center_stress_scenario_retire(
    preview_only: bool = False,
    **kwargs: Any,
) -> dict[str, Any]:
    """Preview or retire a scenario through a replacement revision."""

    return _internal_handler_risk_center_stress_scenario_write(
        "retire", preview_only=preview_only, **kwargs
    )


LEGACY_TOOL_FALLBACKS: dict[str, Callable[..., Any]] = {
    "get_risk_floor": _fallback_get_risk_floor,
    "list_risk_templates": _fallback_list_risk_templates,
    "get_effective_risk_policy": _fallback_get_effective_risk_policy,
    "get_account_risk_policy": _fallback_get_account_risk_policy,
    "list_risk_exceptions": _fallback_list_risk_exceptions,
    "check_pre_trade_risk": _fallback_check_pre_trade_risk,
    "check_post_investment_risk": _fallback_check_post_investment_risk,
    "get_risk_center_daily_report": _fallback_get_risk_center_daily_report,
    "list_risk_center_daily_reports": _fallback_list_risk_center_daily_reports,
}

GOVERNED_HANDLERS: dict[str, Callable[..., Any]] = {
    "risk_center_create_exception": _internal_handler_risk_center_create_exception,
    "risk_center_update_floor": _internal_handler_risk_center_update_floor,
    "risk_center_update_account_policy": _internal_handler_risk_center_update_account_policy,
    "risk_center_generate_daily_report": _internal_handler_risk_center_generate_daily_report,
    "risk_center_stress_scenario_list": _internal_handler_risk_center_stress_scenario_list,
    "risk_center_stress_scenario_read": _internal_handler_risk_center_stress_scenario_read,
    "risk_center_stress_scenario_compare": _internal_handler_risk_center_stress_scenario_compare,
    "risk_center_stress_scenario_validate_revision": (
        _internal_handler_risk_center_stress_scenario_validate_revision
    ),
    "risk_center_stress_scenario_preview_revision": (
        _internal_handler_risk_center_stress_scenario_preview_revision
    ),
    "risk_center_stress_scenario_propose_revision": (
        _internal_handler_risk_center_stress_scenario_propose_revision
    ),
    "risk_center_stress_scenario_activate_revision": (
        _internal_handler_risk_center_stress_scenario_activate_revision
    ),
    "risk_center_stress_scenario_rollback_revision": (
        _internal_handler_risk_center_stress_scenario_rollback_revision
    ),
    "risk_center_stress_scenario_retire": (_internal_handler_risk_center_stress_scenario_retire),
}
