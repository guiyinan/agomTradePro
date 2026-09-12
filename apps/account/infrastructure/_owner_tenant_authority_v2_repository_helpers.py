"""Private pure persistence helpers for the owner/tenant authority v2 repository.

The repository module owns transaction and lock orchestration.  This module
keeps canonical record handling, denormalized seals, and closed-world checks
at a private infrastructure boundary so those responsibilities can evolve
without enlarging the public repository surface.
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
from apps.account.application.owner_tenant_authority_v2_contracts import (
    OwnerTenantAuthorityV2Conflict,
    OwnerTenantAuthorityV2Corruption,
    OwnerTenantAuthorityV2Unavailable,
    PersistedOwnerTenantAuthorityV2,
    PersistedOwnerTenantAuthorityV2Revocation,
)
from apps.account.domain.account_owner_assignment_actor_authority_source_v3 import (
    AccountOwnerAssignmentActorAuthoritySourceV3,
)
from apps.account.domain.owner_tenant_authority_v2 import (
    validate_owner_tenant_authority_v2_root,
)
from apps.account.infrastructure.account_owner_assignment_actor_authority_source_v3_models import (
    AccountOwnerAssignmentActorAuthoritySourceV3Model,
)
from apps.account.infrastructure.account_owner_assignment_evidence_v4_models import (
    AccountOwnerAssignmentEvidenceV4Model,
)
from apps.account.infrastructure.owner_tenant_authority_v2_codec import (
    OwnerTenantAuthorityV2CodecError,
)
from apps.account.infrastructure.owner_tenant_authority_v2_models import (
    OwnerTenantAuthorityV2Model,
    OwnerTenantAuthorityV2RevocationModel,
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

_ROOT_FK_NAMES = frozenset({"assignment_id", "policy_id", "actor_source_id"})
_REVOCATION_FK_NAMES = frozenset({"authority_id", "actor_source_id"})


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
