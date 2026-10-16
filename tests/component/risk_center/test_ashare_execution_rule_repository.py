"""Database behavior for the single-table A-share rule catalog."""

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
    ExecutionRuleCorruption,
    ExecutionRuleUnavailable,
)
from apps.risk_center.domain.execution_trading_constraints import (
    AShareExecutionRule,
    ExecutionQuantityConstraint,
    SellOddLotMode,
)
from apps.risk_center.infrastructure.ashare_execution_rule_codec import (
    encode_a_share_execution_rule,
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


def _rule(
    *,
    security_id: str = "COMPONENT.SECURITY",
    rule_id: str = "component-rule",
    available_at: datetime | None = None,
    effective_from: datetime | None = None,
    valid_until: datetime | None = None,
    board: str = "fixture-board",
) -> AShareExecutionRule:
    return AShareExecutionRule(
        rule_id=rule_id,
        rule_version="v1",
        security_id=security_id,
        market="fixture-market",
        board=board,
        buy_quantity=ExecutionQuantityConstraint(
            minimum=Decimal("100"), step=Decimal("100"), maximum=Decimal("10000")
        ),
        sell_quantity=ExecutionQuantityConstraint(
            minimum=Decimal("100"), step=Decimal("100"), maximum=Decimal("10000")
        ),
        sell_odd_lot_mode=SellOddLotMode.FORBID,
        price_tick=Decimal("0.01"),
        rule_source_id="component-source",
        rule_source_version="v1",
        rule_source_hash="b" * 64,
        source_observed_at=AS_OF - timedelta(days=1),
        source_available_at=available_at or AS_OF - timedelta(hours=1),
        effective_from=effective_from or AS_OF - timedelta(hours=2),
        valid_until=valid_until or AS_OF + timedelta(days=1),
    )


@pytest.mark.django_db(transaction=True, available_apps=["apps.risk_center"])
def test_repository_persists_rule_idempotently_and_reads_exact_active_rule() -> None:
    repository = DjangoAShareExecutionRuleRepository(
        clock=_FixedClock(AS_OF - timedelta(minutes=1))
    )
    rule = _rule()

    first = repository.import_rules(rules=(rule,))
    repeated = repository.import_rules(rules=(rule,))

    assert (first.inserted_count, first.unchanged_count) == (1, 0)
    assert (repeated.inserted_count, repeated.unchanged_count) == (0, 1)
    assert AShareExecutionRuleModel.objects.count() == 1
    assert repository.get_effective_rule(security_id=rule.security_id, as_of=AS_OF) == rule


@pytest.mark.django_db(transaction=True, available_apps=["apps.risk_center"])
def test_repository_rejects_changed_content_for_same_rule_identity() -> None:
    repository = DjangoAShareExecutionRuleRepository(
        clock=_FixedClock(AS_OF - timedelta(minutes=1))
    )
    original = _rule()
    changed = replace(original, board="changed-board", content_hash="")
    repository.import_rules(rules=(original,))

    with pytest.raises(ExecutionRuleConflict):
        repository.import_rules(rules=(changed,))

    assert AShareExecutionRuleModel.objects.count() == 1


@pytest.mark.django_db(transaction=True, available_apps=["apps.risk_center"])
def test_repository_does_not_expose_rule_before_source_available_time() -> None:
    repository = DjangoAShareExecutionRuleRepository(
        clock=_FixedClock(AS_OF - timedelta(minutes=1))
    )
    rule = _rule(
        available_at=AS_OF + timedelta(hours=1),
        effective_from=AS_OF - timedelta(hours=2),
    )
    repository.import_rules(rules=(rule,))

    with pytest.raises(ExecutionRuleUnavailable):
        repository.get_effective_rule(security_id=rule.security_id, as_of=AS_OF)

    assert (
        repository.get_effective_rule(
            security_id=rule.security_id,
            as_of=AS_OF + timedelta(hours=1),
        )
        == rule
    )


@pytest.mark.django_db(transaction=True, available_apps=["apps.risk_center"])
def test_repository_does_not_expose_rule_before_local_recorded_time() -> None:
    imported_at = AS_OF + timedelta(hours=1)
    repository = DjangoAShareExecutionRuleRepository(clock=_FixedClock(imported_at))
    rule = _rule(available_at=AS_OF - timedelta(hours=1))

    repository.import_rules(rules=(rule,))

    stored = AShareExecutionRuleModel.objects.get(security_id=rule.security_id)
    assert stored.source_available_at == rule.source_available_at
    assert stored.recorded_at == imported_at
    with pytest.raises(ExecutionRuleUnavailable):
        repository.get_effective_rule(security_id=rule.security_id, as_of=AS_OF)
    assert (
        repository.get_effective_rule(
            security_id=rule.security_id,
            as_of=imported_at,
        )
        == rule
    )


@pytest.mark.django_db(transaction=True, available_apps=["apps.risk_center"])
def test_repository_rejects_overlapping_windows_but_accepts_adjacent_windows() -> None:
    repository = DjangoAShareExecutionRuleRepository(
        clock=_FixedClock(AS_OF - timedelta(minutes=1))
    )
    first = _rule(valid_until=AS_OF)
    adjacent = _rule(
        rule_id="adjacent-rule",
        effective_from=AS_OF,
        valid_until=AS_OF + timedelta(days=1),
    )
    repository.import_rules(rules=(first,))

    assert repository.import_rules(rules=(adjacent,)).inserted_count == 1
    overlap = _rule(
        rule_id="overlap-rule",
        effective_from=AS_OF - timedelta(minutes=1),
        valid_until=AS_OF + timedelta(days=2),
    )
    with pytest.raises(ExecutionRuleConflict):
        repository.import_rules(rules=(overlap,))
    assert AShareExecutionRuleModel.objects.count() == 2


@pytest.mark.django_db(transaction=True, available_apps=["apps.risk_center"])
def test_repository_batch_conflict_rolls_back_other_security_insert() -> None:
    repository = DjangoAShareExecutionRuleRepository(
        clock=_FixedClock(AS_OF - timedelta(minutes=1))
    )
    existing = _rule(security_id="EXISTING.SECURITY")
    repository.import_rules(rules=(existing,))
    unrelated = _rule(security_id="NEW.SECURITY", rule_id="unrelated-rule")
    conflicting = _rule(
        security_id=existing.security_id,
        rule_id="overlapping-rule",
        effective_from=AS_OF - timedelta(minutes=1),
    )

    with pytest.raises(ExecutionRuleConflict):
        repository.import_rules(rules=(unrelated, conflicting))

    assert AShareExecutionRuleModel.objects.count() == 1


@pytest.mark.django_db(transaction=True, available_apps=["apps.risk_center"])
def test_repository_blocks_multiple_effective_rows_and_corrupt_payloads() -> None:
    repository = DjangoAShareExecutionRuleRepository(
        clock=_FixedClock(AS_OF - timedelta(minutes=1))
    )
    first = _rule()
    repository.import_rules(rules=(first,))
    second = _rule(rule_id="unmanaged-overlap", board="other-board")
    AShareExecutionRuleModel.objects.create(
        security_id=second.security_id,
        rule_id=second.rule_id,
        rule_version=second.rule_version,
        market=second.market,
        board=second.board,
        recorded_at=AS_OF - timedelta(minutes=1),
        source_available_at=second.source_available_at,
        effective_from=second.effective_from,
        valid_until=second.valid_until,
        content_hash=second.content_hash,
        canonical_payload=encode_a_share_execution_rule(second),
    )

    with pytest.raises(ExecutionRuleCorruption):
        repository.get_effective_rule(security_id=first.security_id, as_of=AS_OF)

    AShareExecutionRuleModel.objects.filter(content_hash=second.content_hash).delete()
    AShareExecutionRuleModel.objects.filter(content_hash=first.content_hash).update(
        canonical_payload={**encode_a_share_execution_rule(first), "board": "tampered"}
    )
    with pytest.raises(ExecutionRuleCorruption):
        repository.get_effective_rule(security_id=first.security_id, as_of=AS_OF)


@pytest.mark.django_db(transaction=True, available_apps=["apps.risk_center"])
def test_concurrent_overlapping_imports_have_one_first_winner() -> None:
    barrier = Barrier(2)
    first = _rule(rule_id="concurrent-rule-a")
    second = _rule(rule_id="concurrent-rule-b", board="other-board")

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures: tuple[Future[str], Future[str]] = (
            executor.submit(_import_after_barrier, barrier, first),
            executor.submit(_import_after_barrier, barrier, second),
        )
        outcomes = tuple(future.result(timeout=15) for future in futures)

    assert outcomes.count("inserted") == 1
    assert set(outcomes) <= {"inserted", "conflict", "unavailable"}
    assert AShareExecutionRuleModel.objects.count() == 1


def _import_after_barrier(barrier: Barrier, rule: AShareExecutionRule) -> str:
    """Import from a separate thread-local database connection after a shared start."""

    connections.close_all()
    try:
        barrier.wait(timeout=5)
        repository = DjangoAShareExecutionRuleRepository(
            clock=_FixedClock(AS_OF - timedelta(minutes=1))
        )
        repository.import_rules(rules=(rule,))
        return "inserted"
    except ExecutionRuleConflict:
        return "conflict"
    except ExecutionRuleUnavailable:
        return "unavailable"
    finally:
        connections.close_all()
