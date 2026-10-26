"""Corrupt numeric source values remain UNKNOWN and cannot be recast as N/A."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from math import inf, nan

import pytest

from apps.risk_center.domain.m1_rebalance_risk_policy import (
    M1RiskCondition,
    M1RiskPolicyPublishCommand,
    M1RiskPolicyRevision,
    RiskApplicability,
    RiskQualificationState,
    qualify_revision,
    validate_publish_command,
)
from apps.simulated_trading.application.m1_rebalance_risk_policy import (
    build_m1_risk_source_snapshot,
)
from apps.simulated_trading.infrastructure.m1_risk_policy_account_source_reader import (
    _account_source_from_row,
)
from apps.strategy.application.execution_gateway import InspectionSelection
from apps.strategy.infrastructure.models import StrategyModel
from apps.strategy.infrastructure.position_rule_source_snapshot import (
    invalid_strategy_risk_limit_fields,
)

NOW = datetime(2026, 10, 26, 2, 0, tzinfo=UTC)


def _account_row(
    *,
    max_position_pct: object = 20.0,
    max_total_position_pct: object = 95.0,
    stop_loss_pct: object = 8.0,
) -> dict[str, object]:
    """Return raw DB-shaped values before source normalization."""

    return {
        "id": 613,
        "user_id": 41,
        "account_type": "simulated",
        "is_active": True,
        "max_position_pct": max_position_pct,
        "max_total_position_pct": max_total_position_pct,
        "stop_loss_pct": stop_loss_pct,
    }


@pytest.mark.parametrize(
    "raw_value",
    (
        None,
        nan,
        inf,
        -inf,
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("-Infinity"),
        -1.0,
        101.0,
        "not-a-number",
        True,
    ),
)
def test_nonnullable_account_limit_corruption_is_not_normalized_to_unconfigured(
    raw_value: object,
) -> None:
    """Non-finite, out-of-range, null, and malformed nonnullable DB values retain a marker."""

    source = _account_source_from_row(_account_row(max_position_pct=raw_value))

    assert source is not None
    assert source.max_single_position_pct is None
    assert source.invalid_limit_fields == ("max_single_position_pct",)


@pytest.mark.parametrize("raw_value", (nan, inf, -inf, -1.0, 101.0, "broken"))
def test_malformed_strategy_limit_is_kept_as_a_corruption_marker(raw_value: object) -> None:
    """The Strategy source mapper records the affected public risk dimension."""

    strategy = StrategyModel(
        max_position_pct=raw_value,
        max_total_position_pct=95.0,
        stop_loss_pct=None,
    )

    assert invalid_strategy_risk_limit_fields(strategy) == ("max_single_position_pct",)


def test_nullable_strategy_stop_loss_remains_explicitly_unconfigured() -> None:
    """A genuine Strategy stop-loss NULL is not converted to zero or corruption."""

    strategy = StrategyModel(
        max_position_pct=20.0,
        max_total_position_pct=95.0,
        stop_loss_pct=None,
    )

    assert invalid_strategy_risk_limit_fields(strategy) == ()


def test_nullable_stop_loss_null_is_legitimate_but_nonnullable_null_is_unknown() -> None:
    """A real stop-loss NULL remains distinct from a corrupt max-position NULL."""

    source = _account_source_from_row(_account_row(max_position_pct=20.0, stop_loss_pct=None))

    assert source is not None
    assert source.stop_loss_pct is None
    assert source.invalid_limit_fields == ()


@pytest.mark.parametrize("raw_value", (nan, inf, -inf, -1.0, 101.0, "broken"))
def test_nonnull_malformed_stop_loss_is_not_the_same_as_legal_null(raw_value: object) -> None:
    """Only SQL NULL is explicit legacy stop-loss absence; malformed values are corrupt."""

    source = _account_source_from_row(_account_row(stop_loss_pct=raw_value))

    assert source is not None
    assert source.stop_loss_pct is None
    assert source.invalid_limit_fields == ("stop_loss_pct",)


def test_invalid_source_blocks_publication_even_when_owner_claims_dimension_not_applicable() -> (
    None
):
    """N/A cannot make a broken configured account field disappear at publication."""

    account_source = _account_source_from_row(_account_row(max_position_pct=nan))
    assert account_source is not None
    strategy_selection = InspectionSelection(
        strategy_id=None,
        position_rule_id=None,
        rule_metadata={},
        selection_state="confirmed_unconfigured",
    )
    source = build_m1_risk_source_snapshot(
        account_source=account_source,
        strategy_selection=strategy_selection,
    )
    command = M1RiskPolicyPublishCommand(
        account_id=613,
        actor_user_id=41,
        effective_from=NOW,
        effective_until=NOW + timedelta(days=5),
        reason="Owner reviewed the current explicit risk conditions.",
        max_single_position=M1RiskCondition(
            applicability=RiskApplicability.NOT_APPLICABLE,
            limit_pct=None,
            not_applicable_reason="The owner claims this source does not apply.",
        ),
        max_total_position=M1RiskCondition(
            applicability=RiskApplicability.APPLICABLE,
            limit_pct=Decimal("90"),
        ),
        max_stop_loss=M1RiskCondition(
            applicability=RiskApplicability.APPLICABLE,
            limit_pct=Decimal("7"),
        ),
        source_snapshot=source,
    )

    reasons = validate_publish_command(command)

    assert "ACCOUNT_MAX_SINGLE_POSITION_SOURCE_UNKNOWN" in reasons


def test_invalid_source_keeps_a_preview_qualification_unknown() -> None:
    """A corrupted source snapshot cannot qualify a BUY after a version is read."""

    account_source = _account_source_from_row(_account_row(max_total_position_pct=inf))
    assert account_source is not None
    strategy_selection = InspectionSelection(
        strategy_id=None,
        position_rule_id=None,
        rule_metadata={},
        selection_state="confirmed_unconfigured",
    )
    source = build_m1_risk_source_snapshot(
        account_source=account_source,
        strategy_selection=strategy_selection,
    )
    valid_account_source = _account_source_from_row(_account_row())
    assert valid_account_source is not None
    valid_source = build_m1_risk_source_snapshot(
        account_source=valid_account_source,
        strategy_selection=strategy_selection,
    )
    revision = M1RiskPolicyRevision(
        risk_policy_version="3a34a114-ea06-4b80-bc73-35bc67850b1f",
        account_id=613,
        actor_user_id=41,
        effective_from=NOW,
        effective_until=NOW + timedelta(days=5),
        known_at=NOW - timedelta(minutes=1),
        reason="A previously explicit owner decision.",
        max_single_position=M1RiskCondition(RiskApplicability.APPLICABLE, Decimal("19")),
        max_total_position=M1RiskCondition(RiskApplicability.APPLICABLE, Decimal("90")),
        max_stop_loss=M1RiskCondition(
            RiskApplicability.NOT_APPLICABLE, None, "No configured stop-loss."
        ),
        source_snapshot=valid_source,
    )

    result = qualify_revision(
        revision=revision,
        account_id=613,
        as_of=NOW + timedelta(seconds=1),
        current_source=source,
    )

    assert result.state is RiskQualificationState.UNKNOWN
    assert "ACCOUNT_MAX_TOTAL_POSITION_SOURCE_UNKNOWN" in result.reason_codes
    assert result.ready_for_buy is False
