"""Single-table persistence invariants across v1 and v2 rule schemas."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from threading import Barrier

import pytest
from django.db import connections

from apps.risk_center.application.ashare_execution_rule_catalog import (
    ExecutionRuleConflict,
    ExecutionRuleUnavailable,
    ExecutionRuleVersionMismatch,
)
from apps.risk_center.domain.execution_submission_v2 import ExecutionSubmissionRuleV2
from apps.risk_center.domain.execution_trading_constraints import (
    AShareExecutionRule,
    ExecutionQuantityConstraint,
    SellOddLotMode,
)
from apps.risk_center.domain.price_submission_range import (
    PriceRoundingMode,
    PriceSubmissionRangeRule,
    PriceSubmissionStage,
)
from apps.risk_center.infrastructure.ashare_execution_rule_models import (
    AShareExecutionRuleModel,
)
from apps.risk_center.infrastructure.ashare_execution_rule_repository import (
    DjangoAShareExecutionRuleRepository,
)

AS_OF = datetime(2026, 10, 16, 2, 0, tzinfo=UTC)


class _FixedClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value


def _rule_v1(
    *,
    security_id: str = "V2.COMPONENT.SECURITY",
    rule_id: str = "component-rule",
    effective_from: datetime | None = None,
    valid_until: datetime | None = None,
) -> AShareExecutionRule:
    return AShareExecutionRule(
        rule_id=rule_id,
        rule_version="1",
        security_id=security_id,
        market="SH",
        board="MAIN",
        buy_quantity=ExecutionQuantityConstraint(
            minimum=Decimal("100"), step=Decimal("100"), maximum=Decimal("10000")
        ),
        sell_quantity=ExecutionQuantityConstraint(
            minimum=Decimal("100"), step=Decimal("100"), maximum=Decimal("10000")
        ),
        sell_odd_lot_mode=SellOddLotMode.FORBID,
        price_tick=Decimal("0.01"),
        rule_source_id="component-source",
        rule_source_version="fixture-v1",
        rule_source_hash="b" * 64,
        source_observed_at=AS_OF - timedelta(days=1),
        source_available_at=AS_OF - timedelta(hours=1),
        effective_from=effective_from or AS_OF - timedelta(minutes=30),
        valid_until=valid_until or AS_OF + timedelta(days=1),
    )


def _rule_v2(
    *,
    security_id: str = "V2.COMPONENT.SECURITY",
    rule_id: str = "component-rule-v2",
    effective_from: datetime | None = None,
    valid_until: datetime | None = None,
) -> ExecutionSubmissionRuleV2:
    base = _rule_v1(
        security_id=security_id,
        rule_id=rule_id,
        effective_from=effective_from,
        valid_until=valid_until,
    )
    return ExecutionSubmissionRuleV2(
        execution_rule_v1=base,
        price_submission_range=PriceSubmissionRangeRule(
            market="SH",
            board="MAIN",
            price_tick=Decimal("0.01"),
            buy_deviation_ratio=Decimal("0.02"),
            sell_deviation_ratio=Decimal("0.02"),
            buy_widening_ticks=10,
            sell_widening_ticks=10,
            minimum_distance_ticks=1,
            lower_floor_ticks=1,
            rounding_mode=PriceRoundingMode.HALF_UP,
        ),
        allowed_stages=(PriceSubmissionStage.CONTINUOUS,),
    )


def _repository() -> DjangoAShareExecutionRuleRepository:
    return DjangoAShareExecutionRuleRepository(clock=_FixedClock(AS_OF - timedelta(minutes=1)))


@pytest.mark.django_db(transaction=True, available_apps=["apps.risk_center"])
def test_v2_repository_round_trips_and_replays_exact_content() -> None:
    repository = _repository()
    rule = _rule_v2()

    first = repository.import_submission_rules(rules=(rule,))
    replay = repository.import_submission_rules(rules=(rule,))

    assert (first.inserted_count, first.unchanged_count) == (1, 0)
    assert (replay.inserted_count, replay.unchanged_count) == (0, 1)
    stored = AShareExecutionRuleModel.objects.get(security_id=rule.execution_rule_v1.security_id)
    assert stored.canonical_payload == rule.to_payload()
    assert (
        repository.get_effective_submission_rule(
            security_id=rule.execution_rule_v1.security_id, as_of=AS_OF
        )
        == rule
    )


@pytest.mark.django_db(transaction=True, available_apps=["apps.risk_center"])
def test_repository_reads_reject_cross_version_without_implicit_conversion() -> None:
    repository = _repository()
    v1 = _rule_v1(rule_id="v1-only")
    repository.import_rules(rules=(v1,))
    with pytest.raises(ExecutionRuleVersionMismatch):
        repository.get_effective_submission_rule(security_id=v1.security_id, as_of=AS_OF)

    AShareExecutionRuleModel.objects.filter(security_id=v1.security_id).delete()
    v2 = _rule_v2(rule_id="v2-only")
    repository.import_submission_rules(rules=(v2,))
    with pytest.raises(ExecutionRuleVersionMismatch):
        repository.get_effective_rule(security_id=v1.security_id, as_of=AS_OF)


@pytest.mark.django_db(transaction=True, available_apps=["apps.risk_center"])
@pytest.mark.parametrize("insert_v2_first", [False, True])
def test_same_security_effective_overlap_conflicts_across_rule_versions(
    insert_v2_first: bool,
) -> None:
    repository = _repository()
    v1 = _rule_v1(rule_id="overlap-v1")
    v2 = _rule_v2(rule_id="overlap-v2")

    if insert_v2_first:
        repository.import_submission_rules(rules=(v2,))
        with pytest.raises(ExecutionRuleConflict):
            repository.import_rules(rules=(v1,))
    else:
        repository.import_rules(rules=(v1,))
        with pytest.raises(ExecutionRuleConflict):
            repository.import_submission_rules(rules=(v2,))

    assert AShareExecutionRuleModel.objects.count() == 1


@pytest.mark.django_db(transaction=True, available_apps=["apps.risk_center"])
def test_v2_identity_is_immutable_and_late_recorded_time_is_hidden() -> None:
    recorded_at = AS_OF + timedelta(hours=1)
    repository = DjangoAShareExecutionRuleRepository(clock=_FixedClock(recorded_at))
    rule = _rule_v2()
    repository.import_submission_rules(rules=(rule,))
    changed = replace(
        rule,
        price_submission_range=replace(rule.price_submission_range, buy_widening_ticks=11),
        content_hash="",
    )

    with pytest.raises(ExecutionRuleConflict):
        repository.import_submission_rules(rules=(changed,))
    with pytest.raises(ExecutionRuleUnavailable):
        repository.get_effective_submission_rule(
            security_id=rule.execution_rule_v1.security_id, as_of=AS_OF
        )
    assert (
        repository.get_effective_submission_rule(
            security_id=rule.execution_rule_v1.security_id, as_of=recorded_at
        )
        == rule
    )


@pytest.mark.django_db(transaction=True, available_apps=["apps.risk_center"])
def test_cross_schema_batch_conflict_rolls_back_unrelated_v2_rule() -> None:
    repository = _repository()
    existing = _rule_v1(security_id="EXISTING.SECURITY", rule_id="existing")
    repository.import_rules(rules=(existing,))
    unrelated = _rule_v2(security_id="NEW.SECURITY", rule_id="unrelated")
    overlapping = _rule_v2(security_id=existing.security_id, rule_id="overlap")

    with pytest.raises(ExecutionRuleConflict):
        repository.import_submission_rules(rules=(unrelated, overlapping))

    assert AShareExecutionRuleModel.objects.count() == 1


@pytest.mark.django_db(transaction=True, available_apps=["apps.risk_center"])
def test_concurrent_cross_schema_overlapping_imports_have_one_winner() -> None:
    barrier = Barrier(2)
    v1 = _rule_v1(rule_id="concurrent-v1")
    v2 = _rule_v2(rule_id="concurrent-v2")

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures: tuple[Future[str], Future[str]] = (
            executor.submit(_import_after_barrier, barrier, v1),
            executor.submit(_import_after_barrier, barrier, v2),
        )
        outcomes = tuple(future.result(timeout=15) for future in futures)

    assert outcomes.count("inserted") == 1
    assert set(outcomes) <= {"inserted", "conflict", "unavailable"}
    assert AShareExecutionRuleModel.objects.count() == 1


def _import_after_barrier(
    barrier: Barrier, rule: AShareExecutionRule | ExecutionSubmissionRuleV2
) -> str:
    """Import either rule schema from independent thread-local DB connections."""

    connections.close_all()
    try:
        barrier.wait(timeout=5)
        repository = _repository()
        if type(rule) is AShareExecutionRule:
            repository.import_rules(rules=(rule,))
        else:
            repository.import_submission_rules(rules=(rule,))
        return "inserted"
    except ExecutionRuleConflict:
        return "conflict"
    except ExecutionRuleUnavailable:
        return "unavailable"
    finally:
        connections.close_all()
