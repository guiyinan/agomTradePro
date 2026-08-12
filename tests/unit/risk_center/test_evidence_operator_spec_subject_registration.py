"""Pure contracts for ID-only operator-spec approval subject registration."""

from __future__ import annotations

from contextlib import nullcontext
from datetime import UTC, datetime, timedelta

import pytest

from apps.risk_center.application.evidence_operator_spec_approval import (
    EvidenceOperatorSpecApprovalConflict,
    EvidenceOperatorSpecApprovalCorruption,
    EvidenceOperatorSpecApprovalDefinition,
    EvidenceOperatorSpecApprovalUnavailable,
    RegisterEvidenceOperatorSpecApprovalSubject,
    RegisterEvidenceOperatorSpecApprovalSubjectCommand,
)
from apps.risk_center.domain.evidence_operator_spec_approval import (
    EvidenceOperatorSpecApprovalActor,
    EvidenceOperatorSpecApprovalActorKind,
    EvidenceOperatorSpecApprovalRecord,
    EvidenceOperatorSpecApprovalSubject,
)

AS_OF = datetime(2026, 8, 13, 8, tzinfo=UTC)
RECORDED_AT = datetime(2026, 8, 13, 8, 0, 1, tzinfo=UTC)
VALID_UNTIL = AS_OF + timedelta(days=30)
HASH_A = "a" * 64
HASH_B = "b" * 64


def _actor(
    *,
    actor_id: str = "django-user:41",
    user_id: int = 41,
    is_staff: bool = True,
) -> EvidenceOperatorSpecApprovalActor:
    return EvidenceOperatorSpecApprovalActor(
        actor_id=actor_id,
        kind=EvidenceOperatorSpecApprovalActorKind.HUMAN,
        is_staff=is_staff,
        user_id=user_id,
    )


def _definition(
    *,
    definition_hash: str = HASH_A,
) -> EvidenceOperatorSpecApprovalDefinition:
    return EvidenceOperatorSpecApprovalDefinition(
        operator_id="sector-score",
        operator_version="1",
        definition_hash=definition_hash,
        supersedes_activation_hash=None,
        activated_at=AS_OF - timedelta(days=1),
        valid_until=VALID_UNTIL,
    )


class DefinitionProvider:
    def __init__(self, values: list[EvidenceOperatorSpecApprovalDefinition | None]) -> None:
        self.values = values
        self.calls: list[tuple[str, str, datetime]] = []

    def get_exact(
        self,
        *,
        operator_id: str,
        operator_version: str,
        as_of: datetime,
    ) -> EvidenceOperatorSpecApprovalDefinition | None:
        self.calls.append((operator_id, operator_version, as_of))
        return self.values.pop(0)


class MemoryRepository:
    def __init__(self) -> None:
        self.subject: EvidenceOperatorSpecApprovalSubject | None = None
        self.appended_subjects: list[EvidenceOperatorSpecApprovalSubject] = []

    def atomic(self) -> nullcontext[None]:
        return nullcontext()

    def now(self) -> datetime:
        return RECORDED_AT

    def get_subject_winner(
        self,
        *,
        subject_id: str,
        subject_version: str,
        as_of: datetime,
    ) -> EvidenceOperatorSpecApprovalSubject | None:
        del subject_id, subject_version, as_of
        return self.subject

    def get_approval_winner(
        self,
        *,
        approval_id: str,
        approval_version: str,
        as_of: datetime,
    ) -> EvidenceOperatorSpecApprovalRecord | None:
        del approval_id, approval_version, as_of
        return None

    def append_subject(
        self,
        subject: EvidenceOperatorSpecApprovalSubject,
        *,
        recorded_at: datetime,
    ) -> EvidenceOperatorSpecApprovalSubject:
        assert recorded_at == RECORDED_AT
        self.subject = subject
        self.appended_subjects.append(subject)
        return subject

    def append(
        self,
        approval: EvidenceOperatorSpecApprovalRecord,
        *,
        recorded_at: datetime,
    ) -> EvidenceOperatorSpecApprovalRecord:
        del recorded_at
        return approval

    def get_exact_by_hash(self, **kwargs: object) -> EvidenceOperatorSpecApprovalRecord | None:
        del kwargs
        return None

    def get_for_definition(self, **kwargs: object) -> EvidenceOperatorSpecApprovalRecord | None:
        del kwargs
        return None


def _command() -> RegisterEvidenceOperatorSpecApprovalSubjectCommand:
    return RegisterEvidenceOperatorSpecApprovalSubjectCommand(
        subject_id="operator-subject:sector-score:v1",
        subject_version="1",
        operator_id="sector-score",
        operator_version="1",
        as_of=AS_OF,
    )


def _use_case(
    provider: DefinitionProvider,
    repository: MemoryRepository,
    *,
    actor: EvidenceOperatorSpecApprovalActor | None = None,
) -> RegisterEvidenceOperatorSpecApprovalSubject:
    return RegisterEvidenceOperatorSpecApprovalSubject(
        definition_provider=provider,
        repository=repository,
        actor=actor or _actor(),
    )


def test_registration_seals_only_provider_definition_and_server_actor_clock() -> None:
    definition = _definition()
    provider = DefinitionProvider([definition, definition])
    repository = MemoryRepository()

    subject = _use_case(provider, repository).execute(_command())

    assert subject.operator_id == definition.operator_id
    assert subject.definition_hash == definition.definition_hash
    assert subject.supersedes_activation_hash == definition.supersedes_activation_hash
    assert subject.requested_by == _actor()
    assert subject.requested_at == RECORDED_AT
    assert subject.valid_until == definition.valid_until
    assert repository.appended_subjects == [subject]
    assert provider.calls == [
        ("sector-score", "1", AS_OF),
        ("sector-score", "1", AS_OF),
    ]
    assert tuple(_command().__dict__) == (
        "subject_id",
        "subject_version",
        "operator_id",
        "operator_version",
        "as_of",
    )


def test_registration_is_exact_replay_and_rejects_identity_forks() -> None:
    definition = _definition()
    provider = DefinitionProvider([definition, definition, definition, definition])
    repository = MemoryRepository()
    use_case = _use_case(provider, repository)

    first = use_case.execute(_command())
    assert use_case.execute(_command()) == first
    assert repository.appended_subjects == [first]

    repository.subject = EvidenceOperatorSpecApprovalSubject.create(
        subject_id=first.subject_id,
        subject_version=first.subject_version,
        operator_id=first.operator_id,
        operator_version=first.operator_version,
        definition_hash=HASH_B,
        supersedes_activation_hash=None,
        requested_by=first.requested_by,
        requested_at=first.requested_at,
        valid_until=first.valid_until,
    )
    with pytest.raises(EvidenceOperatorSpecApprovalConflict, match="first winner"):
        _use_case(
            DefinitionProvider([definition, definition]),
            repository,
        ).execute(_command())


def test_registration_fails_closed_for_actor_definition_and_provider_drift() -> None:
    with pytest.raises(EvidenceOperatorSpecApprovalUnavailable, match="human staff"):
        _use_case(
            DefinitionProvider([_definition(), _definition()]),
            MemoryRepository(),
            actor=_actor(is_staff=False),
        ).execute(_command())

    with pytest.raises(EvidenceOperatorSpecApprovalUnavailable, match="unavailable"):
        _use_case(DefinitionProvider([None]), MemoryRepository()).execute(_command())

    with pytest.raises(EvidenceOperatorSpecApprovalCorruption, match="changed"):
        _use_case(
            DefinitionProvider([_definition(), _definition(definition_hash=HASH_B)]),
            MemoryRepository(),
        ).execute(_command())


def test_definition_projection_rejects_expired_or_malformed_semantics() -> None:
    with pytest.raises(ValueError, match="validity"):
        EvidenceOperatorSpecApprovalDefinition(
            operator_id="sector-score",
            operator_version="1",
            definition_hash=HASH_A,
            supersedes_activation_hash=None,
            activated_at=VALID_UNTIL,
            valid_until=VALID_UNTIL,
        )
    with pytest.raises(ValueError, match="definition_hash"):
        EvidenceOperatorSpecApprovalDefinition(
            operator_id="sector-score",
            operator_version="1",
            definition_hash="client-authored",
            supersedes_activation_hash=None,
            activated_at=AS_OF,
            valid_until=VALID_UNTIL,
        )
