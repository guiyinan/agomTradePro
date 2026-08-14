"""Pure coverage for the Risk Center operator specification approval provider."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from apps.risk_center.application.evidence_operator_spec_approval import (
    ApproveEvidenceOperatorSpec,
    ApproveEvidenceOperatorSpecCommand,
    EvidenceOperatorSpecApprovalConflict,
    EvidenceOperatorSpecApprovalCorruption,
    EvidenceOperatorSpecApprovalUnavailable,
    GetEvidenceOperatorSpecApprovalForDefinition,
    GetEvidenceOperatorSpecApprovalForDefinitionCommand,
    GetExactEvidenceOperatorSpecApproval,
    GetExactEvidenceOperatorSpecApprovalCommand,
)
from apps.risk_center.domain.evidence_operator_spec_approval import (
    EvidenceOperatorSpecApprovalActor,
    EvidenceOperatorSpecApprovalActorKind,
    EvidenceOperatorSpecApprovalRecord,
    EvidenceOperatorSpecApprovalSubject,
)
from apps.risk_center.infrastructure.evidence_operator_spec_approval_codec import (
    EvidenceOperatorSpecApprovalCodecError,
    decode_evidence_operator_spec_approval_record,
    encode_evidence_operator_spec_approval_record,
)

REQUESTED_AT = datetime(2026, 8, 12, 8, tzinfo=UTC)
AS_OF = datetime(2026, 8, 12, 9, tzinfo=UTC)
RECORDED_AT = datetime(2026, 8, 12, 10, tzinfo=UTC)
VALID_UNTIL = datetime(2026, 9, 12, 8, tzinfo=UTC)
HASH_A = "a" * 64
HASH_B = "b" * 64


def _requester(
    *,
    actor_id: str = "research.operator-registry",
) -> EvidenceOperatorSpecApprovalActor:
    return EvidenceOperatorSpecApprovalActor(
        actor_id=actor_id,
        kind=EvidenceOperatorSpecApprovalActorKind.SERVICE,
        is_staff=False,
    )


def _approver(
    *,
    actor_id: str = "user:risk-owner",
    user_id: int = 41,
    is_staff: bool = True,
) -> EvidenceOperatorSpecApprovalActor:
    return EvidenceOperatorSpecApprovalActor(
        actor_id=actor_id,
        kind=EvidenceOperatorSpecApprovalActorKind.HUMAN,
        is_staff=is_staff,
        user_id=user_id,
    )


def _subject(
    *,
    subject_id: str = "operator-subject:sector-score:v1",
    subject_version: str = "1",
    definition_hash: str = HASH_A,
    requester: EvidenceOperatorSpecApprovalActor | None = None,
    valid_until: datetime = VALID_UNTIL,
) -> EvidenceOperatorSpecApprovalSubject:
    return EvidenceOperatorSpecApprovalSubject.create(
        subject_id=subject_id,
        subject_version=subject_version,
        operator_id="sector-score",
        operator_version="1",
        definition_hash=definition_hash,
        supersedes_activation_hash=None,
        requested_by=requester or _requester(),
        requested_at=REQUESTED_AT,
        valid_until=valid_until,
    )


class SubjectProvider:
    def __init__(
        self,
        values: list[EvidenceOperatorSpecApprovalSubject | None],
    ) -> None:
        self.values = values
        self.calls: list[tuple[str, str, datetime]] = []

    def get_exact(
        self,
        *,
        subject_id: str,
        subject_version: str,
        as_of: datetime,
    ) -> EvidenceOperatorSpecApprovalSubject | None:
        self.calls.append((subject_id, subject_version, as_of))
        return self.values.pop(0)


class MemoryRepository:
    def __init__(self, *, now: datetime = RECORDED_AT) -> None:
        self.clock = now
        self.subject: EvidenceOperatorSpecApprovalSubject | None = None
        self.approval: EvidenceOperatorSpecApprovalRecord | None = None
        self.appended: list[EvidenceOperatorSpecApprovalRecord] = []
        self.exact_calls: list[tuple[object, ...]] = []
        self.definition_calls: list[tuple[object, ...]] = []

    def atomic(self) -> nullcontext[None]:
        return nullcontext()

    def now(self) -> datetime:
        return self.clock

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
        return self.approval

    def append(
        self,
        approval: EvidenceOperatorSpecApprovalRecord,
        *,
        recorded_at: datetime,
    ) -> EvidenceOperatorSpecApprovalRecord:
        assert recorded_at == self.clock
        self.appended.append(approval)
        self.subject = approval.subject
        self.approval = approval
        return approval

    def get_exact_by_hash(
        self,
        *,
        approval_id: str,
        approval_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> EvidenceOperatorSpecApprovalRecord | None:
        self.exact_calls.append((approval_id, approval_version, expected_content_hash, as_of))
        return self.approval

    def get_for_definition(
        self,
        *,
        approval_id: str,
        approval_version: str,
        operator_id: str,
        operator_version: str,
        definition_hash: str,
        supersedes_activation_hash: str | None,
        as_of: datetime,
    ) -> EvidenceOperatorSpecApprovalRecord | None:
        self.definition_calls.append(
            (
                approval_id,
                approval_version,
                operator_id,
                operator_version,
                definition_hash,
                supersedes_activation_hash,
                as_of,
            )
        )
        return self.approval


def _command() -> ApproveEvidenceOperatorSpecCommand:
    return ApproveEvidenceOperatorSpecCommand(
        subject_id="operator-subject:sector-score:v1",
        subject_version="1",
        approval_id="operator-approval:sector-score:v1",
        approval_version="1",
        as_of=AS_OF,
    )


def _use_case(
    provider: SubjectProvider,
    repository: MemoryRepository,
    *,
    actor: EvidenceOperatorSpecApprovalActor | None = None,
) -> ApproveEvidenceOperatorSpec:
    return ApproveEvidenceOperatorSpec(
        subject_provider=provider,
        repository=repository,
        actor=actor or _approver(),
    )


def test_domain_hashes_bind_subject_actor_validity_and_approval() -> None:
    subject = _subject()
    approval = EvidenceOperatorSpecApprovalRecord.create(
        approval_id="operator-approval:sector-score:v1",
        approval_version="1",
        subject=subject,
        approved_by=_approver(),
        issued_at=RECORDED_AT,
    )

    assert subject.is_valid_at(AS_OF)
    assert approval.is_valid_at(RECORDED_AT)
    with pytest.raises(ValueError, match="content_hash"):
        replace(subject, definition_hash=HASH_B)
    with pytest.raises(ValueError, match="content_hash"):
        replace(approval, approval_version="2")


def test_domain_rejects_non_staff_and_self_approval() -> None:
    subject = _subject()
    with pytest.raises(ValueError, match="human staff"):
        EvidenceOperatorSpecApprovalRecord.create(
            approval_id="approval:a",
            approval_version="1",
            subject=subject,
            approved_by=_approver(is_staff=False),
            issued_at=RECORDED_AT,
        )
    human_requester = _approver(actor_id="requester-alias", user_id=77)
    human_subject = _subject(requester=human_requester)
    with pytest.raises(ValueError, match="self approval"):
        EvidenceOperatorSpecApprovalRecord.create(
            approval_id="approval:b",
            approval_version="1",
            subject=human_subject,
            approved_by=_approver(actor_id="different-alias", user_id=77),
            issued_at=RECORDED_AT,
        )


def test_id_only_command_uses_server_actor_clock_and_double_reads_subject() -> None:
    subject = _subject()
    provider = SubjectProvider([subject, subject])
    repository = MemoryRepository()

    approval = _use_case(provider, repository).execute(_command())

    assert approval.subject == subject
    assert approval.approved_by == _approver()
    assert approval.issued_at == RECORDED_AT
    assert approval.valid_until == VALID_UNTIL
    assert provider.calls == [
        (subject.subject_id, subject.subject_version, AS_OF),
        (subject.subject_id, subject.subject_version, AS_OF),
    ]
    assert repository.appended == [approval]
    assert tuple(_command().__dict__) == (
        "subject_id",
        "subject_version",
        "approval_id",
        "approval_version",
        "as_of",
    )


def test_missing_future_expired_and_provider_drift_fail_closed() -> None:
    subject = _subject()
    with pytest.raises(EvidenceOperatorSpecApprovalUnavailable, match="unavailable"):
        _use_case(SubjectProvider([None]), MemoryRepository()).execute(_command())

    future_repository = MemoryRepository(now=AS_OF - timedelta(microseconds=1))
    with pytest.raises(EvidenceOperatorSpecApprovalUnavailable, match="future"):
        _use_case(
            SubjectProvider([subject, subject]),
            future_repository,
        ).execute(_command())

    expired = _subject(valid_until=AS_OF + timedelta(microseconds=1))
    with pytest.raises(EvidenceOperatorSpecApprovalUnavailable, match="expired"):
        _use_case(
            SubjectProvider([expired, expired]),
            MemoryRepository(),
        ).execute(_command())

    substituted = _subject(definition_hash=HASH_B)
    with pytest.raises(EvidenceOperatorSpecApprovalCorruption, match="changed"):
        _use_case(
            SubjectProvider([subject, substituted]),
            MemoryRepository(),
        ).execute(_command())


def test_first_winner_is_idempotent_and_conflicting_winners_are_rejected() -> None:
    subject = _subject()
    repository = MemoryRepository()
    first = _use_case(SubjectProvider([subject, subject]), repository).execute(_command())

    replay = _use_case(SubjectProvider([subject, subject]), repository).execute(_command())
    assert replay == first
    assert len(repository.appended) == 1

    repository.subject = _subject(definition_hash=HASH_B)
    with pytest.raises(EvidenceOperatorSpecApprovalConflict, match="subject identity"):
        _use_case(SubjectProvider([subject, subject]), repository).execute(_command())


def test_exact_and_definition_read_facades_forward_typed_selectors() -> None:
    repository = MemoryRepository()
    exact_command = GetExactEvidenceOperatorSpecApprovalCommand(
        approval_id="approval:1",
        approval_version="1",
        expected_content_hash=HASH_A,
        as_of=AS_OF,
    )
    assert GetExactEvidenceOperatorSpecApproval(repository).execute(exact_command) is None
    assert repository.exact_calls == [("approval:1", "1", HASH_A, AS_OF)]

    definition_command = GetEvidenceOperatorSpecApprovalForDefinitionCommand(
        approval_id="approval:1",
        approval_version="1",
        operator_id="sector-score",
        operator_version="1",
        definition_hash=HASH_A,
        supersedes_activation_hash=HASH_B,
        as_of=AS_OF,
    )
    assert (
        GetEvidenceOperatorSpecApprovalForDefinition(repository).execute(definition_command) is None
    )
    assert repository.definition_calls == [
        ("approval:1", "1", "sector-score", "1", HASH_A, HASH_B, AS_OF)
    ]


def test_codec_round_trip_is_canonical_and_rejects_tamper() -> None:
    approval = EvidenceOperatorSpecApprovalRecord.create(
        approval_id="operator-approval:sector-score:v1",
        approval_version="1",
        subject=_subject(),
        approved_by=_approver(),
        issued_at=RECORDED_AT,
    )
    payload = encode_evidence_operator_spec_approval_record(approval)
    assert decode_evidence_operator_spec_approval_record(payload) == approval
    assert payload["issued_at"] == "2026-08-12T10:00:00Z"

    tampered = dict(payload)
    tampered["approval_version"] = "2"
    with pytest.raises(EvidenceOperatorSpecApprovalCodecError, match="invalid"):
        decode_evidence_operator_spec_approval_record(tampered)
    noncanonical = dict(payload)
    noncanonical["unexpected"] = True
    with pytest.raises(EvidenceOperatorSpecApprovalCodecError, match="shape"):
        decode_evidence_operator_spec_approval_record(noncanonical)


@pytest.mark.parametrize(
    "value",
    [
        ApproveEvidenceOperatorSpecCommand(
            subject_id="subject",
            subject_version="1",
            approval_id="approval",
            approval_version="1",
            as_of=AS_OF,
        ),
        GetExactEvidenceOperatorSpecApprovalCommand(
            approval_id="approval",
            approval_version="1",
            expected_content_hash=HASH_A,
            as_of=AS_OF,
        ),
    ],
)
def test_commands_are_frozen(value: object) -> None:
    with pytest.raises((AttributeError, TypeError)):
        setattr(value, "as_of", RECORDED_AT)
