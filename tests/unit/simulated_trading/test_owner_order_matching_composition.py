"""Owner-match composition must remain inert until an explicit request executes."""

from __future__ import annotations

import pytest

from apps.simulated_trading import local_daily_match_composition
from apps.simulated_trading import owner_order_matching_composition as composition
from apps.simulated_trading.application.owner_order_matching import OwnerOrderMatchUseCase


def test_owner_match_factory_builds_lazy_source_and_calendar_readers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Composition binds real readers without querying config, policy, or QMT state."""

    def forbidden(*_args: object, **_kwargs: object) -> None:
        pytest.fail("composition must not read source or runtime state")

    class _Bindings:
        """Stand in for the public QMT service without permitting a list query."""

        def list_bindings(self, owner_id: int) -> list[dict[str, object]]:
            del owner_id
            forbidden()
            return []

    monkeypatch.setattr(composition, "_runtime_environment_from_settings_module", lambda: "dev")
    monkeypatch.setattr(composition, "build_qmt_bridge_service", lambda: _Bindings())
    monkeypatch.setattr(
        local_daily_match_composition,
        "get_published_price_bar_source",
        forbidden,
    )
    monkeypatch.setattr(
        local_daily_match_composition,
        "read_instrument_reference_snapshot",
        forbidden,
    )
    monkeypatch.setattr(local_daily_match_composition, "read_qmt_daily_status", forbidden)
    monkeypatch.setattr(
        local_daily_match_composition,
        "read_published_price_limit_reference",
        forbidden,
    )
    monkeypatch.setattr(
        composition,
        "read_calendar_capture_configuration_reference_at",
        forbidden,
    )

    use_case = composition.build_owner_order_matching_use_case()

    assert type(use_case) is OwnerOrderMatchUseCase
    assert callable(use_case.execute)
