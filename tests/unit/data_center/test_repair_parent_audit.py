"""RED contracts for the repair workflow's canonical parent run audit."""

from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import UTC, date, datetime
from typing import Protocol
from uuid import uuid4

import pytest

from apps.data_center.application.dtos import (
    DecisionReliabilityRepairRequest,
    DecisionReliabilitySection,
    SyncResult,
)
from apps.data_center.application.reliability_use_cases import (
    RepairDecisionDataReliabilityUseCase,
)
from apps.data_center.application.sync_identity import (
    SyncExecutionIdentity,
    build_sync_execution_identity,
)

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


class _IdentityIssuer(Protocol):
    def issue(self, *, dataset_key: str, provider_name: str) -> SyncExecutionIdentity:
        """Issue the repair parent identity."""


class _RepairRunIdentityUnitOfWork(Protocol):
    def atomic(self) -> AbstractContextManager[None]:
        """Open the parent identity transaction."""


class _DataRepairAuditWriter(Protocol):
    def write(self, observation: object) -> None:
        """Append one canonical repair completion observation."""


class _IdentityIssuerFake:
    def __init__(self, identity: SyncExecutionIdentity) -> None:
        self.identity = identity
        self.calls: list[tuple[str, str]] = []

    def issue(self, *, dataset_key: str, provider_name: str) -> SyncExecutionIdentity:
        self.calls.append((dataset_key, provider_name))
        return self.identity


class _Atomic(AbstractContextManager[None]):
    def __init__(self, owner: _RepairRunUnitOfWorkFake) -> None:
        self.owner = owner

    def __enter__(self) -> None:
        self.owner.entered += 1
        return None

    def __exit__(self, _exc_type: object, _exc: object, _tb: object) -> bool:
        self.owner.exited += 1
        return False


class _RepairRunUnitOfWorkFake:
    def __init__(self) -> None:
        self.entered = 0
        self.exited = 0

    def atomic(self) -> AbstractContextManager[None]:
        return _Atomic(self)


class _Clock:
    def now(self) -> datetime:
        """Return the authoritative aware test time."""

        return NOW


class _AuditWriterFake:
    def __init__(self, *, failure: BaseException | None = None) -> None:
        self.failure = failure
        self.observations: list[object] = []

    def write(self, observation: object) -> None:
        if self.failure is not None:
            raise self.failure
        self.observations.append(observation)


class _Placeholder:
    """Placeholder for unrelated repository ports in this focused contract."""


def _identity() -> SyncExecutionIdentity:
    return build_sync_execution_identity(
        run_id="00000000-0000-4000-8000-000000000001",
        ingested_run_id="00000000-0000-4000-8000-000000000002",
        batch_id="00000000-0000-4000-8000-000000000003",
        dataset_key="decision.reliability.repair",
        provider_name="data-center-repair",
    )


def _use_case(
    issuer: _IdentityIssuerFake,
    unit_of_work: _RepairRunUnitOfWorkFake,
    writer: _AuditWriterFake,
) -> RepairDecisionDataReliabilityUseCase:
    """Construct the existing repair use case with the intended parent deps."""

    return RepairDecisionDataReliabilityUseCase(
        provider_repo=_Placeholder(),
        provider_registry=_Placeholder(),
        macro_fact_repo=_Placeholder(),
        indicator_catalog_repo=_Placeholder(),
        indicator_unit_rule_repo=_Placeholder(),
        price_bar_repo=_Placeholder(),
        quote_snapshot_repo=_Placeholder(),
        macro_sync_use_case=_Placeholder(),
        price_sync_use_case=_Placeholder(),
        quote_sync_use_case=_Placeholder(),
        decision_read_recorder=_Placeholder(),
        sync_identity_issuer=issuer,
        repair_run_identity_unit_of_work=unit_of_work,
        data_repair_audit_writer=writer,
        clock=_Clock(),
    )


def test_repair_starts_one_parent_identity_transaction_and_exposes_identity(monkeypatch) -> None:
    """The parent run identity is issued once with the canonical repair selector."""

    issuer = _IdentityIssuerFake(_identity())
    unit_of_work = _RepairRunUnitOfWorkFake()
    writer = _AuditWriterFake()
    use_case = _use_case(issuer, unit_of_work, writer)
    ready = DecisionReliabilitySection(status="ready", must_not_use_for_decision=False)
    monkeypatch.setattr(use_case, "_ensure_default_akshare_provider", lambda: {})
    monkeypatch.setattr(use_case, "_repair_macro_inputs", lambda *_args: ready)
    monkeypatch.setattr(use_case, "_repair_quote_inputs", lambda *_args: ready)
    monkeypatch.setattr(use_case, "_repair_pulse", lambda *_args: ready)
    monkeypatch.setattr(use_case, "_repair_alpha", lambda *_args: ready)

    report = use_case.execute(DecisionReliabilityRepairRequest(target_date=date(2026, 8, 27)))

    assert issuer.calls == [("decision.reliability.repair", "data-center-repair")]
    assert unit_of_work.entered == 1
    assert unit_of_work.exited == 1
    assert report.run_id == _identity().run_id
    assert report.ingested_run_id == _identity().ingested_run_id
    assert report.identity_hash == _identity().identity_hash
    assert len(writer.observations) == 1


@pytest.mark.parametrize("status", ["ready", "blocked", "failed"])
def test_parent_outcome_is_derived_from_all_four_sections(monkeypatch, status: str) -> None:
    """Parent completion maps section status and decision blocking deterministically."""

    issuer = _IdentityIssuerFake(_identity())
    unit_of_work = _RepairRunUnitOfWorkFake()
    writer = _AuditWriterFake()
    use_case = _use_case(issuer, unit_of_work, writer)
    section = DecisionReliabilitySection(
        status=status,
        must_not_use_for_decision=status != "ready",
    )
    monkeypatch.setattr(use_case, "_ensure_default_akshare_provider", lambda: {})
    monkeypatch.setattr(use_case, "_repair_macro_inputs", lambda *_args: section)
    monkeypatch.setattr(use_case, "_repair_quote_inputs", lambda *_args: section)
    monkeypatch.setattr(use_case, "_repair_pulse", lambda *_args: section)
    monkeypatch.setattr(use_case, "_repair_alpha", lambda *_args: section)

    report = use_case.execute(DecisionReliabilityRepairRequest())

    assert (
        report.audit_outcome.value
        == {
            "ready": "success",
            "blocked": "partial",
            "failed": "failed",
        }[status]
    )


def test_parent_collects_deduplicated_publication_evidence_from_sync_results(monkeypatch) -> None:
    """All child publication identities are retained once in the parent observation."""

    issuer = _IdentityIssuerFake(_identity())
    unit_of_work = _RepairRunUnitOfWorkFake()
    writer = _AuditWriterFake()
    use_case = _use_case(issuer, unit_of_work, writer)
    publication_id = str(uuid4())
    child = SyncResult(
        domain="price",
        provider_name="provider-primary",
        stored_count=1,
        status="success",
        run_id=_identity().run_id,
        ingested_run_id=_identity().ingested_run_id,
        publication_id=publication_id,
        publication_version="3",
        publication_hash="a" * 64,
    )
    ready = DecisionReliabilitySection(status="ready", must_not_use_for_decision=False)
    monkeypatch.setattr(use_case, "_ensure_default_akshare_provider", lambda: {})

    def _collect_child(*args: object) -> DecisionReliabilitySection:
        target = args[-1]
        assert isinstance(target, list)
        use_case._collect_publication_evidence(
            target,
            sync_result=child,
            dataset_key="equity.price.bar",
        )
        return ready

    monkeypatch.setattr(use_case, "_repair_macro_inputs", _collect_child)
    monkeypatch.setattr(use_case, "_repair_quote_inputs", _collect_child)
    monkeypatch.setattr(use_case, "_repair_pulse", lambda *_args: ready)
    monkeypatch.setattr(use_case, "_repair_alpha", lambda *_args: ready)

    use_case.execute(DecisionReliabilityRepairRequest())

    assert len(writer.observations) == 1
    assert str(writer.observations[0]).count(publication_id) == 1


def test_parent_audit_writer_failure_propagates_without_child_exception_text(monkeypatch) -> None:
    """Audit failure must not be swallowed or replaced by a generic success report."""

    issuer = _IdentityIssuerFake(_identity())
    unit_of_work = _RepairRunUnitOfWorkFake()
    writer = _AuditWriterFake(failure=RuntimeError("provider secret should not surface"))
    use_case = _use_case(issuer, unit_of_work, writer)
    ready = DecisionReliabilitySection(status="ready", must_not_use_for_decision=False)
    monkeypatch.setattr(use_case, "_ensure_default_akshare_provider", lambda: {})
    monkeypatch.setattr(use_case, "_repair_macro_inputs", lambda *_args: ready)
    monkeypatch.setattr(use_case, "_repair_quote_inputs", lambda *_args: ready)
    monkeypatch.setattr(use_case, "_repair_pulse", lambda *_args: ready)
    monkeypatch.setattr(use_case, "_repair_alpha", lambda *_args: ready)

    with pytest.raises(RuntimeError):
        use_case.execute(DecisionReliabilityRepairRequest())
