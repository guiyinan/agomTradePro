from __future__ import annotations

import ast
from contextlib import nullcontext
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentConflict,
    AccountOwnerAssignmentServerActor,
    AccountOwnerAssignmentUnavailable,
)
from apps.account.application.account_owner_assignment_evidence_v3 import (
    ApproveAccountOwnerAssignmentEvidenceV3,
    ApproveAccountOwnerAssignmentEvidenceV3Command,
    GetCurrentAccountOwnerAssignmentEvidenceV3,
    GetCurrentAccountOwnerAssignmentEvidenceV3Command,
    GetExactAccountOwnerAssignmentEvidenceV3,
    GetExactAccountOwnerAssignmentEvidenceV3Command,
    RegisterAccountOwnerAssignmentSubjectV3,
    RegisterAccountOwnerAssignmentSubjectV3Command,
)
from apps.account.domain.account_owner_assignment_evidence_v3 import (
    AccountOwnerAssignmentEvidenceV3,
    AccountOwnerAssignmentSubjectV3,
)
from apps.account.domain.account_owner_assignment_provenance_receipt_v3 import (
    AccountOwnerAssignmentProvenanceReceiptV3,
)
from tests.unit.account.test_account_owner_assignment_provenance_receipt_v3 import _receipt


class _ReceiptProvider:
    def __init__(self, *values: object) -> None:
        self.values = list(values)
        self.calls = 0

    def get_exact_current(self, **_: object) -> object | None:
        self.calls += 1
        if not self.values:
            return None
        return self.values.pop(0) if len(self.values) > 1 else self.values[0]


class _RootProvider:
    def __init__(self, *values: object) -> None:
        self.values = list(values)
        self.calls = 0

    def get_exact_current(self, **_: object) -> object | None:
        self.calls += 1
        if not self.values:
            return None
        return self.values.pop(0) if len(self.values) > 1 else self.values[0]


class _ApproverProvider:
    def __init__(self, *values: object) -> None:
        self.values = list(values)
        self.calls = 0

    def get_current(self, **_: object) -> object | None:
        self.calls += 1
        if not self.values:
            return None
        return self.values.pop(0) if len(self.values) > 1 else self.values[0]


class _Repository:
    def __init__(self, *clocks: datetime) -> None:
        self.clocks = list(clocks)
        self.subject: AccountOwnerAssignmentSubjectV3 | None = None
        self.evidence: AccountOwnerAssignmentEvidenceV3 | None = None
        self.account_head: AccountOwnerAssignmentEvidenceV3 | None = None
        self.underlying_head: AccountOwnerAssignmentEvidenceV3 | None = None
        self.append_subject_calls = 0
        self.append_root_calls = 0

    def atomic(self) -> nullcontext[None]:
        return nullcontext()

    def now(self) -> datetime:
        return self.clocks.pop(0) if len(self.clocks) > 1 else self.clocks[0]

    def get_subject_winner(self, **_: object) -> AccountOwnerAssignmentSubjectV3 | None:
        return self.subject

    def append_subject(
        self, subject: AccountOwnerAssignmentSubjectV3, *, recorded_at: datetime
    ) -> AccountOwnerAssignmentSubjectV3:
        assert recorded_at == subject.requested_at
        self.append_subject_calls += 1
        self.subject = subject
        return subject

    def get_winner(self, **_: object) -> AccountOwnerAssignmentEvidenceV3 | None:
        return self.evidence

    def get_account_head(self, **_: object) -> AccountOwnerAssignmentEvidenceV3 | None:
        return self.account_head

    def get_underlying_head(self, **_: object) -> AccountOwnerAssignmentEvidenceV3 | None:
        return self.underlying_head

    def append_root(
        self,
        evidence: AccountOwnerAssignmentEvidenceV3,
        *,
        expected_account_head_hash: None,
        expected_underlying_head_hash: None,
        recorded_at: datetime,
    ) -> AccountOwnerAssignmentEvidenceV3:
        assert expected_account_head_hash is None
        assert expected_underlying_head_hash is None
        assert recorded_at == evidence.recorded_at
        self.append_root_calls += 1
        self.evidence = evidence
        self.account_head = evidence
        self.underlying_head = evidence
        return evidence

    def get_exact_by_hash(self, **_: object) -> AccountOwnerAssignmentEvidenceV3 | None:
        return self.evidence


def _register_command(
    receipt: AccountOwnerAssignmentProvenanceReceiptV3,
) -> RegisterAccountOwnerAssignmentSubjectV3Command:
    binding = receipt.binding
    root = binding.creation_root
    return RegisterAccountOwnerAssignmentSubjectV3Command(
        "subject-7",
        "v3.1",
        receipt.receipt_id,
        receipt.receipt_version,
        receipt.content_hash,
        binding.binding_id,
        binding.binding_version,
        binding.content_hash,
        root.observation_id,
        root.observation_version,
        root.content_hash,
    )


def _register(
    repository: _Repository,
    receipt: AccountOwnerAssignmentProvenanceReceiptV3,
    receipt_provider: _ReceiptProvider | None = None,
    root_provider: _RootProvider | None = None,
) -> AccountOwnerAssignmentSubjectV3:
    return RegisterAccountOwnerAssignmentSubjectV3(
        receipt_provider=receipt_provider or _ReceiptProvider(receipt),
        root_provider=root_provider or _RootProvider(receipt.binding.creation_root),
        repository=repository,
    ).execute(_register_command(receipt))


def _approve_command(
    subject: AccountOwnerAssignmentSubjectV3,
) -> ApproveAccountOwnerAssignmentEvidenceV3Command:
    return ApproveAccountOwnerAssignmentEvidenceV3Command(
        "evidence-7", "v3.1", subject.subject_id, subject.subject_version, subject.content_hash
    )


def _approver() -> AccountOwnerAssignmentServerActor:
    return AccountOwnerAssignmentServerActor(
        "staff-9", 9, "account_owner_assignment_approver", is_staff=True
    )


def test_register_subject_uses_id_hash_only_double_reads_and_first_winner() -> None:
    receipt = _receipt()
    cutoff = receipt.recorded_at + timedelta(hours=1)
    repository = _Repository(cutoff)
    receipts = _ReceiptProvider(receipt)
    roots = _RootProvider(receipt.binding.creation_root)
    subject = _register(repository, receipt, receipts, roots)
    assert subject.receipt == receipt
    assert receipts.calls == roots.calls == 2
    assert repository.append_subject_calls == 1
    repository.clocks = [subject.valid_until + timedelta(days=1)]
    assert _register(repository, receipt, _ReceiptProvider(), _RootProvider()) == subject
    assert repository.append_subject_calls == 1


def test_register_subject_rejects_upstream_drift_without_append() -> None:
    receipt = _receipt()
    cutoff = receipt.recorded_at + timedelta(hours=1)
    repository = _Repository(cutoff)
    with pytest.raises(AccountOwnerAssignmentConflict, match="changed"):
        _register(
            repository,
            receipt,
            _ReceiptProvider(receipt, None),
            _RootProvider(receipt.binding.creation_root),
        )
    assert repository.append_subject_calls == 0


def test_staff_approval_double_reads_subject_upstream_and_approver() -> None:
    receipt = _receipt()
    cutoff = receipt.recorded_at + timedelta(hours=1)
    recorded_at = cutoff + timedelta(hours=1)
    repository = _Repository(cutoff)
    subject = _register(repository, receipt)
    repository.clocks = [recorded_at, recorded_at + timedelta(minutes=1)]
    receipts = _ReceiptProvider(receipt)
    roots = _RootProvider(receipt.binding.creation_root)
    approvers = _ApproverProvider(_approver())
    evidence = ApproveAccountOwnerAssignmentEvidenceV3(
        receipt_provider=receipts,
        root_provider=roots,
        approver_provider=approvers,
        repository=repository,
        validity_period=timedelta(days=1),
    ).execute(_approve_command(subject))
    assert evidence.assigned_owner_user_id == receipt.claimant.user_id
    assert evidence.approved_by == _approver().to_domain()
    assert receipts.calls == roots.calls == approvers.calls == 3
    assert repository.append_root_calls == 1


def test_approval_rejects_self_approval_and_existing_mapping_root() -> None:
    receipt = _receipt()
    cutoff = receipt.recorded_at + timedelta(hours=1)
    repository = _Repository(cutoff)
    subject = _register(repository, receipt)
    repository.clocks = [cutoff + timedelta(hours=1)]
    self_staff = AccountOwnerAssignmentServerActor(
        "different-actor",
        receipt.claimant.user_id,
        "account_owner_assignment_approver",
        is_staff=True,
    )
    use_case = ApproveAccountOwnerAssignmentEvidenceV3(
        receipt_provider=_ReceiptProvider(receipt),
        root_provider=_RootProvider(receipt.binding.creation_root),
        approver_provider=_ApproverProvider(self_staff),
        repository=repository,
        validity_period=timedelta(days=1),
    )
    with pytest.raises(AccountOwnerAssignmentUnavailable, match="independent"):
        use_case.execute(_approve_command(subject))


def test_exact_is_permanent_but_current_revalidates_both_heads_and_upstream() -> None:
    receipt = _receipt()
    cutoff = receipt.recorded_at + timedelta(hours=1)
    repository = _Repository(cutoff)
    subject = _register(repository, receipt)
    repository.clocks = [cutoff + timedelta(hours=1), cutoff + timedelta(hours=1)]
    evidence = ApproveAccountOwnerAssignmentEvidenceV3(
        receipt_provider=_ReceiptProvider(receipt),
        root_provider=_RootProvider(receipt.binding.creation_root),
        approver_provider=_ApproverProvider(_approver()),
        repository=repository,
        validity_period=timedelta(days=1),
    ).execute(_approve_command(subject))
    after_expiry = evidence.valid_until + timedelta(days=5)
    repository.clocks = [after_expiry]
    replay = ApproveAccountOwnerAssignmentEvidenceV3(
        receipt_provider=_ReceiptProvider(),
        root_provider=_RootProvider(),
        approver_provider=_ApproverProvider(),
        repository=repository,
        validity_period=timedelta(days=1),
    ).execute(_approve_command(subject))
    assert replay == evidence
    assert repository.append_root_calls == 1
    assert (
        GetExactAccountOwnerAssignmentEvidenceV3(repository).execute(
            GetExactAccountOwnerAssignmentEvidenceV3Command(
                evidence.evidence_id,
                evidence.evidence_version,
                evidence.content_hash,
                after_expiry,
            )
        )
        == evidence
    )
    current_at = evidence.recorded_at
    assert (
        GetCurrentAccountOwnerAssignmentEvidenceV3(
            receipt_provider=_ReceiptProvider(receipt),
            root_provider=_RootProvider(receipt.binding.creation_root),
            repository=repository,
        ).execute(
            GetCurrentAccountOwnerAssignmentEvidenceV3Command(
                evidence.evidence_id,
                evidence.evidence_version,
                evidence.content_hash,
                current_at,
            )
        )
        == evidence
    )
    assert (
        GetCurrentAccountOwnerAssignmentEvidenceV3(
            receipt_provider=_ReceiptProvider(),
            root_provider=_RootProvider(receipt.binding.creation_root),
            repository=repository,
        ).execute(
            GetCurrentAccountOwnerAssignmentEvidenceV3Command(
                evidence.evidence_id,
                evidence.evidence_version,
                evidence.content_hash,
                current_at,
            )
        )
        is None
    )


def test_approval_rechecks_all_inputs_at_authoritative_recorded_clock() -> None:
    receipt = _receipt()
    cutoff = receipt.recorded_at + timedelta(hours=1)
    recorded_at = cutoff + timedelta(hours=1)
    repository = _Repository(cutoff)
    subject = _register(repository, receipt)
    repository.clocks = [cutoff, recorded_at]
    with pytest.raises(AccountOwnerAssignmentConflict, match="inputs changed"):
        ApproveAccountOwnerAssignmentEvidenceV3(
            receipt_provider=_ReceiptProvider(receipt, receipt, None),
            root_provider=_RootProvider(receipt.binding.creation_root),
            approver_provider=_ApproverProvider(_approver()),
            repository=repository,
            validity_period=timedelta(days=1),
        ).execute(_approve_command(subject))
    assert repository.append_root_calls == 0


def test_application_has_no_v2_or_infrastructure_imports() -> None:
    source = (
        Path(__file__).parents[3]
        / "apps"
        / "account"
        / "application"
        / "account_owner_assignment_evidence_v3.py"
    )
    imports = {
        node.module
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8")))
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert not any("v2" in name for name in imports)
    assert not any("infrastructure" in name for name in imports)
