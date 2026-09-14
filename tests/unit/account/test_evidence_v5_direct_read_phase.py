"""Direct Evidence V5 Application reads must start a fresh source phase."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from dataclasses import replace
from datetime import datetime, timedelta
from typing import cast

import pytest

from apps.account.application.account_owner_assignment_evidence_v5 import (
    AccountOwnerAssignmentEvidenceV5Conflict,
    ApproveAccountOwnerAssignmentEvidenceV5,
    GetCurrentAccountOwnerAssignmentEvidenceV5,
    GetCurrentAccountOwnerAssignmentEvidenceV5Command,
)
from apps.account.application.account_owner_assignment_evidence_v5_read_phases import (
    AccountOwnerAssignmentEvidenceV5ReadPhase,
)
from apps.account.application.account_owner_assignment_subject_v5 import (
    GetCurrentAccountOwnerAssignmentSubjectV5Command,
)
from apps.account.application.single_owner_actor_authority import (
    CurrentSingleOwnerParticipants,
)
from apps.account.domain.account_owner_assignment_evidence_v5 import (
    AccountOwnerAssignmentEvidenceV5,
)
from apps.account.domain.account_owner_assignment_subject_v5 import (
    AccountOwnerAssignmentSubjectV5,
)
from shared.infrastructure.immutable_read_snapshot import (
    immutable_read_snapshot,
    isolated_immutable_read_snapshot,
    reuse_immutable_read,
    suspend_immutable_read_reuse,
)
from tests.unit.account.test_account_owner_assignment_evidence_v5_application import (
    _approve_command,
    _at,
    _authority,
    _participants,
    _Repository,
    _subject,
)


class _CachedRepository(_Repository):
    """Apply the production immutable-read decorator to the in-memory double."""

    @contextmanager
    def read_phase(self) -> Iterator[None]:
        """Start the same isolated cache boundary required by a real repository."""

        with suspend_immutable_read_reuse(), isolated_immutable_read_snapshot():
            yield

    @reuse_immutable_read("test-evidence-v5-winner")
    def get_winner(self, *, evidence_id: str, evidence_version: str, as_of: datetime):
        """Cache one exact winner only while a caller snapshot is active."""

        return super().get_winner(
            evidence_id=evidence_id,
            evidence_version=evidence_version,
            as_of=as_of,
        )

    @reuse_immutable_read("test-evidence-v5-exact")
    def get_exact_by_hash(
        self,
        *,
        evidence_id: str,
        evidence_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ):
        """Cache one exact historical selector only inside a read phase."""

        return super().get_exact_by_hash(
            evidence_id=evidence_id,
            evidence_version=evidence_version,
            expected_content_hash=expected_content_hash,
            as_of=as_of,
        )

    @reuse_immutable_read("test-evidence-v5-subject-winner")
    def get_subject_winner(
        self,
        *,
        subject_id: str,
        subject_version: str,
        as_of: datetime,
    ):
        """Cache the registered Subject selector only inside a read phase."""

        return super().get_subject_winner(
            subject_id=subject_id,
            subject_version=subject_version,
            as_of=as_of,
        )

    @reuse_immutable_read("test-evidence-v5-account-head")
    def get_account_head(
        self,
        *,
        account_namespace: str,
        account_id: str,
        as_of: datetime,
    ):
        """Cache one account mapping head only inside a read phase."""

        return super().get_account_head(
            account_namespace=account_namespace,
            account_id=account_id,
            as_of=as_of,
        )

    @reuse_immutable_read("test-evidence-v5-underlying-head")
    def get_underlying_head(
        self,
        *,
        underlying_unified_account_namespace: str,
        underlying_unified_account_id: int,
        as_of: datetime,
    ):
        """Cache one underlying mapping head only inside a read phase."""

        return super().get_underlying_head(
            underlying_unified_account_namespace=underlying_unified_account_namespace,
            underlying_unified_account_id=underlying_unified_account_id,
            as_of=as_of,
        )


class _CachedSubjectReader:
    """Cache the current Subject Application reader like a production source port."""

    def __init__(self, subject: AccountOwnerAssignmentSubjectV5) -> None:
        self.value = subject

    @reuse_immutable_read("test-evidence-v5-current-subject")
    def execute(
        self,
        command: GetCurrentAccountOwnerAssignmentSubjectV5Command,
    ) -> AccountOwnerAssignmentSubjectV5:
        """Return the current subject selected by the command."""

        del command
        return self.value


class _CachedParticipantsReader:
    """Cache the current participant projection while a caller phase is active."""

    def __init__(self, value: CurrentSingleOwnerParticipants) -> None:
        self.value = value

    @reuse_immutable_read("test-evidence-v5-current-participants")
    def get_current(self, *, as_of: datetime) -> CurrentSingleOwnerParticipants:
        """Return the projection with the requested observation clock."""

        return replace(self.value, observed_at=as_of)


def _approved_case() -> tuple[
    AccountOwnerAssignmentSubjectV5,
    _CachedRepository,
    _CachedSubjectReader,
    _CachedParticipantsReader,
    AccountOwnerAssignmentEvidenceV5,
]:
    """Create one winner and return its cached source readers."""

    subject = _subject()
    repository = _CachedRepository(_at(15, 14, 35), _at(15, 14, 40))
    repository.subject = subject
    subject_reader = _CachedSubjectReader(subject)
    participants_reader = _CachedParticipantsReader(
        _participants(subject, observed_at=_at(15, 14, 35))
    )
    approval = ApproveAccountOwnerAssignmentEvidenceV5(
        subject_reader=subject_reader,
        participants_reader=participants_reader,
        repository=repository,
        validity_period=timedelta(days=2),
    )
    evidence = approval.execute(_approve_command(subject))
    return subject, repository, subject_reader, participants_reader, evidence


def _prime_stale_sources(
    subject: AccountOwnerAssignmentSubjectV5,
    repository: _CachedRepository,
    subject_reader: _CachedSubjectReader,
    participants_reader: _CachedParticipantsReader,
    evidence: AccountOwnerAssignmentEvidenceV5,
    *,
    as_of: datetime,
) -> None:
    """Populate every V5 selector used by the direct replay/current read."""

    repository.get_winner(
        evidence_id=evidence.evidence_id,
        evidence_version=evidence.evidence_version,
        as_of=as_of,
    )
    repository.get_exact_by_hash(
        evidence_id=evidence.evidence_id,
        evidence_version=evidence.evidence_version,
        expected_content_hash=evidence.content_hash,
        as_of=as_of,
    )
    subject_reader.execute(
        GetCurrentAccountOwnerAssignmentSubjectV5Command(
            subject_id=subject.subject_id,
            subject_version=subject.subject_version,
            expected_content_hash=subject.content_hash,
            as_of=as_of,
        )
    )
    participants_reader.get_current(as_of=as_of)
    binding = subject.binding
    repository.get_account_head(
        account_namespace=binding.account_namespace_claim,
        account_id=binding.account_id_claim,
        as_of=as_of,
    )
    repository.get_underlying_head(
        underlying_unified_account_namespace=binding.underlying_unified_account_namespace_claim,
        underlying_unified_account_id=binding.underlying_unified_account_id_claim,
        as_of=as_of,
    )


def _drift_participants(
    subject: AccountOwnerAssignmentSubjectV5,
) -> CurrentSingleOwnerParticipants:
    """Return a valid participant projection with a changed authority seal."""

    return _participants(
        subject,
        observed_at=_at(15, 14, 45),
        authority=_authority(source_content_hash="d" * 64, valid_until=_at(30)),
    )


@pytest.mark.parametrize(
    "optional_phase",
    [pytest.param(None, id="default"), pytest.param(nullcontext, id="explicit-nullcontext")],
)
def test_direct_approve_does_not_replay_outer_cached_winner_after_source_drift(
    optional_phase: object | None,
) -> None:
    """Approval must reject changed authority despite a positive outer cache."""

    subject, repository, subject_reader, participants_reader, evidence = _approved_case()
    replay_at = _at(15, 14, 45)
    with immutable_read_snapshot():
        _prime_stale_sources(
            subject,
            repository,
            subject_reader,
            participants_reader,
            evidence,
            as_of=replay_at,
        )
        participants_reader.value = _drift_participants(subject)
        repository.clocks = [replay_at]
        approval = ApproveAccountOwnerAssignmentEvidenceV5(
            subject_reader=subject_reader,
            participants_reader=participants_reader,
            repository=repository,
            validity_period=timedelta(days=2),
            read_phase=cast(AccountOwnerAssignmentEvidenceV5ReadPhase | None, optional_phase),
        )
        with pytest.raises(AccountOwnerAssignmentEvidenceV5Conflict, match="winner source"):
            approval.execute(_approve_command(subject))


@pytest.mark.parametrize(
    "optional_phase",
    [pytest.param(None, id="default"), pytest.param(nullcontext, id="explicit-nullcontext")],
)
def test_direct_current_does_not_return_outer_cached_winner_after_source_drift(
    optional_phase: object | None,
) -> None:
    """Current reads must fail closed after a cached positive authority becomes stale."""

    subject, repository, subject_reader, participants_reader, evidence = _approved_case()
    replay_at = _at(15, 14, 45)
    command = GetCurrentAccountOwnerAssignmentEvidenceV5Command(
        evidence.evidence_id,
        evidence.evidence_version,
        evidence.content_hash,
        replay_at,
    )
    with immutable_read_snapshot():
        _prime_stale_sources(
            subject,
            repository,
            subject_reader,
            participants_reader,
            evidence,
            as_of=replay_at,
        )
        participants_reader.value = _drift_participants(subject)
        current = GetCurrentAccountOwnerAssignmentEvidenceV5(
            subject_reader=subject_reader,
            participants_reader=participants_reader,
            repository=repository,
            read_phase=cast(AccountOwnerAssignmentEvidenceV5ReadPhase | None, optional_phase),
        )
        assert current.execute(command) is None
