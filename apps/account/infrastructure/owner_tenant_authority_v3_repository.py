"""PostgreSQL repository for immutable owner/tenant authority v3 decisions.

The repository stores an active decision root and a separate revocation event.
Every read restores the complete local ledger and its durable Evidence v5,
policy, and actor-source parents before selecting a point-in-time result.  A
write takes the existing parent-world lock first, then the two decision-table
locks, so concurrent composition roots use one deterministic lock order.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import NoReturn, Protocol, cast

from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError, connections, transaction
from django.utils import timezone
from django.utils.connection import ConnectionDoesNotExist

from apps.account.application.account_owner_assignment_actor_authority_source_v3 import (
    AccountOwnerAssignmentActorAuthoritySourceV3Conflict,
    AccountOwnerAssignmentActorAuthoritySourceV3Corruption,
    AccountOwnerAssignmentActorAuthoritySourceV3Unavailable,
)
from apps.account.application.account_owner_assignment_actor_authority_v3 import (
    CurrentAccountActorAuthorityV3,
)
from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentConflict,
    AccountOwnerAssignmentCorruption,
    AccountOwnerAssignmentUnavailable,
)
from apps.account.application.owner_tenant_authority_v3_contracts import (
    OwnerTenantAuthorityV3Conflict,
    OwnerTenantAuthorityV3Corruption,
    OwnerTenantAuthorityV3Repository,
    OwnerTenantAuthorityV3Unavailable,
    PersistedOwnerTenantAuthorityV3,
    PersistedOwnerTenantAuthorityV3Revocation,
)
from apps.account.domain.account_owner_assignment_actor_authority_source_v3 import (
    AccountOwnerAssignmentActorAuthoritySourceV3,
)
from apps.account.domain.owner_tenant_authority_v3 import (
    validate_owner_tenant_authority_v3_revocation,
    validate_owner_tenant_authority_v3_root,
    validate_owner_tenant_authority_v3_successor,
)
from apps.account.infrastructure._owner_tenant_authority_v3_repository_helpers import (
    _fk,
    _restore_revocation,
    _restore_root,
    _revocation_record,
    _revocation_values,
    _root_record,
    _root_values,
)
from apps.account.infrastructure.account_owner_assignment_actor_authority_source_v3_models import (
    AccountOwnerAssignmentActorAuthoritySourceV3Model,
)
from apps.account.infrastructure.account_owner_assignment_actor_authority_source_v3_repository import (
    DjangoAccountOwnerAssignmentActorAuthoritySourceV3Repository,
)
from apps.account.infrastructure.account_owner_assignment_evidence_v5_repository import (
    DjangoAccountOwnerAssignmentEvidenceV5Repository,
    lock_account_owner_assignment_evidence_v5_sources,
)
from apps.account.infrastructure.account_owner_assignment_v5_models import (
    AccountOwnerAssignmentEvidenceV5Model,
)
from apps.account.infrastructure.owner_tenant_authority_v3_models import (
    _OWNER_V3_UOW,
    OwnerTenantAuthorityV3Model,
    OwnerTenantAuthorityV3RevocationModel,
    _activate_owner_tenant_authority_v3_uow,
    _claim_owner_tenant_authority_v3_insert,
)
from apps.account.infrastructure.single_owner_authority_policy_v1_models import (
    SingleOwnerAuthorityPolicyV1Model,
)
from apps.account.infrastructure.single_owner_authority_policy_v1_repository import (
    DjangoSingleOwnerAuthorityPolicyV1Repository,
)


class OwnerTenantAuthorityV3Clock(Protocol):
    """Supply the authoritative persistence clock for one repository."""

    def now(self) -> datetime:
        """Return an exact timezone-aware current timestamp."""

        ...


class DjangoOwnerTenantAuthorityV3Clock:
    """Use Django's timezone-aware server clock."""

    def now(self) -> datetime:
        """Return the current timezone-aware timestamp."""

        return timezone.now()


@dataclass(frozen=True, slots=True)
class _World:
    """A closed-world snapshot of all decision and revocation rows."""

    roots: tuple[tuple[OwnerTenantAuthorityV3Model, PersistedOwnerTenantAuthorityV3], ...]
    revocations: tuple[
        tuple[OwnerTenantAuthorityV3RevocationModel, PersistedOwnerTenantAuthorityV3Revocation],
        ...,
    ]


class DjangoOwnerTenantAuthorityV3Repository(OwnerTenantAuthorityV3Repository):
    """Persist and restore one immutable owner/tenant authority v3 world."""

    __slots__ = (
        "_active",
        "_assignments",
        "_actors",
        "_clock",
        "_policies",
        "_token",
        "_uow",
        "_using",
    )

    def __init__(
        self,
        using: str = "default",
        clock: OwnerTenantAuthorityV3Clock | None = None,
    ) -> None:
        """Bind all decision and parent queries to one named database alias."""

        if type(using) is not str or not using or using.strip() != using:
            raise ValueError("owner tenant authority v3 database alias is invalid")
        self._using = using
        self._clock = clock or DjangoOwnerTenantAuthorityV3Clock()
        self._token = object()
        self._uow: object | None = None
        self._active = False
        self._assignments = DjangoAccountOwnerAssignmentEvidenceV5Repository(using=using)
        self._policies = DjangoSingleOwnerAuthorityPolicyV1Repository(using=using)
        self._actors = DjangoAccountOwnerAssignmentActorAuthoritySourceV3Repository(using=using)

    @property
    def unit_of_work_key(self) -> str:
        """Return the transaction identity shared by injected source readers."""

        return f"django:{self._using}"

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Open a private same-alias UOW while allowing an outer transaction."""

        self._postgresql()
        if self._active:
            raise OwnerTenantAuthorityV3Conflict(
                "owner tenant authority v3 UOW cannot be re-entered"
            )
        token = self._token
        self._active = True
        self._uow = token
        try:
            with transaction.atomic(using=self._using):
                with _activate_owner_tenant_authority_v3_uow(token):
                    yield
        except DatabaseError as error:
            raise OwnerTenantAuthorityV3Unavailable(
                "owner tenant authority v3 transaction is unavailable"
            ) from error
        finally:
            self._uow = None
            self._active = False

    def now(self) -> datetime:
        """Return the checked timezone-aware persistence clock."""

        self._postgresql()
        try:
            value = self._clock.now()
        except (AttributeError, TypeError, ValueError) as error:
            raise OwnerTenantAuthorityV3Unavailable(
                "owner tenant authority v3 clock is unavailable"
            ) from error
        if not _is_aware(value):
            raise OwnerTenantAuthorityV3Unavailable(
                "owner tenant authority v3 clock must be timezone-aware"
            )
        return value

    def get_winner(
        self,
        *,
        authority_id: str,
        authority_version: str,
        as_of: datetime,
    ) -> PersistedOwnerTenantAuthorityV3 | None:
        """Return the exact first decision winner known at ``as_of``."""

        self._ensure_selector_token(authority_id, "authority_id")
        self._ensure_selector_token(authority_version, "authority_version")
        self._cutoff(as_of)
        matches = tuple(
            record
            for _, record in self._restore_world(as_of).roots
            if (
                record.authority.authority_id,
                record.authority.authority_version,
            )
            == (authority_id, authority_version)
            and record.authority.recorded_at <= as_of
        )
        return _single(matches, "owner tenant authority v3 winner")

    def get_head(
        self, *, authority_id: str, as_of: datetime
    ) -> PersistedOwnerTenantAuthorityV3 | None:
        """Return the final logical chain head, including an expired head."""

        self._ensure_selector_token(authority_id, "authority_id")
        self._cutoff(as_of)
        return _head(
            tuple(
                item
                for item in self._restore_world(as_of).roots
                if item[1].authority.authority_id == authority_id
                and item[1].authority.recorded_at <= as_of
            ),
            "owner tenant authority v3 authority chain",
        )

    def get_assignment_head(
        self, *, assignment_content_hash: str, as_of: datetime
    ) -> PersistedOwnerTenantAuthorityV3 | None:
        """Return the decision occupying an Evidence v5 assignment slot."""

        _ensure_digest(assignment_content_hash, "assignment_content_hash")
        self._cutoff(as_of)
        return _head(
            tuple(
                item
                for item in self._restore_world(as_of).roots
                if item[1].authority.assignment_evidence_content_hash == assignment_content_hash
                and item[1].authority.recorded_at <= as_of
            ),
            "owner tenant authority v3 assignment chain",
        )

    def get_revocation(
        self, *, authority_content_hash: str, as_of: datetime
    ) -> PersistedOwnerTenantAuthorityV3Revocation | None:
        """Return one durable revocation event known at ``as_of``."""

        _ensure_digest(authority_content_hash, "authority_content_hash")
        self._cutoff(as_of)
        matches = tuple(
            record
            for _, record in self._restore_world(as_of).revocations
            if record.revocation.authority_content_hash == authority_content_hash
            and record.revocation.recorded_at <= as_of
        )
        return _single_revocation(matches, "owner tenant authority v3 revocation")

    def append(
        self,
        record: PersistedOwnerTenantAuthorityV3,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PersistedOwnerTenantAuthorityV3:
        """Append or exactly replay one root/successor under predecessor CAS."""

        self._require_uow()
        checked = _root_record(record)
        authority = checked.authority
        self._require_append_clock(recorded_at, authority.recorded_at)
        if expected_predecessor_hash is None:
            if authority.supersedes_content_hash is not None:
                raise OwnerTenantAuthorityV3Conflict(
                    "owner tenant authority v3 root cannot declare a predecessor"
                )
        else:
            _ensure_digest(expected_predecessor_hash, "expected_predecessor_hash")
            if authority.supersedes_content_hash != expected_predecessor_hash:
                raise OwnerTenantAuthorityV3Conflict(
                    "owner tenant authority v3 predecessor selector differs"
                )
        self._lock_world(authority.policy.policy_id)
        world = self._restore_world(recorded_at)
        collisions = tuple(
            (row, existing)
            for row, existing in world.roots
            if (
                (
                    existing.authority.authority_id == authority.authority_id
                    and existing.authority.authority_version == authority.authority_version
                )
                or existing.authority.identity_hash == authority.identity_hash
                or existing.authority.content_hash == authority.content_hash
            )
        )
        if collisions:
            predecessor_pk: int | None = None
            if expected_predecessor_hash is not None:
                predecessor_rows = tuple(
                    row
                    for row, existing in world.roots
                    if existing.authority.content_hash == expected_predecessor_hash
                )
                if len(predecessor_rows) != 1:
                    raise OwnerTenantAuthorityV3Conflict(
                        "owner tenant authority v3 predecessor is not persisted"
                    )
                predecessor_pk = _pk(predecessor_rows[0])
            if (
                len(collisions) == 1
                and collisions[0][1] == checked
                and _fk(collisions[0][0], "predecessor_id") == predecessor_pk
            ):
                return checked
            raise OwnerTenantAuthorityV3Conflict(
                "owner tenant authority v3 identity contains another winner"
            )
        predecessor_row: OwnerTenantAuthorityV3Model | None = None
        if expected_predecessor_hash is None:
            try:
                validate_owner_tenant_authority_v3_root(authority)
            except (TypeError, ValueError) as error:
                raise OwnerTenantAuthorityV3Conflict(
                    "owner tenant authority v3 root is invalid"
                ) from error
            if any(
                existing.authority.is_root
                and (
                    existing.authority.authority_id == authority.authority_id
                    or existing.authority.assignment_evidence_content_hash
                    == authority.assignment_evidence_content_hash
                )
                for _, existing in world.roots
            ):
                raise OwnerTenantAuthorityV3Conflict(
                    "owner tenant authority v3 root slot contains another winner"
                )
        else:
            predecessor_matches = tuple(
                item
                for item in world.roots
                if item[1].authority.content_hash == expected_predecessor_hash
            )
            if len(predecessor_matches) != 1:
                raise OwnerTenantAuthorityV3Conflict(
                    "owner tenant authority v3 predecessor is not persisted"
                )
            predecessor_row, predecessor = predecessor_matches[0]
            if (
                _head(
                    tuple(
                        item
                        for item in world.roots
                        if item[1].authority.authority_id == authority.authority_id
                    ),
                    "owner tenant authority v3 authority chain",
                )
                != predecessor
            ):
                raise OwnerTenantAuthorityV3Conflict(
                    "owner tenant authority v3 predecessor is not the final head"
                )
            if any(
                revocation.revocation.authority_content_hash == predecessor.authority.content_hash
                for _, revocation in world.revocations
            ):
                raise OwnerTenantAuthorityV3Conflict(
                    "owner tenant authority v3 revoked head cannot receive a successor"
                )
            try:
                validate_owner_tenant_authority_v3_successor(predecessor.authority, authority)
            except (TypeError, ValueError) as error:
                raise OwnerTenantAuthorityV3Conflict(
                    "owner tenant authority v3 successor is invalid"
                ) from error
        assignment_pk, policy_pk, actor_pk = self._root_parents(checked, lock=True)
        values = _root_values(
            checked,
            assignment_pk,
            policy_pk,
            actor_pk,
            _pk(predecessor_row) if predecessor_row is not None else None,
        )
        inserted = cast(
            OwnerTenantAuthorityV3Model,
            self._insert(OwnerTenantAuthorityV3Model, values),
        )
        inserted.refresh_from_db(using=self._using)
        restored = _restore_root(inserted)
        if restored != checked:
            raise OwnerTenantAuthorityV3Corruption(
                "owner tenant authority v3 append restore differs"
            )
        # The parent world is held under the source-table lock acquired above;
        # compare the inserted raw FK scalars with those exact locked IDs
        # instead of rereading the complete parent graph a second time.
        if (
            _fk(inserted, "assignment_id"),
            _fk(inserted, "policy_id"),
            _fk(inserted, "actor_source_id"),
        ) != (assignment_pk, policy_pk, actor_pk):
            raise OwnerTenantAuthorityV3Corruption(
                "owner tenant authority v3 append parent restore differs"
            )
        appended_chain = tuple(
            item for item in world.roots if item[1].authority.authority_id == authority.authority_id
        ) + ((inserted, restored),)
        if _head(appended_chain, "owner tenant authority v3 append chain") != restored:
            raise OwnerTenantAuthorityV3Corruption(
                "owner tenant authority v3 append head restore differs"
            )
        return restored

    def append_revocation(
        self,
        record: PersistedOwnerTenantAuthorityV3Revocation,
        *,
        expected_authority_content_hash: str,
        recorded_at: datetime,
    ) -> PersistedOwnerTenantAuthorityV3Revocation:
        """Append or exactly replay one immutable revocation event."""

        self._require_uow()
        checked = _revocation_record(record)
        revocation = checked.revocation
        _ensure_digest(expected_authority_content_hash, "expected_authority_content_hash")
        if revocation.authority_content_hash != expected_authority_content_hash:
            raise OwnerTenantAuthorityV3Conflict(
                "owner tenant authority v3 revocation selector differs"
            )
        self._require_append_clock(recorded_at, revocation.recorded_at)
        initial = self._restore_world(recorded_at)
        roots = tuple(
            item
            for item in initial.roots
            if item[1].authority.content_hash == revocation.authority_content_hash
        )
        if len(roots) != 1:
            if len(roots) > 1:
                raise OwnerTenantAuthorityV3Corruption(
                    "owner tenant authority v3 root content hash is duplicated"
                )
            raise OwnerTenantAuthorityV3Conflict(
                "owner tenant authority v3 revocation root is not persisted"
            )
        root = roots[0][1]
        self._lock_world(root.authority.policy.policy_id)
        world = self._restore_world(recorded_at)
        current_roots = tuple(
            item
            for item in world.roots
            if item[1].authority.content_hash == revocation.authority_content_hash
        )
        if len(current_roots) != 1:
            raise OwnerTenantAuthorityV3Corruption(
                "owner tenant authority v3 revocation root changed"
            )
        root_row, root = current_roots[0]
        head = _head(
            tuple(
                item
                for item in world.roots
                if item[1].authority.authority_id == root.authority.authority_id
            ),
            "owner tenant authority v3 revocation chain",
        )
        if head != root:
            raise OwnerTenantAuthorityV3Conflict(
                "owner tenant authority v3 revocation requires the final head"
            )
        if revocation.policy_content_hash != root.authority.policy.content_hash:
            raise OwnerTenantAuthorityV3Conflict(
                "owner tenant authority v3 revocation policy differs"
            )
        try:
            validate_owner_tenant_authority_v3_revocation(root.authority, revocation)
        except (TypeError, ValueError) as error:
            raise OwnerTenantAuthorityV3Conflict(
                "owner tenant authority v3 revocation does not bind the exact root"
            ) from error
        collisions = tuple(
            existing
            for row, existing in world.revocations
            if (
                existing.revocation.authority_content_hash == revocation.authority_content_hash
                or existing.revocation.identity_hash == revocation.identity_hash
                or existing.revocation.content_hash == revocation.content_hash
                or _fk(row, "authority_id") == _pk(root_row)
            )
        )
        if collisions:
            if len(collisions) == 1 and collisions[0] == checked:
                return checked
            raise OwnerTenantAuthorityV3Conflict(
                "owner tenant authority v3 revocation already has another winner"
            )
        actor_pk = self._revocation_parent(checked, lock=True)
        values = _revocation_values(checked, _pk(root_row), actor_pk)
        inserted = cast(
            OwnerTenantAuthorityV3RevocationModel,
            self._insert(OwnerTenantAuthorityV3RevocationModel, values),
        )
        inserted.refresh_from_db(using=self._using)
        restored = _restore_revocation(inserted)
        if restored != checked:
            raise OwnerTenantAuthorityV3Corruption(
                "owner tenant authority v3 revocation restore differs"
            )
        # The authority and actor sources are covered by the same locked
        # parent world; both inserted FKs must match the exact rows used to
        # build this event.
        if (
            _fk(inserted, "authority_id"),
            _fk(inserted, "actor_source_id"),
        ) != (_pk(root_row), actor_pk):
            raise OwnerTenantAuthorityV3Corruption(
                "owner tenant authority v3 revocation parent restore differs"
            )
        appended_revocations = world.revocations + ((inserted, restored),)
        _validate_revocation_slots(appended_revocations)
        return restored

    def _postgresql(self) -> None:
        """Require the configured alias to be an available PostgreSQL connection."""

        try:
            connection = connections[self._using]
        except (ConnectionDoesNotExist, DatabaseError, KeyError) as error:
            raise OwnerTenantAuthorityV3Unavailable(
                "owner tenant authority v3 database alias is unavailable"
            ) from error
        if connection.vendor != "postgresql":
            raise OwnerTenantAuthorityV3Unavailable(
                "owner tenant authority v3 ledger requires PostgreSQL"
            )

    def _cutoff(self, as_of: datetime) -> None:
        """Validate an aware historical cutoff that is not from the future."""

        if not _is_aware(as_of):
            raise OwnerTenantAuthorityV3Unavailable(
                "owner tenant authority v3 cutoff must be timezone-aware"
            )
        if as_of > self.now():
            raise OwnerTenantAuthorityV3Unavailable(
                "owner tenant authority v3 future cutoff is forbidden"
            )

    def _ensure_selector_token(self, value: object, name: str) -> str:
        """Validate one exact selector token and return it."""

        if (
            type(value) is not str
            or not value
            or value.strip() != value
            or len(value) > 192
            or any(character.isspace() for character in value)
        ):
            raise OwnerTenantAuthorityV3Unavailable(f"{name} selector is invalid")
        return value

    def _require_uow(self) -> object:
        """Require this repository's active private UOW and insert context."""

        self._postgresql()
        if self._uow is None or _OWNER_V3_UOW.get() is not self._token:
            raise OwnerTenantAuthorityV3Conflict(
                "owner tenant authority v3 append requires private UOW"
            )
        return self._uow

    def _require_append_clock(self, recorded_at: datetime, expected: datetime) -> None:
        """Require an exact source recording clock no later than the server clock."""

        if not _is_aware(recorded_at) or recorded_at != expected:
            raise OwnerTenantAuthorityV3Corruption(
                "owner tenant authority v3 persistence clock differs"
            )
        if recorded_at > self.now():
            raise OwnerTenantAuthorityV3Conflict(
                "owner tenant authority v3 persistence clock is in the future"
            )

    def _lock_world(self, policy_id: str) -> None:
        """Lock all upstream sources before the two owner-decision ledgers."""

        self._ensure_selector_token(policy_id, "policy_id")
        lock_owner_tenant_authority_v3_sources(using=self._using, policy_id=policy_id)

    def _restore_world(self, as_of: datetime) -> _World:
        """Restore every root, revocation, parent, and sealed ledger field."""

        self._postgresql()
        if not _is_aware(as_of):
            raise OwnerTenantAuthorityV3Unavailable(
                "owner tenant authority v3 restore cutoff must be timezone-aware"
            )
        try:
            root_rows = tuple(
                OwnerTenantAuthorityV3Model._default_manager.using(self._using).order_by("pk")
            )
            roots = tuple((row, _restore_root(row)) for row in root_rows)
            _validate_root_slots(roots)
            for row, record in roots:
                expected_parents = self._root_parents(record, lock=False)
                actual_parents = (
                    _fk(row, "assignment_id"),
                    _fk(row, "policy_id"),
                    _fk(row, "actor_source_id"),
                )
                if expected_parents != actual_parents:
                    raise OwnerTenantAuthorityV3Corruption(
                        "owner tenant authority v3 root parent FK substitution"
                    )
            revocation_rows = tuple(
                OwnerTenantAuthorityV3RevocationModel._default_manager.using(self._using).order_by(
                    "pk"
                )
            )
            revocations = tuple((row, _restore_revocation(row)) for row in revocation_rows)
            _validate_revocation_slots(revocations)
            roots_by_pk = {_pk(row): record for row, record in roots}
            for revocation_row, revocation_record in revocations:
                authority_pk = _fk(revocation_row, "authority_id")
                if authority_pk is None or authority_pk not in roots_by_pk:
                    raise OwnerTenantAuthorityV3Corruption(
                        "owner tenant authority v3 revocation root FK is unavailable"
                    )
                root = roots_by_pk[authority_pk]
                head = _head(
                    tuple(
                        item
                        for item in roots
                        if item[1].authority.authority_id == root.authority.authority_id
                    ),
                    "owner tenant authority v3 revocation chain",
                )
                if head != root:
                    raise OwnerTenantAuthorityV3Corruption(
                        "owner tenant authority v3 revocation does not bind the final head"
                    )
                if (
                    revocation_record.revocation.authority_content_hash
                    != root.authority.content_hash
                    or revocation_record.revocation.policy_content_hash
                    != root.authority.policy.content_hash
                ):
                    raise OwnerTenantAuthorityV3Corruption(
                        "owner tenant authority v3 revocation root binding differs"
                    )
                try:
                    validate_owner_tenant_authority_v3_revocation(
                        root.authority, revocation_record.revocation
                    )
                except (TypeError, ValueError) as error:
                    raise OwnerTenantAuthorityV3Corruption(
                        "owner tenant authority v3 revocation binding is invalid"
                    ) from error
                expected_actor = self._revocation_parent(revocation_record, lock=False)
                if expected_actor != _fk(revocation_row, "actor_source_id"):
                    raise OwnerTenantAuthorityV3Corruption(
                        "owner tenant authority v3 revocation actor FK substitution"
                    )
            return _World(roots, revocations)
        except (DatabaseError, ConnectionDoesNotExist) as error:
            raise OwnerTenantAuthorityV3Unavailable(
                "owner tenant authority v3 ledger cannot be read"
            ) from error

    def _root_parents(
        self, record: PersistedOwnerTenantAuthorityV3, *, lock: bool
    ) -> tuple[int, int, int]:
        """Resolve and verify Evidence, policy, and actor parents at source clocks."""

        if type(record) is not PersistedOwnerTenantAuthorityV3:
            raise OwnerTenantAuthorityV3Corruption(
                "owner tenant authority v3 root record type substitution"
            )
        checked = record
        authority = checked.authority
        try:
            assignment = self._assignments.get_exact_by_hash(
                evidence_id=authority.assignment_evidence_id,
                evidence_version=authority.assignment_evidence_version,
                expected_content_hash=authority.assignment_evidence_content_hash,
                as_of=authority.recorded_at,
            )
            if assignment is None or assignment.evidence != authority.assignment:
                raise OwnerTenantAuthorityV3Corruption(
                    "owner tenant authority v3 Evidence v5 parent is unavailable"
                )
            policy_values = tuple(
                self._policies.get_exact_current(
                    policy_id=authority.policy.policy_id,
                    policy_version=authority.policy.policy_version,
                    expected_content_hash=authority.policy.content_hash,
                    as_of=cutoff,
                )
                for cutoff in (authority.approved_at, authority.recorded_at)
            )
            if any(value != authority.policy for value in policy_values):
                raise OwnerTenantAuthorityV3Corruption(
                    "owner tenant authority v3 policy parent is not exact at source clocks"
                )
            stored_actor = self._actors.get_exact_by_hash(
                source_id=checked.authentication.source_id,
                source_version=checked.authentication.source_version,
                expected_content_hash=checked.authentication.source_content_hash,
                as_of=authority.approved_at,
            )
            actor_head = self._actors.get_current_head(
                source_id=checked.authentication.source_id,
                as_of=authority.recorded_at,
            )
            if stored_actor is None or actor_head != stored_actor:
                raise OwnerTenantAuthorityV3Corruption(
                    "owner tenant authority v3 actor parent is not current at recording"
                )
            if _project_actor(stored_actor.source) != checked.authentication:
                raise OwnerTenantAuthorityV3Corruption(
                    "owner tenant authority v3 actor projection differs"
                )
            assignment_query = AccountOwnerAssignmentEvidenceV5Model._default_manager.using(
                self._using
            ).filter(
                evidence_id=authority.assignment_evidence_id,
                evidence_version=authority.assignment_evidence_version,
                content_hash=authority.assignment_evidence_content_hash,
            )
            policy_query = SingleOwnerAuthorityPolicyV1Model._default_manager.using(
                self._using
            ).filter(
                policy_id=authority.policy.policy_id,
                policy_version=authority.policy.policy_version,
                content_hash=authority.policy.content_hash,
            )
            actor_query = AccountOwnerAssignmentActorAuthoritySourceV3Model._default_manager.using(
                self._using
            ).filter(
                source_id=checked.authentication.source_id,
                source_version=checked.authentication.source_version,
                content_hash=checked.authentication.source_content_hash,
            )
            if lock:
                assignment_query = assignment_query.select_for_update()
                policy_query = policy_query.select_for_update()
                actor_query = actor_query.select_for_update()
            assignment_row = assignment_query.first()
            policy_row = policy_query.first()
            actor_row = actor_query.first()
            if assignment_row is None or policy_row is None or actor_row is None:
                raise OwnerTenantAuthorityV3Corruption(
                    "owner tenant authority v3 durable parent row is unavailable"
                )
            return _pk(assignment_row), _pk(policy_row), _pk(actor_row)
        except (
            AccountOwnerAssignmentUnavailable,
            AccountOwnerAssignmentCorruption,
            AccountOwnerAssignmentConflict,
            AccountOwnerAssignmentActorAuthoritySourceV3Unavailable,
            AccountOwnerAssignmentActorAuthoritySourceV3Corruption,
            AccountOwnerAssignmentActorAuthoritySourceV3Conflict,
        ) as error:
            _raise_parent_error(error, "owner tenant authority v3 root parent")

    def _revocation_parent(
        self,
        record: PersistedOwnerTenantAuthorityV3Revocation,
        *,
        lock: bool,
    ) -> int:
        """Resolve one exact revocation actor source at the event clocks."""

        if type(record) is not PersistedOwnerTenantAuthorityV3Revocation:
            raise OwnerTenantAuthorityV3Corruption(
                "owner tenant authority v3 revocation record type substitution"
            )
        checked = record
        authentication = checked.authentication
        event = checked.revocation
        try:
            stored_actor = self._actors.get_exact_by_hash(
                source_id=authentication.source_id,
                source_version=authentication.source_version,
                expected_content_hash=authentication.source_content_hash,
                as_of=event.revoked_at,
            )
            actor_head = self._actors.get_current_head(
                source_id=authentication.source_id,
                as_of=event.recorded_at,
            )
            if stored_actor is None or actor_head != stored_actor:
                raise OwnerTenantAuthorityV3Corruption(
                    "owner tenant authority v3 revocation actor is not current at event"
                )
            if _project_actor(stored_actor.source) != authentication:
                raise OwnerTenantAuthorityV3Corruption(
                    "owner tenant authority v3 revocation actor projection differs"
                )
            actor_query = AccountOwnerAssignmentActorAuthoritySourceV3Model._default_manager.using(
                self._using
            ).filter(
                source_id=authentication.source_id,
                source_version=authentication.source_version,
                content_hash=authentication.source_content_hash,
            )
            if lock:
                actor_query = actor_query.select_for_update()
            actor_row = actor_query.first()
            if actor_row is None:
                raise OwnerTenantAuthorityV3Corruption(
                    "owner tenant authority v3 revocation actor row is unavailable"
                )
            return _pk(actor_row)
        except (
            AccountOwnerAssignmentUnavailable,
            AccountOwnerAssignmentCorruption,
            AccountOwnerAssignmentConflict,
            AccountOwnerAssignmentActorAuthoritySourceV3Unavailable,
            AccountOwnerAssignmentActorAuthoritySourceV3Corruption,
            AccountOwnerAssignmentActorAuthoritySourceV3Conflict,
        ) as error:
            _raise_parent_error(error, "owner tenant authority v3 revocation actor")

    def _insert(
        self,
        model_type: type[OwnerTenantAuthorityV3Model] | type[OwnerTenantAuthorityV3RevocationModel],
        values: dict[str, object],
    ) -> OwnerTenantAuthorityV3Model | OwnerTenantAuthorityV3RevocationModel:
        """Insert one exact root or revocation row inside a savepoint."""

        token = self._require_uow()
        model = model_type(**values)
        # ForeignKey field validation must stay on this explicitly selected PG
        # alias; no validation query may fall back to Django's default alias.
        model._state.db = self._using
        try:
            model.full_clean(validate_unique=False, validate_constraints=False)
            with transaction.atomic(using=self._using):
                with _claim_owner_tenant_authority_v3_insert(
                    token=token,
                    using=self._using,
                    model_type=model_type,
                    values=values,
                ):
                    model.save(force_insert=True, using=self._using)
        except IntegrityError as error:
            raise OwnerTenantAuthorityV3Conflict(
                "owner tenant authority v3 append collided with another writer"
            ) from error
        except ValidationError as error:
            raise OwnerTenantAuthorityV3Corruption(
                "owner tenant authority v3 model validation failed"
            ) from error
        return model


def lock_owner_tenant_authority_v3_sources(*, using: str, policy_id: str) -> None:
    """Lock parent sources and both V3 ledgers in deterministic PostgreSQL order.

    The caller must already be inside a transaction on ``using``.  Existing
    Evidence v5 locking is acquired first because its helper owns the parent
    lock order; the two new decision tables are then locked as the final
    append-only layer.
    """

    if type(using) is not str or not using or using.strip() != using:
        raise OwnerTenantAuthorityV3Unavailable(
            "owner tenant authority v3 database alias is invalid"
        )
    if (
        type(policy_id) is not str
        or not policy_id
        or policy_id.strip() != policy_id
        or len(policy_id) > 192
        or any(character.isspace() for character in policy_id)
    ):
        raise OwnerTenantAuthorityV3Unavailable(
            "owner tenant authority v3 policy selector is invalid"
        )
    try:
        connection = connections[using]
    except (ConnectionDoesNotExist, DatabaseError, KeyError) as error:
        raise OwnerTenantAuthorityV3Unavailable(
            "owner tenant authority v3 database alias is unavailable"
        ) from error
    if (
        connection.vendor != "postgresql"
        or not connection.in_atomic_block
        or connection.get_autocommit()
    ):
        raise OwnerTenantAuthorityV3Unavailable(
            "owner tenant authority v3 locks require an active PostgreSQL transaction"
        )
    try:
        with connection.cursor() as cursor:
            cursor.execute("SHOW transaction_isolation")
            if cursor.fetchone() != ("read committed",):
                raise OwnerTenantAuthorityV3Unavailable(
                    "owner tenant authority v3 locks require READ COMMITTED"
                )
        lock_account_owner_assignment_evidence_v5_sources(
            using=using,
            policy_id=policy_id,
        )
        with connection.cursor() as cursor:
            table_names = sorted(
                (
                    OwnerTenantAuthorityV3Model._meta.db_table,
                    OwnerTenantAuthorityV3RevocationModel._meta.db_table,
                )
            )
            for table_name in table_names:
                cursor.execute(
                    f"LOCK TABLE {connection.ops.quote_name(table_name)} "
                    "IN EXCLUSIVE MODE NOWAIT"
                )
    except OwnerTenantAuthorityV3Unavailable:
        raise
    except (DatabaseError, AccountOwnerAssignmentUnavailable) as error:
        raise OwnerTenantAuthorityV3Unavailable(
            "owner tenant authority v3 source lock is unavailable"
        ) from error


def _validate_root_slots(
    roots: tuple[tuple[OwnerTenantAuthorityV3Model, PersistedOwnerTenantAuthorityV3], ...],
) -> None:
    """Validate closed single-root, single-head predecessor chains."""

    rows_by_pk: dict[int, tuple[OwnerTenantAuthorityV3Model, PersistedOwnerTenantAuthorityV3]] = {}
    seen_versions: set[tuple[str, str]] = set()
    seen_root_authority: set[str] = set()
    seen_root_assignment: set[str] = set()
    seen_predecessors: set[int] = set()
    seen_identity: set[str] = set()
    seen_content: set[str] = set()
    for row, record in roots:
        if row.pk is None:
            raise OwnerTenantAuthorityV3Corruption(
                "owner tenant authority v3 record has no database identity"
            )
        primary_key = _pk(row)
        if primary_key in rows_by_pk:
            raise OwnerTenantAuthorityV3Corruption(
                "owner tenant authority v3 database identity is duplicated"
            )
        rows_by_pk[primary_key] = (row, record)

    for row, record in roots:
        authority = record.authority
        version_key = (authority.authority_id, authority.authority_version)
        if version_key in seen_versions:
            raise OwnerTenantAuthorityV3Corruption(
                "owner tenant authority v3 version slot is duplicated"
            )
        if authority.identity_hash in seen_identity or authority.content_hash in seen_content:
            raise OwnerTenantAuthorityV3Corruption(
                "owner tenant authority v3 sealed identity is duplicated"
            )
        predecessor_pk = _fk(row, "predecessor_id")
        if predecessor_pk is None:
            if authority.authority_id in seen_root_authority:
                raise OwnerTenantAuthorityV3Corruption(
                    "owner tenant authority v3 authority root is duplicated"
                )
            if authority.assignment_evidence_content_hash in seen_root_assignment:
                raise OwnerTenantAuthorityV3Corruption(
                    "owner tenant authority v3 assignment root is duplicated"
                )
            try:
                validate_owner_tenant_authority_v3_root(authority)
            except (TypeError, ValueError) as error:
                raise OwnerTenantAuthorityV3Corruption(
                    "owner tenant authority v3 root is invalid"
                ) from error
            seen_root_authority.add(authority.authority_id)
            seen_root_assignment.add(authority.assignment_evidence_content_hash)
        else:
            if predecessor_pk in seen_predecessors:
                raise OwnerTenantAuthorityV3Corruption(
                    "owner tenant authority v3 predecessor has multiple successors"
                )
            predecessor_item = rows_by_pk.get(predecessor_pk)
            if predecessor_item is None:
                raise OwnerTenantAuthorityV3Corruption(
                    "owner tenant authority v3 predecessor is unavailable"
                )
            predecessor = predecessor_item[1].authority
            if authority.supersedes_content_hash != predecessor.content_hash:
                raise OwnerTenantAuthorityV3Corruption(
                    "owner tenant authority v3 predecessor seal differs"
                )
            try:
                validate_owner_tenant_authority_v3_successor(predecessor, authority)
            except (TypeError, ValueError) as error:
                raise OwnerTenantAuthorityV3Corruption(
                    "owner tenant authority v3 successor is invalid"
                ) from error
            seen_predecessors.add(predecessor_pk)
        seen_versions.add(version_key)
        seen_identity.add(authority.identity_hash)
        seen_content.add(authority.content_hash)

    authority_ids = {record.authority.authority_id for _, record in roots}
    for authority_id in authority_ids:
        chain = tuple(item for item in roots if item[1].authority.authority_id == authority_id)
        root_count = sum(_fk(row, "predecessor_id") is None for row, _ in chain)
        head_count = sum(_pk(row) not in seen_predecessors for row, _ in chain)
        if root_count != 1 or head_count != 1:
            raise OwnerTenantAuthorityV3Corruption(
                "owner tenant authority v3 chain is forked or rootless"
            )
        for row, _ in chain:
            visited: set[int] = set()
            cursor: int | None = _pk(row)
            while cursor is not None:
                if cursor in visited:
                    raise OwnerTenantAuthorityV3Corruption(
                        "owner tenant authority v3 chain contains a cycle"
                    )
                visited.add(cursor)
                cursor_item = rows_by_pk.get(cursor)
                if cursor_item is None:
                    raise OwnerTenantAuthorityV3Corruption(
                        "owner tenant authority v3 chain contains an orphan"
                    )
                cursor = _fk(cursor_item[0], "predecessor_id")


def _validate_revocation_slots(
    revocations: tuple[
        tuple[OwnerTenantAuthorityV3RevocationModel, PersistedOwnerTenantAuthorityV3Revocation],
        ...,
    ],
) -> None:
    """Reject duplicate immutable revocation slots in a tampered world."""

    seen_authority: set[str] = set()
    seen_identity: set[str] = set()
    seen_content: set[str] = set()
    for row, record in revocations:
        if row.pk is None:
            raise OwnerTenantAuthorityV3Corruption(
                "owner tenant authority v3 revocation has no database identity"
            )
        value = record.revocation
        if (
            value.authority_content_hash in seen_authority
            or value.identity_hash in seen_identity
            or value.content_hash in seen_content
        ):
            raise OwnerTenantAuthorityV3Corruption(
                "owner tenant authority v3 revocation slot is duplicated"
            )
        seen_authority.add(value.authority_content_hash)
        seen_identity.add(value.identity_hash)
        seen_content.add(value.content_hash)


def _project_actor(
    source: AccountOwnerAssignmentActorAuthoritySourceV3,
) -> CurrentAccountActorAuthorityV3:
    """Project one exact persisted actor-source Domain value into auth facts."""

    try:
        return CurrentAccountActorAuthorityV3(
            source.principal_id,
            source.user_id,
            source.authentication_context_content_hash,
            source.actor_id,
            source.is_authenticated,
            source.is_active,
            source.is_staff,
            source.is_superuser,
            source.rbac_role,
            source.source_id,
            source.source_version,
            source.content_hash,
            source.recorded_at,
            source.valid_until,
        )
    except (AttributeError, TypeError, ValueError) as error:
        raise OwnerTenantAuthorityV3Corruption(
            "owner tenant authority v3 actor source projection is invalid"
        ) from error


def _raise_parent_error(error: Exception, label: str) -> NoReturn:
    """Translate shared parent repository errors at the V3 boundary."""

    if isinstance(
        error,
        (
            AccountOwnerAssignmentUnavailable,
            AccountOwnerAssignmentActorAuthoritySourceV3Unavailable,
        ),
    ):
        raise OwnerTenantAuthorityV3Unavailable(f"{label} is unavailable") from error
    if isinstance(
        error,
        (AccountOwnerAssignmentCorruption, AccountOwnerAssignmentActorAuthoritySourceV3Corruption),
    ):
        raise OwnerTenantAuthorityV3Corruption(f"{label} is corrupt") from error
    if isinstance(
        error,
        (AccountOwnerAssignmentConflict, AccountOwnerAssignmentActorAuthoritySourceV3Conflict),
    ):
        raise OwnerTenantAuthorityV3Conflict(f"{label} conflicts") from error
    raise OwnerTenantAuthorityV3Corruption(f"{label} failed") from error


def _ensure_digest(value: object, name: str) -> str:
    """Require one exact lowercase SHA-256 selector."""

    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise OwnerTenantAuthorityV3Unavailable(f"{name} must be a lowercase SHA-256 digest")
    return value


def _is_aware(value: object) -> bool:
    """Return whether a value is an exact timezone-aware datetime."""

    return type(value) is datetime and value.tzinfo is not None and value.utcoffset() is not None


def _pk(
    row: (
        OwnerTenantAuthorityV3Model
        | OwnerTenantAuthorityV3RevocationModel
        | AccountOwnerAssignmentEvidenceV5Model
        | SingleOwnerAuthorityPolicyV1Model
        | AccountOwnerAssignmentActorAuthoritySourceV3Model
    ),
) -> int:
    """Return one exact persisted primary key."""

    value = row.pk
    if type(value) is not int or value <= 0:
        raise OwnerTenantAuthorityV3Corruption(
            "owner tenant authority v3 parent has no database identity"
        )
    return value


def _head(
    values: tuple[tuple[OwnerTenantAuthorityV3Model, PersistedOwnerTenantAuthorityV3], ...],
    label: str,
) -> PersistedOwnerTenantAuthorityV3 | None:
    """Return the single childless record from one validated chain selection."""

    if not values:
        return None
    selected_pks = {_pk(row) for row, _ in values}
    predecessor_pks = {
        predecessor_pk
        for row, _ in values
        if (predecessor_pk := _fk(row, "predecessor_id")) in selected_pks
    }
    heads = tuple(record for row, record in values if _pk(row) not in predecessor_pks)
    if len(heads) != 1:
        raise OwnerTenantAuthorityV3Corruption(f"{label} has no single head")
    return heads[0]


def _single(
    values: tuple[PersistedOwnerTenantAuthorityV3, ...], label: str
) -> PersistedOwnerTenantAuthorityV3 | None:
    """Return one selected root or reject an ambiguous closed world."""

    if len(values) > 1:
        raise OwnerTenantAuthorityV3Corruption(f"{label} is ambiguous")
    return values[0] if values else None


def _single_revocation(
    values: tuple[PersistedOwnerTenantAuthorityV3Revocation, ...], label: str
) -> PersistedOwnerTenantAuthorityV3Revocation | None:
    """Return one selected revocation or reject an ambiguous closed world."""

    if len(values) > 1:
        raise OwnerTenantAuthorityV3Corruption(f"{label} is ambiguous")
    return values[0] if values else None


__all__ = [
    "DjangoOwnerTenantAuthorityV3Clock",
    "DjangoOwnerTenantAuthorityV3Repository",
    "OwnerTenantAuthorityV3Clock",
    "lock_owner_tenant_authority_v3_sources",
]
