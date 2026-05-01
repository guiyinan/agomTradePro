"""Application-level query helpers for cross-app signal access."""

from __future__ import annotations

from typing import Any

from apps.macro.application.indicator_service import get_available_indicators_for_frontend
from apps.regime.application.current_regime import resolve_current_regime
from apps.signal.application.repository_provider import (
    DjangoSignalRepository,
    UnifiedSignalRepository,
)
from apps.signal.domain.rules import check_eligibility, get_eligibility_matrix
from core.integration.asset_names import resolve_asset_names_for_signals

from .use_cases import (
    GetRecommendedAssetsRequest,
    GetRecommendedAssetsUseCase,
    ValidateSignalRequest,
    ValidateSignalUseCase,
)


def get_current_regime_payload() -> dict[str, Any]:
    """Return current regime payload for signal pages."""

    from datetime import date

    latest = resolve_current_regime(as_of_date=date.today())
    return {
        "dominant_regime": latest.dominant_regime,
        "confidence": latest.confidence,
        "observed_at": latest.observed_at,
        "distribution": {},
    }


def get_recommended_assets_payload(regime: str) -> dict[str, Any]:
    """Return recommended assets for one regime."""

    response = GetRecommendedAssetsUseCase().execute(
        GetRecommendedAssetsRequest(current_regime=regime)
    )
    return {
        "recommended": response.recommended,
        "neutral": response.neutral,
        "hostile": response.hostile,
    }


def _infer_asset_class(asset_code: str) -> str:
    """Infer asset class from asset code for lightweight eligibility checks."""

    code = (asset_code or "").upper()
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

    repository = DjangoSignalRepository()
    signals = repository.list_signal_records(
        status_filter=status_filter,
        asset_class=asset_class,
        direction=direction,
        search=search,
    )

    asset_codes = [signal.asset_code for signal in signals if signal.asset_code]
    asset_name_map = resolve_asset_names_for_signals(asset_codes)
    for signal in signals:
        signal.asset_name = asset_name_map.get(signal.asset_code, signal.asset_code)

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
        "all_regimes": ["Recovery", "Overheat", "Stagflation", "Deflation"],
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
    invalidation_rules: dict | None,
    target_regime: str,
    is_approved: bool,
    rejection_reason: str,
) -> dict[str, Any]:
    """Create an investment signal via the signal repository."""

    return DjangoSignalRepository().create_signal_record(
        asset_code=asset_code,
        asset_class=asset_class,
        direction=direction,
        logic_desc=logic_desc,
        invalidation_logic=invalidation_logic,
        invalidation_threshold=invalidation_threshold,
        invalidation_rules=invalidation_rules,
        target_regime=target_regime,
        status="approved" if is_approved else "rejected",
        rejection_reason=rejection_reason,
    )


def list_investment_signal_payloads(
    *,
    status_filter: str = "",
    asset_class: str = "",
    direction: str = "",
    search: str = "",
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return serialized investment signals for API responses."""

    return DjangoSignalRepository().list_signal_payloads(
        status_filter=status_filter,
        asset_class=asset_class,
        direction=direction,
        search=search,
        limit=limit,
    )


def get_investment_signal_payload(signal_id: str) -> dict[str, Any] | None:
    """Return one investment signal payload by id."""

    return DjangoSignalRepository().get_signal_payload(signal_id)


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

    parser = InvalidationLogicParser()
    parse_result = parser.parse(invalidation_logic)
    if not parse_result.success:
        raise ValueError(f"解析失败: {parse_result.error}")

    return DjangoSignalRepository().create_signal_record(
        asset_code=asset_code,
        asset_class=asset_class,
        direction=direction,
        logic_desc=logic_desc,
        invalidation_logic=invalidation_logic,
        invalidation_threshold=None,
        invalidation_rules=None,
        invalidation_description=invalidation_logic,
        invalidation_rule_json=parse_result.rule.to_dict(),
        target_regime=target_regime,
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

    update_fields: dict[str, Any] = {}
    if asset_code is not None:
        update_fields["asset_code"] = asset_code
    if asset_class is not None:
        update_fields["asset_class"] = asset_class
    if direction is not None:
        update_fields["direction"] = direction
    if logic_desc is not None:
        update_fields["logic_desc"] = logic_desc
    if target_regime is not None:
        update_fields["target_regime"] = target_regime

    if invalidation_logic is not None:
        from apps.signal.domain.parser import InvalidationLogicParser

        parser = InvalidationLogicParser()
        parse_result = parser.parse(invalidation_logic)
        if not parse_result.success:
            raise ValueError(f"解析失败: {parse_result.error}")
        update_fields["invalidation_logic"] = invalidation_logic
        update_fields["invalidation_description"] = invalidation_logic
        update_fields["invalidation_rule_json"] = parse_result.rule.to_dict()

    return DjangoSignalRepository().update_signal_record_fields(signal_id, **update_fields)


def get_signal_stats_payload() -> dict[str, int]:
    """Return aggregate signal stats for the API."""

    return DjangoSignalRepository().get_signal_management_metadata()["stats"]


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

    asset_code = data.get("asset_code", "")
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
        "rejection_reason": None
        if is_eligible
        else f"当前 Regime ({current_regime.dominant_regime}) 对资产类别 {asset_class} 不友好",
    }


def validate_existing_signal_payload(signal_id: str) -> dict[str, Any] | None:
    """Validate one existing signal against current regime context."""

    signal = get_investment_signal_payload(signal_id)
    if signal is None:
        return None

    current_regime = get_current_regime_payload()
    response = ValidateSignalUseCase().execute(
        ValidateSignalRequest(
            asset_code=signal["asset_code"],
            asset_class=signal["asset_class"],
            direction=signal["direction"],
            logic_desc=signal["logic_desc"],
            invalidation_logic=signal.get("invalidation_description") or "",
            invalidation_threshold=None,
            target_regime=signal["target_regime"],
            current_regime=current_regime["dominant_regime"],
            policy_level=0,
            regime_confidence=float(current_regime["confidence"] or 0),
        )
    )
    return {
        "success": response.is_valid,
        "is_eligible": response.is_approved,
        "eligibility": None if response.is_approved else "hostile",
        "rejection_reason": (
            response.rejection_record.reason
            if response.rejection_record is not None
            else None
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

    return DjangoSignalRepository().update_signal_record_status(
        signal_id=signal_id,
        status=status,
        rejection_reason=rejection_reason,
    )


def delete_investment_signal_record(signal_id: str) -> str | None:
    """Delete one investment signal and return its asset code."""

    return DjangoSignalRepository().delete_signal_record(signal_id)


def get_pending_unified_signals(
    *,
    min_priority: int,
    signal_type: str | None = None,
) -> list[dict[str, Any]]:
    """Return pending unified signals."""

    return UnifiedSignalRepository().get_pending_signals(
        min_priority=min_priority,
        signal_type=signal_type,
    )


def get_unified_signals_by_asset(
    *,
    asset_code: str,
    days: int,
    signal_source: str | None = None,
) -> list[dict[str, Any]]:
    """Return unified signals for one asset."""

    return UnifiedSignalRepository().get_signals_by_asset(
        asset_code,
        days=days,
        signal_source=signal_source,
    )


def mark_unified_signal_executed(signal_id: int | str) -> bool:
    """Mark one unified signal as executed."""

    return UnifiedSignalRepository().mark_executed(signal_id)


def get_signal_invalidation_payloads(signal_ids: list[int]) -> dict[str, dict[str, Any]]:
    """Return invalidation payloads keyed by signal id."""
    normalized_ids = [signal_id for signal_id in signal_ids if signal_id]
    if not normalized_ids:
        return {}
    return DjangoSignalRepository().get_invalidation_payloads(normalized_ids)


def list_active_signal_payloads_by_asset(
    *,
    asset_code: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Return recent active signal payloads for one asset code."""

    signals = DjangoSignalRepository().get_signals_by_asset(
        asset_code=asset_code,
        status="approved",
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
        for signal in signals[:limit]
    ]
