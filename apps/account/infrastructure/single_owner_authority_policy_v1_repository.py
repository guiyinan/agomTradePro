"""PostgreSQL persistence for the immutable single-owner policy ledger."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Protocol, cast

from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError, connections, transaction
from django.utils import timezone

from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentConflict,
    AccountOwnerAssignmentCorruption,
    AccountOwnerAssignmentUnavailable,
)
from apps.account.domain.single_owner_authority_policy_v1 import (
    SingleOwnerAuthorityPolicyV1,
    validate_single_owner_policy_successor,
)
from apps.account.infrastructure.single_owner_authority_policy_v1_codec import (
    SingleOwnerAuthorityPolicyV1CodecError,
    decode_single_owner_authority_policy_v1,
    encode_single_owner_authority_policy_v1,
)
from apps.account.infrastructure.single_owner_authority_policy_v1_models import (
    _POLICY_UOW,
    SingleOwnerAuthorityPolicyV1Model,
    _activate_single_owner_authority_policy_v1_uow,
    _claim_single_owner_authority_policy_v1_insert,
)

_RECORD_SEAL_DOMAIN = "account.single-owner-authority-policy.v1/ledger-record"


class SingleOwnerAuthorityPolicyV1Clock(Protocol):
    """Provide the authoritative persistence timestamp for policy appends."""

    def now(self) -> datetime:
        """Return one timezone-aware server timestamp."""
        ...


class DjangoSingleOwnerAuthorityPolicyV1Repository:
    """Append and restore a closed-world PostgreSQL policy chain."""

    __slots__ = ("_active", "_clock", "_token", "_using")

    def __init__(
        self,
        using: str = "default",
        *,
        clock: SingleOwnerAuthorityPolicyV1Clock | None = None,
    ) -> None:
        """Bind the repository to one named database alias."""

        if type(using) is not str or not using or using.strip() != using:
            raise ValueError("single-owner policy database alias is invalid")
        self._using = using
        self._clock = clock
        self._token = object()
        self._active = False

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Open a private UOW while allowing an outer same-alias transaction."""

        self._ensure_postgresql()
        if self._active:
            raise AccountOwnerAssignmentConflict("single-owner policy UOW cannot be re-entered")
        self._active = True
        try:
            with transaction.atomic(using=self._using):
                with _activate_single_owner_authority_policy_v1_uow(self._token):
                    yield
        except DatabaseError as error:
            raise AccountOwnerAssignmentUnavailable(
                "single-owner policy transaction is unavailable"
            ) from error
        finally:
            self._active = False

    def lock_scope(self, *, account_namespace: str, account_id: str) -> None:
        """Serialize publishers for a canonical scope before reading its heads.

        The caller must reject collisions after acquiring this lock and before
        append. This lock alone neither selects a policy nor grants authority.
        """
        self._ensure_postgresql()
        if not self._active or _POLICY_UOW.get() is not self._token:
            raise AccountOwnerAssignmentUnavailable(
                "single-owner policy scope lock requires private atomic UOW"
            )
        try:
            _token(account_namespace, "account_namespace")
            _token(account_id, "account_id")
        except (TypeError, ValueError) as error:
            raise AccountOwnerAssignmentUnavailable(
                "single-owner policy scope is invalid"
            ) from error
        key = json.dumps(
            ["account.single-owner-policy.scope.v1", account_namespace, account_id],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        try:
            with connections[self._using].cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", [key])
        except DatabaseError as error:
            raise AccountOwnerAssignmentUnavailable(
                "single-owner policy scope lock is unavailable"
            ) from error

    def now(self) -> datetime:
        """Return the timezone-aware application server timestamp."""

        self._ensure_postgresql()
        value = self._clock.now() if self._clock is not None else timezone.now()
        try:
            return _aware(value, "server clock")
        except (TypeError, ValueError) as error:
            raise AccountOwnerAssignmentUnavailable(
                "single-owner policy server clock is unavailable"
            ) from error

    def get_exact_current(
        self,
        *,
        policy_id: str,
        policy_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> SingleOwnerAuthorityPolicyV1 | None:
        """Return the exact current head, never falling back to an older row."""

        self._ensure_read_inputs(
            policy_id=policy_id,
            policy_version=policy_version,
            expected_content_hash=expected_content_hash,
            as_of=as_of,
        )
        records = self._restore_world()
        head = _head_for(
            records,
            policy_id=policy_id,
            as_of=as_of,
        )
        if head is None:
            return None
        if (
            head.policy_version != policy_version
            or head.content_hash != expected_content_hash
            or not head.is_current_at(as_of)
        ):
            return None
        return head

    def get_head(self, *, policy_id: str, as_of: datetime) -> SingleOwnerAuthorityPolicyV1 | None:
        """Return the unique knowable chain head at an aware cutoff."""

        self._ensure_read_inputs(policy_id=policy_id, as_of=as_of)
        return _head_for(self._restore_world(), policy_id=policy_id, as_of=as_of)

    def get_current_for_scope(
        self, *, account_namespace: str, account_id: str, as_of: datetime
    ) -> tuple[SingleOwnerAuthorityPolicyV1, ...]:
        """Return every current chain head for a scope, retaining owner collisions.

        The application must require a unique policy before checking its owner.
        Selecting by user here would hide conflicting active owner declarations.
        A revoked or expired head never falls back to a preceding active row.
        """
        self._ensure_postgresql()
        try:
            _token(account_namespace, "account_namespace")
            _token(account_id, "account_id")
            cutoff = _aware(as_of, "as_of")
        except (TypeError, ValueError) as error:
            raise AccountOwnerAssignmentUnavailable(
                "single-owner policy scope is invalid"
            ) from error
        records = self._restore_world()
        result: list[SingleOwnerAuthorityPolicyV1] = []
        for policy_id in sorted({policy.policy_id for _, policy in records}):
            head = _head_for(records, policy_id=policy_id, as_of=cutoff)
            if (
                head is not None
                and head.account_namespace == account_namespace
                and head.account_id == account_id
                and head.is_current_at(cutoff)
            ):
                result.append(head)
        return tuple(result)

    def append(
        self,
        *,
        policy: SingleOwnerAuthorityPolicyV1,
        expected_previous_content_hash: str | None,
    ) -> SingleOwnerAuthorityPolicyV1:
        """Append one root or compare-and-swap successor inside this UOW."""

        self._ensure_postgresql()
        if not self._active or _POLICY_UOW.get() is not self._token:
            raise AccountOwnerAssignmentUnavailable(
                "single-owner policy append requires private atomic UOW"
            )
        exact = _canonical(policy)
        if expected_previous_content_hash is not None:
            try:
                _digest(expected_previous_content_hash, "expected_previous_content_hash")
            except (TypeError, ValueError) as error:
                raise AccountOwnerAssignmentConflict(
                    "single-owner policy predecessor hash is invalid"
                ) from error
        server_now = self.now()
        if exact.observed_at > server_now:
            raise AccountOwnerAssignmentConflict(
                "single-owner policy observed_at cannot be in the future"
            )

        self.lock_scope(account_namespace=exact.account_namespace, account_id=exact.account_id)
        self._lock_policy_id(exact.policy_id)
        records = self._restore_world()
        replay = _find_replay(
            records,
            exact,
            expected_previous_content_hash=expected_previous_content_hash,
        )
        if replay is not None:
            return replay

        same_identity = tuple(
            (row, value)
            for row, value in records
            if (value.policy_id, value.policy_version) == (exact.policy_id, exact.policy_version)
        )
        if same_identity:
            raise AccountOwnerAssignmentConflict(
                "single-owner policy identity already contains another payload"
            )

        same_content = tuple(
            value for _, value in records if value.content_hash == exact.content_hash
        )
        if same_content:
            raise AccountOwnerAssignmentConflict(
                "single-owner policy content hash is already bound to another row"
            )

        predecessor_id: int | None
        if expected_previous_content_hash is None:
            if any(value.policy_id == exact.policy_id for _, value in records):
                raise AccountOwnerAssignmentConflict("single-owner policy chain already has a root")
            predecessor_id = None
        else:
            predecessor_matches = tuple(
                (row, value)
                for row, value in records
                if value.content_hash == expected_previous_content_hash
            )
            if len(predecessor_matches) != 1:
                if len(predecessor_matches) > 1:
                    raise AccountOwnerAssignmentCorruption(
                        "single-owner policy predecessor hash is duplicated"
                    )
                raise AccountOwnerAssignmentConflict(
                    "single-owner policy predecessor is not persisted"
                )
            predecessor_row, predecessor = predecessor_matches[0]
            if predecessor.policy_id != exact.policy_id:
                raise AccountOwnerAssignmentConflict(
                    "single-owner policy successor changed policy_id"
                )
            try:
                validate_single_owner_policy_successor(predecessor, exact)
            except (TypeError, ValueError) as error:
                raise AccountOwnerAssignmentConflict(
                    "single-owner policy successor violates its immutable scope"
                ) from error
            if any(
                row.expected_previous_content_hash == expected_previous_content_hash
                for row, _ in records
            ):
                raise AccountOwnerAssignmentConflict(
                    "single-owner policy predecessor is no longer the chain head"
                )
            predecessor_id = _predecessor_id(predecessor_row)
            if predecessor_id is None and predecessor_row.pk is None:
                raise AccountOwnerAssignmentCorruption(
                    "single-owner policy predecessor has no persisted identity"
                )
            predecessor_id = predecessor_row.pk

        persisted_at = server_now
        values = _model_values(
            exact,
            predecessor_id=predecessor_id,
            expected_previous_content_hash=expected_previous_content_hash,
            persisted_at=persisted_at,
        )
        model = SingleOwnerAuthorityPolicyV1Model(**values)
        # ForeignKey validation uses the instance state to select its read
        # alias.  Pin it before clean_fields so a successor never probes the
        # default database while this repository is bound to a dedicated PG
        # alias.
        model._state.db = self._using
        try:
            # Model.full_clean() performs uniqueness lookups on Django's
            # process-global connection.  The dedicated EVID-06 alias must
            # never touch the default database, so local field validation is
            # paired with PostgreSQL's constraints on the actual insert.
            model.full_clean(validate_unique=False, validate_constraints=False)
            with transaction.atomic(using=self._using):
                with _claim_single_owner_authority_policy_v1_insert(
                    token=self._token,
                    model_type=SingleOwnerAuthorityPolicyV1Model,
                    expected_values=values,
                ):
                    model.save(force_insert=True, using=self._using)
        except (IntegrityError, ValidationError) as error:
            after = self._restore_world()
            replay = _find_replay(
                after,
                exact,
                expected_previous_content_hash=expected_previous_content_hash,
            )
            if replay is not None:
                return replay
            raise AccountOwnerAssignmentConflict(
                "single-owner policy append conflicted without an exact replay"
            ) from error
        return exact

    def _ensure_postgresql(self) -> None:
        try:
            connection = connections[self._using]
            vendor = connection.vendor
        except (DatabaseError, KeyError) as error:
            raise AccountOwnerAssignmentUnavailable(
                "single-owner policy database alias is unavailable"
            ) from error
        if vendor != "postgresql":
            raise AccountOwnerAssignmentUnavailable(
                "single-owner policy ledger requires PostgreSQL"
            )

    def _ensure_read_inputs(self, **values: object) -> None:
        self._ensure_postgresql()
        try:
            _token(cast(str, values["policy_id"]), "policy_id")
            if "policy_version" in values:
                _token(cast(str, values["policy_version"]), "policy_version")
            if "expected_content_hash" in values:
                _digest(cast(str, values["expected_content_hash"]), "expected_content_hash")
            _aware(values["as_of"], "as_of")
        except (TypeError, ValueError) as error:
            raise AccountOwnerAssignmentUnavailable(
                "single-owner policy selector is invalid"
            ) from error

    def _lock_policy_id(self, policy_id: str) -> None:
        """Serialize roots and successors for one policy identity in PostgreSQL."""

        try:
            with connections[self._using].cursor() as cursor:
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    [policy_id],
                )
        except DatabaseError as error:
            raise AccountOwnerAssignmentUnavailable(
                "single-owner policy serialization lock is unavailable"
            ) from error

    def _restore_world(
        self,
    ) -> tuple[tuple[SingleOwnerAuthorityPolicyV1Model, SingleOwnerAuthorityPolicyV1], ...]:
        try:
            rows = tuple(
                SingleOwnerAuthorityPolicyV1Model._default_manager.using(self._using).order_by("pk")
            )
        except DatabaseError as error:
            raise AccountOwnerAssignmentUnavailable(
                "single-owner policy ledger cannot be read"
            ) from error
        records = tuple((row, _restore(row)) for row in rows)
        _validate_chain(records)
        return records


def _restore(
    row: SingleOwnerAuthorityPolicyV1Model,
) -> SingleOwnerAuthorityPolicyV1:
    """Decode and verify every stored policy and ledger envelope field."""

    try:
        value = decode_single_owner_authority_policy_v1(row.canonical_payload)
        predecessor_id = _predecessor_id(row)
        persisted_at = row.persisted_at
        _aware(persisted_at, "persisted_at")
        expected = _model_values(
            value,
            predecessor_id=predecessor_id,
            expected_previous_content_hash=row.expected_previous_content_hash,
            persisted_at=persisted_at,
        )
        for name, scalar in expected.items():
            actual = predecessor_id if name == "predecessor_id" else getattr(row, name)
            if actual != scalar:
                raise AccountOwnerAssignmentCorruption(
                    f"single-owner policy row scalar {name} is substituted"
                )
        if persisted_at < value.observed_at:
            raise AccountOwnerAssignmentCorruption(
                "single-owner policy row persisted_at precedes observed_at"
            )
    except AccountOwnerAssignmentCorruption:
        raise
    except (AttributeError, TypeError, ValueError, SingleOwnerAuthorityPolicyV1CodecError) as error:
        raise AccountOwnerAssignmentCorruption(
            "single-owner policy row payload or envelope is corrupt"
        ) from error
    return value


def _validate_chain(
    records: tuple[tuple[SingleOwnerAuthorityPolicyV1Model, SingleOwnerAuthorityPolicyV1], ...],
) -> None:
    """Validate roots, links, immutable scope, and connected successor chains."""

    by_pk: dict[int, tuple[SingleOwnerAuthorityPolicyV1Model, SingleOwnerAuthorityPolicyV1]] = {}
    by_content: dict[
        str, tuple[SingleOwnerAuthorityPolicyV1Model, SingleOwnerAuthorityPolicyV1]
    ] = {}
    by_identity: dict[
        tuple[str, str], tuple[SingleOwnerAuthorityPolicyV1Model, SingleOwnerAuthorityPolicyV1]
    ] = {}
    by_record_seal: dict[
        str, tuple[SingleOwnerAuthorityPolicyV1Model, SingleOwnerAuthorityPolicyV1]
    ] = {}
    by_policy: dict[
        str, list[tuple[SingleOwnerAuthorityPolicyV1Model, SingleOwnerAuthorityPolicyV1]]
    ] = {}
    try:
        for row, value in records:
            if row.pk is None:
                raise AccountOwnerAssignmentCorruption(
                    "single-owner policy row has no persisted primary key"
                )
            if row.pk in by_pk:
                raise AccountOwnerAssignmentCorruption("single-owner policy primary key repeats")
            if value.content_hash in by_content:
                raise AccountOwnerAssignmentCorruption("single-owner policy content hash repeats")
            identity = (value.policy_id, value.policy_version)
            if identity in by_identity:
                raise AccountOwnerAssignmentCorruption("single-owner policy identity repeats")
            if row.record_seal in by_record_seal:
                raise AccountOwnerAssignmentCorruption("single-owner policy record seal repeats")
            by_pk[row.pk] = (row, value)
            by_content[value.content_hash] = (row, value)
            by_identity[identity] = (row, value)
            by_record_seal[row.record_seal] = (row, value)
            by_policy.setdefault(value.policy_id, []).append((row, value))

        children_by_previous: dict[
            str, tuple[SingleOwnerAuthorityPolicyV1Model, SingleOwnerAuthorityPolicyV1]
        ] = {}
        for row, value in records:
            predecessor_id = _predecessor_id(row)
            previous_hash = row.expected_previous_content_hash
            if previous_hash is None:
                if predecessor_id is not None:
                    raise AccountOwnerAssignmentCorruption(
                        "single-owner policy root contains a predecessor id"
                    )
                continue
            if predecessor_id is None:
                raise AccountOwnerAssignmentCorruption(
                    "single-owner policy successor is missing its predecessor id"
                )
            predecessor = by_pk.get(predecessor_id)
            if predecessor is None:
                raise AccountOwnerAssignmentCorruption(
                    "single-owner policy predecessor row is missing"
                )
            predecessor_row, predecessor_value = predecessor
            del predecessor_row
            if predecessor_value.policy_id != value.policy_id:
                raise AccountOwnerAssignmentCorruption(
                    "single-owner policy predecessor crosses policy_id"
                )
            if predecessor_value.content_hash != previous_hash:
                raise AccountOwnerAssignmentCorruption(
                    "single-owner policy predecessor hash is substituted"
                )
            if previous_hash in children_by_previous:
                raise AccountOwnerAssignmentCorruption("single-owner policy chain forks")
            children_by_previous[previous_hash] = (row, value)

        for policy_id, chain in by_policy.items():
            roots = tuple(
                record for record in chain if record[0].expected_previous_content_hash is None
            )
            if len(roots) != 1:
                raise AccountOwnerAssignmentCorruption(
                    f"single-owner policy {policy_id} must have exactly one root"
                )
            root = roots[0]
            visited: set[int] = set()
            current = root
            while True:
                row, value = current
                if row.pk is None or row.pk in visited:
                    raise AccountOwnerAssignmentCorruption("single-owner policy chain cycles")
                visited.add(row.pk)
                child = children_by_previous.get(value.content_hash)
                if child is None:
                    break
                try:
                    validate_single_owner_policy_successor(value, child[1])
                except (TypeError, ValueError) as error:
                    raise AccountOwnerAssignmentCorruption(
                        "single-owner policy successor violates its immutable scope"
                    ) from error
                current = child
            if len(visited) != len(chain):
                raise AccountOwnerAssignmentCorruption(
                    f"single-owner policy {policy_id} chain is disconnected"
                )
    except AccountOwnerAssignmentCorruption:
        raise
    except (AttributeError, TypeError, ValueError) as error:
        raise AccountOwnerAssignmentCorruption("single-owner policy chain is corrupt") from error


def _head_for(
    records: tuple[tuple[SingleOwnerAuthorityPolicyV1Model, SingleOwnerAuthorityPolicyV1], ...],
    *,
    policy_id: str,
    as_of: datetime,
) -> SingleOwnerAuthorityPolicyV1 | None:
    known = tuple(
        (row, value)
        for row, value in records
        if value.policy_id == policy_id and row.persisted_at <= as_of and value.observed_at <= as_of
    )
    if not known:
        return None
    children = {
        row.expected_previous_content_hash
        for row, _ in known
        if row.expected_previous_content_hash is not None
    }
    heads = tuple(value for _, value in known if value.content_hash not in children)
    if len(heads) != 1:
        raise AccountOwnerAssignmentCorruption(
            "single-owner policy chain has no unique point-in-time head"
        )
    return heads[0]


def _find_replay(
    records: tuple[tuple[SingleOwnerAuthorityPolicyV1Model, SingleOwnerAuthorityPolicyV1], ...],
    expected: SingleOwnerAuthorityPolicyV1,
    *,
    expected_previous_content_hash: str | None,
) -> SingleOwnerAuthorityPolicyV1 | None:
    matches = tuple(
        value
        for row, value in records
        if value == expected
        and row.expected_previous_content_hash == expected_previous_content_hash
    )
    if len(matches) > 1:
        raise AccountOwnerAssignmentCorruption("single-owner policy exact replay is duplicated")
    return matches[0] if matches else None


def _canonical(value: SingleOwnerAuthorityPolicyV1) -> SingleOwnerAuthorityPolicyV1:
    if type(value) is not SingleOwnerAuthorityPolicyV1:
        raise AccountOwnerAssignmentCorruption(
            "single-owner policy must have its exact Domain type"
        )
    try:
        return decode_single_owner_authority_policy_v1(
            encode_single_owner_authority_policy_v1(value)
        )
    except (SingleOwnerAuthorityPolicyV1CodecError, TypeError, ValueError) as error:
        raise AccountOwnerAssignmentCorruption(
            "single-owner policy cannot be canonicalized"
        ) from error


def _model_values(
    value: SingleOwnerAuthorityPolicyV1,
    *,
    predecessor_id: int | None,
    expected_previous_content_hash: str | None,
    persisted_at: datetime,
) -> dict[str, object]:
    payload = encode_single_owner_authority_policy_v1(value)
    return {
        "policy_id": value.policy_id,
        "policy_version": value.policy_version,
        "tenant_id": value.tenant_id,
        "owner_id": value.owner_id,
        "account_namespace": value.account_namespace,
        "account_id": value.account_id,
        "owner_user_id": value.owner_user_id,
        "authorization_content_hash": value.authorization_content_hash,
        "observed_at": value.observed_at,
        "valid_from": value.valid_from,
        "valid_until": value.valid_until,
        "status": value.status,
        "schema": value.schema,
        "artifact_type": value.artifact_type,
        "mode": value.mode,
        "identity_hash": value.identity_hash,
        "content_hash": value.content_hash,
        "canonical_payload": payload,
        "expected_previous_content_hash": expected_previous_content_hash,
        "predecessor_id": predecessor_id,
        "record_seal": _record_seal(
            payload,
            expected_previous_content_hash,
            predecessor_id,
            persisted_at,
        ),
        "persisted_at": persisted_at,
    }


def _record_seal(
    payload: dict[str, object],
    previous_hash: str | None,
    predecessor_id: int | None,
    persisted_at: datetime,
) -> str:
    """Seal policy, CAS predecessor, FK identity, and persistence timestamp."""

    encoded = json.dumps(
        {
            "domain": _RECORD_SEAL_DOMAIN,
            "expected_previous_content_hash": previous_hash,
            "persisted_at": _utc_text(persisted_at),
            "predecessor_id": predecessor_id,
            "policy": payload,
        },
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _utc_text(value: datetime) -> str:
    """Serialize a stored aware timestamp canonically for the record seal."""

    _aware(value, "persisted_at")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _predecessor_id(row: SingleOwnerAuthorityPolicyV1Model) -> int | None:
    """Read Django's generated foreign-key scalar without following a relation."""

    return cast(int | None, row.__dict__.get("predecessor_id"))


def _token(value: object, name: str) -> None:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{name} must be a bounded canonical token")


def _digest(value: object, name: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


def _aware(value: object, name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


__all__ = [
    "DjangoSingleOwnerAuthorityPolicyV1Repository",
    "SingleOwnerAuthorityPolicyV1Clock",
]
