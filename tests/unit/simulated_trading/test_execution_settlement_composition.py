"""Explicit composition checks for settlement-bound simulated trading."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from apps.risk_center.domain.execution_settlement_v3 import ExecutionSettlementBundleV3
from apps.simulated_trading.application.execution_settlement_uow import (
    ExecuteSettlementBoundSimulatedTradeUseCase,
    ReleaseDueSimulatedSettlementsUseCase,
)
from apps.simulated_trading.application.fee_policy_v2 import (
    CreateFeePolicyVersionUseCase,
    FeePolicyVersionStorageUnavailable,
)
from apps.simulated_trading.domain.execution_settlement_identity import (
    ExecutionInstrumentIdentityEvidenceV1,
)
from apps.simulated_trading.domain.execution_settlement_uow import ExecutionCalendarEvidence
from apps.simulated_trading.execution_settlement_composition import (
    build_create_fee_policy_version_use_case,
    build_execute_settlement_bound_simulated_trade_use_case,
    build_release_due_simulated_settlements_use_case,
)
from apps.simulated_trading.infrastructure.execution_settlement_uow_repository import (
    DjangoSimulatedTradeExecutionRepository,
)
from apps.simulated_trading.infrastructure.fee_policy_v2_repository import (
    DjangoFeePolicyV2Repository,
)


class _RuleReader:
    def execute(self, *, security_id: str, as_of: datetime) -> ExecutionSettlementBundleV3:
        raise AssertionError("composition must not read a rule")


class _CalendarReader:
    def get_effective_execution_calendar(
        self,
        *,
        exchange: str,
        as_of: datetime,
        coverage_start: date | None,
    ) -> ExecutionCalendarEvidence | None:
        raise AssertionError("composition must not read a calendar")


class _IdentityReader:
    def get_execution_instrument_identity(
        self,
        *,
        security_id: str,
        asset_code: str,
        as_of: datetime,
    ) -> ExecutionInstrumentIdentityEvidenceV1 | None:
        raise AssertionError("composition must not read instrument identity")


class _Clock:
    def now(self) -> datetime:
        return datetime(2026, 10, 16, tzinfo=UTC)


def test_trade_composition_requires_ports_and_shares_alias_bound_repository() -> None:
    rule_reader = _RuleReader()
    calendar_reader = _CalendarReader()
    identity_reader = _IdentityReader()
    clock = _Clock()

    use_case = build_execute_settlement_bound_simulated_trade_use_case(
        using="execution_test",
        rule_reader=rule_reader,
        identity_reader=identity_reader,
        calendar_reader=calendar_reader,
        clock=clock,
    )

    assert type(use_case) is ExecuteSettlementBoundSimulatedTradeUseCase
    repository = use_case._repository
    assert type(repository) is DjangoSimulatedTradeExecutionRepository
    assert repository._using == "execution_test"
    assert use_case._fee_policy_reader is repository
    assert use_case._rule_reader is rule_reader
    assert use_case._identity_reader is identity_reader
    assert use_case._calendar_reader is calendar_reader
    assert use_case._clock is clock


def test_release_composition_requires_calendar_and_explicit_database_alias() -> None:
    calendar_reader = _CalendarReader()
    clock = _Clock()

    use_case = build_release_due_simulated_settlements_use_case(
        using="release_test",
        calendar_reader=calendar_reader,
        clock=clock,
    )

    assert type(use_case) is ReleaseDueSimulatedSettlementsUseCase
    assert type(use_case._repository) is DjangoSimulatedTradeExecutionRepository
    assert use_case._repository._using == "release_test"
    assert use_case._calendar_reader is calendar_reader
    assert use_case._clock is clock


def test_composition_rejects_an_invalid_alias_without_provider_defaults() -> None:
    with pytest.raises(ValueError, match="using"):
        build_release_due_simulated_settlements_use_case(
            using=" ",
            calendar_reader=_CalendarReader(),
            clock=_Clock(),
        )


def test_fee_policy_composition_retains_explicit_alias_without_database_access() -> None:
    """An operator-selected alias reaches the policy repository unchanged."""

    use_case = build_create_fee_policy_version_use_case(using="fee_operator_test")

    assert type(use_case) is CreateFeePolicyVersionUseCase
    assert type(use_case._repository) is DjangoFeePolicyV2Repository
    assert use_case._repository._using == "fee_operator_test"


@pytest.mark.parametrize("alias", ["", " ", "default "])
def test_fee_policy_composition_rejects_invalid_alias_without_a_default(alias: str) -> None:
    """A missing or noncanonical alias cannot fall back to the default database."""

    with pytest.raises(FeePolicyVersionStorageUnavailable, match="database alias"):
        build_create_fee_policy_version_use_case(using=alias)
