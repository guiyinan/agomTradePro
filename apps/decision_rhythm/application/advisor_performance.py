"""Recommendation consolidation, tracking, and attribution helpers."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from apps.decision_rhythm.application.advisor_contracts import (
    AdvisorOrderIntent,
    RecommendationPerformanceProviderProtocol,
)
from apps.decision_rhythm.application.advisor_intents import (
    _dedupe_preserve_order,
    _normalize_recommendation_side,
    _recommendation_asset_code,
    _recommendation_id,
    _recommendation_price,
    _recommendation_reason,
    _recommendation_source_candidate_ids,
    _recommendation_source_signal_ids,
    _replace_intent,
)
from apps.decision_rhythm.application.advisor_serialization import (
    _decimal_to_number,
    _optional_decimal,
    _serialize_time,
    _to_decimal,
)


def _find_recommendation_for_asset(recommendations: list[Any], asset_code: str) -> Any | None:
    normalized = asset_code.upper()
    for side in ["EXIT", "SELL", "REDUCE", "BUY", "ADD", "HOLD"]:
        for recommendation in recommendations:
            if (
                _recommendation_asset_code(recommendation) == normalized
                and _normalize_recommendation_side(recommendation) == side
            ):
                return recommendation
    return None


def _consolidate_recommendations(
    recommendations: list[Any],
    *,
    held_asset_codes: set[str],
) -> dict[str, Any]:
    """Resolve duplicate/conflicting recommendations into one final input per asset."""

    grouped: dict[str, list[Any]] = {}
    for recommendation in recommendations:
        asset_code = _recommendation_asset_code(recommendation)
        if asset_code:
            grouped.setdefault(asset_code, []).append(recommendation)

    selected: list[Any] = []
    resolutions_by_asset: dict[str, dict[str, Any]] = {}
    conflicts: list[dict[str, Any]] = []
    for asset_code, candidates in grouped.items():
        has_holding = asset_code in held_asset_codes
        ranked = sorted(
            candidates,
            key=lambda item: _recommendation_sort_key(item, has_holding=has_holding),
        )
        accepted = ranked[0]
        rejected = ranked[1:]
        accepted_side = _normalize_recommendation_side(accepted) or "UNKNOWN"
        sides = _dedupe_preserve_order(
            [_normalize_recommendation_side(item) or "UNKNOWN" for item in candidates]
        )
        has_conflict = len({side for side in sides if side != "UNKNOWN"}) > 1
        conflict_reason = ""
        if has_conflict:
            rejected_labels = ", ".join(
                f"{_recommendation_id(item)}:{_normalize_recommendation_side(item) or 'UNKNOWN'}"
                for item in rejected
            )
            conflict_reason = (
                f"同一标的出现方向冲突 {', '.join(sides)}；"
                f"最终采纳 {accepted_side}，拒绝 {rejected_labels or '-'}。"
            )
            conflicts.append(
                {
                    "asset_code": asset_code,
                    "accepted_recommendation_id": _recommendation_id(accepted),
                    "accepted_side": accepted_side,
                    "rejected_recommendations": [_recommendation_trace(item) for item in rejected],
                    "conflict_reason": conflict_reason,
                }
            )
        elif rejected:
            conflict_reason = (
                "同一标的出现重复建议；保留评分/优先级最高的一条，" "其余作为来源信号附加。"
            )

        selected.append(accepted)
        resolutions_by_asset[asset_code] = {
            "asset_code": asset_code,
            "status": "CONFLICT" if has_conflict else "MERGED" if rejected else "SINGLE",
            "accepted_recommendation_id": _recommendation_id(accepted),
            "accepted_side": accepted_side,
            "source_recommendation_ids": _dedupe_preserve_order(
                [_recommendation_id(item) for item in candidates if _recommendation_id(item)]
            ),
            "source_signal_ids": _dedupe_preserve_order(
                [
                    str(signal_id)
                    for item in candidates
                    for signal_id in _recommendation_source_signal_ids(item)
                ]
            ),
            "source_candidate_ids": _dedupe_preserve_order(
                [
                    str(candidate_id)
                    for item in candidates
                    for candidate_id in _recommendation_source_candidate_ids(item)
                ]
            ),
            "rejected_recommendations": [_recommendation_trace(item) for item in rejected],
            "conflict_reason": conflict_reason,
        }

    return {
        "selected_recommendations": selected,
        "resolutions_by_asset": resolutions_by_asset,
        "conflicts": conflicts,
    }


def _recommendation_sort_key(
    recommendation: Any,
    *,
    has_holding: bool,
) -> tuple[int, Decimal, Decimal, str]:
    side = _normalize_recommendation_side(recommendation)
    if has_holding:
        side_rank = {"EXIT": 0, "REDUCE": 1, "BUY": 2, "ADD": 2, "HOLD": 3}.get(side, 4)
    else:
        side_rank = {"BUY": 0, "ADD": 0, "HOLD": 2, "REDUCE": 3, "EXIT": 3}.get(side, 4)
    confidence = _to_decimal(getattr(recommendation, "confidence", 0))
    composite_score = _to_decimal(getattr(recommendation, "composite_score", 0))
    return (side_rank, -confidence, -composite_score, _recommendation_id(recommendation))


def _attach_recommendation_resolution(
    intent: AdvisorOrderIntent,
    resolution: dict[str, Any] | None,
) -> AdvisorOrderIntent:
    if not resolution:
        return intent
    risk_notes = list(intent.risk_notes)
    conflict_reason = str(resolution.get("conflict_reason") or "")
    if resolution.get("status") == "CONFLICT" and conflict_reason:
        risk_notes.append(conflict_reason)
    return _replace_intent(
        intent,
        source_recommendation_ids=list(resolution.get("source_recommendation_ids") or []),
        conflict_resolution=resolution,
        risk_notes=_dedupe_preserve_order(risk_notes),
    )


def _recommendation_trace(recommendation: Any) -> dict[str, Any]:
    return {
        "recommendation_id": _recommendation_id(recommendation),
        "side": _normalize_recommendation_side(recommendation) or "UNKNOWN",
        "confidence": _decimal_to_number(_to_decimal(getattr(recommendation, "confidence", 0))),
        "composite_score": _decimal_to_number(
            _to_decimal(getattr(recommendation, "composite_score", 0))
        ),
        "reason": _recommendation_reason(recommendation),
    }


def _recommendation_tracking_payload(
    *,
    recommendation_id: str,
    recommendation: Any | None,
    execution_links: list[dict[str, Any]],
    performance: dict[str, Any],
    lookup_error: str,
    attribution_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    user_action = str(getattr(recommendation, "user_action", "") or "UNKNOWN")
    if hasattr(getattr(recommendation, "user_action", None), "value"):
        user_action = str(recommendation.user_action.value)
    enriched_performance = _performance_with_deep_attribution(
        performance=performance,
        recommendation=recommendation,
        user_action=user_action,
        attribution_context=attribution_context or {},
    )
    return {
        "recommendation_id": recommendation_id,
        "user_action": user_action,
        "user_action_note": str(getattr(recommendation, "user_action_note", "") or ""),
        "user_action_at": _serialize_time(getattr(recommendation, "user_action_at", "")),
        "execution_links": execution_links,
        "execution_count": len(execution_links),
        "is_executed": bool(execution_links),
        "performance": enriched_performance,
        "lookup_error": lookup_error,
    }


def _order_tracking_payload(
    intent: AdvisorOrderIntent,
    tracking_map: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    source_ids = list(intent.source_recommendation_ids or [])
    recommendation_rows = [
        tracking_map.get(source_id)
        or _recommendation_tracking_payload(
            recommendation_id=source_id,
            recommendation=None,
            execution_links=[],
            performance=_empty_recommendation_performance_payload(
                status="NO_RECOMMENDATION",
                reason="source recommendation is not available",
            ),
            lookup_error="",
            attribution_context={},
        )
        for source_id in source_ids
    ]
    execution_links = [
        link for row in recommendation_rows for link in row.get("execution_links", [])
    ]
    if not source_ids:
        review_status = "NO_SOURCE_RECOMMENDATION"
    elif execution_links:
        review_status = "EXECUTED"
    elif any(row.get("user_action") == "ADOPTED" for row in recommendation_rows):
        review_status = "ADOPTED_PENDING_EXECUTION"
    else:
        review_status = "PENDING_REVIEW"
    return {
        "review_status": review_status,
        "source_recommendation_ids": source_ids,
        "recommendations": recommendation_rows,
        "execution_links": execution_links,
        "execution_count": len(execution_links),
        "is_executed": bool(execution_links),
        "performance": _combined_order_performance(recommendation_rows),
    }


def _recommendation_performance_payload(
    *,
    recommendation: Any | None,
    performance_provider: RecommendationPerformanceProviderProtocol,
) -> dict[str, Any]:
    if recommendation is None:
        return _empty_recommendation_performance_payload(
            status="NO_RECOMMENDATION",
            reason="source recommendation is not available",
        )

    anchor_date = _recommendation_anchor_date(recommendation)
    if anchor_date is None:
        return _empty_recommendation_performance_payload(
            status="MISSING_ANCHOR_DATE",
            reason="recommendation created_at/user_action_at is unavailable",
        )

    asset_code = _recommendation_asset_code(recommendation)
    if not asset_code:
        return _empty_recommendation_performance_payload(
            status="MISSING_ASSET_CODE",
            reason="recommendation asset code is unavailable",
        )

    try:
        series = performance_provider.get_close_price_series(
            asset_code=asset_code,
            start_date=anchor_date,
            end_date=anchor_date + timedelta(days=70),
        )
    except Exception as exc:
        return _empty_recommendation_performance_payload(
            status="PRICE_LOOKUP_FAILED",
            reason=str(exc),
            anchor_date=anchor_date,
        )

    normalized_series = _normalize_price_series(series)
    anchor_price = _recommendation_price(recommendation)
    anchor_price_date: date | None = anchor_date if anchor_price else None
    if anchor_price is None or anchor_price <= 0:
        anchor_bar = _first_price_on_or_after(normalized_series, anchor_date)
        if anchor_bar is not None:
            anchor_price_date, anchor_price = anchor_bar
    if anchor_price is None or anchor_price <= 0:
        return _empty_recommendation_performance_payload(
            status="ANCHOR_PRICE_UNAVAILABLE",
            reason="anchor close price is unavailable",
            anchor_date=anchor_date,
        )

    side = _normalize_recommendation_side(recommendation)
    direction = Decimal("-1") if side in {"EXIT", "REDUCE"} else Decimal("1")
    windows = {
        f"{days}d": _performance_window_payload(
            series=normalized_series,
            anchor_date=anchor_date,
            anchor_price=anchor_price,
            days=days,
            direction=direction,
        )
        for days in (7, 20, 60)
    }
    available_count = sum(1 for item in windows.values() if item["status"] == "AVAILABLE")
    return {
        "status": "AVAILABLE" if available_count else "PENDING",
        "asset_code": asset_code,
        "side": side or "UNKNOWN",
        "anchor_date": anchor_date.isoformat(),
        "anchor_price": _decimal_to_number(anchor_price),
        "anchor_price_date": anchor_price_date.isoformat() if anchor_price_date else None,
        "windows": windows,
        "error_attribution": _performance_error_attribution(windows),
    }


def _empty_recommendation_performance_payload(
    *,
    status: str,
    reason: str,
    anchor_date: date | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "reason": reason,
        "anchor_date": anchor_date.isoformat() if anchor_date else None,
        "anchor_price": None,
        "anchor_price_date": None,
        "windows": {
            f"{days}d": {
                "status": status,
                "target_date": (
                    (anchor_date + timedelta(days=days)).isoformat() if anchor_date else None
                ),
                "price_date": None,
                "close_price": None,
                "raw_return": None,
                "directional_return": None,
            }
            for days in (7, 20, 60)
        },
        "error_attribution": {
            "status": "PENDING",
            "primary_category": None,
            "reason": reason,
            "evidence": [],
        },
    }


def _performance_window_payload(
    *,
    series: list[tuple[date, Decimal]],
    anchor_date: date,
    anchor_price: Decimal,
    days: int,
    direction: Decimal,
) -> dict[str, Any]:
    target_date = anchor_date + timedelta(days=days)
    price_bar = _first_price_on_or_after(series, target_date)
    if price_bar is None:
        status = "NOT_DUE" if target_date > datetime.now(UTC).date() else "PRICE_UNAVAILABLE"
        return {
            "status": status,
            "target_date": target_date.isoformat(),
            "price_date": None,
            "close_price": None,
            "raw_return": None,
            "directional_return": None,
        }

    price_date, close_price = price_bar
    raw_return = (close_price / anchor_price) - Decimal("1")
    return {
        "status": "AVAILABLE",
        "target_date": target_date.isoformat(),
        "price_date": price_date.isoformat(),
        "close_price": _decimal_to_number(close_price),
        "raw_return": _decimal_to_number(raw_return),
        "directional_return": _decimal_to_number(raw_return * direction),
    }


def _combined_order_performance(recommendation_rows: list[dict[str, Any]]) -> dict[str, Any]:
    windows: dict[str, dict[str, Any]] = {}
    for days in (7, 20, 60):
        key = f"{days}d"
        values = [
            _optional_decimal(
                (row.get("performance") or {})
                .get("windows", {})
                .get(key, {})
                .get("directional_return")
            )
            for row in recommendation_rows
        ]
        available = [value for value in values if value is not None]
        windows[key] = {
            "status": "AVAILABLE" if available else "PENDING",
            "available_count": len(available),
            "recommendation_count": len(recommendation_rows),
            "directional_return_avg": (
                _decimal_to_number(sum(available, Decimal("0")) / Decimal(len(available)))
                if available
                else None
            ),
        }
    return {
        "recommendation_count": len(recommendation_rows),
        "windows": windows,
        "error_attribution": _combined_error_attribution(recommendation_rows),
    }


def _performance_error_attribution(windows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    available = [
        (key, _optional_decimal(payload.get("directional_return")))
        for key, payload in windows.items()
        if payload.get("status") == "AVAILABLE"
    ]
    available = [(key, value) for key, value in available if value is not None]
    if not available:
        return {
            "status": "PENDING",
            "primary_category": None,
            "reason": "No matured performance window is available.",
            "evidence": [],
        }

    latest_key, latest_return = available[-1]
    evidence = [
        {"window": key, "directional_return": _decimal_to_number(value)} for key, value in available
    ]
    if latest_return >= 0:
        return {
            "status": "NO_ERROR",
            "primary_category": None,
            "reason": f"Latest available {latest_key} directional return is non-negative.",
            "evidence": evidence,
        }

    first_key, first_return = available[0]
    if (
        first_return is not None
        and first_return < 0
        and any(value > 0 for _, value in available[1:])
    ):
        category = "EXECUTION_TOO_EARLY"
        reason = "Early window was negative but a later window recovered."
    elif len(available) >= 2 and all(value < 0 for _, value in available):
        category = "MODEL_MISJUDGMENT"
        reason = "All matured windows are negative."
    else:
        category = "MODEL_MISJUDGMENT"
        reason = f"Latest available {latest_key} directional return is negative."

    return {
        "status": "ATTRIBUTED",
        "primary_category": category,
        "reason": reason,
        "evidence": evidence,
        "first_negative_window": (
            first_key if first_return is not None and first_return < 0 else latest_key
        ),
    }


def _combined_error_attribution(recommendation_rows: list[dict[str, Any]]) -> dict[str, Any]:
    attributions = [
        (row.get("performance") or {}).get("error_attribution") or {} for row in recommendation_rows
    ]
    attributed = [item for item in attributions if item.get("status") == "ATTRIBUTED"]
    if not attributed:
        return {
            "status": "PENDING_OR_NO_ERROR",
            "primary_categories": [],
            "attribution_count": 0,
        }
    categories = _dedupe_preserve_order(
        [str(item.get("primary_category") or "") for item in attributed]
    )
    deep_categories = _dedupe_preserve_order(
        str(category)
        for item in attributions
        for category in ((item.get("deep_attribution") or {}).get("secondary_categories") or [])
        if category
    )
    return {
        "status": "ATTRIBUTED",
        "primary_categories": categories,
        "deep_categories": deep_categories,
        "attribution_count": len(attributed),
    }


def _performance_with_deep_attribution(
    *,
    performance: dict[str, Any],
    recommendation: Any | None,
    user_action: str,
    attribution_context: dict[str, Any],
) -> dict[str, Any]:
    payload = dict(performance or {})
    attribution = dict(payload.get("error_attribution") or {})
    attribution["deep_attribution"] = _deep_error_attribution_payload(
        performance=payload,
        recommendation=recommendation,
        user_action=user_action,
        attribution_context=attribution_context,
    )
    payload["error_attribution"] = attribution
    return payload


def _deep_error_attribution_payload(
    *,
    performance: dict[str, Any],
    recommendation: Any | None,
    user_action: str,
    attribution_context: dict[str, Any],
) -> dict[str, Any]:
    latest_window = _latest_available_performance_window(performance)
    regime = str(getattr(recommendation, "regime", "") or "").strip()
    policy_level = str(getattr(recommendation, "policy_level", "") or "").strip()
    regime_confidence = _optional_decimal(getattr(recommendation, "regime_confidence", None))
    recommendation_context = dict(attribution_context.get("recommendation") or {})
    outcome_context = dict(attribution_context.get("outcome") or {})
    actual_regime = str(outcome_context.get("regime") or "").strip()
    actual_policy_level = str(outcome_context.get("policy_level") or "").strip()
    secondary_categories: list[str] = []

    regime_payload = {
        "status": "EVIDENCE_AVAILABLE" if regime else "EVIDENCE_MISSING",
        "category": None,
        "regime": regime or None,
        "regime_confidence": _decimal_to_number(regime_confidence),
        "recommendation_context": recommendation_context,
        "outcome_context": outcome_context,
        "actual_regime": actual_regime or None,
    }
    if not regime or regime.upper() == "UNKNOWN":
        regime_payload["category"] = "REGIME_CONTEXT_MISSING"
        secondary_categories.append("REGIME_CONTEXT_MISSING")
    elif regime_confidence is not None and regime_confidence < Decimal("0.5"):
        regime_payload["category"] = "REGIME_CONTEXT_WEAK"
        secondary_categories.append("REGIME_CONTEXT_WEAK")
    elif actual_regime and _normalize_context_value(actual_regime) != _normalize_context_value(
        regime
    ):
        regime_payload["category"] = "REGIME_JUDGMENT_ERROR"
        secondary_categories.append("REGIME_JUDGMENT_ERROR")

    policy_payload = {
        "status": "EVIDENCE_AVAILABLE" if policy_level else "EVIDENCE_MISSING",
        "category": None,
        "policy_level": policy_level or None,
        "recommendation_context": recommendation_context,
        "outcome_context": outcome_context,
        "actual_policy_level": actual_policy_level or None,
    }
    if not policy_level or policy_level.upper() == "UNKNOWN":
        policy_payload["category"] = "POLICY_CONTEXT_MISSING"
        secondary_categories.append("POLICY_CONTEXT_MISSING")
    elif actual_policy_level and _normalize_context_value(
        actual_policy_level
    ) != _normalize_context_value(policy_level):
        policy_payload["category"] = "POLICY_MISJUDGMENT"
        secondary_categories.append("POLICY_MISJUDGMENT")

    manual_override_payload = _manual_override_attribution_payload(
        latest_window=latest_window,
        user_action=user_action,
    )
    if manual_override_payload.get("category"):
        secondary_categories.append(str(manual_override_payload["category"]))

    return {
        "status": "ATTRIBUTED" if secondary_categories else "EVIDENCE_ONLY",
        "secondary_categories": _dedupe_preserve_order(secondary_categories),
        "regime": regime_payload,
        "policy": policy_payload,
        "manual_override": manual_override_payload,
    }


def _manual_override_attribution_payload(
    *,
    latest_window: dict[str, Any] | None,
    user_action: str,
) -> dict[str, Any]:
    normalized_action = str(user_action or "UNKNOWN").upper()
    directional_return = (
        _optional_decimal(latest_window.get("directional_return")) if latest_window else None
    )
    payload = {
        "status": "PENDING",
        "category": None,
        "user_action": normalized_action,
        "latest_window": latest_window or {},
    }
    if directional_return is None:
        return payload

    not_adopted = normalized_action in {"PENDING", "WATCHING", "IGNORED", "UNKNOWN"}
    if not_adopted and directional_return > 0:
        payload.update(
            {
                "status": "ATTRIBUTED",
                "category": "MANUAL_OVERRIDE_ERROR",
                "reason": "未采纳建议后的方向性表现为正。",
            }
        )
    elif not_adopted and directional_return < 0:
        payload.update(
            {
                "status": "NO_ERROR",
                "category": "MANUAL_OVERRIDE_PROTECTED_CAPITAL",
                "reason": "未采纳建议后的方向性表现为负。",
            }
        )
    else:
        payload.update(
            {
                "status": "EVIDENCE_ONLY",
                "reason": "建议已采纳或已有执行证据，不判定人工 override 错误。",
            }
        )
    return payload


def _latest_available_performance_window(performance: dict[str, Any]) -> dict[str, Any] | None:
    windows = dict(performance.get("windows") or {})
    for key in ("60d", "20d", "7d"):
        window = dict(windows.get(key) or {})
        if window.get("status") == "AVAILABLE":
            return {"window": key, **window}
    return None


def _performance_outcome_date(performance: dict[str, Any]) -> date | None:
    latest_window = _latest_available_performance_window(performance)
    if latest_window is None:
        return None
    return _date_from_any(latest_window.get("price_date") or latest_window.get("target_date"))


def _normalize_context_value(value: Any) -> str:
    return str(value or "").strip().upper().replace("-", "_")


def _recommendation_anchor_date(recommendation: Any) -> date | None:
    for attr in ("created_at", "generated_at", "user_action_at", "updated_at"):
        parsed = _date_from_any(getattr(recommendation, attr, None))
        if parsed is not None:
            return parsed
    return None


def _date_from_any(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            try:
                return date.fromisoformat(value[:10])
            except ValueError:
                return None
    return None


def _normalize_price_series(series: list[tuple[date, float]]) -> list[tuple[date, Decimal]]:
    normalized: list[tuple[date, Decimal]] = []
    for raw_date, raw_price in series or []:
        price_date = _date_from_any(raw_date)
        price = _optional_decimal(raw_price)
        if price_date is not None and price is not None and price > 0:
            normalized.append((price_date, price))
    return sorted(normalized, key=lambda item: item[0])


def _first_price_on_or_after(
    series: list[tuple[date, Decimal]],
    target_date: date,
) -> tuple[date, Decimal] | None:
    for price_date, close_price in series:
        if price_date >= target_date:
            return price_date, close_price
    return None


__all__ = [
    "_find_recommendation_for_asset",
    "_consolidate_recommendations",
    "_recommendation_sort_key",
    "_attach_recommendation_resolution",
    "_recommendation_trace",
    "_recommendation_tracking_payload",
    "_order_tracking_payload",
    "_recommendation_performance_payload",
    "_empty_recommendation_performance_payload",
    "_performance_window_payload",
    "_combined_order_performance",
    "_performance_error_attribution",
    "_combined_error_attribution",
    "_performance_with_deep_attribution",
    "_deep_error_attribution_payload",
    "_manual_override_attribution_payload",
    "_latest_available_performance_window",
    "_performance_outcome_date",
    "_normalize_context_value",
    "_recommendation_anchor_date",
    "_date_from_any",
    "_normalize_price_series",
    "_first_price_on_or_after",
]
