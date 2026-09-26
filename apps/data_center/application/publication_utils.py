"""Shared deterministic helpers for canonical publication writers."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from datetime import datetime
from typing import Final
from uuid import NAMESPACE_URL, uuid5

from apps.data_center.domain.control_plane import (
    PublicationFactReference,
    PublicationMember,
    PublicationScopeBlock,
)

_POLICY_IDENTITY_RE: Final[re.Pattern[str]] = re.compile(r"p2:[^:\s]{1,40}:[0-9a-f]{64}")


def publication_hash(
    references: Sequence[PublicationFactReference],
    *,
    policy_identity: str | None = None,
    scope_blocks: Sequence[PublicationScopeBlock] = (),
) -> str:
    """Return a legacy or policy-bound digest for an ordered member snapshot.

    ``policy_identity=None`` deliberately preserves the exact legacy payload
    and byte encoding.  A versioned identity selects the self-describing v2
    envelope and binds all frozen evidence metadata to the digest.
    """

    if policy_identity is None:
        if scope_blocks:
            raise ValueError("legacy publication hashes cannot contain scope blocks")
        payload: object = [_legacy_reference_payload(reference) for reference in references]
    else:
        if _POLICY_IDENTITY_RE.fullmatch(policy_identity) is None:
            raise ValueError("policy_identity must be p2:<version>:<sha256>")
        # publication_id is derived from this digest, so binding it here would be circular.
        normalized_blocks = sorted(
            (
                {key: value for key, value in block.to_dict().items() if key != "publication_id"}
                for block in scope_blocks
            ),
            key=lambda item: (
                str(item["asset_code"]),
                str(item["reason_code"]),
                str(item.get("target_trade_date") or ""),
                str(item.get("source") or ""),
                str(item.get("publication_run_id") or ""),
                str(item.get("policy_version") or ""),
            ),
        )
        versioned_payload: dict[str, object] = {
            "encoding": (
                "publication-evidence-v3" if normalized_blocks else "publication-evidence-v2"
            ),
            "policy_identity": policy_identity,
            "members": [_versioned_reference_payload(reference) for reference in references],
        }
        if normalized_blocks:
            versioned_payload["scope_blocks"] = normalized_blocks
        payload = versioned_payload
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def current_publication_id_for_hash(
    dataset_key: str,
    publication_key: str,
    content_hash: str,
) -> str:
    """Return the deterministic ID bound to one current-publication digest."""

    for field_name, value in (
        ("dataset_key", dataset_key),
        ("publication_key", publication_key),
        ("content_hash", content_hash),
    ):
        if not value.strip():
            raise ValueError(f"{field_name} cannot be empty")
    return str(
        uuid5(
            NAMESPACE_URL,
            f"agomtradepro:{dataset_key}:{publication_key}:{content_hash}",
        )
    )


def member_reference(member: PublicationMember) -> PublicationFactReference:
    """Restore one typed hash input from a frozen publication member."""

    if member.observed_at is None:
        raise ValueError("published member requires observed_at")
    return PublicationFactReference(
        natural_key=member.natural_key,
        source=member.source,
        source_record_id=member.source_record_id,
        fact_table=member.fact_table,
        fact_pk=member.fact_pk,
        observed_at=member.observed_at,
        raw_payload_hash=member.raw_payload_hash,
        quality_status=member.quality_status,
        revision_number=member.revision_number,
        available_at=member.available_at,
        fetched_at=member.fetched_at,
        source_published_at=member.source_published_at,
        raw_payload_scope=member.raw_payload_scope,
        fact_content_hash=member.fact_content_hash,
    )


def publication_member_from_reference(
    reference: PublicationFactReference,
    *,
    member_id: str,
    publication_id: str,
    dataset_key: str,
) -> PublicationMember:
    """Build one immutable member while preserving all reference evidence."""

    return PublicationMember(
        member_id=member_id,
        publication_id=publication_id,
        dataset_key=dataset_key,
        natural_key=reference.natural_key,
        source=reference.source,
        source_record_id=reference.source_record_id,
        fact_table=reference.fact_table,
        fact_pk=reference.fact_pk,
        observed_at=reference.observed_at,
        raw_payload_hash=reference.raw_payload_hash,
        quality_status=reference.quality_status,
        revision_number=reference.revision_number,
        available_at=reference.available_at,
        fetched_at=reference.fetched_at,
        source_published_at=reference.source_published_at,
        raw_payload_scope=reference.raw_payload_scope,
        fact_content_hash=reference.fact_content_hash,
    )


def _legacy_reference_payload(reference: PublicationFactReference) -> dict[str, object]:
    """Return the unchanged v1 hash member payload."""

    return {
        "natural_key": reference.natural_key,
        "source": reference.source,
        "fact_table": reference.fact_table,
        "fact_pk": reference.fact_pk,
        "observed_at": reference.observed_at.isoformat(),
        "raw_payload_hash": reference.raw_payload_hash,
        "quality_status": reference.quality_status,
        "revision_number": reference.revision_number,
    }


def _versioned_reference_payload(reference: PublicationFactReference) -> dict[str, object]:
    """Return every frozen identity and provenance field for v2."""

    return {
        **_legacy_reference_payload(reference),
        "source_record_id": reference.source_record_id,
        "available_at": _timestamp(reference.available_at),
        "fetched_at": _timestamp(reference.fetched_at),
        "source_published_at": _timestamp(reference.source_published_at),
        "raw_payload_scope": reference.raw_payload_scope,
        "fact_content_hash": reference.fact_content_hash,
    }


def _timestamp(value: datetime | None) -> str | None:
    """Return one optional timestamp in the stable JSON representation."""

    return value.isoformat() if value is not None else None


__all__ = [
    "current_publication_id_for_hash",
    "member_reference",
    "publication_hash",
    "publication_member_from_reference",
]
