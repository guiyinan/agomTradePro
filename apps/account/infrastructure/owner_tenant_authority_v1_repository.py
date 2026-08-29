"""Closed-world Django repository for owner/tenant authority v1."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Protocol, cast

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.account.application.owner_tenant_authority_v1 import (
    OwnerTenantAuthorityV1Conflict,
    OwnerTenantAuthorityV1Corruption,
    OwnerTenantAuthorityV1Unavailable,
)
from apps.account.domain.owner_tenant_authority_v1 import (
    OwnerTenantAuthorityV1,
    validate_owner_tenant_authority_v1_root,
    validate_owner_tenant_authority_v1_successor,
)
from apps.account.infrastructure.owner_tenant_authority_v1_codec import (
    OwnerTenantAuthorityV1CodecError,
    decode_owner_tenant_authority_v1,
    encode_owner_tenant_authority_v1,
)
from apps.account.infrastructure.owner_tenant_authority_v1_models import (
    OwnerTenantAuthorityV1Model,
    _activate_owner_tenant_authority_v1_uow,
    _claim_owner_tenant_authority_v1_insert,
)


class OwnerTenantAuthorityV1Clock(Protocol):
    """Authoritative repository clock."""

    def now(self) -> datetime:
        """Return a timezone-aware server timestamp."""


class DjangoOwnerTenantAuthorityV1Clock:
    """Django timezone-backed authority clock."""

    def now(self) -> datetime:
        """Return the current timezone-aware server timestamp."""

        return timezone.now()


class DjangoOwnerTenantAuthorityV1Repository:
    """Append roots/successors and restore the complete immutable world."""

    __slots__ = ("_clock", "_token", "_using")

    def __init__(
        self,
        *,
        using: str = "default",
        clock: OwnerTenantAuthorityV1Clock | None = None,
    ) -> None:
        if type(using) is not str or not using or using.strip() != using:
            raise ValueError("owner/tenant authority database alias is invalid")
        self._using = using
        self._clock = clock or DjangoOwnerTenantAuthorityV1Clock()
        self._token = object()

    @property
    def unit_of_work_key(self) -> str:
        """Return the database alias identity used by this repository."""

        return f"django:{self._using}"

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Open one repository-owned transaction and private insert UOW."""

        with (
            transaction.atomic(using=self._using),
            _activate_owner_tenant_authority_v1_uow(self._token),
        ):
            yield

    def now(self) -> datetime:
        """Return the validated authoritative server clock."""

        try:
            value = self._clock.now()
            _aware(value, "server clock")
            return value
        except (TypeError, ValueError) as error:
            raise OwnerTenantAuthorityV1Unavailable(
                "owner/tenant authority server clock is unavailable"
            ) from error

    def get_winner(
        self, *, authority_id: str, authority_version: str, as_of: datetime
    ) -> OwnerTenantAuthorityV1 | None:
        """Return one immutable first winner at a historical cutoff."""

        _token(authority_id, "authority_id")
        _token(authority_version, "authority_version")
        self._cutoff(as_of)
        matches = tuple(
            value
            for value in self._restore_world()
            if value.authority_id == authority_id and value.authority_version == authority_version
        )
        if len(matches) > 1:
            raise OwnerTenantAuthorityV1Corruption("authority identity has multiple winners")
        return matches[0] if matches and matches[0].recorded_at <= as_of else None

    def get_head(self, *, authority_id: str, as_of: datetime) -> OwnerTenantAuthorityV1 | None:
        """Return the final logical head without filtering inactive rows."""

        _token(authority_id, "authority_id")
        self._cutoff(as_of)
        known = tuple(
            value
            for value in self._restore_world()
            if value.authority_id == authority_id and value.recorded_at <= as_of
        )
        if not known:
            return None
        heads = tuple(
            value
            for value in known
            if not any(child.supersedes_content_hash == value.content_hash for child in known)
        )
        if len(heads) != 1:
            raise OwnerTenantAuthorityV1Corruption("authority chain has no unique PIT head")
        return heads[0]

    def get_exact(
        self,
        *,
        authority_id: str,
        authority_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> OwnerTenantAuthorityV1 | None:
        """Return one exact knowable authority row."""

        _token(authority_id, "authority_id")
        _token(authority_version, "authority_version")
        _digest(expected_content_hash, "expected_content_hash")
        self._cutoff(as_of)
        matches = tuple(
            value
            for value in self._restore_world()
            if (
                value.authority_id,
                value.authority_version,
                value.content_hash,
            )
            == (authority_id, authority_version, expected_content_hash)
        )
        if len(matches) > 1:
            raise OwnerTenantAuthorityV1Corruption("authority exact selector has multiple matches")
        return matches[0] if matches and matches[0].recorded_at <= as_of else None

    def append(
        self,
        authority: OwnerTenantAuthorityV1,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> OwnerTenantAuthorityV1:
        """Append a root or one exact compare-and-swap successor."""

        exact = _canonical(authority)
        _aware(recorded_at, "recorded_at")
        if exact.recorded_at != recorded_at or recorded_at > self.now():
            raise OwnerTenantAuthorityV1Conflict("authority recorded_at is invalid")
        records = self._restore_world()
        rows = tuple(OwnerTenantAuthorityV1Model._default_manager.using(self._using).order_by("pk"))
        if len(records) != len(rows):
            raise OwnerTenantAuthorityV1Corruption("authority restore is unstable")
        by_hash = {
            value.content_hash: (value, row) for value, row in zip(records, rows, strict=True)
        }
        if expected_predecessor_hash is None:
            validate_owner_tenant_authority_v1_root(exact)
            predecessor_id = None
            if exact.supersedes_content_hash is not None:
                raise OwnerTenantAuthorityV1Conflict("authority root cannot declare a predecessor")
        else:
            _digest(expected_predecessor_hash, "expected_predecessor_hash")
            persisted = by_hash.get(expected_predecessor_hash)
            if persisted is None:
                raise OwnerTenantAuthorityV1Conflict("authority predecessor is not persisted")
            predecessor, predecessor_row = persisted
            validate_owner_tenant_authority_v1_successor(predecessor, exact)
            predecessor_id = predecessor_row.pk
        candidates = tuple(
            (value, row)
            for value, row in zip(records, rows, strict=True)
            if value.authority_id == exact.authority_id
            and (
                value.authority_version == exact.authority_version
                or value.content_hash == exact.content_hash
                or (
                    exact.supersedes_content_hash is not None
                    and value.supersedes_content_hash == exact.supersedes_content_hash
                )
                or (exact.supersedes_content_hash is None and value.supersedes_content_hash is None)
            )
        )
        if candidates:
            return _replay_or_conflict(candidates, exact, predecessor_id)
        values = _model_values(exact, predecessor_id=predecessor_id)
        model = OwnerTenantAuthorityV1Model(**values)
        try:
            model.full_clean()
            with transaction.atomic(using=self._using):
                with _claim_owner_tenant_authority_v1_insert(
                    token=self._token,
                    model_type=OwnerTenantAuthorityV1Model,
                    expected_values=values,
                ):
                    model.save(force_insert=True, using=self._using)
        except (IntegrityError, ValidationError, ValueError) as error:
            after_records = self._restore_world()
            after_rows = tuple(
                OwnerTenantAuthorityV1Model._default_manager.using(self._using).order_by("pk")
            )
            after = tuple(
                (value, row)
                for value, row in zip(after_records, after_rows, strict=True)
                if value.authority_id == exact.authority_id
                and (
                    value.authority_version == exact.authority_version
                    or value.content_hash == exact.content_hash
                    or value.supersedes_content_hash == exact.supersedes_content_hash
                )
            )
            if after:
                return _replay_or_conflict(after, exact, predecessor_id)
            raise OwnerTenantAuthorityV1Conflict(
                "authority append conflicted without an exact winner"
            ) from error
        return exact

    def _cutoff(self, value: datetime) -> None:
        _aware(value, "as_of")
        if value > self.now():
            raise OwnerTenantAuthorityV1Unavailable("future authority cutoff is forbidden")

    def _restore_world(self) -> tuple[OwnerTenantAuthorityV1, ...]:
        rows = tuple(OwnerTenantAuthorityV1Model._default_manager.using(self._using).order_by("pk"))
        values = tuple(_restore(row) for row in rows)
        by_id: dict[str, list[OwnerTenantAuthorityV1]] = {}
        for value in values:
            by_id.setdefault(value.authority_id, []).append(value)
        for chain in by_id.values():
            _validate_chain(tuple(chain))
        return values


def _restore(row: OwnerTenantAuthorityV1Model) -> OwnerTenantAuthorityV1:
    try:
        value = decode_owner_tenant_authority_v1(row.canonical_payload)
    except OwnerTenantAuthorityV1CodecError as error:
        raise OwnerTenantAuthorityV1Corruption("authority row payload is corrupt") from error
    expected = _model_values(value, predecessor_id=_predecessor_id(row))
    for name, scalar in expected.items():
        if getattr(row, name) != scalar:
            raise OwnerTenantAuthorityV1Corruption(f"authority row scalar {name} is substituted")
    return value


def _validate_chain(chain: tuple[OwnerTenantAuthorityV1, ...]) -> None:
    roots = tuple(value for value in chain if value.supersedes_content_hash is None)
    if len(roots) != 1:
        raise OwnerTenantAuthorityV1Corruption("authority chain must have one root")
    try:
        validate_owner_tenant_authority_v1_root(roots[0])
        visited = {roots[0].content_hash}
        head = roots[0]
        while True:
            children = tuple(
                value for value in chain if value.supersedes_content_hash == head.content_hash
            )
            if not children:
                break
            if len(children) != 1:
                raise OwnerTenantAuthorityV1Corruption("authority chain forks")
            child = children[0]
            validate_owner_tenant_authority_v1_successor(head, child)
            if child.content_hash in visited:
                raise OwnerTenantAuthorityV1Corruption("authority chain cycles")
            visited.add(child.content_hash)
            head = child
        if len(visited) != len(chain):
            raise OwnerTenantAuthorityV1Corruption("authority chain is disconnected")
    except (TypeError, ValueError) as error:
        if isinstance(error, OwnerTenantAuthorityV1Corruption):
            raise
        raise OwnerTenantAuthorityV1Corruption("authority chain is invalid") from error


def _canonical(value: OwnerTenantAuthorityV1) -> OwnerTenantAuthorityV1:
    if type(value) is not OwnerTenantAuthorityV1:
        raise TypeError("authority must be an exact OwnerTenantAuthorityV1")
    try:
        return decode_owner_tenant_authority_v1(encode_owner_tenant_authority_v1(value))
    except OwnerTenantAuthorityV1CodecError as error:
        raise OwnerTenantAuthorityV1Corruption("authority cannot be canonicalized") from error


def _model_values(
    value: OwnerTenantAuthorityV1, *, predecessor_id: int | None
) -> dict[str, object]:
    approver = value.approved_by
    return {
        "authority_id": value.authority_id,
        "authority_version": value.authority_version,
        "tenant_id": value.tenant_id,
        "owner_id": value.owner_id,
        "account_namespace": value.account_namespace,
        "account_id": value.account_id,
        "actor_id": value.actor_id,
        "actor_user_id": value.actor_user_id,
        "assignment_evidence_id": value.assignment_evidence_id,
        "assignment_evidence_version": value.assignment_evidence_version,
        "assignment_evidence_content_hash": value.assignment_evidence_content_hash,
        "status": value.status,
        "approved_actor_id": approver.actor_id,
        "approved_user_id": approver.user_id,
        "approved_role": approver.role,
        "approved_kind": approver.kind,
        "approved_is_staff": approver.is_staff,
        "approved_at": value.approved_at,
        "recorded_at": value.recorded_at,
        "valid_until": value.valid_until,
        "supersedes_content_hash": value.supersedes_content_hash,
        "predecessor_id": predecessor_id,
        "identity_hash": value.identity_hash,
        "content_hash": value.content_hash,
        "authority_owner": value.owner,
        "authority_artifact_type": value.artifact_type,
        "authority_schema": value.schema,
        "permission": value.permission,
        "canonical_payload": value.to_payload(),
        "persisted_at": value.recorded_at,
    }


def _replay_or_conflict(
    candidates: tuple[tuple[OwnerTenantAuthorityV1, OwnerTenantAuthorityV1Model], ...],
    expected: OwnerTenantAuthorityV1,
    predecessor_id: int | None,
) -> OwnerTenantAuthorityV1:
    exact = tuple(
        value
        for value, row in candidates
        if value == expected and _predecessor_id(row) == predecessor_id
    )
    if len(exact) == 1:
        return exact[0]
    raise OwnerTenantAuthorityV1Conflict("authority immutable winner differs")


def _predecessor_id(row: OwnerTenantAuthorityV1Model) -> int | None:
    """Read Django's generated foreign-key scalar at the ORM boundary."""

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
    "DjangoOwnerTenantAuthorityV1Repository",
    "DjangoOwnerTenantAuthorityV1Clock",
    "OwnerTenantAuthorityV1Clock",
]
