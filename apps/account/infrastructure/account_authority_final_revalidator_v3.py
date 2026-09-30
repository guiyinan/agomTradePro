"""Disconnected final-check foundations for Account Authority V3.

The legacy API revalidates one root row and its revocation slot only. The
separate complete-graph API rereads the selected graph under the same
generation-first RC fence; neither API is connected to production decisions.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from threading import Lock
from typing import Literal, NoReturn, Protocol, SupportsIndex

from django.db import DatabaseError, connections, transaction
from django.db.backends.base.base import BaseDatabaseWrapper
from django.utils.connection import ConnectionDoesNotExist

from apps.account.application.account_authority_final_revalidation_v3_contracts import (
    AccountAuthorityV3FinalRootSelection,
    AccountAuthorityV3RootRevocationRevalidationRepository,
)
from apps.account.application.owner_tenant_authority_v3 import (
    GetCurrentOwnerTenantAuthorityV3Command,
)
from apps.account.application.owner_tenant_authority_v3_contracts import (
    PersistedOwnerTenantAuthorityV3Revocation,
)
from apps.account.application.physical_account_row_observation_v2 import (
    PhysicalAccountRowProviderIdentity,
)
from apps.account.domain.owner_tenant_authority_v3 import (
    validate_owner_tenant_authority_v3_revocation,
)
from apps.account.infrastructure.account_authority_generation import (
    AccountAuthorityGenerationChanged,
    AccountAuthorityGenerationProof,
    AccountAuthorityGenerationUnavailable,
    caller_owned_account_authority_generation_fence,
    capture_account_authority_snapshot_physical_provider_identity,
    capture_active_account_authority_physical_provider_identity,
    read_account_authority_generation_proof,
    require_active_account_authority_generation_fence,
)
from apps.account.infrastructure.account_authority_shadow_scanner import (
    AccountAuthorityCurrentGraphReadV3,
    AccountAuthorityCurrentGraphSelectorV3,
    AccountAuthorityShadowFingerprintV3,
    AccountAuthorityShadowScanResultV3,
    AccountAuthorityV3CallerTransactionMode,
)


class AccountAuthorityFinalRevalidationUnavailable(AccountAuthorityGenerationUnavailable):
    """The partial Authority V3 final check cannot establish its bounded claim."""


class AccountAuthorityFinalRevalidationProofV3:
    """Opaque process-local, one-use handle for a server-retained selection."""

    __slots__ = ()

    def __reduce__(self) -> NoReturn:
        """Prevent proof serialization through the pickle protocol."""

        raise TypeError("server-side Authority V3 proof cannot be serialized")

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        """Prevent proof serialization through explicit protocol selection."""

        del protocol
        raise TypeError("server-side Authority V3 proof cannot be serialized")

    def __copy__(self) -> NoReturn:
        """Prevent creating a second client-visible handle by shallow copy."""

        raise TypeError("server-side Authority V3 proof cannot be copied")

    def __deepcopy__(self, memo: dict[int, object]) -> NoReturn:
        """Prevent creating a second client-visible handle by deep copy."""

        del memo
        raise TypeError("server-side Authority V3 proof cannot be copied")


class AccountAuthorityCompleteGraphFinalRevalidationProofV3:
    """Opaque process-local, one-use handle for a complete-graph proof."""

    __slots__ = ()

    def __reduce__(self) -> NoReturn:
        """Prevent serialization into a transferable complete-graph proof."""

        raise TypeError("server-side complete graph proof cannot be serialized")

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        """Reject explicit pickle protocol selection as well."""

        del protocol
        raise TypeError("server-side complete graph proof cannot be serialized")

    def __copy__(self) -> NoReturn:
        """Prevent a second handle from consuming the same retained proof."""

        raise TypeError("server-side complete graph proof cannot be copied")

    def __deepcopy__(self, memo: dict[int, object]) -> NoReturn:
        """Prevent creating a second client-visible handle by deep copy."""

        del memo
        raise TypeError("server-side complete graph proof cannot be copied")


@dataclass(frozen=True, slots=True)
class AccountAuthorityV3RootRevocationRevalidationResult:
    """In-fence evidence for one root row and its revocation slot only.

    The result is valid only while yielded by the open finalization fence. It
    does not establish currentness of the Authority V3 parent graph.
    """

    authority_content_hash: str
    generation: int
    checked_at: datetime
    valid_until: datetime
    scope: Literal["owner_tenant_authority_v3_root_revocation_only"] = (
        "owner_tenant_authority_v3_root_revocation_only"
    )

    def __post_init__(self) -> None:
        """Keep result scope and fields exact and bounded."""

        if (
            type(self.authority_content_hash) is not str
            or len(self.authority_content_hash) != 64
            or any(character not in "0123456789abcdef" for character in self.authority_content_hash)
        ):
            raise ValueError("Authority V3 result content hash is invalid")
        if type(self.generation) is not int or self.generation < 0:
            raise ValueError("Authority V3 result generation is invalid")
        if type(self.checked_at) is not datetime or not _is_aware(self.checked_at):
            raise ValueError("Authority V3 result clock must be timezone-aware")
        if type(self.valid_until) is not datetime or not _is_aware(self.valid_until):
            raise ValueError("Authority V3 result expiry must be timezone-aware")
        if self.checked_at >= self.valid_until:
            raise ValueError("Authority V3 result must be checked before expiry")
        if self.scope != "owner_tenant_authority_v3_root_revocation_only":
            raise ValueError("Authority V3 result scope is invalid")


@dataclass(frozen=True, slots=True)
class AccountAuthorityV3CompleteGraphRevalidationResult:
    """In-fence evidence for a complete current Account authority graph."""

    database_alias: str
    selector: AccountAuthorityCurrentGraphSelectorV3
    fingerprint: AccountAuthorityShadowFingerprintV3
    generation: int
    shadow_checked_at: datetime
    capture_checked_at: datetime
    checked_at: datetime
    valid_until: datetime
    shadow_backend_pid: int
    shadow_transaction_xid: str
    capture_backend_pid: int
    capture_transaction_xid: str
    backend_pid: int
    transaction_xid: str
    scope: Literal["account_authority_complete_graph"] = "account_authority_complete_graph"

    def __post_init__(self) -> None:
        """Reject incomplete graph claims and invalid cutoff or identity ordering."""

        if type(self.database_alias) is not str or not self.database_alias:
            raise ValueError("complete graph result alias is invalid")
        if type(self.selector) is not AccountAuthorityCurrentGraphSelectorV3:
            raise TypeError("complete graph selector is invalid")
        if self.selector.database_alias != self.database_alias:
            raise ValueError("complete graph selector belongs to another alias")
        if type(self.fingerprint) is not AccountAuthorityShadowFingerprintV3:
            raise TypeError("complete graph fingerprint is invalid")
        if self.fingerprint.complete_graph_hash is None:
            raise ValueError("complete graph fingerprint is missing its complete digest")
        if type(self.generation) is not int or self.generation < 0:
            raise ValueError("complete graph generation is invalid")
        for name, timestamp in (
            ("shadow_checked_at", self.shadow_checked_at),
            ("capture_checked_at", self.capture_checked_at),
            ("checked_at", self.checked_at),
            ("valid_until", self.valid_until),
        ):
            if type(timestamp) is not datetime or not _is_aware(timestamp):
                raise ValueError(f"complete graph {name} must be timezone-aware")
        if not self.shadow_checked_at <= self.capture_checked_at <= self.checked_at:
            raise ValueError("complete graph cutoff ordering is invalid")
        if self.checked_at >= self.valid_until:
            raise ValueError("complete graph must be read before its earliest expiry")
        for name, backend_pid in (
            ("shadow_backend_pid", self.shadow_backend_pid),
            ("capture_backend_pid", self.capture_backend_pid),
            ("backend_pid", self.backend_pid),
        ):
            if type(backend_pid) is not int or backend_pid <= 0:
                raise ValueError(f"complete graph {name} is invalid")
        for name, transaction_xid in (
            ("shadow_transaction_xid", self.shadow_transaction_xid),
            ("capture_transaction_xid", self.capture_transaction_xid),
            ("transaction_xid", self.transaction_xid),
        ):
            if type(transaction_xid) is not str or not transaction_xid:
                raise ValueError(f"complete graph {name} is invalid")
        if self.scope != "account_authority_complete_graph":
            raise ValueError("complete graph result scope is invalid")


@dataclass(frozen=True, slots=True)
class _PreparedRootSelection:
    """Private data retained by one revalidator between RR and RC transactions."""

    command: GetCurrentOwnerTenantAuthorityV3Command
    generation_proof: AccountAuthorityGenerationProof
    selection: AccountAuthorityV3FinalRootSelection


@dataclass(frozen=True, slots=True)
class _PreparedCompleteGraph:
    """Server-retained scan proof and physical identities for one complete reread."""

    command: GetCurrentOwnerTenantAuthorityV3Command
    generation_proof: AccountAuthorityGenerationProof
    selector: AccountAuthorityCurrentGraphSelectorV3
    fingerprint: AccountAuthorityShadowFingerprintV3
    shadow_checked_at: datetime
    capture_checked_at: datetime
    valid_until: datetime
    shadow_physical_identity: PhysicalAccountRowProviderIdentity
    capture_physical_identity: PhysicalAccountRowProviderIdentity


class _AccountAuthorityCompleteGraphReaderV3(Protocol):
    """Reader capability injected for one exact alias and RC/RW mode."""

    @property
    def database_alias(self) -> str:
        """Return the exact alias used by graph repositories."""

    @property
    def transaction_mode(self) -> AccountAuthorityV3CallerTransactionMode:
        """Return the required caller-owned transaction mode."""

    def selector_for(
        self,
        command: GetCurrentOwnerTenantAuthorityV3Command,
    ) -> AccountAuthorityCurrentGraphSelectorV3:
        """Return the redacted selector fixed by command and actor-source config."""

    def read(
        self,
        command: GetCurrentOwnerTenantAuthorityV3Command,
        *,
        generation: int | None = None,
    ) -> AccountAuthorityCurrentGraphReadV3:
        """Read the graph using the caller's current transaction and generation."""


class AccountAuthorityFinalRevalidatorV3:
    """Revalidate one selected Authority V3 row after locking its generation.

    The proof handle is server-side and is consumed before opening the final
    transaction, including when a generation or row check rejects it. This
    class has no production composition and does not call the old V3 facade,
    whole-world readers, publication/audit/outbox, external providers, or the
    old relation/advisory lock helpers.
    """

    __slots__ = (
        "_complete_graph_reader",
        "_complete_issued",
        "_issued",
        "_lock",
        "_repository",
        "_using",
    )
    _MAX_PENDING_PROOFS = 128

    def __init__(
        self,
        repository: AccountAuthorityV3RootRevocationRevalidationRepository,
        *,
        using: str = "default",
        complete_graph_reader: _AccountAuthorityCompleteGraphReaderV3 | None = None,
    ) -> None:
        """Bind one targeted repository to one explicit database alias."""

        _validate_alias(using)
        if repository.database_alias != using:
            raise ValueError("targeted repository must use the finalizer database alias")
        if complete_graph_reader is not None and (
            complete_graph_reader.database_alias != using
            or complete_graph_reader.transaction_mode
            != "generation_fenced_read_committed_read_write"
        ):
            raise ValueError("complete graph reader must use this alias in generation-fenced RC/RW")
        self._repository = repository
        self._using = using
        self._complete_graph_reader = complete_graph_reader
        self._issued: dict[AccountAuthorityFinalRevalidationProofV3, _PreparedRootSelection] = {}
        self._complete_issued: dict[
            AccountAuthorityCompleteGraphFinalRevalidationProofV3,
            _PreparedCompleteGraph,
        ] = {}
        self._lock = Lock()

    def capture(
        self,
        command: GetCurrentOwnerTenantAuthorityV3Command,
        scan: AccountAuthorityShadowScanResultV3,
    ) -> AccountAuthorityFinalRevalidationProofV3:
        """Bind a matched shadow selection to the same verified RR generation."""

        if type(command) is not GetCurrentOwnerTenantAuthorityV3Command:
            raise TypeError("command must be exact GetCurrentOwnerTenantAuthorityV3Command")
        command.__post_init__()
        if type(scan) is not AccountAuthorityShadowScanResultV3:
            raise TypeError("scan must be exact AccountAuthorityShadowScanResultV3")
        if type(scan.database_alias) is not str or scan.database_alias != self._using:
            raise AccountAuthorityFinalRevalidationUnavailable(
                "shadow scan database alias differs from finalizer"
            )
        shadow = scan.comparison.shadow
        if (
            scan.comparison.matches is not True
            or scan.comparison.differing_fields != ()
            or shadow is None
            or shadow.authority_content_hash != command.expected_content_hash
        ):
            raise AccountAuthorityFinalRevalidationUnavailable(
                "a matched shadow selection is required for the partial final proof"
            )
        if type(scan.proof_generation) is not int or scan.proof_generation < 0:
            raise AccountAuthorityFinalRevalidationUnavailable("shadow scan generation is invalid")

        with _read_only_repeatable_read_snapshot(self._using) as generation_proof:
            if (
                type(generation_proof) is not AccountAuthorityGenerationProof
                or generation_proof.using != self._using
            ):
                raise AccountAuthorityFinalRevalidationUnavailable(
                    "repeatable-read generation proof belongs to another alias"
                )
            if generation_proof.generation != scan.proof_generation:
                raise AccountAuthorityGenerationChanged(
                    "Authority V3 generation changed after the shadow scan"
                )
            now = self._repository.database_clock()
            _validate_database_time(now)
            selection = self._repository.get_selected_root(
                authority_id=command.authority_id,
                authority_version=command.authority_version,
                expected_content_hash=command.expected_content_hash,
                as_of=now,
            )
            if type(selection) is not AccountAuthorityV3FinalRootSelection:
                raise AccountAuthorityFinalRevalidationUnavailable(
                    "the selected Authority V3 root row is unavailable"
                )
            selection.__post_init__()
            authority = selection.record.authority
            if (
                authority.identity_hash != shadow.authority_identity_hash
                or authority.content_hash != shadow.authority_content_hash
                or not authority.is_current_at(now)
            ):
                raise AccountAuthorityFinalRevalidationUnavailable(
                    "the selected Authority V3 row differs from the shadow scan"
                )
            if self._read_revocation(selection, now) is not None:
                raise AccountAuthorityFinalRevalidationUnavailable(
                    "the selected Authority V3 root is revoked"
                )

        handle = AccountAuthorityFinalRevalidationProofV3()
        prepared = _PreparedRootSelection(
            command=command,
            generation_proof=generation_proof,
            selection=selection,
        )
        with self._lock:
            expired = tuple(
                issued_handle
                for issued_handle, issued in self._issued.items()
                if issued.selection.record.authority.valid_until <= now
            )
            for partial_handle in expired:
                del self._issued[partial_handle]
            expired_complete = tuple(
                complete_handle
                for complete_handle, issued in self._complete_issued.items()
                if issued.valid_until <= now
            )
            for complete_handle in expired_complete:
                del self._complete_issued[complete_handle]
            if len(self._issued) + len(self._complete_issued) >= self._MAX_PENDING_PROOFS:
                raise AccountAuthorityFinalRevalidationUnavailable(
                    "server-side final proof capacity is exhausted"
                )
            self._issued[handle] = prepared
        return handle

    @contextmanager
    def fence(
        self,
        proof: AccountAuthorityFinalRevalidationProofV3,
    ) -> Iterator[AccountAuthorityV3RootRevocationRevalidationResult]:
        """Hold the generation-first RC fence open through caller-owned work.

        Caller work that relies on this check must use the same database alias
        and finish before the context exits. External effects are not covered by
        this transaction.
        """

        prepared = self._consume(proof)
        with _read_committed_generation_fence(
            prepared.generation_proof,
            using=self._using,
        ) as generation:
            now = self._repository.database_clock()
            _validate_database_time(now)
            expected = prepared.selection
            if not expected.record.authority.is_current_at(now):
                raise AccountAuthorityFinalRevalidationUnavailable(
                    "the selected Authority V3 root has expired"
                )
            current = self._repository.get_selected_root(
                authority_id=prepared.command.authority_id,
                authority_version=prepared.command.authority_version,
                expected_content_hash=prepared.command.expected_content_hash,
                as_of=now,
            )
            if current != expected:
                raise AccountAuthorityGenerationChanged(
                    "the selected Authority V3 root row changed before final revalidation"
                )
            if self._read_revocation(current, now) is not None:
                raise AccountAuthorityFinalRevalidationUnavailable(
                    "the selected Authority V3 root is revoked"
                )
            result = AccountAuthorityV3RootRevocationRevalidationResult(
                authority_content_hash=current.record.authority.content_hash,
                generation=generation,
                checked_at=now,
                valid_until=current.record.authority.valid_until,
            )
            yield result
            exit_checked_at = self._repository.database_clock()
            _validate_database_time(exit_checked_at)
            if exit_checked_at < result.checked_at:
                raise AccountAuthorityFinalRevalidationUnavailable(
                    "the final revalidation database clock moved backwards"
                )
            if exit_checked_at >= result.valid_until:
                raise AccountAuthorityFinalRevalidationUnavailable(
                    "the selected Authority V3 root expired during final revalidation"
                )

    def capture_complete(
        self,
        command: GetCurrentOwnerTenantAuthorityV3Command,
        scan: AccountAuthorityShadowScanResultV3,
    ) -> AccountAuthorityCompleteGraphFinalRevalidationProofV3:
        """Bind a complete shadow graph to a fresh same-alias RR generation snapshot."""

        graph_reader = self._complete_graph_reader
        if graph_reader is None:
            raise AccountAuthorityFinalRevalidationUnavailable(
                "complete graph final reread is not configured"
            )
        selector, fingerprint, shadow_checked_at, shadow_identity = self._validate_complete_scan(
            command, scan, graph_reader
        )

        with _read_only_repeatable_read_snapshot(self._using) as generation_proof:
            if (
                type(generation_proof) is not AccountAuthorityGenerationProof
                or generation_proof.using != self._using
            ):
                raise AccountAuthorityFinalRevalidationUnavailable(
                    "complete graph capture generation belongs to another alias"
                )
            if generation_proof.generation != scan.proof_generation:
                raise AccountAuthorityGenerationChanged(
                    "Authority V3 generation changed after the complete shadow scan"
                )
            connection = _connection(self._using)
            capture_identity = capture_account_authority_snapshot_physical_provider_identity(
                using=self._using,
                connection=connection,
            )
            _validate_snapshot_identity(capture_identity, self._using)
            capture_checked_at = self._repository.database_clock()
            _validate_database_time(capture_checked_at)
            if capture_checked_at < shadow_checked_at:
                raise AccountAuthorityFinalRevalidationUnavailable(
                    "complete graph capture database clock moved behind the shadow cutoff"
                )
            if capture_checked_at >= fingerprint.valid_until:
                raise AccountAuthorityFinalRevalidationUnavailable(
                    "complete shadow graph expired before proof capture"
                )
            capture_identity_after_clock = (
                capture_account_authority_snapshot_physical_provider_identity(
                    using=self._using,
                    connection=connection,
                )
            )
            _require_same_physical_identity(capture_identity, capture_identity_after_clock)
            if graph_reader.selector_for(command) != selector:
                raise AccountAuthorityFinalRevalidationUnavailable(
                    "complete graph selector changed during proof capture"
                )

        handle = AccountAuthorityCompleteGraphFinalRevalidationProofV3()
        prepared = _PreparedCompleteGraph(
            command=command,
            generation_proof=generation_proof,
            selector=selector,
            fingerprint=fingerprint,
            shadow_checked_at=shadow_checked_at,
            capture_checked_at=capture_checked_at,
            valid_until=fingerprint.valid_until,
            shadow_physical_identity=shadow_identity,
            capture_physical_identity=capture_identity,
        )
        with self._lock:
            expired_partial = tuple(
                partial_handle
                for partial_handle, issued in self._issued.items()
                if issued.selection.record.authority.valid_until <= capture_checked_at
            )
            for partial_handle in expired_partial:
                del self._issued[partial_handle]
            expired_complete = tuple(
                complete_handle
                for complete_handle, issued in self._complete_issued.items()
                if issued.valid_until <= capture_checked_at
            )
            for complete_handle in expired_complete:
                del self._complete_issued[complete_handle]
            if len(self._issued) + len(self._complete_issued) >= self._MAX_PENDING_PROOFS:
                raise AccountAuthorityFinalRevalidationUnavailable(
                    "server-side final proof capacity is exhausted"
                )
            self._complete_issued[handle] = prepared
        return handle

    @contextmanager
    def fence_complete(
        self,
        proof: AccountAuthorityCompleteGraphFinalRevalidationProofV3,
    ) -> Iterator[AccountAuthorityV3CompleteGraphRevalidationResult]:
        """Reread and hold a complete graph under the generation-first RC fence."""

        if type(proof) is not AccountAuthorityCompleteGraphFinalRevalidationProofV3:
            raise TypeError(
                "proof must be exact AccountAuthorityCompleteGraphFinalRevalidationProofV3"
            )
        graph_reader = self._complete_graph_reader
        if graph_reader is None:
            raise AccountAuthorityFinalRevalidationUnavailable(
                "complete graph final reread is not configured"
            )
        prepared = self._consume_complete(proof)
        with _read_committed_generation_fence(
            prepared.generation_proof,
            using=self._using,
        ) as generation:
            if generation != prepared.generation_proof.generation:
                raise AccountAuthorityGenerationChanged(
                    "generation lock differs from the captured complete graph proof"
                )
            connection = _connection(self._using)
            fence_identity = capture_active_account_authority_physical_provider_identity(
                using=self._using,
                connection=connection,
                generation=generation,
            )
            _validate_fenced_identity(fence_identity, self._using, generation)
            if graph_reader.selector_for(prepared.command) != prepared.selector:
                raise AccountAuthorityFinalRevalidationUnavailable(
                    "complete graph selector differs from the captured proof"
                )

            graph_read = graph_reader.read(prepared.command, generation=generation)
            if type(graph_read) is not AccountAuthorityCurrentGraphReadV3:
                raise AccountAuthorityFinalRevalidationUnavailable(
                    "complete graph reader returned an invalid read result"
                )
            graph_read.__post_init__()
            graph_identity = graph_read.physical_identity
            if graph_identity is None:
                raise AccountAuthorityFinalRevalidationUnavailable(
                    "complete graph reread omitted physical transaction identity"
                )
            _validate_fenced_identity(graph_identity, self._using, generation)
            _require_same_physical_identity(fence_identity, graph_identity)
            after_graph_identity = capture_active_account_authority_physical_provider_identity(
                using=self._using,
                connection=connection,
                generation=generation,
            )
            _require_same_physical_identity(fence_identity, after_graph_identity)

            fingerprint = graph_read.fingerprint
            valid_until = graph_read.valid_until
            if graph_read.authority is None or fingerprint is None or valid_until is None:
                raise AccountAuthorityFinalRevalidationUnavailable(
                    "complete current authority graph is missing"
                )
            if fingerprint.complete_graph_hash is None or fingerprint != prepared.fingerprint:
                raise AccountAuthorityGenerationChanged(
                    "complete current authority graph differs from its captured fingerprint"
                )
            if graph_reader.selector_for(prepared.command) != prepared.selector:
                raise AccountAuthorityFinalRevalidationUnavailable(
                    "complete graph selector changed during final reread"
                )
            if graph_read.checked_at < prepared.capture_checked_at:
                raise AccountAuthorityFinalRevalidationUnavailable(
                    "complete graph reread database clock moved behind proof capture"
                )
            if graph_read.checked_at >= valid_until:
                raise AccountAuthorityFinalRevalidationUnavailable(
                    "complete current authority graph is expired at final reread"
                )

            result = AccountAuthorityV3CompleteGraphRevalidationResult(
                database_alias=self._using,
                selector=prepared.selector,
                fingerprint=fingerprint,
                generation=generation,
                shadow_checked_at=prepared.shadow_checked_at,
                capture_checked_at=prepared.capture_checked_at,
                checked_at=graph_read.checked_at,
                valid_until=valid_until,
                shadow_backend_pid=prepared.shadow_physical_identity.backend_pid,
                shadow_transaction_xid=prepared.shadow_physical_identity.transaction_xid,
                capture_backend_pid=prepared.capture_physical_identity.backend_pid,
                capture_transaction_xid=prepared.capture_physical_identity.transaction_xid,
                backend_pid=graph_identity.backend_pid,
                transaction_xid=graph_identity.transaction_xid,
            )
            yield result

            require_active_account_authority_generation_fence(
                using=self._using,
                connection=connection,
                generation=generation,
            )
            before_exit_clock = capture_active_account_authority_physical_provider_identity(
                using=self._using,
                connection=connection,
                generation=generation,
            )
            _require_same_physical_identity(fence_identity, before_exit_clock)
            if graph_reader.selector_for(prepared.command) != prepared.selector:
                raise AccountAuthorityFinalRevalidationUnavailable(
                    "complete graph selector changed during caller work"
                )
            exit_checked_at = self._repository.database_clock()
            _validate_database_time(exit_checked_at)
            after_exit_clock = capture_active_account_authority_physical_provider_identity(
                using=self._using,
                connection=connection,
                generation=generation,
            )
            _require_same_physical_identity(fence_identity, after_exit_clock)
            if exit_checked_at < result.checked_at:
                raise AccountAuthorityFinalRevalidationUnavailable(
                    "complete graph final database clock moved backwards"
                )
            if exit_checked_at >= result.valid_until:
                raise AccountAuthorityFinalRevalidationUnavailable(
                    "complete current authority graph expired during final revalidation"
                )

    def _validate_complete_scan(
        self,
        command: GetCurrentOwnerTenantAuthorityV3Command,
        scan: AccountAuthorityShadowScanResultV3,
        graph_reader: _AccountAuthorityCompleteGraphReaderV3,
    ) -> tuple[
        AccountAuthorityCurrentGraphSelectorV3,
        AccountAuthorityShadowFingerprintV3,
        datetime,
        PhysicalAccountRowProviderIdentity,
    ]:
        """Require complete scan metadata before opening a capture transaction."""

        if type(command) is not GetCurrentOwnerTenantAuthorityV3Command:
            raise TypeError("command must be exact GetCurrentOwnerTenantAuthorityV3Command")
        command.__post_init__()
        if type(scan) is not AccountAuthorityShadowScanResultV3:
            raise TypeError("scan must be exact AccountAuthorityShadowScanResultV3")
        if scan.database_alias != self._using or graph_reader.database_alias != self._using:
            raise AccountAuthorityFinalRevalidationUnavailable(
                "complete graph scan database alias differs from finalizer"
            )
        if type(scan.proof_generation) is not int or scan.proof_generation < 0:
            raise AccountAuthorityFinalRevalidationUnavailable(
                "complete graph scan generation is invalid"
            )
        selector = scan.selector
        fingerprint = scan.comparison.shadow
        checked_at = scan.checked_at
        identity = scan.physical_identity
        if (
            type(selector) is not AccountAuthorityCurrentGraphSelectorV3
            or type(fingerprint) is not AccountAuthorityShadowFingerprintV3
            or type(checked_at) is not datetime
            or type(identity) is not PhysicalAccountRowProviderIdentity
        ):
            raise AccountAuthorityFinalRevalidationUnavailable(
                "complete graph scan omitted selector, cutoff, fingerprint, or physical identity"
            )
        if not _is_aware(checked_at):
            raise AccountAuthorityFinalRevalidationUnavailable(
                "complete graph scan cutoff is not timezone-aware"
            )
        if (
            scan.comparison.matches is not True
            or scan.comparison.differing_fields != ()
            or fingerprint.complete_graph_hash is None
            or fingerprint.authority_content_hash != command.expected_content_hash
            or fingerprint.valid_until <= checked_at
        ):
            raise AccountAuthorityFinalRevalidationUnavailable(
                "a matched, current complete graph scan is required"
            )
        if (
            selector.database_alias != self._using
            or selector.authority_content_hash != command.expected_content_hash
            or graph_reader.selector_for(command) != selector
        ):
            raise AccountAuthorityFinalRevalidationUnavailable(
                "complete graph scan selector does not match the injected reader"
            )
        _validate_snapshot_identity(identity, self._using)
        return selector, fingerprint, checked_at, identity

    def _consume_complete(
        self,
        proof: AccountAuthorityCompleteGraphFinalRevalidationProofV3,
    ) -> _PreparedCompleteGraph:
        """Atomically consume one exact complete-graph proof handle."""

        if type(proof) is not AccountAuthorityCompleteGraphFinalRevalidationProofV3:
            raise TypeError(
                "proof must be exact AccountAuthorityCompleteGraphFinalRevalidationProofV3"
            )
        with self._lock:
            prepared = self._complete_issued.pop(proof, None)
        if prepared is None:
            raise AccountAuthorityFinalRevalidationUnavailable(
                "complete graph proof is unknown or already consumed"
            )
        return prepared

    def _read_revocation(
        self,
        selection: AccountAuthorityV3FinalRootSelection,
        as_of: datetime,
    ) -> PersistedOwnerTenantAuthorityV3Revocation | None:
        """Read and independently bind the selected root's one revocation slot."""

        record = self._repository.get_exact_revocation(selection=selection, as_of=as_of)
        if record is None:
            return None
        if type(record) is not PersistedOwnerTenantAuthorityV3Revocation:
            raise AccountAuthorityFinalRevalidationUnavailable(
                "targeted repository returned an invalid Authority V3 revocation"
            )
        record.__post_init__()
        try:
            validate_owner_tenant_authority_v3_revocation(
                selection.record.authority,
                record.revocation,
            )
        except (TypeError, ValueError) as error:
            raise AccountAuthorityFinalRevalidationUnavailable(
                "selected Authority V3 revocation failed root binding"
            ) from error
        return record

    def _consume(
        self,
        proof: AccountAuthorityFinalRevalidationProofV3,
    ) -> _PreparedRootSelection:
        """Atomically remove and return one registered proof payload."""

        if type(proof) is not AccountAuthorityFinalRevalidationProofV3:
            raise TypeError("proof must be exact AccountAuthorityFinalRevalidationProofV3")
        with self._lock:
            prepared = self._issued.pop(proof, None)
        if prepared is None:
            raise AccountAuthorityFinalRevalidationUnavailable(
                "server-side final proof is unknown or already consumed"
            )
        return prepared


@contextmanager
def _read_only_repeatable_read_snapshot(
    using: str,
) -> Iterator[AccountAuthorityGenerationProof]:
    """Open an outermost same-alias RR/READ ONLY snapshot and capture generation."""

    connection = _connection(using)
    if connection.in_atomic_block or not connection.get_autocommit():
        raise AccountAuthorityFinalRevalidationUnavailable(
            "proof capture requires its own outer PostgreSQL transaction"
        )
    try:
        with transaction.atomic(using=using):
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            proof = read_account_authority_generation_proof(using=using)
            yield proof
    except AccountAuthorityGenerationUnavailable:
        raise
    except (DatabaseError, ConnectionDoesNotExist, KeyError) as error:
        raise AccountAuthorityFinalRevalidationUnavailable(
            "repeatable-read proof snapshot is unavailable"
        ) from error


@contextmanager
def _read_committed_generation_fence(
    proof: AccountAuthorityGenerationProof,
    *,
    using: str,
) -> Iterator[int]:
    """Lock and compare generation before any clock or selected-row read."""

    connection = _connection(using)
    if connection.in_atomic_block or not connection.get_autocommit():
        raise AccountAuthorityFinalRevalidationUnavailable(
            "final revalidation requires its own outer PostgreSQL transaction"
        )
    try:
        with transaction.atomic(using=using):
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED READ WRITE")
            with caller_owned_account_authority_generation_fence(proof, using=using) as generation:
                yield generation
    except AccountAuthorityGenerationUnavailable:
        raise
    except (DatabaseError, ConnectionDoesNotExist, KeyError) as error:
        raise AccountAuthorityFinalRevalidationUnavailable(
            "generation-first final transaction is unavailable"
        ) from error


def _connection(using: str) -> BaseDatabaseWrapper:
    """Resolve one exact PostgreSQL alias for a proof or final transaction."""

    _validate_alias(using)
    try:
        connection = connections[using]
    except (ConnectionDoesNotExist, KeyError) as error:
        raise AccountAuthorityFinalRevalidationUnavailable(
            "final revalidation database alias is unavailable"
        ) from error
    if connection.vendor != "postgresql" or getattr(connection, "alias", None) != using:
        raise AccountAuthorityFinalRevalidationUnavailable(
            "final revalidation requires the exact PostgreSQL alias"
        )
    return connection


def _validate_alias(value: object) -> None:
    """Require one exact, whitespace-free Django database alias."""

    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or any(character.isspace() for character in value)
    ):
        raise ValueError("using must be one exact database alias")


def _validate_database_time(value: object) -> None:
    """Require a timezone-aware database clock with no local fallback."""

    if type(value) is not datetime or not _is_aware(value):
        raise AccountAuthorityFinalRevalidationUnavailable(
            "final revalidation requires a timezone-aware database clock"
        )


def _validate_snapshot_identity(
    identity: PhysicalAccountRowProviderIdentity,
    using: str,
) -> None:
    """Require one exact physical identity from an RR/READ ONLY transaction."""

    if (
        type(identity) is not PhysicalAccountRowProviderIdentity
        or identity.using != using
        or identity.generation is not None
    ):
        raise AccountAuthorityFinalRevalidationUnavailable(
            "complete graph snapshot physical identity is invalid"
        )


def _validate_fenced_identity(
    identity: PhysicalAccountRowProviderIdentity,
    using: str,
    generation: int,
) -> None:
    """Require one exact physical identity from the locked RC/RW generation."""

    if (
        type(identity) is not PhysicalAccountRowProviderIdentity
        or identity.using != using
        or identity.generation != generation
    ):
        raise AccountAuthorityFinalRevalidationUnavailable(
            "complete graph physical identity differs from the active generation fence"
        )


def _require_same_physical_identity(
    expected: PhysicalAccountRowProviderIdentity,
    actual: PhysicalAccountRowProviderIdentity,
) -> None:
    """Reject a changed wrapper, connection, xid, task, or generation identity."""

    if (
        type(expected) is not PhysicalAccountRowProviderIdentity
        or type(actual) is not PhysicalAccountRowProviderIdentity
        or expected.using != actual.using
        or expected.wrapper_token is not actual.wrapper_token
        or expected.dbapi_token is not actual.dbapi_token
        or expected.backend_pid != actual.backend_pid
        or expected.transaction_xid != actual.transaction_xid
        or expected.thread_id != actual.thread_id
        or expected.task_token is not actual.task_token
        or expected.generation != actual.generation
    ):
        raise AccountAuthorityFinalRevalidationUnavailable(
            "complete graph physical transaction identity changed"
        )


def _is_aware(value: datetime) -> bool:
    """Return whether a datetime has a usable UTC offset."""

    return value.tzinfo is not None and value.utcoffset() is not None


__all__ = [
    "AccountAuthorityCompleteGraphFinalRevalidationProofV3",
    "AccountAuthorityFinalRevalidationProofV3",
    "AccountAuthorityFinalRevalidationUnavailable",
    "AccountAuthorityFinalRevalidatorV3",
    "AccountAuthorityV3CompleteGraphRevalidationResult",
    "AccountAuthorityV3RootRevocationRevalidationResult",
]
