"""Immutable candidate-level manifests for multi-batch RawAudit evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from uuid import UUID, uuid4

MANIFEST_VERSION = "1"
RAW_AUDIT_REFERENCE_VERSION = "1"
_RAW_AUDIT_SOURCE_TYPE_ALPHABET = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_.-")
_CURRENT_MARKET_DATASET_CAPABILITIES: Mapping[str, str] = MappingProxyType(
    {
        "equity.quote.snapshot": "realtime_quote",
        "equity.price.bar": "historical_price",
        "equity.valuation.fact": "valuation",
    }
)
CURRENT_MARKET_PUBLICATION_DATASETS: frozenset[str] = frozenset(
    _CURRENT_MARKET_DATASET_CAPABILITIES
)


def canonical_capability_for_publication_dataset(dataset_key: str) -> str | None:
    """Return the canonical provider capability required by a publication dataset."""

    return _CURRENT_MARKET_DATASET_CAPABILITIES.get(dataset_key)


def requires_group_publication_activation(dataset_key: str) -> bool:
    """Return whether this current market dataset must activate as one group."""

    return dataset_key in _CURRENT_MARKET_DATASET_CAPABILITIES


class CandidateRawAuditManifestError(ValueError):
    """Raised when candidate RawAudit lineage is incomplete or inconsistent."""


def validate_raw_audit_source_type(value: str) -> str:
    """Require a canonical, bounded, single-line RawAudit source-type token."""

    if (
        type(value) is not str
        or not value
        or len(value) > 50
        or not value.isascii()
        or any(character not in _RAW_AUDIT_SOURCE_TYPE_ALPHABET for character in value)
    ):
        raise CandidateRawAuditManifestError(
            "RawAudit source_type must be a canonical token of at most 50 characters"
        )
    return value


@dataclass(frozen=True, slots=True)
class CandidateRawAuditReference:
    """Exact immutable reference to one persisted RawAudit row."""

    raw_audit_id: str
    version: str
    content_hash: str
    provider_name: str
    capability: str
    run_id: str
    ingested_run_id: str

    def __post_init__(self) -> None:
        """Reject unbound, non-canonical, or unhashed raw-audit evidence."""

        if (
            not isinstance(self.raw_audit_id, str)
            or not self.raw_audit_id.isascii()
            or not self.raw_audit_id.isdecimal()
            or int(self.raw_audit_id) <= 0
            or str(int(self.raw_audit_id)) != self.raw_audit_id
        ):
            raise CandidateRawAuditManifestError(
                "raw_audit_id must be a canonical positive decimal identity"
            )
        if self.version != RAW_AUDIT_REFERENCE_VERSION:
            raise CandidateRawAuditManifestError("unsupported RawAudit reference version")
        _require_text(self.content_hash, "content_hash", 64)
        _require_sha256(self.content_hash, "content_hash")
        _require_text(self.provider_name, "provider_name", 50)
        _require_text(self.capability, "capability", 30)
        _require_uuid(self.run_id, "run_id")
        _require_uuid(self.ingested_run_id, "ingested_run_id")

    def canonical_fields(self) -> dict[str, str]:
        """Return the stable hash representation of this reference."""

        return {
            "raw_audit_id": self.raw_audit_id,
            "version": self.version,
            "content_hash": self.content_hash,
            "provider_name": self.provider_name,
            "capability": self.capability,
            "run_id": self.run_id,
            "ingested_run_id": self.ingested_run_id,
        }


@dataclass(frozen=True, slots=True)
class CandidateRawAuditManifest:
    """Frozen RawAudit set bound to one publication candidate and task attempt."""

    manifest_id: str
    manifest_version: str
    publication_id: str
    publication_hash: str
    run_id: str
    dataset_key: str
    publication_key: str
    task_attempt_id: str
    raw_audits: tuple[CandidateRawAuditReference, ...]
    raw_audit_count: int
    raw_audit_hash: str
    manifest_hash: str

    def __post_init__(self) -> None:
        """Verify canonical ordering, count, and both content digests."""

        _require_uuid(self.manifest_id, "manifest_id")
        _require_uuid(self.publication_id, "publication_id")
        _require_uuid(self.run_id, "run_id")
        if self.manifest_version != MANIFEST_VERSION:
            raise CandidateRawAuditManifestError("unsupported candidate manifest version")
        _require_sha256(self.publication_hash, "publication_hash")
        _require_text(self.dataset_key, "dataset_key", 160)
        _require_text(self.publication_key, "publication_key", 300)
        _require_text(self.task_attempt_id, "task_attempt_id", 160)
        if not isinstance(self.raw_audits, tuple) or not self.raw_audits:
            raise CandidateRawAuditManifestError("candidate manifest requires RawAudit references")
        if any(not isinstance(item, CandidateRawAuditReference) for item in self.raw_audits):
            raise CandidateRawAuditManifestError("candidate manifest contains an invalid reference")
        identifiers = tuple(item.raw_audit_id for item in self.raw_audits)
        if len(identifiers) != len(set(identifiers)):
            raise CandidateRawAuditManifestError("RawAudit references must be unique")
        if self.raw_audits != tuple(
            sorted(self.raw_audits, key=lambda item: int(item.raw_audit_id))
        ):
            raise CandidateRawAuditManifestError("RawAudit references are not stably ordered")
        if self.raw_audit_count != len(self.raw_audits):
            raise CandidateRawAuditManifestError("RawAudit reference count does not match")
        expected_raw_hash = candidate_raw_audit_references_hash(self.raw_audits)
        if self.raw_audit_hash != expected_raw_hash:
            raise CandidateRawAuditManifestError("RawAudit reference hash does not match")
        expected_manifest_hash = candidate_raw_audit_manifest_hash(
            manifest_version=self.manifest_version,
            publication_id=self.publication_id,
            publication_hash=self.publication_hash,
            run_id=self.run_id,
            dataset_key=self.dataset_key,
            publication_key=self.publication_key,
            task_attempt_id=self.task_attempt_id,
            raw_audits=self.raw_audits,
            raw_audit_hash=self.raw_audit_hash,
        )
        if self.manifest_hash != expected_manifest_hash:
            raise CandidateRawAuditManifestError("candidate manifest hash does not match")

    @classmethod
    def create(
        cls,
        *,
        publication_id: str,
        publication_hash: str,
        run_id: str,
        dataset_key: str,
        publication_key: str,
        task_attempt_id: str,
        raw_audits: tuple[CandidateRawAuditReference, ...],
        manifest_id: str | None = None,
    ) -> CandidateRawAuditManifest:
        """Create a canonical manifest, sorting references by numeric row id."""

        if not isinstance(raw_audits, tuple) or not raw_audits:
            raise CandidateRawAuditManifestError("candidate manifest requires RawAudit references")
        if any(not isinstance(item, CandidateRawAuditReference) for item in raw_audits):
            raise CandidateRawAuditManifestError("candidate manifest contains an invalid reference")
        identity = str(uuid4()) if manifest_id is None else manifest_id
        ordered_audits = tuple(sorted(raw_audits, key=lambda item: int(item.raw_audit_id)))
        references_hash = candidate_raw_audit_references_hash(ordered_audits)
        digest = candidate_raw_audit_manifest_hash(
            manifest_version=MANIFEST_VERSION,
            publication_id=publication_id,
            publication_hash=publication_hash,
            run_id=run_id,
            dataset_key=dataset_key,
            publication_key=publication_key,
            task_attempt_id=task_attempt_id,
            raw_audits=ordered_audits,
            raw_audit_hash=references_hash,
        )
        return cls(
            manifest_id=identity,
            manifest_version=MANIFEST_VERSION,
            publication_id=publication_id,
            publication_hash=publication_hash,
            run_id=run_id,
            dataset_key=dataset_key,
            publication_key=publication_key,
            task_attempt_id=task_attempt_id,
            raw_audits=ordered_audits,
            raw_audit_count=len(ordered_audits),
            raw_audit_hash=references_hash,
            manifest_hash=digest,
        )


def candidate_raw_audit_references_hash(
    raw_audits: tuple[CandidateRawAuditReference, ...],
) -> str:
    """Hash a stable ordered list of exact RawAudit references."""

    payload = {
        "format": "candidate-raw-audit-references-v1",
        "references": [item.canonical_fields() for item in raw_audits],
    }
    return _sha256_json(payload)


def candidate_raw_audit_manifest_hash(
    *,
    manifest_version: str,
    publication_id: str,
    publication_hash: str,
    run_id: str,
    dataset_key: str,
    publication_key: str,
    task_attempt_id: str,
    raw_audits: tuple[CandidateRawAuditReference, ...],
    raw_audit_hash: str,
) -> str:
    """Hash all candidate identity fields and the complete ordered RawAudit set."""

    payload = {
        "format": "candidate-raw-audit-manifest-v1",
        "manifest_version": manifest_version,
        "publication_id": publication_id,
        "publication_hash": publication_hash,
        "run_id": run_id,
        "dataset_key": dataset_key,
        "publication_key": publication_key,
        "task_attempt_id": task_attempt_id,
        "raw_audit_count": len(raw_audits),
        "raw_audit_hash": raw_audit_hash,
        "raw_audits": [item.canonical_fields() for item in raw_audits],
    }
    return _sha256_json(payload)


def _require_text(value: str, field_name: str, maximum_length: int) -> None:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or len(value) > maximum_length
    ):
        raise CandidateRawAuditManifestError(
            f"{field_name} must be canonical, non-empty text of at most {maximum_length} characters"
        )


def _require_uuid(value: str, field_name: str) -> None:
    try:
        parsed = UUID(value)
    except (AttributeError, TypeError, ValueError) as exc:
        raise CandidateRawAuditManifestError(f"{field_name} must be a UUID string") from exc
    if str(parsed) != value:
        raise CandidateRawAuditManifestError(f"{field_name} must use canonical UUID form")


def _require_sha256(value: str, field_name: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise CandidateRawAuditManifestError(f"{field_name} must be a lowercase sha256 digest")


def _sha256_json(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "CURRENT_MARKET_PUBLICATION_DATASETS",
    "canonical_capability_for_publication_dataset",
    "requires_group_publication_activation",
    "CandidateRawAuditManifest",
    "CandidateRawAuditManifestError",
    "CandidateRawAuditReference",
    "MANIFEST_VERSION",
    "RAW_AUDIT_REFERENCE_VERSION",
    "candidate_raw_audit_manifest_hash",
    "candidate_raw_audit_references_hash",
    "validate_raw_audit_source_type",
]
