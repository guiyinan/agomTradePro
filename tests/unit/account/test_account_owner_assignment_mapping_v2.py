from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from apps.account.application.account_owner_assignment_evidence_v2 import (
    AccountOwnerAssignmentEvidenceV2Corruption,
    GetCurrentAccountOwnerAssignmentEvidenceV2Command,
)
from apps.account.application.account_owner_assignment_mapping_v2 import (
    AuthoritativeAccountMappingV2,
    GetCurrentAuthoritativeAccountMappingV2,
    GetCurrentAuthoritativeAccountMappingV2Command,
)
from apps.account.domain.account_owner_assignment_evidence import (
    AccountOwnerAssignmentActor,
)
from apps.account.domain.account_owner_assignment_evidence_v2 import (
    AccountOwnerAssignmentEvidenceV2,
)
from tests.unit.account.test_account_owner_assignment_evidence_v2 import (
    _evidence,
    _subject,
)
from tests.unit.account.test_account_owner_assignment_provenance_receipt_v2 import (
    _receipt,
    _row,
)


def _at(day: int) -> datetime:
    return datetime(2026, 8, day, 12, tzinfo=UTC)


class _HeadReader:
    def __init__(self, value: object) -> None:
        self.value = value
        self.calls: list[tuple[str, int, datetime]] = []

    def get_underlying_head(
        self,
        *,
        underlying_unified_account_namespace: str,
        underlying_unified_account_id: int,
        as_of: datetime,
    ) -> AccountOwnerAssignmentEvidenceV2 | None:
        self.calls.append(
            (
                underlying_unified_account_namespace,
                underlying_unified_account_id,
                as_of,
            )
        )
        return self.value  # type: ignore[return-value]


class _CurrentReader:
    def __init__(self, value: object) -> None:
        self.value = value
        self.calls: list[GetCurrentAccountOwnerAssignmentEvidenceV2Command] = []

    def execute(
        self, command: GetCurrentAccountOwnerAssignmentEvidenceV2Command
    ) -> AccountOwnerAssignmentEvidenceV2 | None:
        self.calls.append(command)
        return self.value  # type: ignore[return-value]


def _command() -> GetCurrentAuthoritativeAccountMappingV2Command:
    return GetCurrentAuthoritativeAccountMappingV2Command(
        underlying_unified_account_namespace="simulated-account-row",
        underlying_unified_account_id=7,
        as_of=_at(8) + timedelta(hours=1),
    )


def test_current_authoritative_mapping_projects_only_identity_authority() -> None:
    evidence = _evidence()
    heads = _HeadReader(evidence)
    current = _CurrentReader(evidence)

    value = GetCurrentAuthoritativeAccountMappingV2(
        head_reader=heads,
        current_reader=current,
    ).execute(_command())

    assert value == AuthoritativeAccountMappingV2(
        account_namespace="account",
        account_id="0007",
        underlying_unified_account_namespace="simulated-account-row",
        underlying_unified_account_id=7,
        assigned_owner_user_id=8,
        evidence_id=evidence.evidence_id,
        evidence_version=evidence.evidence_version,
        evidence_content_hash=evidence.content_hash,
        valid_until=evidence.valid_until,
    )
    assert value.execution_allowed is False
    assert value.authority_scope == "identity_mapping_only"
    assert current.calls == [
        GetCurrentAccountOwnerAssignmentEvidenceV2Command(evidence, _command().as_of)
    ]


def test_missing_head_fails_closed_without_current_read() -> None:
    current = _CurrentReader(_evidence())
    value = GetCurrentAuthoritativeAccountMappingV2(
        head_reader=_HeadReader(None),
        current_reader=current,
    ).execute(_command())
    assert value is None
    assert current.calls == []


def test_non_current_mapping_fails_closed() -> None:
    evidence = _evidence()
    value = GetCurrentAuthoritativeAccountMappingV2(
        head_reader=_HeadReader(evidence),
        current_reader=_CurrentReader(None),
    ).execute(_command())
    assert value is None


def test_legacy_default_never_becomes_an_authoritative_mapping() -> None:
    row = _row()
    receipt = _receipt(
        row,
        provenance_kind="migration",
        assignment_state="legacy_default_claim",
        assigned_owner_user_id=None,
        claimant=AccountOwnerAssignmentActor(
            "reviewer-11", 11, "legacy_assignment_reviewer", is_staff=True
        ),
    )
    legacy = _evidence(
        subject=_subject(physical=row, receipt=receipt),
        assignment_state="legacy_default",
        assigned_owner_user_id=None,
    )
    value = GetCurrentAuthoritativeAccountMappingV2(
        head_reader=_HeadReader(legacy),
        current_reader=_CurrentReader(legacy),
    ).execute(_command())
    assert value is None


def test_underlying_selector_substitution_is_corruption() -> None:
    substituted = _evidence()
    command = GetCurrentAuthoritativeAccountMappingV2Command("other-row", 9, _command().as_of)
    with pytest.raises(AccountOwnerAssignmentEvidenceV2Corruption, match="selector"):
        GetCurrentAuthoritativeAccountMappingV2(
            head_reader=_HeadReader(substituted),
            current_reader=_CurrentReader(substituted),
        ).execute(command)


def test_current_reader_cannot_substitute_a_different_evidence() -> None:
    evidence = _evidence()
    substituted = replace(
        evidence,
        evidence_id="assignment-8",
        identity_hash="",
        content_hash="",
    )
    with pytest.raises(AccountOwnerAssignmentEvidenceV2Corruption, match="substituted"):
        GetCurrentAuthoritativeAccountMappingV2(
            head_reader=_HeadReader(evidence),
            current_reader=_CurrentReader(substituted),
        ).execute(_command())


@pytest.mark.parametrize("value", [object(), "evidence"])
def test_head_type_substitution_is_corruption(value: object) -> None:
    with pytest.raises(AccountOwnerAssignmentEvidenceV2Corruption, match="type"):
        GetCurrentAuthoritativeAccountMappingV2(
            head_reader=_HeadReader(value),
            current_reader=_CurrentReader(None),
        ).execute(_command())


@pytest.mark.parametrize(
    "command",
    [
        GetCurrentAuthoritativeAccountMappingV2Command,
        object(),
    ],
)
def test_command_type_is_exact(command: object) -> None:
    with pytest.raises(TypeError, match="exact"):
        GetCurrentAuthoritativeAccountMappingV2(
            head_reader=_HeadReader(None),
            current_reader=_CurrentReader(None),
        ).execute(
            command
        )  # type: ignore[arg-type]


def test_command_rejects_naive_cutoff_and_bool_row_id() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        GetCurrentAuthoritativeAccountMappingV2Command(
            "simulated-account-row", 7, datetime(2026, 8, 8, 12)
        )
    with pytest.raises(ValueError, match="positive integer"):
        GetCurrentAuthoritativeAccountMappingV2Command("simulated-account-row", True, _at(8))
