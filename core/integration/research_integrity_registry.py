"""Runtime provider registry for research-integrity cross-app contracts."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

_pit_view_factory: Callable[[str], Any] | None = None
_decision_snapshot_getter: Callable[[str], Any] | None = None
_pit_manifest_evidence_getter: Callable[[str], dict[str, Any] | None] | None = None
_backtest_evidence_getter: Callable[[int], dict[str, Any] | None] | None = None
_research_promotion_checker: Callable[[str], bool] | None = None
_active_prompt_checker: Callable[[str], bool] | None = None
_forecast_entry_provider: Callable[[], Any] | None = None
_forecast_evaluation_recorder: Callable[..., Any] | None = None
_scenario_forecast_reference_checker: Callable[[str, str | None], bool] | None = None


def configure_pit_providers(
    *,
    view_factory: Callable[[str], Any],
    manifest_evidence_getter: Callable[[str], dict[str, Any] | None],
) -> None:
    global _pit_view_factory, _pit_manifest_evidence_getter
    _pit_view_factory = view_factory
    _pit_manifest_evidence_getter = manifest_evidence_getter


def make_manifest_bound_pit_view(manifest_id: str) -> Any:
    if _pit_view_factory is None:
        raise RuntimeError("PIT provider is not configured")
    return _pit_view_factory(manifest_id)


def get_pit_manifest_evidence(manifest_id: str) -> dict[str, Any] | None:
    if _pit_manifest_evidence_getter is None:
        raise RuntimeError("PIT manifest provider is not configured")
    return _pit_manifest_evidence_getter(manifest_id)


def configure_decision_snapshot_getter(getter: Callable[[str], Any]) -> None:
    global _decision_snapshot_getter
    _decision_snapshot_getter = getter


def get_decision_snapshot(snapshot_id: str) -> Any:
    if _decision_snapshot_getter is None:
        raise RuntimeError("decision snapshot provider is not configured")
    return _decision_snapshot_getter(snapshot_id)


def configure_backtest_evidence_getter(
    getter: Callable[[int], dict[str, Any] | None],
) -> None:
    global _backtest_evidence_getter
    _backtest_evidence_getter = getter


def get_backtest_evidence(backtest_id: int) -> dict[str, Any] | None:
    if _backtest_evidence_getter is None:
        raise RuntimeError("backtest evidence provider is not configured")
    return _backtest_evidence_getter(backtest_id)


def configure_research_promotion_checker(checker: Callable[[str], bool]) -> None:
    global _research_promotion_checker
    _research_promotion_checker = checker


def is_research_promotion_approved(decision_id: str) -> bool:
    return bool(_research_promotion_checker and _research_promotion_checker(decision_id))


def configure_active_prompt_checker(checker: Callable[[str], bool]) -> None:
    global _active_prompt_checker
    _active_prompt_checker = checker


def is_prompt_version_active(version_id: str) -> bool:
    return bool(_active_prompt_checker and _active_prompt_checker(version_id))


def configure_forecast_entry_provider(provider: Callable[[], Any]) -> None:
    """Register the read provider used by the audit forecast scoreboard."""

    global _forecast_entry_provider
    _forecast_entry_provider = provider


def get_finalized_forecast_entries() -> Any:
    """Return finalized forecast entries without importing signal infrastructure."""

    if _forecast_entry_provider is None:
        raise RuntimeError("forecast ledger provider is not configured")
    return _forecast_entry_provider()


def configure_forecast_evaluation_recorder(recorder: Callable[..., Any]) -> None:
    """Register the signal-owned writer used by scheduled invalidation checks."""

    global _forecast_evaluation_recorder
    _forecast_evaluation_recorder = recorder


def record_forecast_evaluation_for_signal(
    *,
    signal_id: str,
    checked_at: Any,
    data_version_ids: list[int],
    conditions: list[dict[str, Any]],
    missing_reason: str,
) -> Any:
    """Append one forecast check when a ledger entry exists for the signal."""

    if _forecast_evaluation_recorder is None:
        raise RuntimeError("forecast evaluation recorder is not configured")
    return _forecast_evaluation_recorder(
        signal_id=signal_id,
        checked_at=checked_at,
        data_version_ids=data_version_ids,
        conditions=conditions,
        missing_reason=missing_reason,
    )


def configure_scenario_forecast_reference_checker(
    checker: Callable[[str, str | None], bool],
) -> None:
    """Register the Risk Center-owned immutable revision membership checker."""

    global _scenario_forecast_reference_checker
    _scenario_forecast_reference_checker = checker


def is_scenario_forecast_reference_valid(
    scenario_revision_id: str,
    scenario_set_revision_id: str | None,
) -> bool:
    """Fail closed unless Risk Center confirms the published revision reference."""

    return bool(
        _scenario_forecast_reference_checker
        and _scenario_forecast_reference_checker(
            scenario_revision_id,
            scenario_set_revision_id,
        )
    )
