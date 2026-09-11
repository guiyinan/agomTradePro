"""PostgreSQL repository for immutable owner/tenant authority v2 decisions.

The repository stores an active decision root and a separate revocation event.
Every read restores the complete local ledger and its durable Evidence v4,
policy, and actor-source parents before selecting a point-in-time result.  A
write takes the existing parent-world lock first, then the two decision-table
locks, so concurrent composition roots use one deterministic lock order.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
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
from apps.account.application.owner_tenant_authority_v2_contracts import (
    OwnerTenantAuthorityV2Conflict,
    OwnerTenantAuthorityV2Corruption,
    OwnerTenantAuthorityV2Repository,
    OwnerTenantAuthorityV2Unavailable,
    PersistedOwnerTenantAuthorityV2,
    PersistedOwnerTenantAuthorityV2Revocation,
)
from apps.account.domain.account_owner_assignment_actor_authority_source_v3 import (
    AccountOwnerAssignmentActorAuthoritySourceV3,
)
from apps.account.domain.owner_tenant_authority_v2 import (
    validate_owner_tenant_authority_v2_revocation,
    validate_owner_tenant_authority_v2_root,
)
from apps.account.infrastructure.account_owner_assignment_actor_authority_source_v3_models import (
    AccountOwnerAssignmentActorAuthoritySourceV3Model,
)
from apps.account.infrastructure.account_owner_assignment_actor_authority_source_v3_repository import (
    DjangoAccountOwnerAssignmentActorAuthoritySourceV3Repository,
)
from apps.account.infrastructure.account_owner_assignment_evidence_v4_models import (
    AccountOwnerAssignmentEvidenceV4Model,
)
from apps.account.infrastructure.account_owner_assignment_evidence_v4_repository import (
    DjangoAccountOwnerAssignmentEvidenceV4Repository,
    lock_account_owner_assignment_evidence_v4_sources,
)
from apps.account.infrastructure.owner_tenant_authority_v2_codec import (
    OwnerTenantAuthorityV2CodecError,
)
from apps.account.infrastructure.owner_tenant_authority_v2_models import (
    _OWNER_V2_UOW,
    OwnerTenantAuthorityV2Model,
    OwnerTenantAuthorityV2RevocationModel,
    _activate_owner_tenant_authority_v2_uow,
    _claim_owner_tenant_authority_v2_insert,
)
from apps.account.infrastructure.owner_tenant_authority_v2_record_codec import (
    OwnerTenantAuthorityV2RecordCodecError,
    decode_owner_tenant_authority_v2_record,
    decode_owner_tenant_authority_v2_revocation_record,
    encode_owner_tenant_authority_v2_record,
    encode_owner_tenant_authority_v2_revocation_record,
)
from apps.account.infrastructure.single_owner_authority_policy_v1_models import (
    SingleOwnerAuthorityPolicyV1Model,
)
from apps.account.infrastructure.single_owner_authority_policy_v1_repository import (
    DjangoSingleOwnerAuthorityPolicyV1Repository,
)

_ROOT_FK_NAMES = frozenset({"assignment_id", "policy_id", "actor_source_id"})
_REVOCATION_FK_NAMES = frozenset({"authority_id", "actor_source_id"})


class OwnerTenantAuthorityV2Clock(Protocol):
    """Supply the authoritative persistence clock for one repository."""

    def now(self) -> datetime:
        """Return an exact timezone-aware current timestamp."""

        ...


class DjangoOwnerTenantAuthorityV2Clock:
    """Use Django's timezone-aware server clock."""

    def now(self) -> datetime:
        """Return the current timezone-aware timestamp."""

        return timezone.now()


@dataclass(frozen=True, slots=True)
class _World:
    """A closed-world snapshot of all decision and revocation rows."""

    roots: tuple[tuple[OwnerTenantAuthorityV2Model, PersistedOwnerTenantAuthorityV2], ...]
    revocations: tuple[
        tuple[OwnerTenantAuthorityV2RevocationModel, PersistedOwnerTenantAuthorityV2Revocation],
        ...,
    ]


class DjangoOwnerTenantAuthorityV2Repository(OwnerTenantAuthorityV2Repository):
    """Persist and restore one immutable owner/tenant authority v2 world."""

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
        clock: OwnerTenantAuthorityV2Clock | None = None,
    ) -> None:
        """Bind all decision and parent queries to one named database alias."""

        if type(using) is not str or not using or using.strip() != using:
            raise ValueError("owner tenant authority v2 database alias is invalid")
        self._using = using
        self._clock = clock or DjangoOwnerTenantAuthorityV2Clock()
        self._token = object()
        self._uow: object | None = None
        self._active = False
        self._assignments = DjangoAccountOwnerAssignmentEvidenceV4Repository(using=using)
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
            raise OwnerTenantAuthorityV2Conflict(
                "owner tenant authority v2 UOW cannot be re-entered"
            )
        token = self._token
        self._active = True
        self._uow = token
        try:
            with transaction.atomic(using=self._using):
                with _activate_owner_tenant_authority_v2_uow(token):
                    yield
        except DatabaseError as error:
            raise OwnerTenantAuthorityV2Unavailable(
                "owner tenant authority v2 transaction is unavailable"
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
            raise OwnerTenantAuthorityV2Unavailable(
                "owner tenant authority v2 clock is unavailable"
            ) from error
        if not _is_aware(value):
            raise OwnerTenantAuthorityV2Unavailable(
                "owner tenant authority v2 clock must be timezone-aware"
            )
        return value

    def get_winner(
        self,
        *,
        authority_id: str,
        authority_version: str,
        as_of: datetime,
    ) -> PersistedOwnerTenantAuthorityV2 | None:
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
        return _single(matches, "owner tenant authority v2 winner")

    def get_head(
        self, *, authority_id: str, as_of: datetime
    ) -> PersistedOwnerTenantAuthorityV2 | None:
        """Return the occupied decision root, including an expired root."""

        self._ensure_selector_token(authority_id, "authority_id")
        self._cutoff(as_of)
        matches = tuple(
            record
            for _, record in self._restore_world(as_of).roots
            if record.authority.authority_id == authority_id
            and record.authority.recorded_at <= as_of
        )
        return _single(matches, "owner tenant authority v2 authority slot")

    def get_assignment_head(
        self, *, assignment_content_hash: str, as_of: datetime
    ) -> PersistedOwnerTenantAuthorityV2 | None:
        """Return the decision occupying an Evidence v4 assignment slot."""

        _ensure_digest(assignment_content_hash, "assignment_content_hash")
        self._cutoff(as_of)
        matches = tuple(
            record
            for _, record in self._restore_world(as_of).roots
            if record.authority.assignment_evidence_content_hash == assignment_content_hash
            and record.authority.recorded_at <= as_of
        )
        return _single(matches, "owner tenant authority v2 assignment slot")

    def get_revocation(
        self, *, authority_content_hash: str, as_of: datetime
    ) -> PersistedOwnerTenantAuthorityV2Revocation | None:
        """Return one durable revocation event known at ``as_of``."""

        _ensure_digest(authority_content_hash, "authority_content_hash")
        self._cutoff(as_of)
        matches = tuple(
            record
            for _, record in self._restore_world(as_of).revocations
            if record.revocation.authority_content_hash == authority_content_hash
            and record.revocation.recorded_at <= as_of
        )
        return _single_revocation(matches, "owner tenant authority v2 revocation")

    def append_root(
        self,
        record: PersistedOwnerTenantAuthorityV2,
        *,
        recorded_at: datetime,
    ) -> PersistedOwnerTenantAuthorityV2:
        """Append or exactly replay one immutable decision root."""

        self._require_uow()
        checked = _root_record(record)
        authority = checked.authority
        self._require_append_clock(recorded_at, authority.recorded_at)
        self._lock_world(authority.policy.policy_id)
        world = self._restore_world(recorded_at)
        collisions = tuple(
            existing
            for _, existing in world.roots
            if (
                existing.authority.authority_id == authority.authority_id
                or existing.authority.assignment_evidence_content_hash
                == authority.assignment_evidence_content_hash
                or existing.authority.identity_hash == authority.identity_hash
                or existing.authority.content_hash == authority.content_hash
                or _hash(encode_owner_tenant_authority_v2_record(existing))
                == _hash(encode_owner_tenant_authority_v2_record(checked))
            )
        )
        if collisions:
            if len(collisions) == 1 and collisions[0] == checked:
                return checked
            raise OwnerTenantAuthorityV2Conflict(
                "owner tenant authority v2 root slot contains another winner"
            )
        assignment_pk, policy_pk, actor_pk = self._root_parents(checked, lock=True)
        values = _root_values(checked, assignment_pk, policy_pk, actor_pk)
        self._insert(OwnerTenantAuthorityV2Model, values)
        restored = self.get_winner(
            authority_id=authority.authority_id,
            authority_version=authority.authority_version,
            as_of=recorded_at,
        )
        if restored != checked:
            raise OwnerTenantAuthorityV2Corruption("owner tenant authority v2 root restore differs")
        return restored

    def append_revocation(
        self,
        record: PersistedOwnerTenantAuthorityV2Revocation,
        *,
        expected_authority_content_hash: str,
        recorded_at: datetime,
    ) -> PersistedOwnerTenantAuthorityV2Revocation:
        """Append or exactly replay one immutable revocation event."""

        self._require_uow()
        checked = _revocation_record(record)
        revocation = checked.revocation
        _ensure_digest(expected_authority_content_hash, "expected_authority_content_hash")
        if revocation.authority_content_hash != expected_authority_content_hash:
            raise OwnerTenantAuthorityV2Conflict(
                "owner tenant authority v2 revocation selector differs"
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
                raise OwnerTenantAuthorityV2Corruption(
                    "owner tenant authority v2 root content hash is duplicated"
                )
            raise OwnerTenantAuthorityV2Conflict(
                "owner tenant authority v2 revocation root is not persisted"
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
            raise OwnerTenantAuthorityV2Corruption(
                "owner tenant authority v2 revocation root changed"
            )
        root_row, root = current_roots[0]
        if revocation.policy_content_hash != root.authority.policy.content_hash:
            raise OwnerTenantAuthorityV2Conflict(
                "owner tenant authority v2 revocation policy differs"
            )
        try:
            validate_owner_tenant_authority_v2_revocation(root.authority, revocation)
        except (TypeError, ValueError) as error:
            raise OwnerTenantAuthorityV2Conflict(
                "owner tenant authority v2 revocation does not bind the exact root"
            ) from error
        collisions = tuple(
            existing
            for row, existing in world.revocations
            if (
                existing.revocation.authority_content_hash == revocation.authority_content_hash
                or existing.revocation.identity_hash == revocation.identity_hash
                or existing.revocation.content_hash == revocation.content_hash
                or _hash(encode_owner_tenant_authority_v2_revocation_record(existing))
                == _hash(encode_owner_tenant_authority_v2_revocation_record(checked))
                or _fk(row, "authority_id") == _pk(root_row)
            )
        )
        if collisions:
            if len(collisions) == 1 and collisions[0] == checked:
                return checked
            raise OwnerTenantAuthorityV2Conflict(
                "owner tenant authority v2 revocation already has another winner"
            )
        actor_pk = self._revocation_parent(checked, lock=True)
        values = _revocation_values(checked, _pk(root_row), actor_pk)
        self._insert(OwnerTenantAuthorityV2RevocationModel, values)
        restored = self.get_revocation(
            authority_content_hash=revocation.authority_content_hash,
            as_of=recorded_at,
        )
        if restored != checked:
            raise OwnerTenantAuthorityV2Corruption(
                "owner tenant authority v2 revocation restore differs"
            )
        return restored

    def _postgresql(self) -> None:
        """Require the configured alias to be an available PostgreSQL connection."""

        try:
            connection = connections[self._using]
        except (ConnectionDoesNotExist, DatabaseError, KeyError) as error:
            raise OwnerTenantAuthorityV2Unavailable(
                "owner tenant authority v2 database alias is unavailable"
            ) from error
        if connection.vendor != "postgresql":
            raise OwnerTenantAuthorityV2Unavailable(
                "owner tenant authority v2 ledger requires PostgreSQL"
            )

    def _cutoff(self, as_of: datetime) -> None:
        """Validate an aware historical cutoff that is not from the future."""

        if not _is_aware(as_of):
            raise OwnerTenantAuthorityV2Unavailable(
                "owner tenant authority v2 cutoff must be timezone-aware"
            )
        if as_of > self.now():
            raise OwnerTenantAuthorityV2Unavailable(
                "owner tenant authority v2 future cutoff is forbidden"
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
            raise OwnerTenantAuthorityV2Unavailable(f"{name} selector is invalid")
        return value

    def _require_uow(self) -> object:
        """Require this repository's active private UOW and insert context."""

        self._postgresql()
        if self._uow is None or _OWNER_V2_UOW.get() is not self._token:
            raise OwnerTenantAuthorityV2Conflict(
                "owner tenant authority v2 append requires private UOW"
            )
        return self._uow

    def _require_append_clock(self, recorded_at: datetime, expected: datetime) -> None:
        """Require an exact source recording clock no later than the server clock."""

        if not _is_aware(recorded_at) or recorded_at != expected:
            raise OwnerTenantAuthorityV2Corruption(
                "owner tenant authority v2 persistence clock differs"
            )
        if recorded_at > self.now():
            raise OwnerTenantAuthorityV2Conflict(
                "owner tenant authority v2 persistence clock is in the future"
            )

    def _lock_world(self, policy_id: str) -> None:
        """Lock all upstream sources before the two owner-decision ledgers."""

        self._ensure_selector_token(policy_id, "policy_id")
        lock_owner_tenant_authority_v2_sources(using=self._using, policy_id=policy_id)

    def _restore_world(self, as_of: datetime) -> _World:
        """Restore every root, revocation, parent, and sealed ledger field."""

        self._postgresql()
        if not _is_aware(as_of):
            raise OwnerTenantAuthorityV2Unavailable(
                "owner tenant authority v2 restore cutoff must be timezone-aware"
            )
        try:
            root_rows = tuple(
                OwnerTenantAuthorityV2Model._default_manager.using(self._using).order_by("pk")
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
                    raise OwnerTenantAuthorityV2Corruption(
                        "owner tenant authority v2 root parent FK substitution"
                    )
            revocation_rows = tuple(
                OwnerTenantAuthorityV2RevocationModel._default_manager.using(self._using).order_by(
                    "pk"
                )
            )
            revocations = tuple((row, _restore_revocation(row)) for row in revocation_rows)
            _validate_revocation_slots(revocations)
            roots_by_pk = {_pk(row): record for row, record in roots}
            for revocation_row, revocation_record in revocations:
                authority_pk = _fk(revocation_row, "authority_id")
                if authority_pk is None or authority_pk not in roots_by_pk:
                    raise OwnerTenantAuthorityV2Corruption(
                        "owner tenant authority v2 revocation root FK is unavailable"
                    )
                root = roots_by_pk[authority_pk]
                if (
                    revocation_record.revocation.authority_content_hash
                    != root.authority.content_hash
                    or revocation_record.revocation.policy_content_hash
                    != root.authority.policy.content_hash
                ):
                    raise OwnerTenantAuthorityV2Corruption(
                        "owner tenant authority v2 revocation root binding differs"
                    )
                try:
                    validate_owner_tenant_authority_v2_revocation(
                        root.authority, revocation_record.revocation
                    )
                except (TypeError, ValueError) as error:
                    raise OwnerTenantAuthorityV2Corruption(
                        "owner tenant authority v2 revocation binding is invalid"
                    ) from error
                expected_actor = self._revocation_parent(revocation_record, lock=False)
                if expected_actor != _fk(revocation_row, "actor_source_id"):
                    raise OwnerTenantAuthorityV2Corruption(
                        "owner tenant authority v2 revocation actor FK substitution"
                    )
            return _World(roots, revocations)
        except (DatabaseError, ConnectionDoesNotExist) as error:
            raise OwnerTenantAuthorityV2Unavailable(
                "owner tenant authority v2 ledger cannot be read"
            ) from error

    def _root_parents(
        self, record: PersistedOwnerTenantAuthorityV2, *, lock: bool
    ) -> tuple[int, int, int]:
        """Resolve and verify Evidence, policy, and actor parents at source clocks."""

        checked = _root_record(record)
        authority = checked.authority
        try:
            assignment = self._assignments.get_exact_by_hash(
                evidence_id=authority.assignment_evidence_id,
                evidence_version=authority.assignment_evidence_version,
                expected_content_hash=authority.assignment_evidence_content_hash,
                as_of=authority.recorded_at,
            )
            if assignment is None or assignment.evidence != authority.assignment:
                raise OwnerTenantAuthorityV2Corruption(
                    "owner tenant authority v2 Evidence v4 parent is unavailable"
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
                raise OwnerTenantAuthorityV2Corruption(
                    "owner tenant authority v2 policy parent is not exact at source clocks"
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
                raise OwnerTenantAuthorityV2Corruption(
                    "owner tenant authority v2 actor parent is not current at recording"
                )
            if _project_actor(stored_actor.source) != checked.authentication:
                raise OwnerTenantAuthorityV2Corruption(
                    "owner tenant authority v2 actor projection differs"
                )
            assignment_query = AccountOwnerAssignmentEvidenceV4Model._default_manager.using(
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
                raise OwnerTenantAuthorityV2Corruption(
                    "owner tenant authority v2 durable parent row is unavailable"
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
            _raise_parent_error(error, "owner tenant authority v2 root parent")

    def _revocation_parent(
        self,
        record: PersistedOwnerTenantAuthorityV2Revocation,
        *,
        lock: bool,
    ) -> int:
        """Resolve one exact revocation actor source at the event clocks."""

        checked = _revocation_record(record)
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
                raise OwnerTenantAuthorityV2Corruption(
                    "owner tenant authority v2 revocation actor is not current at event"
                )
            if _project_actor(stored_actor.source) != authentication:
                raise OwnerTenantAuthorityV2Corruption(
                    "owner tenant authority v2 revocation actor projection differs"
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
                raise OwnerTenantAuthorityV2Corruption(
                    "owner tenant authority v2 revocation actor row is unavailable"
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
            _raise_parent_error(error, "owner tenant authority v2 revocation actor")

    def _insert(
        self,
        model_type: type[OwnerTenantAuthorityV2Model] | type[OwnerTenantAuthorityV2RevocationModel],
        values: dict[str, object],
    ) -> None:
        """Insert one exact root or revocation row inside a savepoint."""

        token = self._require_uow()
        model = model_type(**values)
        # ForeignKey field validation must stay on this explicitly selected PG
        # alias; no validation query may fall back to Django's default alias.
        model._state.db = self._using
        try:
            model.full_clean(validate_unique=False, validate_constraints=False)
            with transaction.atomic(using=self._using):
                with _claim_owner_tenant_authority_v2_insert(
                    token=token,
                    using=self._using,
                    model_type=model_type,
                    values=values,
                ):
                    model.save(force_insert=True, using=self._using)
        except IntegrityError as error:
            raise OwnerTenantAuthorityV2Conflict(
                "owner tenant authority v2 append collided with another writer"
            ) from error
        except ValidationError as error:
            raise OwnerTenantAuthorityV2Corruption(
                "owner tenant authority v2 model validation failed"
            ) from error


def lock_owner_tenant_authority_v2_sources(*, using: str, policy_id: str) -> None:
    """Lock parent sources and both V2 ledgers in deterministic PostgreSQL order.

    The caller must already be inside a transaction on ``using``.  Existing
    Evidence v4 locking is acquired first because its helper owns the parent
    lock order; the two new decision tables are then locked as the final
    append-only layer.
    """

    if type(using) is not str or not using or using.strip() != using:
        raise OwnerTenantAuthorityV2Unavailable(
            "owner tenant authority v2 database alias is invalid"
        )
    if (
        type(policy_id) is not str
        or not policy_id
        or policy_id.strip() != policy_id
        or len(policy_id) > 192
        or any(character.isspace() for character in policy_id)
    ):
        raise OwnerTenantAuthorityV2Unavailable(
            "owner tenant authority v2 policy selector is invalid"
        )
    try:
        connection = connections[using]
    except (ConnectionDoesNotExist, DatabaseError, KeyError) as error:
        raise OwnerTenantAuthorityV2Unavailable(
            "owner tenant authority v2 database alias is unavailable"
        ) from error
    if (
        connection.vendor != "postgresql"
        or not connection.in_atomic_block
        or connection.get_autocommit()
    ):
        raise OwnerTenantAuthorityV2Unavailable(
            "owner tenant authority v2 locks require an active PostgreSQL transaction"
        )
    try:
        with connection.cursor() as cursor:
            cursor.execute("SHOW transaction_isolation")
            if cursor.fetchone() != ("read committed",):
                raise OwnerTenantAuthorityV2Unavailable(
                    "owner tenant authority v2 locks require READ COMMITTED"
                )
        lock_account_owner_assignment_evidence_v4_sources(
            using=using,
            policy_id=policy_id,
        )
        with connection.cursor() as cursor:
            table_names = sorted(
                (
                    OwnerTenantAuthorityV2Model._meta.db_table,
                    OwnerTenantAuthorityV2RevocationModel._meta.db_table,
                )
            )
            for table_name in table_names:
                cursor.execute(
                    f"LOCK TABLE {connection.ops.quote_name(table_name)} "
                    "IN EXCLUSIVE MODE NOWAIT"
                )
    except OwnerTenantAuthorityV2Unavailable:
        raise
    except (DatabaseError, AccountOwnerAssignmentUnavailable) as error:
        raise OwnerTenantAuthorityV2Unavailable(
            "owner tenant authority v2 source lock is unavailable"
        ) from error


def _root_record(value: object) -> PersistedOwnerTenantAuthorityV2:
    """Canonicalize one exact root record before persistence or comparison."""

    if type(value) is not PersistedOwnerTenantAuthorityV2:
        raise OwnerTenantAuthorityV2Corruption(
            "owner tenant authority v2 root record type substitution"
        )
    try:
        return decode_owner_tenant_authority_v2_record(
            encode_owner_tenant_authority_v2_record(value)
        )
    except (OwnerTenantAuthorityV2RecordCodecError, TypeError, ValueError) as error:
        raise OwnerTenantAuthorityV2Corruption(
            "owner tenant authority v2 root record is corrupt"
        ) from error


def _revocation_record(value: object) -> PersistedOwnerTenantAuthorityV2Revocation:
    """Canonicalize one exact revocation record before persistence or comparison."""

    if type(value) is not PersistedOwnerTenantAuthorityV2Revocation:
        raise OwnerTenantAuthorityV2Corruption(
            "owner tenant authority v2 revocation record type substitution"
        )
    try:
        return decode_owner_tenant_authority_v2_revocation_record(
            encode_owner_tenant_authority_v2_revocation_record(value)
        )
    except (OwnerTenantAuthorityV2RecordCodecError, TypeError, ValueError) as error:
        raise OwnerTenantAuthorityV2Corruption(
            "owner tenant authority v2 revocation record is corrupt"
        ) from error


def _restore_root(row: OwnerTenantAuthorityV2Model) -> PersistedOwnerTenantAuthorityV2:
    """Decode a root and verify every denormalized field and ledger seal."""

    try:
        record = decode_owner_tenant_authority_v2_record(row.canonical_payload)
        values = _root_values(
            record,
            _fk(row, "assignment_id"),
            _fk(row, "policy_id"),
            _fk(row, "actor_source_id"),
        )
        _verify_row(row, values, _ROOT_FK_NAMES)
        validate_owner_tenant_authority_v2_root(record.authority)
        return record
    except OwnerTenantAuthorityV2Corruption:
        raise
    except (
        OwnerTenantAuthorityV2CodecError,
        OwnerTenantAuthorityV2RecordCodecError,
        AttributeError,
        TypeError,
        ValueError,
    ) as error:
        raise OwnerTenantAuthorityV2Corruption(
            "owner tenant authority v2 root payload or seal is corrupt"
        ) from error


def _restore_revocation(
    row: OwnerTenantAuthorityV2RevocationModel,
) -> PersistedOwnerTenantAuthorityV2Revocation:
    """Decode a revocation and verify every denormalized field and seal."""

    try:
        record = decode_owner_tenant_authority_v2_revocation_record(row.canonical_payload)
        values = _revocation_values(
            record,
            _fk(row, "authority_id"),
            _fk(row, "actor_source_id"),
        )
        _verify_row(row, values, _REVOCATION_FK_NAMES)
        return record
    except OwnerTenantAuthorityV2Corruption:
        raise
    except (
        OwnerTenantAuthorityV2CodecError,
        OwnerTenantAuthorityV2RecordCodecError,
        AttributeError,
        TypeError,
        ValueError,
    ) as error:
        raise OwnerTenantAuthorityV2Corruption(
            "owner tenant authority v2 revocation payload or seal is corrupt"
        ) from error


def _root_values(
    record: PersistedOwnerTenantAuthorityV2,
    assignment_pk: int | None,
    policy_pk: int | None,
    actor_pk: int | None,
) -> dict[str, object]:
    """Build all root denormalized columns and the parent-bound ledger seal."""

    authority = record.authority
    payload = encode_owner_tenant_authority_v2_record(record)
    return {
        "authority_id": authority.authority_id,
        "authority_version": authority.authority_version,
        "assignment_id": assignment_pk,
        "assignment_evidence_id": authority.assignment_evidence_id,
        "assignment_evidence_version": authority.assignment_evidence_version,
        "assignment_evidence_content_hash": authority.assignment_evidence_content_hash,
        "policy_id": policy_pk,
        "policy_identifier": authority.policy.policy_id,
        "policy_version": authority.policy.policy_version,
        "policy_content_hash": authority.policy.content_hash,
        "tenant_id": authority.tenant_id,
        "owner_id": authority.owner_id,
        "account_namespace": authority.account_namespace,
        "account_id": authority.account_id,
        "actor_id": authority.actor_id,
        "actor_user_id": authority.actor_user_id,
        "actor_source_id": actor_pk,
        "owner": authority.owner,
        "artifact_type": authority.artifact_type,
        "schema": authority.schema,
        "permission": authority.permission,
        "status": authority.status,
        "approved_at": authority.approved_at,
        "recorded_at": authority.recorded_at,
        "valid_until": authority.valid_until,
        "persisted_at": authority.recorded_at,
        "identity_hash": authority.identity_hash,
        "content_hash": authority.content_hash,
        "canonical_payload": payload,
        "record_seal": _hash(payload),
        "ledger_seal": _hash(
            {
                "domain": "account.owner-tenant-authority.v2/ledger",
                "record": payload,
                "assignment_pk": assignment_pk,
                "policy_pk": policy_pk,
                "actor_source_pk": actor_pk,
                "persisted_at": _time(authority.recorded_at),
            }
        ),
    }


def _revocation_values(
    record: PersistedOwnerTenantAuthorityV2Revocation,
    authority_pk: int | None,
    actor_pk: int | None,
) -> dict[str, object]:
    """Build all revocation denormalized columns and its parent-bound seal."""

    revocation = record.revocation
    payload = encode_owner_tenant_authority_v2_revocation_record(record)
    return {
        "authority_id": authority_pk,
        "actor_source_id": actor_pk,
        "authority_content_hash": revocation.authority_content_hash,
        "policy_content_hash": revocation.policy_content_hash,
        "owner": revocation.owner,
        "artifact_type": revocation.artifact_type,
        "schema": revocation.schema,
        "permission": revocation.permission,
        "status": revocation.status,
        "revoked_at": revocation.revoked_at,
        "recorded_at": revocation.recorded_at,
        "persisted_at": revocation.recorded_at,
        "reason": revocation.reason,
        "identity_hash": revocation.identity_hash,
        "content_hash": revocation.content_hash,
        "canonical_payload": payload,
        "record_seal": _hash(payload),
        "ledger_seal": _hash(
            {
                "domain": "account.owner-tenant-authority.v2/revocation-ledger",
                "record": payload,
                "authority_pk": authority_pk,
                "actor_source_pk": actor_pk,
                "persisted_at": _time(revocation.recorded_at),
            }
        ),
    }


def _verify_row(
    row: OwnerTenantAuthorityV2Model | OwnerTenantAuthorityV2RevocationModel,
    expected: dict[str, object],
    fk_names: frozenset[str],
) -> None:
    """Compare every stored model column with the canonical expected value."""

    for name, expected_value in expected.items():
        actual = _fk(row, name) if name in fk_names else getattr(row, name)
        if actual != expected_value:
            raise OwnerTenantAuthorityV2Corruption(
                f"owner tenant authority v2 stored field {name} is substituted"
            )


def _validate_root_slots(
    roots: tuple[tuple[OwnerTenantAuthorityV2Model, PersistedOwnerTenantAuthorityV2], ...],
) -> None:
    """Reject duplicate permanent authority and assignment slots in a tampered world."""

    seen_authority: set[str] = set()
    seen_assignment: set[str] = set()
    seen_identity: set[str] = set()
    seen_content: set[str] = set()
    for row, record in roots:
        if row.pk is None:
            raise OwnerTenantAuthorityV2Corruption(
                "owner tenant authority v2 root has no database identity"
            )
        authority = record.authority
        if authority.authority_id in seen_authority:
            raise OwnerTenantAuthorityV2Corruption(
                "owner tenant authority v2 authority slot is duplicated"
            )
        if authority.assignment_evidence_content_hash in seen_assignment:
            raise OwnerTenantAuthorityV2Corruption(
                "owner tenant authority v2 assignment slot is duplicated"
            )
        if authority.identity_hash in seen_identity or authority.content_hash in seen_content:
            raise OwnerTenantAuthorityV2Corruption(
                "owner tenant authority v2 sealed identity is duplicated"
            )
        seen_authority.add(authority.authority_id)
        seen_assignment.add(authority.assignment_evidence_content_hash)
        seen_identity.add(authority.identity_hash)
        seen_content.add(authority.content_hash)


def _validate_revocation_slots(
    revocations: tuple[
        tuple[OwnerTenantAuthorityV2RevocationModel, PersistedOwnerTenantAuthorityV2Revocation],
        ...,
    ],
) -> None:
    """Reject duplicate immutable revocation slots in a tampered world."""

    seen_authority: set[str] = set()
    seen_identity: set[str] = set()
    seen_content: set[str] = set()
    for row, record in revocations:
        if row.pk is None:
            raise OwnerTenantAuthorityV2Corruption(
                "owner tenant authority v2 revocation has no database identity"
            )
        value = record.revocation
        if (
            value.authority_content_hash in seen_authority
            or value.identity_hash in seen_identity
            or value.content_hash in seen_content
        ):
            raise OwnerTenantAuthorityV2Corruption(
                "owner tenant authority v2 revocation slot is duplicated"
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
        raise OwnerTenantAuthorityV2Corruption(
            "owner tenant authority v2 actor source projection is invalid"
        ) from error


def _raise_parent_error(error: Exception, label: str) -> NoReturn:
    """Translate shared parent repository errors at the V2 boundary."""

    if isinstance(
        error,
        (
            AccountOwnerAssignmentUnavailable,
            AccountOwnerAssignmentActorAuthoritySourceV3Unavailable,
        ),
    ):
        raise OwnerTenantAuthorityV2Unavailable(f"{label} is unavailable") from error
    if isinstance(
        error,
        (AccountOwnerAssignmentCorruption, AccountOwnerAssignmentActorAuthoritySourceV3Corruption),
    ):
        raise OwnerTenantAuthorityV2Corruption(f"{label} is corrupt") from error
    if isinstance(
        error,
        (AccountOwnerAssignmentConflict, AccountOwnerAssignmentActorAuthoritySourceV3Conflict),
    ):
        raise OwnerTenantAuthorityV2Conflict(f"{label} conflicts") from error
    raise OwnerTenantAuthorityV2Corruption(f"{label} failed") from error


def _hash(value: object) -> str:
    """Hash one canonical JSON-compatible ledger value."""

    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _time(value: datetime) -> str:
    """Serialize one aware timestamp for a ledger seal."""

    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _ensure_digest(value: object, name: str) -> str:
    """Require one exact lowercase SHA-256 selector."""

    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise OwnerTenantAuthorityV2Unavailable(f"{name} must be a lowercase SHA-256 digest")
    return value


def _is_aware(value: object) -> bool:
    """Return whether a value is an exact timezone-aware datetime."""

    return type(value) is datetime and value.tzinfo is not None and value.utcoffset() is not None


def _fk(
    row: (
        OwnerTenantAuthorityV2Model
        | OwnerTenantAuthorityV2RevocationModel
        | AccountOwnerAssignmentEvidenceV4Model
        | SingleOwnerAuthorityPolicyV1Model
        | AccountOwnerAssignmentActorAuthoritySourceV3Model
    ),
    name: str,
) -> int | None:
    """Read a raw Django foreign-key scalar without following another alias."""

    value = cast(object, row.__dict__.get(name))
    if value is None:
        return None
    if type(value) is not int or value <= 0:
        raise OwnerTenantAuthorityV2Corruption(f"owner tenant authority v2 FK {name} is invalid")
    return value


def _pk(
    row: (
        OwnerTenantAuthorityV2Model
        | OwnerTenantAuthorityV2RevocationModel
        | AccountOwnerAssignmentEvidenceV4Model
        | SingleOwnerAuthorityPolicyV1Model
        | AccountOwnerAssignmentActorAuthoritySourceV3Model
    ),
) -> int:
    """Return one exact persisted primary key."""

    value = row.pk
    if type(value) is not int or value <= 0:
        raise OwnerTenantAuthorityV2Corruption(
            "owner tenant authority v2 parent has no database identity"
        )
    return value


def _single(
    values: tuple[PersistedOwnerTenantAuthorityV2, ...], label: str
) -> PersistedOwnerTenantAuthorityV2 | None:
    """Return one selected root or reject an ambiguous closed world."""

    if len(values) > 1:
        raise OwnerTenantAuthorityV2Corruption(f"{label} is ambiguous")
    return values[0] if values else None


def _single_revocation(
    values: tuple[PersistedOwnerTenantAuthorityV2Revocation, ...], label: str
) -> PersistedOwnerTenantAuthorityV2Revocation | None:
    """Return one selected revocation or reject an ambiguous closed world."""

    if len(values) > 1:
        raise OwnerTenantAuthorityV2Corruption(f"{label} is ambiguous")
    return values[0] if values else None


__all__ = [
    "DjangoOwnerTenantAuthorityV2Clock",
    "DjangoOwnerTenantAuthorityV2Repository",
    "OwnerTenantAuthorityV2Clock",
    "lock_owner_tenant_authority_v2_sources",
]
