from __future__ import annotations

import copy
import pickle
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from apps.account.application.account_authority_final_revalidation_v3_contracts import (
    AccountAuthorityV3FinalRootSelection,
)
from apps.account.application.owner_tenant_authority_v3 import (
    GetCurrentOwnerTenantAuthorityV3Command,
)
from apps.account.application.owner_tenant_authority_v3_contracts import (
    CurrentOwnerTenantAuthorityV3,
    PersistedOwnerTenantAuthorityV3,
)
from apps.account.application.physical_account_row_observation_v2 import (
    PhysicalAccountRowProviderIdentity,
)
from apps.account.infrastructure import account_authority_final_revalidator_v3 as module
from apps.account.infrastructure.account_authority_final_revalidator_v3 import (
    AccountAuthorityCompleteGraphFinalRevalidationProofV3,
    AccountAuthorityFinalRevalidationProofV3,
    AccountAuthorityFinalRevalidationUnavailable,
    AccountAuthorityFinalRevalidatorV3,
)
from apps.account.infrastructure.account_authority_generation import (
    AccountAuthorityGenerationChanged,
    AccountAuthorityGenerationProof,
)
from apps.account.infrastructure.account_authority_shadow_scanner import (
    AccountAuthorityCurrentGraphReadV3,
    AccountAuthorityCurrentGraphSelectorV3,
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


def _physical_identity(
    *,
    using: str = "default",
    xid: str = "test-xid",
    generation: int | None = None,
) -> PhysicalAccountRowProviderIdentity:
    """Build one synthetic, internally consistent physical transaction identity."""

    return PhysicalAccountRowProviderIdentity(
        using=using,
        wrapper_token=object(),
        dbapi_token=object(),
        backend_pid=54321,
        transaction_xid=xid,
        thread_id=1,
        task_token=None,
        generation=generation,
    )


class _CompleteGraphReader:
    """Return one injectable current graph while recording complete-read order."""

    def __init__(
        self,
        events: list[str],
        current: CurrentOwnerTenantAuthorityV3,
        *,
        selector: AccountAuthorityCurrentGraphSelectorV3,
        physical_identity: PhysicalAccountRowProviderIdentity,
        checked_at: datetime,
    ) -> None:
        self.events = events
        self.current = current
        self._selector = selector
        self.physical_identity = physical_identity
        self.checked_at = checked_at
        self.read_error: BaseException | None = None

    @property
    def database_alias(self) -> str:
        """Return the exact synthetic alias."""

        return "default"

    @property
    def transaction_mode(self) -> str:
        """Require the final generation-fenced RC/RW transaction."""

        return "generation_fenced_read_committed_read_write"

    def selector_for(
        self,
        command: GetCurrentOwnerTenantAuthorityV3Command,
    ) -> AccountAuthorityCurrentGraphSelectorV3:
        """Return the expected redacted complete-graph selector."""

        assert command.expected_content_hash == self._selector.authority_content_hash
        return self._selector

    def read(
        self,
        command: GetCurrentOwnerTenantAuthorityV3Command,
        *,
        generation: int | None = None,
    ) -> AccountAuthorityCurrentGraphReadV3:
        """Record the reread and return its exact graph cutoff and identity."""

        self.events.append(f"graph_read:{generation}")
        if self.read_error is not None:
            raise self.read_error
        authority = (
            None if self.current is None else replace(self.current, observed_at=self.checked_at)
        )
        return AccountAuthorityCurrentGraphReadV3(
            checked_at=self.checked_at,
            authority=authority,
            physical_identity=self.physical_identity,
        )


def _complete_scan_and_reader(
    events: list[str],
    *,
    current: CurrentOwnerTenantAuthorityV3 | None = None,
    checked_at: datetime | None = None,
) -> tuple[
    GetCurrentOwnerTenantAuthorityV3Command,
    AccountAuthorityShadowScanResultV3,
    _CompleteGraphReader,
    PhysicalAccountRowProviderIdentity,
    PhysicalAccountRowProviderIdentity,
]:
    """Build a matched complete scan and the independent final graph reader."""

    current = _legacy_current() if current is None else current
    shadow_checked_at = current.observed_at
    final_checked_at = (
        shadow_checked_at + timedelta(seconds=2) if checked_at is None else checked_at
    )
    command = GetCurrentOwnerTenantAuthorityV3Command(
        current.authority.authority_id,
        current.authority.authority_version,
        current.authority.content_hash,
    )
    comparison = _compare_current_observations(current, current)
    shadow_fingerprint = comparison.shadow
    assert shadow_fingerprint is not None
    selector = AccountAuthorityCurrentGraphSelectorV3(
        database_alias="default",
        authority_selector_hash=shadow_fingerprint.authority_identity_hash,
        authority_content_hash=command.expected_content_hash,
        actor_source_selector_hash=shadow_fingerprint.actor_source_identity_hash,
        actor_source_content_hash=current.authentication.source_content_hash,
    )
    shadow_identity = _physical_identity(xid="shadow-xid")
    capture_identity = _physical_identity(xid="capture-xid")
    final_identity = _physical_identity(xid="final-xid", generation=73)
    scan = AccountAuthorityShadowScanResultV3(
        database_alias="default",
        proof_generation=73,
        comparison=comparison,
        selector=selector,
        checked_at=shadow_checked_at,
        physical_identity=shadow_identity,
    )
    reader = _CompleteGraphReader(
        events,
        current,
        selector=selector,
        physical_identity=final_identity,
        checked_at=final_checked_at,
    )
    return command, scan, reader, capture_identity, final_identity


def _install_complete_fence_fakes(
    monkeypatch: pytest.MonkeyPatch,
    events: list[str],
    *,
    scan: AccountAuthorityShadowScanResultV3,
    capture_identity: PhysicalAccountRowProviderIdentity,
    final_identity: PhysicalAccountRowProviderIdentity,
    fenced_generation: int | None = None,
) -> None:
    """Replace only transaction capabilities while preserving observable ordering."""

    @contextmanager
    def rr_snapshot(using: str) -> Iterator[AccountAuthorityGenerationProof]:
        assert using == scan.database_alias
        events.append("rr_generation")
        yield AccountAuthorityGenerationProof(
            using=using,
            generation=scan.proof_generation,
        )

    @contextmanager
    def rc_fence(
        proof: AccountAuthorityGenerationProof,
        *,
        using: str,
    ) -> Iterator[int]:
        assert using == scan.database_alias
        events.append("generation_for_share")
        try:
            yield proof.generation if fenced_generation is None else fenced_generation
        except BaseException:
            events.append("rollback")
            raise

    def snapshot_identity(*, using: str, connection: object) -> PhysicalAccountRowProviderIdentity:
        del connection
        assert using == scan.database_alias
        events.append("snapshot_identity")
        return capture_identity

    def validate_active_identity(
        identity: PhysicalAccountRowProviderIdentity,
        *,
        using: str,
        generation: int,
    ) -> None:
        assert using == scan.database_alias
        events.append(f"fence_identity:{generation}")
        if identity != final_identity:
            raise AccountAuthorityFinalRevalidationUnavailable(
                "injected graph physical identity mismatch"
            )

    monkeypatch.setattr(module, "_connection", lambda _using: object())
    monkeypatch.setattr(module, "_read_only_repeatable_read_snapshot", rr_snapshot)
    monkeypatch.setattr(module, "_read_committed_generation_fence", rc_fence)
    monkeypatch.setattr(
        module,
        "capture_account_authority_snapshot_physical_provider_identity",
        snapshot_identity,
    )
    monkeypatch.setattr(
        module,
        "validate_active_account_authority_physical_provider_identity",
        validate_active_identity,
    )


def test_server_proof_cannot_be_serialized_or_copied() -> None:
    proof = AccountAuthorityFinalRevalidationProofV3()

    with pytest.raises((TypeError, pickle.PicklingError)):
        pickle.dumps(proof)
    with pytest.raises(TypeError):
        copy.copy(proof)
    with pytest.raises(TypeError):
        copy.deepcopy(proof)


def test_complete_proof_is_a_distinct_nontransferable_handle() -> None:
    proof = AccountAuthorityCompleteGraphFinalRevalidationProofV3()

    with pytest.raises((TypeError, pickle.PicklingError)):
        pickle.dumps(proof)
    with pytest.raises(TypeError):
        copy.copy(proof)
    with pytest.raises(TypeError):
        copy.deepcopy(proof)


def test_partial_and_complete_proof_types_cannot_be_mixed() -> None:
    events: list[str] = []
    repository = _Repository(events, clock=_legacy_current().observed_at + timedelta(seconds=1))
    revalidator = AccountAuthorityFinalRevalidatorV3(repository, using="default")

    with pytest.raises(TypeError, match="exact AccountAuthorityCompleteGraph"):
        with revalidator.fence_complete(AccountAuthorityFinalRevalidationProofV3()):
            pytest.fail("a partial proof must not enter a complete graph fence")
    with pytest.raises(TypeError, match="exact AccountAuthorityFinalRevalidationProofV3"):
        with revalidator.fence(AccountAuthorityCompleteGraphFinalRevalidationProofV3()):
            pytest.fail("a complete proof must not enter a partial root fence")


def test_complete_capture_and_fence_bind_ordered_full_graph_and_consume_proof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    command, scan, reader, capture_identity, final_identity = _complete_scan_and_reader(events)
    repository = _Repository(events, clock=scan.checked_at + timedelta(seconds=1))
    revalidator = AccountAuthorityFinalRevalidatorV3(
        repository,
        using="default",
        complete_graph_reader=reader,
    )
    _install_complete_fence_fakes(
        monkeypatch,
        events,
        scan=scan,
        capture_identity=capture_identity,
        final_identity=final_identity,
    )

    proof = revalidator.capture_complete(command, scan)
    assert events == [
        "rr_generation",
        "snapshot_identity",
        "database_clock",
        "snapshot_identity",
    ]

    events.clear()
    repository.clock = reader.checked_at + timedelta(seconds=1)
    with revalidator.fence_complete(proof) as result:
        assert result.scope == "account_authority_complete_graph"
        assert result.selector == scan.selector
        assert result.fingerprint == scan.comparison.shadow
        assert result.generation == scan.proof_generation
        assert result.shadow_checked_at == scan.checked_at
        assert result.checked_at == reader.checked_at
        assert result.backend_pid == final_identity.backend_pid
        assert result.transaction_xid == final_identity.transaction_xid
        assert events == [
            "generation_for_share",
            "graph_read:73",
            "fence_identity:73",
        ]
    assert events[-3:] == [
        "graph_read:73",
        "fence_identity:73",
        "database_clock",
    ]
    with pytest.raises(AccountAuthorityFinalRevalidationUnavailable, match="already consumed"):
        with revalidator.fence_complete(proof):
            pytest.fail("a consumed complete proof must not enter another fence")


def test_complete_capture_rejects_legacy_scan_without_opening_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    command, partial_scan = _scan()
    current = _legacy_current()
    shadow = _compare_current_observations(current, current).shadow
    assert shadow is not None
    selector = AccountAuthorityCurrentGraphSelectorV3(
        database_alias="default",
        authority_selector_hash=shadow.authority_identity_hash,
        authority_content_hash=command.expected_content_hash,
        actor_source_selector_hash=shadow.actor_source_identity_hash,
        actor_source_content_hash=current.authentication.source_content_hash,
    )
    reader = _CompleteGraphReader(
        events,
        current,
        selector=selector,
        physical_identity=_physical_identity(xid="final-xid", generation=73),
        checked_at=current.observed_at + timedelta(seconds=2),
    )
    revalidator = AccountAuthorityFinalRevalidatorV3(
        _Repository(events, clock=current.observed_at + timedelta(seconds=1)),
        using="default",
        complete_graph_reader=reader,
    )
    monkeypatch.setattr(
        module,
        "_read_only_repeatable_read_snapshot",
        lambda _using: pytest.fail("an incomplete partial scan must be rejected first"),
    )

    with pytest.raises(AccountAuthorityFinalRevalidationUnavailable, match="omitted"):
        revalidator.capture_complete(command, partial_scan)


def test_complete_capture_rejects_selector_mismatch_and_cutoff_rollback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    command, scan, reader, capture_identity, final_identity = _complete_scan_and_reader(events)
    repository = _Repository(events, clock=scan.checked_at + timedelta(seconds=1))
    revalidator = AccountAuthorityFinalRevalidatorV3(
        repository,
        using="default",
        complete_graph_reader=reader,
    )
    _install_complete_fence_fakes(
        monkeypatch,
        events,
        scan=scan,
        capture_identity=capture_identity,
        final_identity=final_identity,
    )
    mismatched = replace(
        scan,
        selector=replace(scan.selector, authority_content_hash="f" * 64),
    )
    with pytest.raises(AccountAuthorityFinalRevalidationUnavailable, match="selector"):
        revalidator.capture_complete(command, mismatched)
    assert "rr_generation" not in events

    repository.clock = scan.checked_at - timedelta(microseconds=1)
    with pytest.raises(AccountAuthorityFinalRevalidationUnavailable, match="moved behind"):
        revalidator.capture_complete(command, scan)


@pytest.mark.parametrize(
    "failure",
    ["missing", "mismatch", "generation", "reader_error", "cutoff", "physical"],
)
def test_complete_fence_fails_closed_before_yield_and_marks_rollback(
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    events: list[str] = []
    command, scan, reader, capture_identity, final_identity = _complete_scan_and_reader(events)
    repository = _Repository(events, clock=scan.checked_at + timedelta(seconds=1))
    revalidator = AccountAuthorityFinalRevalidatorV3(
        repository,
        using="default",
        complete_graph_reader=reader,
    )
    fenced_generation = None
    if failure == "missing":
        reader.current = None
    elif failure == "mismatch":
        assert reader.current is not None
        reader.current = replace(
            reader.current,
            valid_until=reader.current.valid_until - timedelta(seconds=1),
        )
    elif failure == "generation":
        fenced_generation = scan.proof_generation + 1
    elif failure == "reader_error":
        reader.read_error = RuntimeError("injected graph read failure")
    elif failure == "cutoff":
        reader.checked_at = scan.checked_at
    elif failure == "physical":
        reader.physical_identity = _physical_identity(xid="switched-transaction", generation=73)
    _install_complete_fence_fakes(
        monkeypatch,
        events,
        scan=scan,
        capture_identity=capture_identity,
        final_identity=final_identity,
        fenced_generation=fenced_generation,
    )

    proof = revalidator.capture_complete(command, scan)
    events.clear()
    expected_error = (
        RuntimeError
        if failure == "reader_error"
        else (
            AccountAuthorityGenerationChanged
            if failure in {"mismatch", "generation"}
            else AccountAuthorityFinalRevalidationUnavailable
        )
    )
    with pytest.raises(expected_error):
        with revalidator.fence_complete(proof):
            pytest.fail("an incomplete or changed graph must not be yielded")
    assert events[-1] == "rollback"
    if failure == "generation":
        assert not any(event.startswith("graph_read:") for event in events)


@pytest.mark.parametrize("exit_mode", ["equal", "past", "backwards"])
def test_complete_exit_lease_is_strict_and_clock_must_not_move_backwards(
    monkeypatch: pytest.MonkeyPatch,
    exit_mode: str,
) -> None:
    events: list[str] = []
    command, scan, reader, capture_identity, final_identity = _complete_scan_and_reader(events)
    repository = _Repository(events, clock=scan.checked_at + timedelta(seconds=1))
    revalidator = AccountAuthorityFinalRevalidatorV3(
        repository,
        using="default",
        complete_graph_reader=reader,
    )
    _install_complete_fence_fakes(
        monkeypatch,
        events,
        scan=scan,
        capture_identity=capture_identity,
        final_identity=final_identity,
    )
    proof = revalidator.capture_complete(command, scan)
    repository.clock = reader.checked_at + timedelta(seconds=1)
    with pytest.raises(AccountAuthorityFinalRevalidationUnavailable):
        with revalidator.fence_complete(proof) as result:
            if exit_mode == "equal":
                repository.clock = result.valid_until
            elif exit_mode == "past":
                repository.clock = result.valid_until + timedelta(microseconds=1)
            else:
                repository.clock = result.checked_at - timedelta(microseconds=1)
    assert events[-1] == "rollback"


def test_complete_caller_exception_propagates_through_rollback_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    command, scan, reader, capture_identity, final_identity = _complete_scan_and_reader(events)
    repository = _Repository(events, clock=scan.checked_at + timedelta(seconds=1))
    revalidator = AccountAuthorityFinalRevalidatorV3(
        repository,
        using="default",
        complete_graph_reader=reader,
    )
    _install_complete_fence_fakes(
        monkeypatch,
        events,
        scan=scan,
        capture_identity=capture_identity,
        final_identity=final_identity,
    )
    proof = revalidator.capture_complete(command, scan)

    with pytest.raises(RuntimeError, match="caller failure"):
        with revalidator.fence_complete(proof):
            raise RuntimeError("caller failure")
    assert events[-1] == "rollback"


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
        assert result.valid_until == current.authority.valid_until
        assert events == [
            "generation_for_update_compare",
            "database_clock",
            "selected_root",
            "revocation",
        ]
    assert events[-1] == "database_clock"
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


def test_final_fence_rejects_when_authority_expires_during_caller_work(
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
        yield proof.generation

    monkeypatch.setattr(module, "_read_only_repeatable_read_snapshot", rr_snapshot)
    monkeypatch.setattr(module, "_read_committed_generation_fence", rc_fence)

    proof = revalidator.capture(command, scan)
    with pytest.raises(AccountAuthorityFinalRevalidationUnavailable, match="expired"):
        with revalidator.fence(proof) as result:
            assert result.checked_at < result.valid_until
            repository.clock = result.valid_until

    assert events[-1] == "database_clock"


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
