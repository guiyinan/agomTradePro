"""Component attacks for the independent governed R8 input receipt ledger."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import connection

from apps.portfolio.application.governed_optimization import (
    CanonicalGovernedOptimizationOwnerGraph,
    RegisterGovernedOptimizationInputReceiptCommand,
    RegisterGovernedOptimizationInputReceiptUseCase,
)
from apps.portfolio.domain.canonical_snapshots import CanonicalPortfolioSnapshot
from apps.portfolio.domain.governed_input_set import (
    ExactPromotionAttestation,
    GovernedOptimizationInputSet,
)
from apps.portfolio.domain.investable_universe import InvestableUniverseSnapshot
from apps.portfolio.infrastructure.optimization_input_receipt_repository import (
    DjangoGovernedOptimizationInputReceiptRepository,
    DjangoGovernedOptimizationUnitOfWork,
    GovernedOptimizationReceiptConflict,
    GovernedOptimizationReceiptCorruption,
    _build_input_receipt_writer,
)
from apps.portfolio.infrastructure.optimization_research_models import (
    GovernedOptimizationInputReceiptModel,
)
from tests.unit.portfolio.test_governed_optimization_inputs import (
    LATER,
    NOW,
    _input_set,
    _snapshot,
)


class _Clock:
    def __init__(self, now: datetime = NOW) -> None:
        self.current = now

    def now(self) -> datetime:
        return self.current


class _CanonicalInputSetSource:
    def __init__(
        self,
        *,
        unit_of_work_key: str,
        input_set: GovernedOptimizationInputSet | None,
    ) -> None:
        self._unit_of_work_key = unit_of_work_key
        self._input_set = input_set

    @property
    def unit_of_work_key(self) -> str:
        return self._unit_of_work_key

    def get_exact(
        self,
        *,
        input_set_id: str,
        input_set_version: str,
        evaluated_at: datetime,
    ) -> GovernedOptimizationInputSet | None:
        del evaluated_at
        candidate = self._input_set
        if candidate is None or (
            candidate.input_set_id != input_set_id
            or candidate.input_set_version != input_set_version
        ):
            return None
        return candidate


class _OwnerGraphSource:
    def __init__(self, *, unit_of_work_key: str, input_set: GovernedOptimizationInputSet) -> None:
        self._unit_of_work_key = unit_of_work_key
        self._input_set = input_set

    @property
    def unit_of_work_key(self) -> str:
        return self._unit_of_work_key

    def get_exact(
        self,
        *,
        input_set_id: str,
        input_set_version: str,
        evaluated_at: datetime,
    ) -> CanonicalGovernedOptimizationOwnerGraph | None:
        del evaluated_at
        if (
            input_set_id != self._input_set.input_set_id
            or input_set_version != self._input_set.input_set_version
        ):
            return None
        return CanonicalGovernedOptimizationOwnerGraph(
            payloads=self._input_set.payloads,
            owner_bindings=self._input_set.owner_bindings,
        )


class _UniverseSource:
    def __init__(self, *, unit_of_work_key: str, input_set: GovernedOptimizationInputSet) -> None:
        self._unit_of_work_key = unit_of_work_key
        self._universe = input_set.universe

    @property
    def unit_of_work_key(self) -> str:
        return self._unit_of_work_key

    def get_exact(
        self,
        *,
        universe_id: str,
        universe_version: str,
        evaluated_at: datetime,
    ) -> InvestableUniverseSnapshot | None:
        del evaluated_at
        if universe_id != self._universe.universe_id or universe_version != self._universe.version:
            return None
        return self._universe


class _SnapshotSource:
    def __init__(self, *, unit_of_work_key: str) -> None:
        self._unit_of_work_key = unit_of_work_key

    @property
    def unit_of_work_key(self) -> str:
        return self._unit_of_work_key

    def get_exact(
        self,
        *,
        snapshot_id: str,
        evaluated_at: datetime,
    ) -> CanonicalPortfolioSnapshot | None:
        del evaluated_at
        snapshot = _snapshot()
        return snapshot if snapshot.snapshot_id == snapshot_id else None


class _PromotionSource:
    def __init__(self, *, unit_of_work_key: str, input_set: GovernedOptimizationInputSet) -> None:
        self._unit_of_work_key = unit_of_work_key
        self._promotions = {
            (item.capability_key, item.decision_id): item for item in input_set.promotions
        }

    @property
    def unit_of_work_key(self) -> str:
        return self._unit_of_work_key

    def get_exact(
        self,
        *,
        capability_key: str,
        decision_id: str,
        evaluated_at: datetime,
    ) -> ExactPromotionAttestation | None:
        del evaluated_at
        return self._promotions.get((capability_key, decision_id))


def _repository(
    *,
    clock: _Clock | None = None,
) -> tuple[
    DjangoGovernedOptimizationInputReceiptRepository,
    DjangoGovernedOptimizationUnitOfWork,
]:
    unit_of_work = DjangoGovernedOptimizationUnitOfWork()
    return (
        DjangoGovernedOptimizationInputReceiptRepository(
            unit_of_work=unit_of_work,
            clock=clock or _Clock(),
        ),
        unit_of_work,
    )


def _registration_use_case(
    *,
    repository: DjangoGovernedOptimizationInputReceiptRepository,
    unit_of_work: DjangoGovernedOptimizationUnitOfWork,
    clock: _Clock,
    input_set: GovernedOptimizationInputSet | None,
) -> RegisterGovernedOptimizationInputReceiptUseCase:
    authoritative = _input_set() if input_set is None else input_set
    key = unit_of_work.unit_of_work_key
    return RegisterGovernedOptimizationInputReceiptUseCase(
        transaction_boundary=unit_of_work,
        writer=_build_input_receipt_writer(repository),
        input_set_provider=_CanonicalInputSetSource(
            unit_of_work_key=key,
            input_set=input_set,
        ),
        owner_graph_provider=_OwnerGraphSource(
            unit_of_work_key=key,
            input_set=authoritative,
        ),
        universe_provider=_UniverseSource(
            unit_of_work_key=key,
            input_set=authoritative,
        ),
        snapshot_provider=_SnapshotSource(unit_of_work_key=key),
        promotion_provider=_PromotionSource(
            unit_of_work_key=key,
            input_set=authoritative,
        ),
        clock=clock,
    )


@pytest.mark.django_db
def test_id_only_registration_reconstructs_graph_and_public_repository_is_read_only() -> None:
    clock = _Clock()
    repository, unit_of_work = _repository(clock=clock)
    input_set = _input_set()
    use_case = _registration_use_case(
        repository=repository,
        unit_of_work=unit_of_work,
        clock=clock,
        input_set=input_set,
    )

    receipt = use_case.execute(
        RegisterGovernedOptimizationInputReceiptCommand(
            input_set_id=input_set.input_set_id,
            input_set_version=input_set.input_set_version,
        )
    )

    assert receipt.input_set == input_set
    assert not hasattr(repository, "append")
    with pytest.raises(TypeError, match="input_set"):
        RegisterGovernedOptimizationInputReceiptCommand(
            input_set_id=input_set.input_set_id,
            input_set_version=input_set.input_set_version,
            input_set=input_set,  # type: ignore[call-arg]
        )


@pytest.mark.django_db
def test_registration_missing_authoritative_input_set_is_zero_write() -> None:
    clock = _Clock()
    repository, unit_of_work = _repository(clock=clock)
    use_case = _registration_use_case(
        repository=repository,
        unit_of_work=unit_of_work,
        clock=clock,
        input_set=None,
    )

    with pytest.raises(ValueError, match="input set is unavailable"):
        use_case.execute(
            RegisterGovernedOptimizationInputReceiptCommand(
                input_set_id="missing-input-set",
                input_set_version="missing.v1",
            )
        )

    assert GovernedOptimizationInputReceiptModel._default_manager.count() == 0


def _forked_input_set() -> GovernedOptimizationInputSet:
    source = _input_set()
    return GovernedOptimizationInputSet.create(
        input_set_id=source.input_set_id,
        input_set_version=source.input_set_version,
        contract_version="optimizer-contract.fork",
        portfolio_snapshot_id=source.portfolio_snapshot_id,
        portfolio_snapshot_hash=source.portfolio_snapshot_hash,
        universe=source.universe,
        payloads=source.payloads,
        owner_bindings=source.owner_bindings,
        promotions=source.promotions,
        created_at=source.created_at,
        valid_until=source.valid_until,
    )


@pytest.mark.django_db
def test_append_is_exact_idempotent_and_get_is_id_only_pit_bound() -> None:
    clock = _Clock()
    repository, unit_of_work = _repository(clock=clock)
    input_set = _input_set()

    with unit_of_work.atomic():
        receipt = repository._store_verified(input_set, clock.current)
    clock.current += timedelta(seconds=1)

    with unit_of_work.atomic():
        assert repository._store_verified(input_set, clock.current) == receipt
    assert GovernedOptimizationInputReceiptModel._default_manager.count() == 1
    with unit_of_work.atomic():
        assert (
            repository.get_exact(
                input_set_id=input_set.input_set_id,
                evaluated_at=NOW,
            )
            == receipt
        )
        assert (
            repository.get_exact(
                input_set_id="missing-input-set",
                evaluated_at=NOW,
            )
            is None
        )
        clock.current = LATER
        assert (
            repository.get_exact(
                input_set_id=input_set.input_set_id,
                evaluated_at=LATER,
            )
            is None
        )


@pytest.mark.django_db
def test_get_rejects_outside_uow_future_and_pre_receipt_reads() -> None:
    clock = _Clock(NOW + timedelta(hours=1))
    repository, unit_of_work = _repository(clock=clock)
    input_set = _input_set()
    with unit_of_work.atomic():
        repository._store_verified(input_set, clock.current)

    with pytest.raises(ValidationError, match="shared unit of work"):
        repository.get_exact(
            input_set_id=input_set.input_set_id,
            evaluated_at=NOW,
        )
    with unit_of_work.atomic():
        assert (
            repository.get_exact(
                input_set_id=input_set.input_set_id,
                evaluated_at=NOW + timedelta(minutes=30),
            )
            is None
        )
        with pytest.raises(ValueError, match="future"):
            repository.get_exact(
                input_set_id=input_set.input_set_id,
                evaluated_at=clock.current + timedelta(microseconds=1),
            )


@pytest.mark.django_db
def test_same_input_identity_cannot_fork_to_different_evidence() -> None:
    repository, unit_of_work = _repository()
    with unit_of_work.atomic():
        repository._store_verified(_input_set(), NOW)

    with pytest.raises(GovernedOptimizationReceiptConflict, match="different canonical"):
        with unit_of_work.atomic():
            repository._store_verified(_forked_input_set(), NOW)

    assert GovernedOptimizationInputReceiptModel._default_manager.count() == 1


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("column", "replacement"),
    [
        ("canonical_payload", "{}"),
        ("portfolio_snapshot_hash", "f" * 64),
    ],
)
def test_raw_payload_or_header_tamper_fails_live_reconstruction(
    column: str,
    replacement: str,
) -> None:
    repository, unit_of_work = _repository()
    input_set = _input_set()
    with unit_of_work.atomic():
        repository._store_verified(input_set, NOW)
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE portfolio_governed_optimization_input_receipt "
            f"SET {column} = %s WHERE input_set_id = %s",
            [replacement, input_set.input_set_id],
        )

    with unit_of_work.atomic(), pytest.raises(GovernedOptimizationReceiptCorruption):
        repository.get_exact(
            input_set_id=input_set.input_set_id,
            evaluated_at=NOW,
        )


@pytest.mark.django_db
def test_outer_failure_rolls_back_receipt_append() -> None:
    repository, unit_of_work = _repository()

    with pytest.raises(RuntimeError, match="fault injection"):
        with unit_of_work.atomic():
            repository._store_verified(_input_set(), NOW)
            raise RuntimeError("fault injection")

    assert GovernedOptimizationInputReceiptModel._default_manager.count() == 0


@pytest.mark.django_db
def test_actual_unique_conflict_rolls_back_savepoint_and_replays_exact_winner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, unit_of_work = _repository()
    input_set = _input_set()
    with unit_of_work.atomic():
        expected = repository._store_verified(input_set, NOW)
    original_find = repository._find_alias
    calls = 0

    def miss_once(*args: object, **kwargs: object):
        nonlocal calls
        calls += 1
        if calls == 1:
            return None
        return original_find(*args, **kwargs)

    monkeypatch.setattr(repository, "_find_alias", miss_once)

    with unit_of_work.atomic():
        assert repository._store_verified(input_set, NOW) == expected
        assert GovernedOptimizationInputReceiptModel._default_manager.count() == 1

    assert calls == 2
