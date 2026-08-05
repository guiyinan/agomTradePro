"""Application-level query helpers for cross-app signal access."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date
from math import isfinite
from typing import Any, cast

from apps.asset_analysis.application.asset_name_service import resolve_asset_names
from apps.data_center.application.public import (
    list_published_macro_indicator_summaries as get_available_indicators_for_frontend,
)
from apps.regime.application.current_regime import resolve_current_regime
from apps.regime.domain.asset_eligibility import get_eligibility_matrix
from apps.regime.domain.services_v2 import RegimeType
from apps.signal.application.repository_provider import (
    DjangoSignalRepository,
    UnifiedSignalRepository,
    get_signal_diagnostic_repository,
)
from apps.signal.domain.diagnostics import SignalDiagnosticSummary
from apps.signal.domain.entities import SignalStatus
from apps.signal.domain.rules import check_eligibility

from .use_cases import (
    GetRecommendedAssetsRequest,
    GetRecommendedAssetsUseCase,
    ValidateSignalRequest,
    ValidateSignalUseCase,
)

_ASSET_CODE_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9._:-]{0,19}$")
_DIRECTIONS = frozenset({"LONG", "SHORT", "NEUTRAL"})
_REGIMES = frozenset(item.value for item in RegimeType)
_STATUSES = frozenset(item.value for item in SignalStatus)
_MAX_LIST_LIMIT = 500
_MAX_UNIFIED_DAYS = 3650
_MAX_INVALIDATION_IDS = 500


def _asset_code(value: str) -> str:
    """Normalize one bounded asset identifier."""

    normalized = value.strip().upper()
    if not _ASSET_CODE_PATTERN.fullmatch(normalized):
        raise ValueError("asset_code is invalid")
    return normalized


def _bounded_text(
    value: str,
    *,
    field_name: str,
    maximum: int,
    allow_blank: bool = False,
) -> str:
    """Normalize one bounded text value."""

    normalized = value.strip()
    if (not normalized and not allow_blank) or len(normalized) > maximum:
        raise ValueError(f"{field_name} is invalid")
    return normalized


def _positive_integer(
    value: object,
    *,
    field_name: str,
    maximum: int | None = None,
) -> int:
    """Parse a positive non-boolean integer."""

    if isinstance(value, bool):
        raise ValueError(f"{field_name} is invalid")
    try:
        normalized = int(cast(Any, value))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field_name} is invalid") from exc
    if normalized <= 0 or (maximum is not None and normalized > maximum):
        raise ValueError(f"{field_name} is invalid")
    return normalized


def _signal_id_or_none(value: object) -> str | None:
    """Return a canonical persisted signal ID or None."""

    try:
        return str(_positive_integer(value, field_name="signal_id"))
    except ValueError:
        return None


def _validated_list_filters(
    *,
    status_filter: str,
    asset_class: str,
    direction: str,
    search: str,
    include_test: bool,
    limit: int,
) -> tuple[str, str, str, str, bool, int]:
    """Validate signal list filters before persistence access."""

    normalized_status = status_filter.strip()
    if normalized_status and normalized_status not in _STATUSES:
        raise ValueError("status_filter is invalid")
    normalized_direction = direction.strip().upper()
    if normalized_direction and normalized_direction not in _DIRECTIONS:
        raise ValueError("direction is invalid")
    normalized_asset_class = _bounded_text(
        asset_class,
        field_name="asset_class",
        maximum=50,
        allow_blank=True,
    )
    normalized_search = _bounded_text(
        search,
        field_name="search",
        maximum=200,
        allow_blank=True,
    )
    if not isinstance(include_test, bool):
        raise ValueError("include_test is invalid")
    normalized_limit = _positive_integer(
        limit,
        field_name="limit",
        maximum=_MAX_LIST_LIMIT,
    )
    return (
        normalized_status,
        normalized_asset_class,
        normalized_direction,
        normalized_search,
        include_test,
        normalized_limit,
    )


def get_current_regime_payload() -> dict[str, Any]:
    """Return current regime payload for signal pages."""

    latest = resolve_current_regime(as_of_date=date.today())
    if latest is None:
        raise LookupError("No regime data available")
    must_not_use_for_decision = bool(latest.must_not_use_for_decision) or (
        latest.dominant_regime in (None, "Unknown")
    )
    return {
        "status": "blocked" if must_not_use_for_decision else "ok",
        "dominant_regime": latest.dominant_regime,
        "confidence": latest.confidence,
        "observed_at": latest.observed_at,
        "distribution": dict(latest.distribution or {}) if not must_not_use_for_decision else {},
        "must_not_use_for_decision": must_not_use_for_decision,
        "blocked_reason": (
            latest.blocked_reason or "regime_data_unavailable" if must_not_use_for_decision else ""
        ),
    }


def get_recommended_assets_payload(regime: str) -> dict[str, Any]:
    """Return recommended assets for one regime."""

    normalized_regime = regime.strip()
    if normalized_regime not in _REGIMES:
        return {
            "recommended": [],
            "neutral": [],
            "hostile": sorted(get_eligibility_matrix()),
        }
    response = GetRecommendedAssetsUseCase().execute(
        GetRecommendedAssetsRequest(current_regime=normalized_regime)
    )
    return {
        "recommended": response.recommended,
        "neutral": response.neutral,
        "hostile": response.hostile,
    }


def _infer_asset_class(asset_code: str) -> str:
    """Infer asset class from asset code for lightweight eligibility checks."""

    code = _asset_code(asset_code)
    if code.startswith(("511", "128", "019")):
        return "china_bond"
    if code.startswith(("518", "159934")):
        return "gold"
    if code.startswith(("159985", "510170")):
        return "commodity"
    if code.startswith(("511880", "511990")):
        return "cash"
    return "a_share_growth"


def build_signal_management_context(
    *,
    status_filter: str = "",
    asset_class: str = "",
    direction: str = "",
    search: str = "",
) -> dict[str, Any]:
    """Build template context for the signal management page."""

    (
        status_filter,
        asset_class,
        direction,
        search,
        _include_test,
        _limit,
    ) = _validated_list_filters(
        status_filter=status_filter,
        asset_class=asset_class,
        direction=direction,
        search=search,
        include_test=False,
        limit=500,
    )
    repository = DjangoSignalRepository()
    signals = repository.list_signal_records(
        status_filter=status_filter,
        asset_class=asset_class,
        direction=direction,
        search=search,
    )

    asset_codes = [signal.asset_code for signal in signals if signal.asset_code]
    asset_name_map = resolve_asset_names(asset_codes)
    for signal in signals:
        cast(Any, signal).asset_name = asset_name_map.get(
            signal.asset_code,
            signal.asset_code,
        )

    metadata = repository.get_signal_management_metadata()
    current_regime = get_current_regime_payload()
    recommended_assets = get_recommended_assets_payload(
        current_regime["dominant_regime"] if current_regime else "Deflation"
    )

    return {
        "signals": signals,
        "stats": metadata["stats"],
        "asset_classes": metadata["asset_classes"],
        "directions": metadata["directions"],
        "filter_status": status_filter,
        "filter_asset_class": asset_class,
        "filter_direction": direction,
        "filter_search": search,
        "current_regime": current_regime,
        "recommended_assets": recommended_assets,
        "all_asset_classes": list(get_eligibility_matrix().keys()),
        "all_regimes": sorted(_REGIMES),
        "available_indicators": get_available_indicators_for_frontend(),
    }


def create_investment_signal_record(
    *,
    asset_code: str,
    asset_class: str,
    direction: str,
    logic_desc: str,
    invalidation_logic: str,
    invalidation_threshold: float | None,
    invalidation_rules: dict[str, Any] | None,
    target_regime: str,
    is_approved: bool,
    rejection_reason: str,
) -> dict[str, Any]:
    """Create an investment signal via the signal repository."""

    normalized_asset_class = _bounded_text(
        asset_class,
        field_name="asset_class",
        maximum=50,
    )
    if normalized_asset_class not in get_eligibility_matrix():
        raise ValueError("asset_class is invalid")
    normalized_direction = direction.strip().upper()
    if normalized_direction not in _DIRECTIONS:
        raise ValueError("direction is invalid")
    normalized_regime = target_regime.strip()
    if normalized_regime not in _REGIMES:
        raise ValueError("target_regime is invalid")
    if not isinstance(is_approved, bool):
        raise ValueError("is_approved is invalid")
    if invalidation_threshold is not None and (
        isinstance(invalidation_threshold, bool)
        or not isinstance(invalidation_threshold, (int, float))
        or not isfinite(float(invalidation_threshold))
    ):
        raise ValueError("invalidation_threshold is invalid")
    if invalidation_rules is not None and not isinstance(
        invalidation_rules,
        Mapping,
    ):
        raise ValueError("invalidation_rules is invalid")
    return DjangoSignalRepository().create_signal_record(
        asset_code=_asset_code(asset_code),
        asset_class=normalized_asset_class,
        direction=normalized_direction,
        logic_desc=_bounded_text(
            logic_desc,
            field_name="logic_desc",
            maximum=5000,
        ),
        invalidation_logic=_bounded_text(
            invalidation_logic,
            field_name="invalidation_logic",
            maximum=2000,
        ),
        invalidation_threshold=invalidation_threshold,
        invalidation_rules=(dict(invalidation_rules) if invalidation_rules is not None else None),
        target_regime=normalized_regime,
        status="approved" if is_approved else "rejected",
        rejection_reason=_bounded_text(
            rejection_reason,
            field_name="rejection_reason",
            maximum=1000,
            allow_blank=True,
        ),
    )


def list_investment_signal_payloads(
    *,
    status_filter: str = "",
    asset_class: str = "",
    direction: str = "",
    search: str = "",
    include_test: bool = False,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return serialized investment signals for API responses."""

    normalized = _validated_list_filters(
        status_filter=status_filter,
        asset_class=asset_class,
        direction=direction,
        search=search,
        include_test=include_test,
        limit=limit,
    )
    return DjangoSignalRepository().list_signal_payloads(
        status_filter=normalized[0],
        asset_class=normalized[1],
        direction=normalized[2],
        search=normalized[3],
        include_test=normalized[4],
        limit=normalized[5],
    )


def get_investment_signal_payload(signal_id: str) -> dict[str, Any] | None:
    """Return one investment signal payload by id."""

    normalized_id = _signal_id_or_none(signal_id)
    if normalized_id is None:
        return None
    return DjangoSignalRepository().get_signal_payload(normalized_id)


def create_investment_signal_payload(
    *,
    asset_code: str,
    asset_class: str,
    direction: str,
    logic_desc: str,
    invalidation_logic: str,
    target_regime: str,
) -> dict[str, Any]:
    """Parse invalidation logic and create one investment signal payload."""

    from apps.signal.domain.parser import InvalidationLogicParser

    normalized_asset_class = _bounded_text(
        asset_class,
        field_name="asset_class",
        maximum=50,
    )
    if normalized_asset_class not in get_eligibility_matrix():
        raise ValueError("asset_class is invalid")
    normalized_direction = direction.strip().upper()
    if normalized_direction not in _DIRECTIONS:
        raise ValueError("direction is invalid")
    normalized_regime = target_regime.strip()
    if normalized_regime not in _REGIMES:
        raise ValueError("target_regime is invalid")
    normalized_invalidation = _bounded_text(
        invalidation_logic,
        field_name="invalidation_logic",
        maximum=2000,
    )
    parse_result = InvalidationLogicParser().parse(normalized_invalidation)
    if not parse_result.success or parse_result.rule is None:
        raise ValueError(f"解析失败: {parse_result.error}")

    return DjangoSignalRepository().create_signal_record(
        asset_code=_asset_code(asset_code),
        asset_class=normalized_asset_class,
        direction=normalized_direction,
        logic_desc=_bounded_text(
            logic_desc,
            field_name="logic_desc",
            maximum=5000,
        ),
        invalidation_logic=normalized_invalidation,
        invalidation_threshold=None,
        invalidation_rules=None,
        invalidation_description=normalized_invalidation,
        invalidation_rule_json=parse_result.rule.to_dict(),
        target_regime=normalized_regime,
        status="pending",
        rejection_reason="",
    )


def update_investment_signal_payload(
    signal_id: str,
    *,
    asset_code: str | None = None,
    asset_class: str | None = None,
    direction: str | None = None,
    logic_desc: str | None = None,
    invalidation_logic: str | None = None,
    target_regime: str | None = None,
) -> dict[str, Any] | None:
    """Update one investment signal payload, parsing invalidation logic if provided."""

    normalized_id = _signal_id_or_none(signal_id)
    if normalized_id is None:
        return None

    update_fields: dict[str, Any] = {}
    if asset_code is not None:
        update_fields["asset_code"] = _asset_code(asset_code)
    if asset_class is not None:
        normalized_asset_class = _bounded_text(
            asset_class,
            field_name="asset_class",
            maximum=50,
        )
        if normalized_asset_class not in get_eligibility_matrix():
            raise ValueError("asset_class is invalid")
        update_fields["asset_class"] = normalized_asset_class
    if direction is not None:
        normalized_direction = direction.strip().upper()
        if normalized_direction not in _DIRECTIONS:
            raise ValueError("direction is invalid")
        update_fields["direction"] = normalized_direction
    if logic_desc is not None:
        update_fields["logic_desc"] = _bounded_text(
            logic_desc,
            field_name="logic_desc",
            maximum=5000,
        )
    if target_regime is not None:
        normalized_regime = target_regime.strip()
        if normalized_regime not in _REGIMES:
            raise ValueError("target_regime is invalid")
        update_fields["target_regime"] = normalized_regime

    if invalidation_logic is not None:
        from apps.signal.domain.parser import InvalidationLogicParser

        normalized_invalidation = _bounded_text(
            invalidation_logic,
            field_name="invalidation_logic",
            maximum=2000,
        )
        parse_result = InvalidationLogicParser().parse(normalized_invalidation)
        if not parse_result.success or parse_result.rule is None:
            raise ValueError(f"解析失败: {parse_result.error}")
        update_fields["invalidation_logic"] = normalized_invalidation
        update_fields["invalidation_description"] = normalized_invalidation
        update_fields["invalidation_rule_json"] = parse_result.rule.to_dict()

    if not update_fields:
        raise ValueError("At least one update field is required")
    return DjangoSignalRepository().update_signal_record_fields(
        normalized_id,
        **update_fields,
    )


def get_signal_stats_payload() -> dict[str, int]:
    """Return aggregate signal stats for the API."""

    metadata = DjangoSignalRepository().get_signal_management_metadata()
    stats = metadata.get("stats")
    if not isinstance(stats, Mapping):
        raise ValueError("Signal statistics are invalid")
    normalized: dict[str, int] = {}
    for key, value in stats.items():
        if (
            not isinstance(key, str)
            or isinstance(value, bool)
            or not isinstance(value, int)
            or value < 0
        ):
            raise ValueError("Signal statistics are invalid")
        normalized[key] = value
    return normalized


def get_signal_diagnostic_count() -> int:
    """Return investment signal count for operational diagnostics."""

    return get_signal_diagnostic_repository().get_signal_count()


def get_signal_diagnostic_summary() -> SignalDiagnosticSummary:
    """Return signal summary for operational diagnostics."""

    return get_signal_diagnostic_repository().get_signal_summary()


def list_signal_diagnostic_asset_codes() -> list[str]:
    """Return distinct signal asset codes for operational diagnostics."""

    return get_signal_diagnostic_repository().list_distinct_asset_codes()


def get_signal_health_payload() -> dict[str, Any]:
    """Return health payload for the signal service."""

    return {
        "status": "healthy",
        "service": "signal",
        "records_count": DjangoSignalRepository().count_signal_records(),
    }


def validate_signal_eligibility_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Run a lightweight eligibility validation for the signal API."""

    current_regime = resolve_current_regime()
    if not current_regime or current_regime.dominant_regime == "Unknown":
        raise LookupError("No regime data available")

    raw_asset_code = data.get("asset_code")
    if not isinstance(raw_asset_code, str):
        raise ValueError("asset_code is invalid")
    asset_code = _asset_code(raw_asset_code)
    asset_class = _infer_asset_class(asset_code)
    eligibility = check_eligibility(
        asset_class=asset_class,
        regime=current_regime.dominant_regime,
    )
    is_eligible = eligibility.value != "hostile"
    return {
        "success": True,
        "is_eligible": is_eligible,
        "eligibility": eligibility.value if eligibility else None,
        "regime_match": is_eligible,
        "policy_match": True,
        "current_regime": current_regime.dominant_regime,
        "rejection_reason": (
            None
            if is_eligible
            else f"当前 Regime ({current_regime.dominant_regime}) 对资产类别 {asset_class} 不友好"
        ),
    }


def validate_existing_signal_payload(signal_id: str) -> dict[str, Any] | None:
    """Validate one existing signal against current regime context."""

    signal = get_investment_signal_payload(signal_id)
    if signal is None:
        return None

    required_fields = (
        "asset_code",
        "asset_class",
        "direction",
        "logic_desc",
        "target_regime",
    )
    if any(not isinstance(signal.get(field_name), str) for field_name in required_fields):
        raise ValueError("Persisted signal payload is invalid")
    current_regime = get_current_regime_payload()
    dominant_regime = current_regime.get("dominant_regime")
    confidence = current_regime.get("confidence")
    if (
        not isinstance(dominant_regime, str)
        or dominant_regime not in _REGIMES
        or isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not isfinite(float(confidence))
        or not 0 <= confidence <= 1
    ):
        raise ValueError("Current regime payload is invalid")
    response = ValidateSignalUseCase().execute(
        ValidateSignalRequest(
            asset_code=cast(str, signal["asset_code"]),
            asset_class=cast(str, signal["asset_class"]),
            direction=cast(str, signal["direction"]),
            logic_desc=cast(str, signal["logic_desc"]),
            invalidation_logic=(
                signal["invalidation_description"]
                if isinstance(signal.get("invalidation_description"), str)
                else ""
            ),
            invalidation_threshold=None,
            target_regime=cast(str, signal["target_regime"]),
            current_regime=dominant_regime,
            policy_level=0,
            regime_confidence=float(confidence),
        )
    )
    return {
        "success": response.is_valid,
        "is_eligible": response.is_approved,
        "eligibility": None if response.is_approved else "hostile",
        "rejection_reason": (
            response.rejection_record.reason if response.rejection_record is not None else None
        ),
        "warnings": response.warnings,
    }


def update_investment_signal_status(
    *,
    signal_id: str,
    status: str,
    rejection_reason: str = "",
) -> dict[str, Any] | None:
    """Update one investment signal status."""

    normalized_id = _signal_id_or_none(signal_id)
    if normalized_id is None:
        return None
    normalized_status = status.strip()
    if normalized_status not in _STATUSES:
        raise ValueError("status is invalid")
    return DjangoSignalRepository().update_signal_record_status(
        signal_id=normalized_id,
        status=normalized_status,
        rejection_reason=_bounded_text(
            rejection_reason,
            field_name="rejection_reason",
            maximum=1000,
            allow_blank=True,
        ),
    )


def delete_investment_signal_record(signal_id: str) -> str | None:
    """Delete one investment signal and return its asset code."""

    normalized_id = _signal_id_or_none(signal_id)
    if normalized_id is None:
        return None
    return DjangoSignalRepository().delete_signal_record(normalized_id)


def get_pending_unified_signals(
    *,
    min_priority: int,
    signal_type: str | None = None,
) -> list[dict[str, Any]]:
    """Return pending unified signals."""

    normalized_priority = _positive_integer(
        min_priority,
        field_name="min_priority",
        maximum=100,
    )
    normalized_type = (
        _bounded_text(
            signal_type,
            field_name="signal_type",
            maximum=64,
        )
        if signal_type is not None
        else None
    )
    return UnifiedSignalRepository().get_pending_signals(
        min_priority=normalized_priority,
        signal_type=normalized_type,
    )


def get_unified_signals_by_asset(
    *,
    asset_code: str,
    days: int,
    signal_source: str | None = None,
) -> list[dict[str, Any]]:
    """Return unified signals for one asset."""

    normalized_days = _positive_integer(
        days,
        field_name="days",
        maximum=_MAX_UNIFIED_DAYS,
    )
    normalized_source = (
        _bounded_text(
            signal_source,
            field_name="signal_source",
            maximum=64,
        )
        if signal_source is not None
        else None
    )
    return UnifiedSignalRepository().get_signals_by_asset(
        _asset_code(asset_code),
        days=normalized_days,
        signal_source=normalized_source,
    )


def mark_unified_signal_executed(signal_id: int | str) -> bool:
    """Mark one unified signal as executed."""

    try:
        normalized_id = _positive_integer(
            signal_id,
            field_name="signal_id",
        )
    except ValueError:
        return False
    return UnifiedSignalRepository().mark_executed(normalized_id)


def get_signal_invalidation_payloads(signal_ids: list[int]) -> dict[str, dict[str, Any]]:
    """Return invalidation payloads keyed by signal id."""
    if len(signal_ids) > _MAX_INVALIDATION_IDS:
        raise ValueError("Too many signal IDs")
    normalized_ids = sorted(
        {_positive_integer(signal_id, field_name="signal_id") for signal_id in signal_ids}
    )
    if not normalized_ids:
        return {}
    return DjangoSignalRepository().get_invalidation_payloads(normalized_ids)


def list_active_signal_payloads_by_asset(
    *,
    asset_code: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Return recent active signal payloads for one asset code."""

    normalized_limit = _positive_integer(
        limit,
        field_name="limit",
        maximum=100,
    )
    signals = DjangoSignalRepository().get_signals_by_asset(
        asset_code=_asset_code(asset_code),
        status=SignalStatus.APPROVED,
    )
    return [
        {
            "id": signal.id,
            "asset_code": signal.asset_code,
            "direction": signal.direction,
            "logic_desc": signal.logic_desc,
            "created_at": signal.created_at,
            "status": getattr(signal.status, "value", signal.status),
        }
        for signal in signals[:normalized_limit]
    ]
