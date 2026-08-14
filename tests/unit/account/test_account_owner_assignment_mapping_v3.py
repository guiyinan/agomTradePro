from __future__ import annotations

from dataclasses import replace
from datetime import datetime

import pytest

from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentCorruption,
)
from apps.account.application.account_owner_assignment_evidence_v3 import (
    GetCurrentAccountOwnerAssignmentEvidenceV3Command,
)
from apps.account.application.account_owner_assignment_mapping_v3 import (
    AuthoritativeAccountMappingV3,
    GetCurrentAuthoritativeAccountMappingV3,
    GetCurrentAuthoritativeAccountMappingV3Command,
)
from apps.account.domain.account_owner_assignment_evidence_v3 import (
    AccountOwnerAssignmentEvidenceV3,
)
from tests.unit.account.test_account_owner_assignment_evidence_v3 import _evidence


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
    ) -> AccountOwnerAssignmentEvidenceV3 | None:
        self.calls.append(
            (underlying_unified_account_namespace, underlying_unified_account_id, as_of)
        )
        if self.value is None or type(self.value) is AccountOwnerAssignmentEvidenceV3:
            return self.value
        return self.value  # type: ignore[return-value]


class _CurrentReader:
    def __init__(self, value: object) -> None:
        self.value = value
        self.calls: list[GetCurrentAccountOwnerAssignmentEvidenceV3Command] = []

    def execute(
        self, command: GetCurrentAccountOwnerAssignmentEvidenceV3Command
    ) -> AccountOwnerAssignmentEvidenceV3 | None:
        self.calls.append(command)
        if self.value is None or type(self.value) is AccountOwnerAssignmentEvidenceV3:
            return self.value
        return self.value  # type: ignore[return-value]


def _command(
    evidence: AccountOwnerAssignmentEvidenceV3,
) -> GetCurrentAuthoritativeAccountMappingV3Command:
    binding = evidence.subject.binding
    return GetCurrentAuthoritativeAccountMappingV3Command(
        binding.underlying_unified_account_namespace_claim,
        binding.underlying_unified_account_id_claim,
        evidence.recorded_at,
    )


def test_projects_only_current_authoritative_identity_mapping() -> None:
    evidence = _evidence()
    command = _command(evidence)
    current = _CurrentReader(evidence)

    value = GetCurrentAuthoritativeAccountMappingV3(
        head_reader=_HeadReader(evidence), current_reader=current
    ).execute(command)

    binding = evidence.subject.binding
    assert value == AuthoritativeAccountMappingV3(
        account_namespace=binding.account_namespace_claim,
        account_id=binding.account_id_claim,
        underlying_unified_account_namespace=binding.underlying_unified_account_namespace_claim,
        underlying_unified_account_id=binding.underlying_unified_account_id_claim,
        assigned_owner_user_id=evidence.assigned_owner_user_id,
        evidence_id=evidence.evidence_id,
        evidence_version=evidence.evidence_version,
        evidence_content_hash=evidence.content_hash,
        valid_until=evidence.valid_until,
    )
    assert value.authority_scope == "identity_mapping_only"
    assert value.evidence_status == "inactive"
    assert value.execution_allowed is False
    assert current.calls == [
        GetCurrentAccountOwnerAssignmentEvidenceV3Command(
            evidence.evidence_id,
            evidence.evidence_version,
            evidence.content_hash,
            command.as_of,
        )
    ]


def test_missing_or_legacy_only_state_has_no_v3_fallback() -> None:
    evidence = _evidence()
    current = _CurrentReader(evidence)
    assert (
        GetCurrentAuthoritativeAccountMappingV3(
            head_reader=_HeadReader(None), current_reader=current
        ).execute(_command(evidence))
        is None
    )
    assert current.calls == []


def test_stale_evidence_fails_closed() -> None:
    evidence = _evidence()
    assert (
        GetCurrentAuthoritativeAccountMappingV3(
            head_reader=_HeadReader(evidence), current_reader=_CurrentReader(None)
        ).execute(_command(evidence))
        is None
    )


def test_underlying_head_selector_substitution_is_corruption() -> None:
    evidence = _evidence()
    command = GetCurrentAuthoritativeAccountMappingV3Command(
        "wrong-row",
        evidence.subject.binding.underlying_unified_account_id_claim,
        evidence.recorded_at,
    )
    with pytest.raises(AccountOwnerAssignmentCorruption, match="selector"):
        GetCurrentAuthoritativeAccountMappingV3(
            head_reader=_HeadReader(evidence), current_reader=_CurrentReader(evidence)
        ).execute(command)


def test_current_reader_must_return_the_exact_head() -> None:
    evidence = _evidence()
    substituted = replace(
        evidence, evidence_id="creation-evidence-8", identity_hash="", content_hash=""
    )
    with pytest.raises(AccountOwnerAssignmentCorruption, match="substituted"):
        GetCurrentAuthoritativeAccountMappingV3(
            head_reader=_HeadReader(evidence), current_reader=_CurrentReader(substituted)
        ).execute(_command(evidence))


def test_type_substitution_and_invalid_command_fail_closed() -> None:
    evidence = _evidence()
    with pytest.raises(AccountOwnerAssignmentCorruption, match="type"):
        GetCurrentAuthoritativeAccountMappingV3(
            head_reader=_HeadReader(object()), current_reader=_CurrentReader(None)
        ).execute(_command(evidence))
    with pytest.raises(TypeError, match="exact"):
        GetCurrentAuthoritativeAccountMappingV3(
            head_reader=_HeadReader(None), current_reader=_CurrentReader(None)
        ).execute(
            object()
        )  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="positive integer"):
        GetCurrentAuthoritativeAccountMappingV3Command("row", True, evidence.recorded_at)
    with pytest.raises(ValueError, match="timezone-aware"):
        GetCurrentAuthoritativeAccountMappingV3Command("row", 1, datetime(2026, 8, 14))
