from __future__ import annotations

import copy
import pickle
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta

import pytest

from apps.account.application.account_authority_final_revalidation_v3_contracts import (
    AccountAuthorityV3FinalRootSelection,
)
from apps.account.application.owner_tenant_authority_v3 import (
    GetCurrentOwnerTenantAuthorityV3Command,
)
from apps.account.application.owner_tenant_authority_v3_contracts import (
    PersistedOwnerTenantAuthorityV3,
)
from apps.account.infrastructure import account_authority_final_revalidator_v3 as module
from apps.account.infrastructure.account_authority_final_revalidator_v3 import (
    AccountAuthorityFinalRevalidationProofV3,
    AccountAuthorityFinalRevalidationUnavailable,
    AccountAuthorityFinalRevalidatorV3,
)
from apps.account.infrastructure.account_authority_generation import (
    AccountAuthorityGenerationChanged,
    AccountAuthorityGenerationProof,
)
from apps.account.infrastructure.account_authority_shadow_scanner import (
    AccountAuthorityShadowScanResultV3,
    _compare_current_observations,
)
from tests.unit.account.test_account_authority_shadow_scanner import _legacy_current


class _Repository:
    def __init__(self, events: list[str], *, clock: datetime) -> None:
        current = _legacy_current()
        self.selection = AccountAuthorityV3FinalRootSelection(
            row_id=41,
            record=PersistedOwnerTenantAuthorityV3(
                authority=current.authority,
                authentication=current.authentication,
            ),
        )
        self.events = events
        self.clock = clock

    @property
    def database_alias(self) -> str:
        """Return the fake repository alias used by this test."""

        return "default"

    def database_clock(self) -> datetime:
        self.events.append("database_clock")
        return self.clock

    def get_selected_root(
        self,
        *,
        authority_id: str,
        authority_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> AccountAuthorityV3FinalRootSelection | None:
        self.events.append("selected_root")
        authority = self.selection.record.authority
        if (authority_id, authority_version, expected_content_hash) != (
            authority.authority_id,
            authority.authority_version,
            authority.content_hash,
        ):
            return None
        if authority.recorded_at > as_of:
            return None
        return self.selection

    def get_exact_revocation(
        self,
        *,
        selection: AccountAuthorityV3FinalRootSelection,
        as_of: datetime,
    ) -> None:
        self.events.append("revocation")
        assert selection == self.selection
        assert as_of == self.clock
        return None


def _scan() -> tuple[GetCurrentOwnerTenantAuthorityV3Command, AccountAuthorityShadowScanResultV3]:
    current = _legacy_current()
    command = GetCurrentOwnerTenantAuthorityV3Command(
        current.authority.authority_id,
        current.authority.authority_version,
        current.authority.content_hash,
    )
    return command, AccountAuthorityShadowScanResultV3(
        database_alias="default",
        proof_generation=73,
        comparison=_compare_current_observations(current, current),
    )


def test_server_proof_cannot_be_serialized_or_copied() -> None:
    proof = AccountAuthorityFinalRevalidationProofV3()

    with pytest.raises((TypeError, pickle.PicklingError)):
        pickle.dumps(proof)
    with pytest.raises(TypeError):
        copy.copy(proof)
    with pytest.raises(TypeError):
        copy.deepcopy(proof)


def test_capture_and_final_revalidation_recheck_in_order_and_consume_proof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    current = _legacy_current()
    repository = _Repository(
        events,
        clock=current.observed_at + timedelta(seconds=1),
    )
    command, scan = _scan()
    revalidator = AccountAuthorityFinalRevalidatorV3(repository, using="default")

    @contextmanager
    def rr_snapshot(using: str) -> Iterator[AccountAuthorityGenerationProof]:
        assert using == "default"
        events.append("rr_generation")
        yield AccountAuthorityGenerationProof(using=using, generation=scan.proof_generation)

    @contextmanager
    def rc_fence(
        proof: AccountAuthorityGenerationProof,
        *,
        using: str,
    ) -> Iterator[int]:
        assert using == "default"
        events.append("generation_for_update_compare")
        yield proof.generation

    monkeypatch.setattr(module, "_read_only_repeatable_read_snapshot", rr_snapshot)
    monkeypatch.setattr(module, "_read_committed_generation_fence", rc_fence)

    proof = revalidator.capture(command, scan)
    assert events == ["rr_generation", "database_clock", "selected_root", "revocation"]

    events.clear()
    with revalidator.fence(proof) as result:
        assert result.scope == "owner_tenant_authority_v3_root_revocation_only"
        assert events == [
            "generation_for_update_compare",
            "database_clock",
            "selected_root",
            "revocation",
        ]
    with pytest.raises(AccountAuthorityFinalRevalidationUnavailable, match="consumed"):
        with revalidator.fence(proof):
            pytest.fail("a consumed proof must not enter the final fence")


def test_stale_generation_rejects_before_clock_or_selected_row_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    current = _legacy_current()
    repository = _Repository(events, clock=current.observed_at + timedelta(seconds=1))
    command, scan = _scan()
    revalidator = AccountAuthorityFinalRevalidatorV3(repository, using="default")

    @contextmanager
    def rr_snapshot(using: str) -> Iterator[AccountAuthorityGenerationProof]:
        yield AccountAuthorityGenerationProof(using=using, generation=scan.proof_generation)

    @contextmanager
    def rc_fence(
        proof: AccountAuthorityGenerationProof,
        *,
        using: str,
    ) -> Iterator[int]:
        events.append("generation_for_update_compare")
        raise AccountAuthorityGenerationChanged("test generation changed")
        yield proof.generation  # pragma: no cover

    monkeypatch.setattr(module, "_read_only_repeatable_read_snapshot", rr_snapshot)
    monkeypatch.setattr(module, "_read_committed_generation_fence", rc_fence)

    proof = revalidator.capture(command, scan)
    events.clear()
    with pytest.raises(AccountAuthorityGenerationChanged, match="changed"):
        with revalidator.fence(proof):
            pytest.fail("a changed generation must not yield a final result")
    assert events == ["generation_for_update_compare"]


def test_capture_rejects_unmatched_scan_before_opening_database_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    current = _legacy_current()
    repository = _Repository(events, clock=current.observed_at + timedelta(seconds=1))
    command, scan = _scan()
    mismatched_scan = AccountAuthorityShadowScanResultV3(
        database_alias=scan.database_alias,
        proof_generation=scan.proof_generation,
        comparison=_compare_current_observations(None, current),
    )
    revalidator = AccountAuthorityFinalRevalidatorV3(repository, using="default")

    def unexpected_snapshot(_using: str) -> None:
        events.append("opened")
        pytest.fail("an unmatched shadow result cannot issue a final proof")

    monkeypatch.setattr(module, "_read_only_repeatable_read_snapshot", unexpected_snapshot)

    with pytest.raises(AccountAuthorityFinalRevalidationUnavailable, match="matched shadow"):
        revalidator.capture(command, mismatched_scan)
    assert events == []


def test_capture_rejects_scan_from_another_database_alias_before_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    current = _legacy_current()
    repository = _Repository(events, clock=current.observed_at + timedelta(seconds=1))
    command, scan = _scan()
    cross_alias_scan = AccountAuthorityShadowScanResultV3(
        database_alias="other",
        proof_generation=scan.proof_generation,
        comparison=scan.comparison,
    )
    revalidator = AccountAuthorityFinalRevalidatorV3(repository, using="default")

    def unexpected_snapshot(_using: str) -> None:
        events.append("opened")
        pytest.fail("a scan from another alias cannot issue a final proof")

    monkeypatch.setattr(module, "_read_only_repeatable_read_snapshot", unexpected_snapshot)

    with pytest.raises(AccountAuthorityFinalRevalidationUnavailable, match="database alias"):
        revalidator.capture(command, cross_alias_scan)
    assert events == []
