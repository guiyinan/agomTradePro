"""Pure tests for the Account owner-assignment Application workflow."""

from __future__ import annotations

import ast
from contextlib import nullcontext
from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentConflict,
    AccountOwnerAssignmentCorruption,
    AccountOwnerAssignmentServerActor,
    AccountOwnerAssignmentSubject,
    AccountOwnerAssignmentUnavailable,
    ApproveAccountOwnerAssignment,
    ApproveAccountOwnerAssignmentCommand,
    ExactAccountAssignmentProvenanceReceipt,
    ExactAccountRowObservation,
    GetCurrentAccountOwnerAssignment,
    GetCurrentAccountOwnerAssignmentCommand,
    GetExactAccountOwnerAssignment,
    GetExactAccountOwnerAssignmentCommand,
    RegisterAccountOwnerAssignment,
    RegisterAccountOwnerAssignmentCommand,
)
from apps.account.domain.account_owner_assignment_evidence import (
    AccountOwnerAssignmentEvidence,
)

NOW = datetime(2026, 8, 13, 8, tzinfo=UTC)


def _actor(
    actor_id: str = "staff:11",
    user_id: int = 11,
    *,
    is_staff: bool = True,
) -> AccountOwnerAssignmentServerActor:
    return AccountOwnerAssignmentServerActor(
        actor_id=actor_id,
        user_id=user_id,
        role="account_owner_assignment_approver",
        is_staff=is_staff,
    )


def _row(**changes: object) -> ExactAccountRowObservation:
    values: dict[str, object] = {
        "observation_id": "row-observation-7",
        "observation_version": "row-observation.v1",
        "content_hash": "a" * 64,
        "account_namespace": "account",
        "account_id": "real-account-7",
        "underlying_unified_account_namespace": "simulated-account-row",
        "underlying_unified_account_id": 7,
        "observed_at": NOW - timedelta(minutes=2),
        "recorded_at": NOW - timedelta(minutes=1),
        "valid_until": NOW + timedelta(days=5),
    }
    values.update(changes)
    return ExactAccountRowObservation(**values)  # type: ignore[arg-type]


def _receipt(**changes: object) -> ExactAccountAssignmentProvenanceReceipt:
    values: dict[str, object] = {
        "receipt_id": "account-creation-7",
        "receipt_version": "account-creation.v1",
        "content_hash": "b" * 64,
        "provenance_kind": "creation",
        "assignment_state": "authoritative",
        "assigned_owner_user_id": 19,
        "account_namespace": "account",
        "account_id": "real-account-7",
        "underlying_unified_account_namespace": "simulated-account-row",
        "underlying_unified_account_id": 7,
        "row_observation_id": "row-observation-7",
        "row_observation_version": "row-observation.v1",
        "row_observation_content_hash": "a" * 64,
        "claimant_actor_id": "claimant:19",
        "claimant_user_id": 19,
        "claimant_role": "account_owner_claimant",
        "claimant_kind": "human",
        "claimant_is_staff": False,
        "issued_at": NOW - timedelta(minutes=3),
        "recorded_at": NOW - timedelta(minutes=1),
        "valid_until": NOW + timedelta(days=4),
    }
    values.update(changes)
    return ExactAccountAssignmentProvenanceReceipt(**values)  # type: ignore[arg-type]


def _legacy_receipt(**changes: object) -> ExactAccountAssignmentProvenanceReceipt:
    values: dict[str, object] = {
        "receipt_id": "legacy-migration-7",
        "receipt_version": "legacy-migration.v1",
        "content_hash": "c" * 64,
        "provenance_kind": "migration",
        "artifact_type": "account_legacy_default_assignment_receipt",
        "assignment_state": "legacy_default",
        "assigned_owner_user_id": None,
        "claimant_actor_id": "migration-reviewer:23",
        "claimant_user_id": 23,
        "claimant_role": "legacy_assignment_reviewer",
        "claimant_is_staff": True,
    }
    values.update(changes)
    return _receipt(**values)


class _SequenceProvider:
    def __init__(self, *values: object) -> None:
        self.values = list(values)
        self.calls: list[dict[str, object]] = []

    def get_exact_current(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if len(self.values) > 1:
            return self.values.pop(0)
        return self.values[0]


class _Repository:
    def __init__(self) -> None:
        self.clock = NOW
        self.now_calls = 0
        self.subject: AccountOwnerAssignmentSubject | None = None
        self.evidence: AccountOwnerAssignmentEvidence | None = None
        self.head: AccountOwnerAssignmentEvidence | None = None
        self.subject_writes = 0
        self.evidence_writes = 0
        self.expected_predecessors: list[str | None] = []

    def atomic(self) -> nullcontext[None]:
        return nullcontext()

    def now(self) -> datetime:
        self.now_calls += 1
        return self.clock

    def get_subject_winner(self, **kwargs: object) -> AccountOwnerAssignmentSubject | None:
        del kwargs
        return self.subject

    def append_subject(
        self, subject: AccountOwnerAssignmentSubject, **kwargs: object
    ) -> AccountOwnerAssignmentSubject:
        del kwargs
        self.subject_writes += 1
        if self.subject is None:
            self.subject = subject
        return self.subject

    def get_winner(self, **kwargs: object) -> AccountOwnerAssignmentEvidence | None:
        del kwargs
        return self.evidence

    def get_current_head(self, **kwargs: object) -> AccountOwnerAssignmentEvidence | None:
        del kwargs
        return self.head

    def append(
        self,
        evidence: AccountOwnerAssignmentEvidence,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> AccountOwnerAssignmentEvidence:
        assert recorded_at == evidence.recorded_at
        actual = self.head.content_hash if self.head is not None else None
        if actual != expected_predecessor_hash:
            raise AccountOwnerAssignmentConflict("stale predecessor")
        self.expected_predecessors.append(expected_predecessor_hash)
        self.evidence_writes += 1
        if self.evidence is None:
            self.evidence = evidence
            self.head = evidence
        return self.evidence

    def get_exact_by_hash(self, **kwargs: object) -> AccountOwnerAssignmentEvidence | None:
        if self.evidence is None:
            return None
        if (
            kwargs["evidence_id"] != self.evidence.evidence_id
            or kwargs["evidence_version"] != self.evidence.evidence_version
            or kwargs["expected_content_hash"] != self.evidence.content_hash
        ):
            return None
        return self.evidence


def _register(
    repository: _Repository,
    *,
    row_provider: _SequenceProvider | None = None,
    receipt_provider: _SequenceProvider | None = None,
    version: str = "assignment.v1",
    receipt_id: str = "account-creation-7",
    receipt_version: str = "account-creation.v1",
) -> AccountOwnerAssignmentSubject:
    return RegisterAccountOwnerAssignment(
        row_provider=row_provider or _SequenceProvider(_row()),  # type: ignore[arg-type]
        receipt_provider=receipt_provider or _SequenceProvider(_receipt()),  # type: ignore[arg-type]
        repository=repository,
    ).execute(
        RegisterAccountOwnerAssignmentCommand(
            evidence_id="assignment-7",
            evidence_version=version,
            row_observation_id="row-observation-7",
            row_observation_version="row-observation.v1",
            provenance_receipt_id=receipt_id,
            provenance_receipt_version=receipt_version,
        )
    )


def _approve(
    repository: _Repository,
    *,
    actor: AccountOwnerAssignmentServerActor | None = None,
    row_provider: _SequenceProvider | None = None,
    receipt_provider: _SequenceProvider | None = None,
    version: str = "assignment.v1",
) -> AccountOwnerAssignmentEvidence:
    return ApproveAccountOwnerAssignment(
        row_provider=row_provider or _SequenceProvider(_row()),  # type: ignore[arg-type]
        receipt_provider=receipt_provider or _SequenceProvider(_receipt()),  # type: ignore[arg-type]
        repository=repository,
        actor=actor or _actor(),
        validity_period=timedelta(days=2),
    ).execute(
        ApproveAccountOwnerAssignmentCommand(
            evidence_id="assignment-7",
            evidence_version=version,
        )
    )


def test_commands_are_id_only_and_claimant_comes_from_exact_receipt() -> None:
    assert {field.name for field in fields(RegisterAccountOwnerAssignmentCommand)} == {
        "evidence_id",
        "evidence_version",
        "row_observation_id",
        "row_observation_version",
        "provenance_receipt_id",
        "provenance_receipt_version",
    }
    assert {field.name for field in fields(ApproveAccountOwnerAssignmentCommand)} == {
        "evidence_id",
        "evidence_version",
    }
    repository = _Repository()
    row_provider = _SequenceProvider(_row())
    receipt_provider = _SequenceProvider(_receipt())

    subject = _register(
        repository,
        row_provider=row_provider,
        receipt_provider=receipt_provider,
    )

    assert subject.claimant.actor_id == "claimant:19"
    assert subject.claimant.user_id == 19
    assert subject.claimant.is_staff is False
    assert len(subject.content_hash) == 64
    assert len(row_provider.calls) == len(receipt_provider.calls) == 2
    assert repository.now_calls == 1


def test_subject_seal_binds_exact_row_receipt_claimant_and_clocks() -> None:
    repository = _Repository()
    subject = _register(repository)

    with pytest.raises(ValueError, match="subject content_hash"):
        replace(subject, row=_row(content_hash="d" * 64))
    with pytest.raises(ValueError, match="subject content_hash"):
        replace(subject, requested_at=NOW + timedelta(seconds=1))


def test_register_rejects_definition_drift_and_exact_legacy_receipt_absence() -> None:
    repository = _Repository()
    with pytest.raises(AccountOwnerAssignmentCorruption, match="exact row"):
        _register(
            repository,
            row_provider=_SequenceProvider(_row(), _row(content_hash="d" * 64)),
        )
    assert repository.subject_writes == 0

    legacy_repository = _Repository()
    with pytest.raises(AccountOwnerAssignmentUnavailable, match="receipt"):
        _register(
            legacy_repository,
            receipt_provider=_SequenceProvider(None),
        )
    assert legacy_repository.subject_writes == 0


def test_legacy_subject_requires_exact_migration_receipt_and_claims_no_owner() -> None:
    repository = _Repository()
    subject = _register(
        repository,
        receipt_provider=_SequenceProvider(_legacy_receipt()),
        receipt_id="legacy-migration-7",
        receipt_version="legacy-migration.v1",
    )
    assert subject.receipt.assignment_state == "legacy_default"
    assert subject.receipt.assigned_owner_user_id is None
    assert subject.claimant.actor_id == "migration-reviewer:23"


def test_approve_uses_server_staff_actor_clocks_and_double_reads() -> None:
    repository = _Repository()
    subject = _register(repository)
    row_provider = _SequenceProvider(_row())
    receipt_provider = _SequenceProvider(_receipt())

    evidence = _approve(
        repository,
        row_provider=row_provider,
        receipt_provider=receipt_provider,
    )

    assert evidence.claimant == subject.claimant.to_domain()
    assert evidence.subject_content_hash == subject.content_hash
    assert evidence.approved_by.actor_id == "staff:11"
    assert evidence.issued_at == subject.requested_at == NOW
    assert evidence.approved_at == evidence.recorded_at == NOW
    assert evidence.valid_until == NOW + timedelta(days=2)
    assert evidence.activation_available is False
    assert evidence.must_not_execute is True
    assert len(row_provider.calls) == len(receipt_provider.calls) == 2
    assert repository.now_calls == 2


def test_approval_requires_independent_staff_and_writes_nothing_on_failure() -> None:
    repository = _Repository()
    _register(repository)
    with pytest.raises(AccountOwnerAssignmentUnavailable, match="human staff"):
        _approve(repository, actor=_actor(is_staff=False))
    with pytest.raises(AccountOwnerAssignmentUnavailable, match="independent"):
        _approve(repository, actor=_actor("claimant:19", 11))
    with pytest.raises(AccountOwnerAssignmentUnavailable, match="independent"):
        _approve(repository, actor=_actor("other-actor", 19))
    assert repository.evidence_writes == 0


def test_approval_rejects_subject_definition_substitution_before_write() -> None:
    repository = _Repository()
    _register(repository)
    with pytest.raises(AccountOwnerAssignmentCorruption, match="exact row"):
        _approve(
            repository,
            row_provider=_SequenceProvider(_row(content_hash="d" * 64)),
        )
    assert repository.evidence_writes == 0


def test_original_approver_replays_first_winner_across_server_clocks() -> None:
    repository = _Repository()
    _register(repository)
    first = _approve(repository)
    repository.clock += timedelta(hours=1)

    assert _approve(repository) == first
    with pytest.raises(AccountOwnerAssignmentConflict, match="another approver"):
        _approve(repository, actor=_actor("staff:12", 12))
    assert repository.evidence_writes == 1


def test_successor_uses_repository_head_as_predecessor_cas() -> None:
    repository = _Repository()
    _register(repository)
    first = _approve(repository)
    repository.clock += timedelta(hours=1)
    repository.subject = None
    repository.evidence = None
    row_v2 = _row(
        observation_version="row-observation.v2",
        content_hash="d" * 64,
    )
    receipt_v2 = _receipt(
        receipt_version="account-creation.v2",
        content_hash="e" * 64,
        row_observation_version="row-observation.v2",
        row_observation_content_hash="d" * 64,
    )
    subject = RegisterAccountOwnerAssignment(
        row_provider=_SequenceProvider(row_v2),  # type: ignore[arg-type]
        receipt_provider=_SequenceProvider(receipt_v2),  # type: ignore[arg-type]
        repository=repository,
    ).execute(
        RegisterAccountOwnerAssignmentCommand(
            evidence_id="assignment-7",
            evidence_version="assignment.v2",
            row_observation_id="row-observation-7",
            row_observation_version="row-observation.v2",
            provenance_receipt_id="account-creation-7",
            provenance_receipt_version="account-creation.v2",
        )
    )
    assert subject.evidence_version == "assignment.v2"
    second = _approve(
        repository,
        version="assignment.v2",
        row_provider=_SequenceProvider(row_v2),
        receipt_provider=_SequenceProvider(receipt_v2),
    )
    assert second.supersedes_content_hash == first.content_hash
    assert repository.expected_predecessors == [None, first.content_hash]


def test_exact_pit_and_full_selector_current_reader_remain_inactive() -> None:
    repository = _Repository()
    _register(repository)
    evidence = _approve(repository)
    exact = GetExactAccountOwnerAssignment(repository)
    command = GetExactAccountOwnerAssignmentCommand(
        evidence_id=evidence.evidence_id,
        evidence_version=evidence.evidence_version,
        expected_content_hash=evidence.content_hash,
        as_of=NOW,
    )
    assert exact.execute(command) == evidence
    assert exact.execute(replace(command, as_of=evidence.valid_until)) is None

    current = GetCurrentAccountOwnerAssignment(repository)
    assert (
        current.execute(GetCurrentAccountOwnerAssignmentCommand(evidence=evidence, as_of=NOW))
        == evidence
    )
    substituted = replace(
        evidence,
        approved_by=replace(evidence.approved_by, role="substituted_approver"),
        content_hash="",
    )
    assert (
        current.execute(
            GetCurrentAccountOwnerAssignmentCommand(
                evidence=substituted,
                as_of=NOW,
            )
        )
        is None
    )

    with pytest.raises(TypeError, match="exact GetExact"):
        exact.execute(object())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="exact GetCurrent"):
        current.execute(object())  # type: ignore[arg-type]
    repository.head = replace(
        evidence,
        evidence_version="assignment.v2",
        identity_hash="",
        content_hash="",
    )
    assert (
        current.execute(GetCurrentAccountOwnerAssignmentCommand(evidence=evidence, as_of=NOW))
        is None
    )


def test_application_has_no_orm_or_cross_app_implementation_imports() -> None:
    path = (
        Path(__file__).parents[3] / "apps/account/application/account_owner_assignment_evidence.py"
    )
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert all("infrastructure" not in module for module in imports)
    assert all(
        not module.startswith("apps.") or module.startswith("apps.account.domain")
        for module in imports
    )
    assert ".objects" not in path.read_text(encoding="utf-8")
