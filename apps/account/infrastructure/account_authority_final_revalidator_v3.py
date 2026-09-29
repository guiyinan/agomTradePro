"""Disconnected RC final-check foundation for Authority V3 root/revocation rows.

This intentionally revalidates only one Authority V3 root row and its
revocation slot. It does not restore the selected root's parent graph and its
result must not be used as complete Account authority or connected to
production decisions.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from threading import Lock
from typing import Literal, NoReturn, SupportsIndex

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
from apps.account.domain.owner_tenant_authority_v3 import (
    validate_owner_tenant_authority_v3_revocation,
)
from apps.account.infrastructure.account_authority_generation import (
    AccountAuthorityGenerationChanged,
    AccountAuthorityGenerationProof,
    AccountAuthorityGenerationUnavailable,
    lock_account_authority_generation_fence,
    read_account_authority_generation_proof,
)
from apps.account.infrastructure.account_authority_shadow_scanner import (
    AccountAuthorityShadowScanResultV3,
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


@dataclass(frozen=True, slots=True)
class AccountAuthorityV3RootRevocationRevalidationResult:
    """In-fence evidence for one root row and its revocation slot only.

    The result is valid only while yielded by the open finalization fence. It
    does not establish currentness of the Authority V3 parent graph.
    """

    authority_content_hash: str
    generation: int
    checked_at: datetime
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
        if self.scope != "owner_tenant_authority_v3_root_revocation_only":
            raise ValueError("Authority V3 result scope is invalid")


@dataclass(frozen=True, slots=True)
class _PreparedRootSelection:
    """Private data retained by one revalidator between RR and RC transactions."""

    command: GetCurrentOwnerTenantAuthorityV3Command
    generation_proof: AccountAuthorityGenerationProof
    selection: AccountAuthorityV3FinalRootSelection


class AccountAuthorityFinalRevalidatorV3:
    """Revalidate one selected Authority V3 row after locking its generation.

    The proof handle is server-side and is consumed before opening the final
    transaction, including when a generation or row check rejects it. This
    class has no production composition and does not call the old V3 facade,
    whole-world readers, publication/audit/outbox, external providers, or the
    old relation/advisory lock helpers.
    """

    __slots__ = ("_issued", "_lock", "_repository", "_using")
    _MAX_PENDING_PROOFS = 128

    def __init__(
        self,
        repository: AccountAuthorityV3RootRevocationRevalidationRepository,
        *,
        using: str = "default",
    ) -> None:
        """Bind one targeted repository to one explicit database alias."""

        _validate_alias(using)
        if repository.database_alias != using:
            raise ValueError("targeted repository must use the finalizer database alias")
        self._repository = repository
        self._using = using
        self._issued: dict[AccountAuthorityFinalRevalidationProofV3, _PreparedRootSelection] = {}
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
            for issued_handle in expired:
                del self._issued[issued_handle]
            if len(self._issued) >= self._MAX_PENDING_PROOFS:
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
            )
            yield result

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
            generation = lock_account_authority_generation_fence(proof, using=using)
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


def _is_aware(value: datetime) -> bool:
    """Return whether a datetime has a usable UTC offset."""

    return value.tzinfo is not None and value.utcoffset() is not None


__all__ = [
    "AccountAuthorityFinalRevalidationProofV3",
    "AccountAuthorityFinalRevalidationUnavailable",
    "AccountAuthorityFinalRevalidatorV3",
    "AccountAuthorityV3RootRevocationRevalidationResult",
]
