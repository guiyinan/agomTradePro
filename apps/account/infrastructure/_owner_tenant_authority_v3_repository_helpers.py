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
from typing import cast

from apps.account.application.owner_tenant_authority_v3_contracts import (
    OwnerTenantAuthorityV3Corruption,
    PersistedOwnerTenantAuthorityV3,
    PersistedOwnerTenantAuthorityV3Revocation,
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
