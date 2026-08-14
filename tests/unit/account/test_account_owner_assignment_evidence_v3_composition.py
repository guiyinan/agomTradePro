from __future__ import annotations

import os
from pathlib import Path

import django
import pytest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings_account_creation_consumption")
django.setup()

from apps.account import account_owner_assignment_evidence_v3_composition as composition
from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentCorruption,
    AccountOwnerAssignmentUnavailable,
)
from apps.account.application.account_owner_assignment_evidence_v3 import (
    GetCurrentAccountOwnerAssignmentEvidenceV3,
)
from apps.account.application.account_owner_assignment_mapping_v3 import (
    GetCurrentAuthoritativeAccountMappingV3,
)
from apps.account.application.allocated_physical_account_row_observation_v3 import (
    AllocatedPhysicalAccountRowObservationV3Conflict,
    AllocatedPhysicalAccountRowObservationV3Corruption,
    AllocatedPhysicalAccountRowObservationV3Unavailable,
)
from apps.account.application.canonical_account_creation_binding_v2 import (
    CanonicalAccountCreationBindingV2Conflict,
    CanonicalAccountCreationBindingV2Corruption,
    CanonicalAccountCreationBindingV2Unavailable,
)
from tests.unit.account.test_account_owner_assignment_provenance_receipt_v3 import (
    _receipt,
)


class _Reader:
    def __init__(self, values: list[object]) -> None:
        self.values = values
        self.commands: list[object] = []

    def execute(self, command: object) -> object:
        self.commands.append(command)
        value = self.values.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


class _NeverReader:
    def execute(self, command: object) -> object:
        raise AssertionError(f"unexpected current read: {command!r}")


def _physical_provider(
    exact: _Reader, current: _Reader | _NeverReader
) -> composition.AccountExactCurrentAllocatedPhysicalAccountRowObservationV3Provider:
    provider = object.__new__(
        composition.AccountExactCurrentAllocatedPhysicalAccountRowObservationV3Provider
    )
    provider._exact = exact
    provider._current = current
    return provider


def test_physical_provider_delegates_id_hash_selector_to_current_reader() -> None:
    root = _receipt().binding.creation_root
    current = _Reader([root])
    provider = _physical_provider(_NeverReader(), current)

    assert (
        provider.get_exact_current(
            observation_id=root.observation_id,
            observation_version=root.observation_version,
            expected_content_hash=root.content_hash,
            as_of=root.recorded_at,
        )
        == root
    )
    assert len(current.commands) == 1
    assert not hasattr(current.commands[0], "expected_observation")


def test_physical_provider_propagates_none_from_current_reader() -> None:
    root = _receipt().binding.creation_root
    provider = _physical_provider(_NeverReader(), _Reader([None]))

    assert (
        provider.get_exact_current(
            observation_id=root.observation_id,
            observation_version=root.observation_version,
            expected_content_hash=root.content_hash,
            as_of=root.recorded_at,
        )
        is None
    )


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (
            AllocatedPhysicalAccountRowObservationV3Unavailable("x"),
            AccountOwnerAssignmentUnavailable,
        ),
        (
            AllocatedPhysicalAccountRowObservationV3Conflict("x"),
            AccountOwnerAssignmentCorruption,
        ),
        (AllocatedPhysicalAccountRowObservationV3Corruption("x"), AccountOwnerAssignmentCorruption),
    ],
)
def test_physical_provider_translates_taxonomy(source: Exception, target: type[Exception]) -> None:
    root = _receipt().binding.creation_root
    provider = _physical_provider(_Reader([source]), _NeverReader())

    with pytest.raises(target):
        provider.get_exact(
            observation_id=root.observation_id,
            observation_version=root.observation_version,
            expected_content_hash=root.content_hash,
            as_of=root.recorded_at,
        )


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (CanonicalAccountCreationBindingV2Unavailable("x"), AccountOwnerAssignmentUnavailable),
        (CanonicalAccountCreationBindingV2Conflict("x"), AccountOwnerAssignmentCorruption),
        (CanonicalAccountCreationBindingV2Corruption("x"), AccountOwnerAssignmentCorruption),
    ],
)
def test_binding_provider_translates_taxonomy(source: Exception, target: type[Exception]) -> None:
    provider = object.__new__(composition.AccountExactCanonicalAccountCreationBindingV2Provider)
    provider._reader = _Reader([source])
    binding = _receipt().binding

    with pytest.raises(target):
        provider.get_exact(
            binding_id=binding.binding_id,
            binding_version=binding.binding_version,
            expected_content_hash=binding.content_hash,
            as_of=binding.recorded_at,
        )


def test_receipt_provider_delegates_id_hash_selector_to_current_reader() -> None:
    receipt = _receipt()
    provider = object.__new__(
        composition.AccountExactCurrentAccountOwnerAssignmentProvenanceReceiptV3Provider
    )
    current = _Reader([receipt])
    provider._current = current

    assert (
        provider.get_exact_current(
            receipt_id=receipt.receipt_id,
            receipt_version=receipt.receipt_version,
            expected_content_hash=receipt.content_hash,
            as_of=receipt.recorded_at,
        )
        == receipt
    )
    assert len(current.commands) == 1
    assert not hasattr(current.commands[0], "expected_receipt")


def test_receipt_provider_propagates_none_from_current_reader() -> None:
    receipt = _receipt()
    provider = object.__new__(
        composition.AccountExactCurrentAccountOwnerAssignmentProvenanceReceiptV3Provider
    )
    provider._current = _Reader([None])

    assert (
        provider.get_exact_current(
            receipt_id=receipt.receipt_id,
            receipt_version=receipt.receipt_version,
            expected_content_hash=receipt.content_hash,
            as_of=receipt.recorded_at,
        )
        is None
    )


class _Repository:
    aliases: list[str] = []

    def __init__(self, *, using: str) -> None:
        self.aliases.append(using)


def test_builders_publish_only_read_use_cases(monkeypatch: pytest.MonkeyPatch) -> None:
    _Repository.aliases.clear()
    for name in (
        "DjangoCanonicalAccountCreationConsumptionRepository",
        "DjangoAllocatedPhysicalAccountRowObservationV3Repository",
        "DjangoAccountOwnerAssignmentProvenanceReceiptV3Repository",
        "DjangoAccountOwnerAssignmentEvidenceV3Repository",
    ):
        monkeypatch.setattr(composition, name, _Repository)

    evidence = composition.build_current_account_owner_assignment_evidence_v3(using="audit")
    mapping = composition.build_current_authoritative_account_mapping_v3(using="audit")

    assert type(evidence) is GetCurrentAccountOwnerAssignmentEvidenceV3
    assert type(mapping) is GetCurrentAuthoritativeAccountMappingV3
    assert _Repository.aliases == ["audit"] * 8
    for graph in (evidence, mapping):
        assert all(
            not hasattr(graph, capability)
            for capability in ("append", "atomic", "approve", "execute_approval")
        )


def test_composition_has_no_simulated_owner_dependency() -> None:
    source = Path(composition.__file__).read_text(encoding="utf-8")

    assert "apps.simulated_trading" not in source
