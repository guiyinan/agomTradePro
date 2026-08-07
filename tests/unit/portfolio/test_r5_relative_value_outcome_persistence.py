"""Application contracts for Portfolio-owned R5 outcome persistence."""

from __future__ import annotations

from dataclasses import fields
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from apps.fixed_income.application.relative_value_projection import (
    project_r5_relative_value_owner_record,
)
from apps.fixed_income.domain.relative_value_record_seal import (
    R5RelativeValueOwnerRecordSeal,
)
from apps.portfolio.application.r5_relative_value_outcome import (
    PersistR5PortfolioOutcomeCommand,
    R5PortfolioOutcomePersistenceDraft,
    R5PortfolioOutcomeSourceRecord,
    r5_portfolio_outcome_command_hash,
)
from apps.portfolio.domain.r5_relative_value_outcome import R5PortfolioOutcomeSeal
from tests.unit.research.r5_relative_value_promotion_factories import make_persisted_bundles


def _fixed_income(monkeypatch: pytest.MonkeyPatch) -> R5RelativeValueOwnerRecordSeal:
    bundle, _ = make_persisted_bundles(monkeypatch)
    return project_r5_relative_value_owner_record(bundle)


def _source(
    fixed_income: R5RelativeValueOwnerRecordSeal,
) -> R5PortfolioOutcomeSourceRecord:
    selection_as_of = fixed_income.recorded_at + timedelta(days=1)
    return R5PortfolioOutcomeSourceRecord.create(
        owner_record_id="portfolio-outcome-owner-1",
        owner_record_version="portfolio-outcome-owner.v1",
        observation_id="portfolio-observation-1",
        fixed_income_result_id=fixed_income.result_id,
        fixed_income_result_version=fixed_income.result_version,
        fixed_income_result_record_hash=fixed_income.result_record_hash,
        selection_as_of=selection_as_of,
        outcome_observed_at=selection_as_of + timedelta(days=30),
        outcome_available_at=selection_as_of + timedelta(days=31),
        valid_until=selection_as_of + timedelta(days=90),
        target_gross_return=Decimal("0.08"),
        target_cost=Decimal("0.01"),
        benchmark_gross_return=Decimal("0.05"),
        benchmark_cost=Decimal("0.005"),
        target_maximum_drawdown=Decimal("0.10"),
        benchmark_maximum_drawdown=Decimal("0.12"),
        capacity_utilization=Decimal("0.75"),
        liquidity_breached=False,
        realized_credit_loss=Decimal("0"),
    )


def test_persistence_command_is_strictly_id_version_only() -> None:
    command = PersistR5PortfolioOutcomeCommand(
        owner_record_id="portfolio-outcome-owner-1",
        owner_record_version="portfolio-outcome-owner.v1",
    )

    assert tuple(field.name for field in fields(command)) == (
        "owner_record_id",
        "owner_record_version",
    )
    assert command.command_hash == r5_portfolio_outcome_command_hash(
        owner_record_id=command.owner_record_id,
        owner_record_version=command.owner_record_version,
    )


def test_draft_binds_authoritative_portfolio_record_to_exact_fixed_income_seal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixed_income = _fixed_income(monkeypatch)
    source = _source(fixed_income)

    draft = R5PortfolioOutcomePersistenceDraft(
        source_record=source,
        fixed_income_record=fixed_income,
    )
    recorded_at = source.outcome_available_at + timedelta(seconds=1)
    outcome = draft.to_outcome(recorded_at=recorded_at)

    assert isinstance(outcome, R5PortfolioOutcomeSeal)
    assert outcome.owner_record_hash == source.owner_record_hash
    assert outcome.fixed_income_owner_seal_hash == fixed_income.content_hash
    assert outcome.recorded_at == recorded_at
    assert outcome.is_active_at(recorded_at)


def test_draft_rejects_fabricated_or_mismatched_fixed_income_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixed_income = _fixed_income(monkeypatch)
    source = _source(fixed_income)
    mismatched = R5PortfolioOutcomeSourceRecord.create(
        **{
            **source.factory_values,
            "fixed_income_result_record_hash": "f" * 64,
        }
    )

    with pytest.raises(ValueError, match="fixed-income"):
        R5PortfolioOutcomePersistenceDraft(
            source_record=mismatched,
            fixed_income_record=fixed_income,
        )


def test_source_record_rejects_naive_clocks_and_noncanonical_hash_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixed_income = _fixed_income(monkeypatch)
    source = _source(fixed_income)

    with pytest.raises(ValueError, match="timezone-aware"):
        R5PortfolioOutcomeSourceRecord.create(
            **{
                **source.factory_values,
                "selection_as_of": datetime(2026, 8, 1),
            }
        )
    with pytest.raises(ValueError, match="hash"):
        R5PortfolioOutcomeSourceRecord(
            **{
                **source.constructor_values,
                "owner_record_hash": "0" * 64,
            }
        )


def test_server_clock_must_be_after_availability_and_before_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixed_income = _fixed_income(monkeypatch)
    source = _source(fixed_income)
    draft = R5PortfolioOutcomePersistenceDraft(source, fixed_income)

    with pytest.raises(ValueError, match="clocks"):
        draft.to_outcome(recorded_at=source.outcome_available_at - timedelta(seconds=1))
    with pytest.raises(ValueError, match="clocks"):
        draft.to_outcome(recorded_at=source.valid_until)


def test_owner_move_keeps_research_compatibility_class_identity() -> None:
    from apps.research.domain.r5_relative_value_portfolio_outcome import (
        R5PortfolioOutcomeSeal as CompatibilityOutcome,
    )
    from apps.research.domain.r5_relative_value_promotion_record import (
        R5RelativeValueOwnerRecordSeal as CompatibilityFixedIncome,
    )

    assert CompatibilityOutcome is R5PortfolioOutcomeSeal
    assert CompatibilityFixedIncome is R5RelativeValueOwnerRecordSeal
