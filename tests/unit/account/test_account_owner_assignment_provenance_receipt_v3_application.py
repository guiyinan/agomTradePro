from __future__ import annotations

import ast
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentConflict,
    AccountOwnerAssignmentCorruption,
    AccountOwnerAssignmentServerActor,
    AccountOwnerAssignmentUnavailable,
)
from apps.account.application.account_owner_assignment_provenance_receipt_v3 import (
    GetCurrentAccountOwnerAssignmentProvenanceReceiptV3,
    GetCurrentAccountOwnerAssignmentProvenanceReceiptV3Command,
    GetExactAccountOwnerAssignmentProvenanceReceiptV3,
    GetExactAccountOwnerAssignmentProvenanceReceiptV3Command,
    IssueAccountOwnerAssignmentProvenanceReceiptV3,
    IssueAccountOwnerAssignmentProvenanceReceiptV3Command,
    PersistedAccountOwnerAssignmentProvenanceReceiptV3,
)
from apps.account.domain.account_owner_assignment_provenance_receipt_v3 import (
    AccountOwnerAssignmentProvenanceReceiptV3,
)
from apps.account.domain.allocated_physical_account_row_observation_v3 import (
    AllocatedPhysicalAccountRowObservationV3,
)
from apps.account.domain.canonical_account_creation_binding_v2 import (
    CanonicalAccountCreationBindingV2,
)
from tests.unit.account.test_canonical_account_creation_binding_v2 import _binding


def _at(day: int) -> datetime:
    return datetime(2026, 8, day, 12, tzinfo=UTC)


class BindingProvider:
    def __init__(self, values: list[CanonicalAccountCreationBindingV2 | None]) -> None:
        self.values = values
        self.calls: list[dict[str, object]] = []

    def get_exact(self, **kwargs: object) -> CanonicalAccountCreationBindingV2 | None:
        self.calls.append(kwargs)
        return self.values.pop(0) if len(self.values) > 1 else self.values[0]


class RootProvider:
    def __init__(self, values: list[AllocatedPhysicalAccountRowObservationV3 | None]) -> None:
        self.values = values
        self.current_calls: list[dict[str, object]] = []

    def get_exact_current(
        self, **kwargs: object
    ) -> AllocatedPhysicalAccountRowObservationV3 | None:
        self.current_calls.append(kwargs)
        return self.values.pop(0) if len(self.values) > 1 else self.values[0]


class ClaimantProvider:
    def __init__(self, values: list[AccountOwnerAssignmentServerActor | None]) -> None:
        self.values = values
        self.calls: list[dict[str, object]] = []

    def get_current(self, **kwargs: object) -> AccountOwnerAssignmentServerActor | None:
        self.calls.append(kwargs)
        return self.values.pop(0) if len(self.values) > 1 else self.values[0]


class Repository:
    def __init__(self, now: datetime = _at(9)) -> None:
        self.clock = now
        self.winner: PersistedAccountOwnerAssignmentProvenanceReceiptV3 | None = None
        self.head: PersistedAccountOwnerAssignmentProvenanceReceiptV3 | None = None
        self.exact: PersistedAccountOwnerAssignmentProvenanceReceiptV3 | None = None
        self.head_calls = 0
        self.expected_predecessor_hash: str | None = "unset"

    def atomic(self):  # type: ignore[no-untyped-def]
        return nullcontext()

    def now(self) -> datetime:
        return self.clock

    def get_winner(self, **kwargs: object):  # type: ignore[no-untyped-def]
        return self.winner

    def get_current_head(self, **kwargs: object):  # type: ignore[no-untyped-def]
        self.head_calls += 1
        return self.head

    def append(
        self,
        record: PersistedAccountOwnerAssignmentProvenanceReceiptV3,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PersistedAccountOwnerAssignmentProvenanceReceiptV3:
        self.expected_predecessor_hash = expected_predecessor_hash
        self.winner = self.head = self.exact = record
        return record

    def get_exact_by_hash(self, **kwargs: object):  # type: ignore[no-untyped-def]
        return self.exact


def _actor(user_id: int = 42) -> AccountOwnerAssignmentServerActor:
    return AccountOwnerAssignmentServerActor(f"human-{user_id}", user_id, "account_owner_claimant")


def _command(
    binding: CanonicalAccountCreationBindingV2, **changes: object
) -> IssueAccountOwnerAssignmentProvenanceReceiptV3Command:
    values: dict[str, object] = {
        "receipt_id": "creation-claim-7",
        "receipt_version": "v3.1",
        "binding_id": binding.binding_id,
        "binding_version": binding.binding_version,
        "expected_binding_content_hash": binding.content_hash,
        "expected_creation_root_content_hash": binding.creation_root_content_hash,
    }
    values.update(changes)
    return IssueAccountOwnerAssignmentProvenanceReceiptV3Command(**values)  # type: ignore[arg-type]


def _issuer(
    binding_provider: BindingProvider,
    root_provider: RootProvider,
    claimant_provider: ClaimantProvider,
    repository: Repository,
) -> IssueAccountOwnerAssignmentProvenanceReceiptV3:
    return IssueAccountOwnerAssignmentProvenanceReceiptV3(
        binding_provider=binding_provider,
        root_provider=root_provider,
        claimant_provider=claimant_provider,
        repository=repository,
        validity_period=timedelta(days=2),
    )


def _current_command(
    receipt: object, as_of: datetime
) -> GetCurrentAccountOwnerAssignmentProvenanceReceiptV3Command:
    checked = cast(AccountOwnerAssignmentProvenanceReceiptV3, receipt)
    return GetCurrentAccountOwnerAssignmentProvenanceReceiptV3Command(
        checked.receipt_id,
        checked.receipt_version,
        checked.content_hash,
        as_of,
    )


def _issue(repository: Repository | None = None):  # type: ignore[no-untyped-def]
    binding = _binding()
    repo = repository or Repository()
    bindings = BindingProvider([binding])
    roots = RootProvider([binding.creation_root])
    claimants = ClaimantProvider([_actor()])
    receipt = _issuer(bindings, roots, claimants, repo).execute(_command(binding))
    return binding, repo, bindings, roots, claimants, receipt


def test_command_is_id_hash_only_and_issue_double_reads_one_cutoff() -> None:
    binding, _, bindings, roots, claimants, receipt = _issue()
    assert set(_command(binding).__dataclass_fields__) == {
        "receipt_id",
        "receipt_version",
        "binding_id",
        "binding_version",
        "expected_binding_content_hash",
        "expected_creation_root_content_hash",
    }
    assert len(bindings.calls) == len(roots.current_calls) == len(claimants.calls) == 2
    assert {call["as_of"] for call in bindings.calls} == {_at(9)}
    assert receipt.binding == binding
    assert receipt.claimant.user_id == 42


def test_winner_replay_precedes_and_skips_all_current_reads_and_head() -> None:
    binding, repository, _, _, _, receipt = _issue()
    bindings = BindingProvider([binding])
    roots = RootProvider([None])
    claimants = ClaimantProvider([_actor()])
    repository.clock = _at(16)
    replay = _issuer(bindings, roots, claimants, repository).execute(_command(binding))
    assert replay == receipt
    assert len(bindings.calls) == 1
    assert roots.current_calls == []
    assert len(claimants.calls) == 1
    assert repository.head_calls == 1  # only the original issuance


def test_winner_selector_or_future_record_fails_closed() -> None:
    binding, repository, _, _, _, _ = _issue()
    with pytest.raises(AccountOwnerAssignmentConflict):
        _issuer(
            BindingProvider([binding]),
            RootProvider([None]),
            ClaimantProvider([_actor()]),
            repository,
        ).execute(_command(binding, expected_creation_root_content_hash="0" * 64))
    repository.clock = _at(8)
    with pytest.raises(AccountOwnerAssignmentCorruption, match="future"):
        _issuer(
            BindingProvider([binding]),
            RootProvider([None]),
            ClaimantProvider([_actor()]),
            repository,
        ).execute(_command(binding))
    repository.clock = _at(16)
    with pytest.raises(AccountOwnerAssignmentConflict, match="another claimant"):
        _issuer(
            BindingProvider([binding]),
            RootProvider([None]),
            ClaimantProvider([_actor(7)]),
            repository,
        ).execute(_command(binding))


def test_current_input_substitution_drift_and_claimant_mismatch_fail_closed() -> None:
    binding = _binding()
    with pytest.raises(AccountOwnerAssignmentCorruption):
        _issuer(
            BindingProvider([cast(CanonicalAccountCreationBindingV2, object())]),
            RootProvider([binding.creation_root]),
            ClaimantProvider([_actor()]),
            Repository(),
        ).execute(_command(binding))
    with pytest.raises(AccountOwnerAssignmentConflict):
        _issuer(
            BindingProvider([binding, binding]),
            RootProvider([binding.creation_root, binding.creation_root]),
            ClaimantProvider([_actor(), _actor(7)]),
            Repository(),
        ).execute(_command(binding))
    with pytest.raises(AccountOwnerAssignmentUnavailable):
        _issuer(
            BindingProvider([binding]),
            RootProvider([binding.creation_root]),
            ClaimantProvider([_actor(7)]),
            Repository(),
        ).execute(_command(binding))


def test_successor_uses_logical_head_predecessor_cas() -> None:
    binding, repository, _, _, _, first = _issue()
    repository.winner = None
    repository.clock = _at(10)
    second = _issuer(
        BindingProvider([binding]),
        RootProvider([binding.creation_root]),
        ClaimantProvider([_actor()]),
        repository,
    ).execute(_command(binding, receipt_version="v3.2"))
    assert second.supersedes_content_hash == first.content_hash
    assert repository.expected_predecessor_hash == first.content_hash


def test_exact_history_survives_receipt_and_root_ttl_expiry() -> None:
    binding, repository, _, _, _, receipt = _issue()
    exact = GetExactAccountOwnerAssignmentProvenanceReceiptV3(
        repository=repository, binding_provider=BindingProvider([binding])
    ).execute(
        GetExactAccountOwnerAssignmentProvenanceReceiptV3Command(
            receipt.receipt_id,
            receipt.receipt_version,
            receipt.content_hash,
            _at(16),
        )
    )
    assert exact == receipt
    assert (
        GetExactAccountOwnerAssignmentProvenanceReceiptV3(
            repository=repository, binding_provider=BindingProvider([binding])
        ).execute(
            GetExactAccountOwnerAssignmentProvenanceReceiptV3Command(
                receipt.receipt_id,
                receipt.receipt_version,
                receipt.content_hash,
                _at(8),
            )
        )
        is None
    )


def test_closed_current_requires_receipt_ttl_final_head_and_exact_current_root() -> None:
    binding, repository, _, _, _, receipt = _issue()
    reader = GetCurrentAccountOwnerAssignmentProvenanceReceiptV3(
        repository=repository,
        binding_provider=BindingProvider([binding]),
        root_provider=RootProvider([binding.creation_root]),
    )
    assert reader.execute(_current_command(receipt, _at(10))) == receipt
    assert (
        GetCurrentAccountOwnerAssignmentProvenanceReceiptV3(
            repository=repository,
            binding_provider=BindingProvider([binding]),
            root_provider=RootProvider([None]),
        ).execute(_current_command(receipt, _at(10)))
        is None
    )
    assert (
        GetCurrentAccountOwnerAssignmentProvenanceReceiptV3(
            repository=repository,
            binding_provider=BindingProvider([binding]),
            root_provider=RootProvider([binding.creation_root]),
        ).execute(_current_command(receipt, _at(11)))
        is None
    )


def test_current_command_is_id_hash_only_and_server_restores_exact_receipt() -> None:
    binding, repository, _, _, _, receipt = _issue()
    command = _current_command(receipt, _at(10))
    assert set(command.__dataclass_fields__) == {
        "receipt_id",
        "receipt_version",
        "expected_content_hash",
        "as_of",
    }
    repository.exact = None
    head_calls_before = repository.head_calls
    reader = GetCurrentAccountOwnerAssignmentProvenanceReceiptV3(
        repository=repository,
        binding_provider=BindingProvider([binding]),
        root_provider=RootProvider([binding.creation_root]),
    )
    assert reader.execute(command) is None
    assert repository.head_calls == head_calls_before


def test_application_has_no_orm_infrastructure_or_prior_receipt_fallback() -> None:
    source = (
        Path(__file__).parents[3]
        / "apps/account/application/account_owner_assignment_provenance_receipt_v3.py"
    ).read_text(encoding="utf-8")
    modules = {
        node.module
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert ".objects" not in source
    assert not any("infrastructure" in module for module in modules)
    assert not any("provenance_receipt_v2" in module for module in modules)
