"""Private persistence helpers for the owner/tenant authority v3 repository.

The public repository keeps transaction and lock orchestration in its main
module.  This module contains the pure canonicalization, restore, seal, and
foreign-key helpers used by that orchestration so the repository stays within
the project's per-file governance limit.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import NoReturn, cast

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
    OwnerTenantAuthorityV3Unavailable,
    PersistedOwnerTenantAuthorityV3,
    PersistedOwnerTenantAuthorityV3Revocation,
)
from apps.account.domain.account_owner_assignment_actor_authority_source_v3 import (
    AccountOwnerAssignmentActorAuthoritySourceV3,
)
from apps.account.domain.owner_tenant_authority_v3 import (
    validate_owner_tenant_authority_v3_root,
    validate_owner_tenant_authority_v3_successor,
)
from apps.account.infrastructure.account_owner_assignment_actor_authority_source_v3_models import (
    AccountOwnerAssignmentActorAuthoritySourceV3Model,
)
from apps.account.infrastructure.account_owner_assignment_v5_models import (
    AccountOwnerAssignmentEvidenceV5Model,
)
from apps.account.infrastructure.owner_tenant_authority_v3_codec import (
    OwnerTenantAuthorityV3CodecError,
)
from apps.account.infrastructure.owner_tenant_authority_v3_models import (
    OwnerTenantAuthorityV3Model,
    OwnerTenantAuthorityV3RevocationModel,
)
from apps.account.infrastructure.owner_tenant_authority_v3_record_codec import (
    OwnerTenantAuthorityV3RecordCodecError,
    decode_owner_tenant_authority_v3_record,
    decode_owner_tenant_authority_v3_revocation_record,
    encode_owner_tenant_authority_v3_record,
    encode_owner_tenant_authority_v3_revocation_record,
)
from apps.account.infrastructure.single_owner_authority_policy_v1_models import (
    SingleOwnerAuthorityPolicyV1Model,
)

_ROOT_FK_NAMES = frozenset({"assignment_id", "policy_id", "actor_source_id", "predecessor_id"})
_REVOCATION_FK_NAMES = frozenset({"authority_id", "actor_source_id"})


def _root_record(value: object) -> PersistedOwnerTenantAuthorityV3:
    """Canonicalize one exact root record before persistence or comparison."""

    if type(value) is not PersistedOwnerTenantAuthorityV3:
        raise OwnerTenantAuthorityV3Corruption(
            "owner tenant authority v3 root record type substitution"
        )
    try:
        return decode_owner_tenant_authority_v3_record(
            encode_owner_tenant_authority_v3_record(value)
        )
    except (OwnerTenantAuthorityV3RecordCodecError, TypeError, ValueError) as error:
        raise OwnerTenantAuthorityV3Corruption(
            "owner tenant authority v3 root record is corrupt"
        ) from error


def _revocation_record(value: object) -> PersistedOwnerTenantAuthorityV3Revocation:
    """Canonicalize one exact revocation record before persistence or comparison."""

    if type(value) is not PersistedOwnerTenantAuthorityV3Revocation:
        raise OwnerTenantAuthorityV3Corruption(
            "owner tenant authority v3 revocation record type substitution"
        )
    try:
        return decode_owner_tenant_authority_v3_revocation_record(
            encode_owner_tenant_authority_v3_revocation_record(value)
        )
    except (OwnerTenantAuthorityV3RecordCodecError, TypeError, ValueError) as error:
        raise OwnerTenantAuthorityV3Corruption(
            "owner tenant authority v3 revocation record is corrupt"
        ) from error


def _restore_root(row: OwnerTenantAuthorityV3Model) -> PersistedOwnerTenantAuthorityV3:
    """Decode a root and verify every denormalized field and ledger seal."""

    try:
        record = decode_owner_tenant_authority_v3_record(row.canonical_payload)
        values = _root_values(
            record,
            _fk(row, "assignment_id"),
            _fk(row, "policy_id"),
            _fk(row, "actor_source_id"),
            _fk(row, "predecessor_id"),
            payload=cast(dict[str, object], row.canonical_payload),
        )
        _verify_row(row, values, _ROOT_FK_NAMES)
        return record
    except OwnerTenantAuthorityV3Corruption:
        raise
    except (
        OwnerTenantAuthorityV3CodecError,
        OwnerTenantAuthorityV3RecordCodecError,
        AttributeError,
        TypeError,
        ValueError,
    ) as error:
        raise OwnerTenantAuthorityV3Corruption(
            "owner tenant authority v3 root payload or seal is corrupt"
        ) from error


def _restore_revocation(
    row: OwnerTenantAuthorityV3RevocationModel,
) -> PersistedOwnerTenantAuthorityV3Revocation:
    """Decode a revocation and verify every denormalized field and seal."""

    try:
        record = decode_owner_tenant_authority_v3_revocation_record(row.canonical_payload)
        values = _revocation_values(
            record,
            _fk(row, "authority_id"),
            _fk(row, "actor_source_id"),
            payload=cast(dict[str, object], row.canonical_payload),
        )
        _verify_row(row, values, _REVOCATION_FK_NAMES)
        return record
    except OwnerTenantAuthorityV3Corruption:
        raise
    except (
        OwnerTenantAuthorityV3CodecError,
        OwnerTenantAuthorityV3RecordCodecError,
        AttributeError,
        TypeError,
        ValueError,
    ) as error:
        raise OwnerTenantAuthorityV3Corruption(
            "owner tenant authority v3 revocation payload or seal is corrupt"
        ) from error


def _root_values(
    record: PersistedOwnerTenantAuthorityV3,
    assignment_pk: int | None,
    policy_pk: int | None,
    actor_pk: int | None,
    predecessor_pk: int | None,
    *,
    payload: dict[str, object] | None = None,
) -> dict[str, object]:
    """Build all authority columns and the parent-bound ledger seal."""

    authority = record.authority
    if payload is None:
        payload = encode_owner_tenant_authority_v3_record(record)
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
        "supersedes_content_hash": authority.supersedes_content_hash,
        "predecessor_id": predecessor_pk,
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
                "domain": "account.owner-tenant-authority.v3/ledger",
                "record": payload,
                "assignment_pk": assignment_pk,
                "policy_pk": policy_pk,
                "actor_source_pk": actor_pk,
                "predecessor_pk": predecessor_pk,
                "persisted_at": _time(authority.recorded_at),
            }
        ),
    }


def _revocation_values(
    record: PersistedOwnerTenantAuthorityV3Revocation,
    authority_pk: int | None,
    actor_pk: int | None,
    *,
    payload: dict[str, object] | None = None,
) -> dict[str, object]:
    """Build all revocation denormalized columns and its parent-bound seal."""

    revocation = record.revocation
    if payload is None:
        payload = encode_owner_tenant_authority_v3_revocation_record(record)
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
                "domain": "account.owner-tenant-authority.v3/revocation-ledger",
                "record": payload,
                "authority_pk": authority_pk,
                "actor_source_pk": actor_pk,
                "persisted_at": _time(revocation.recorded_at),
            }
        ),
    }


def _verify_row(
    row: OwnerTenantAuthorityV3Model | OwnerTenantAuthorityV3RevocationModel,
    expected: dict[str, object],
    fk_names: frozenset[str],
) -> None:
    """Compare every stored model column with the canonical expected value."""

    for name, expected_value in expected.items():
        actual = _fk(row, name) if name in fk_names else getattr(row, name)
        if actual != expected_value:
            raise OwnerTenantAuthorityV3Corruption(
                f"owner tenant authority v3 stored field {name} is substituted"
            )


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


def _fk(
    row: (
        OwnerTenantAuthorityV3Model
        | OwnerTenantAuthorityV3RevocationModel
        | AccountOwnerAssignmentEvidenceV5Model
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
        raise OwnerTenantAuthorityV3Corruption(f"owner tenant authority v3 FK {name} is invalid")
    return value


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
