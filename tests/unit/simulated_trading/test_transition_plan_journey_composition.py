"""Production journey wiring selects official coverage only from active configuration."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import Mock

import pytest

from apps.simulated_trading.application.rebalance_journey_public import (
    RebalanceJourneyUnavailable,
)
from apps.simulated_trading.transition_plan_journey_composition import (
    _official_event_gate_enabled,
    build_rebalance_journey_service,
)

_AS_OF = datetime(2026, 11, 11, 1, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        (None, False),
        ({"enabled": False}, False),
        ({"enabled": True}, True),
    ],
)
def test_official_event_gate_requires_explicit_active_toggle(
    monkeypatch: pytest.MonkeyPatch, configured: object, expected: bool
) -> None:
    """The unconfigured M1 path remains available; explicit enable selects capture."""

    calls: list[tuple[str, str, datetime]] = []

    def read(*, environment: str, definition_key: str, as_of: datetime) -> object:
        calls.append((environment, definition_key, as_of))
        return configured

    monkeypatch.setattr(
        "apps.simulated_trading.transition_plan_journey_composition.get_active_runtime_value",
        read,
    )
    assert _official_event_gate_enabled(runtime_environment="development", as_of=_AS_OF) is expected
    assert calls == [
        (
            "development",
            "config_center.market.simulated_disclosure_coverage_policy",
            _AS_OF,
        )
    ]


def test_official_event_gate_rejects_malformed_active_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A present but invalid toggle cannot silently fall back to the M1 path."""

    monkeypatch.setattr(
        "apps.simulated_trading.transition_plan_journey_composition.get_active_runtime_value",
        lambda **kwargs: {"enabled": "yes"},
    )
    with pytest.raises(RebalanceJourneyUnavailable) as error:
        _official_event_gate_enabled(runtime_environment="development", as_of=_AS_OF)
    assert error.value.code == "REBALANCE_PLAN_EVENT_POLICY_INVALID"


@pytest.mark.parametrize("enabled", [False, True])
def test_production_journey_selects_capture_and_pin_as_one_opt_in_unit(
    monkeypatch: pytest.MonkeyPatch, enabled: bool
) -> None:
    """Active selection wires both source capture and final proof pin to plan creation."""

    pinner = Mock()
    refresher = Mock()
    build_pinner = Mock(return_value=pinner)
    build_refresher = Mock(return_value=refresher)
    monkeypatch.setattr(
        "apps.simulated_trading.transition_plan_journey_composition.get_active_runtime_value",
        lambda **kwargs: {"enabled": True} if enabled else None,
    )
    monkeypatch.setattr(
        "apps.simulated_trading.transition_plan_journey_composition.build_configured_rebalance_journey_event_coverage_pinner",
        build_pinner,
    )
    monkeypatch.setattr(
        "apps.simulated_trading.transition_plan_journey_composition.build_official_szse_distribution_refresher",
        build_refresher,
    )

    service = build_rebalance_journey_service()
    provider = service._preparation_factory(
        target_weights="002727.SZ,100",
        reference_price_basis="market",
    )
    assert provider._event_coverage_required is enabled
    assert (provider._event_coverage_pinner is pinner) is enabled
    assert (provider._event_refresher is refresher) is enabled
    assert build_pinner.call_count == int(enabled)
    assert build_refresher.call_count == int(enabled)
