"""Price-limit-only publication evidence and point-in-time pointer history.

This module binds one exact security, provider, and effective trade date to its
immutable raw-backed fact. It does not infer source clocks, currency, freshness,
market-wide coverage, decision eligibility, or execution eligibility.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from .contracts import (
    DatasetContract,
    DatasetFieldContract,
    DatasetKey,
    PublicationPolicy,
)
from .control_plane import PublicationMember, PublicationRollback
from .price_limit_snapshot import PriceLimitSnapshot, PriceLimitSnapshotReference
from .publication_member_codec import PriceLimitNullableMemberCodecVersion

_DATASET_KEY = "equity.price.limit"
_FACT_TABLE = "data_center_price_limit_snapshot_fact"
_RAW_PAYLOAD_SCOPE = "record_response_body"
_HASH_SCHEMA = "price-limit-formal-publication.v1"
_MEMBER_HASH_SCHEMA = "price-limit-nullable-member.v1"
_BARE_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,299}\Z")


class PriceLimitPublicationError(ValueError):
    """Recognized invalid price-limit publication evidence or history."""

    def __init__(self, code: str, message: str) -> None:
        """Expose a stable reason code to Application callers."""

        self.code = code
        super().__init__(message)


def _fail(code: str, message: str) -> PriceLimitPublicationError:
    """Create one stable Domain failure."""

    return PriceLimitPublicationError(code, message)


def _require_text(value: object, field_name: str, *, maximum: int = 300) -> str:
    """Require canonical bounded text with no controls or surrounding space."""

    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > maximum
        or any(ord(character) < 32 for character in value)
    ):
        raise _fail("PRICE_LIMIT_PUBLICATION_TEXT_INVALID", f"{field_name} is invalid")
    return value


def _require_digest(value: object, field_name: str) -> str:
    """Require one lowercase bare SHA-256 digest."""

    if type(value) is not str or _BARE_SHA256.fullmatch(value) is None:
        raise _fail("PRICE_LIMIT_PUBLICATION_HASH_INVALID", f"{field_name} must be bare SHA-256")
    return value


def _require_uuid(value: object, field_name: str) -> str:
    """Require a canonical lowercase UUID string."""

    if type(value) is not str:
        raise _fail("PRICE_LIMIT_PUBLICATION_UUID_INVALID", f"{field_name} must be a UUID")
    try:
        parsed = UUID(value)
    except (AttributeError, TypeError, ValueError) as error:
        raise _fail(
            "PRICE_LIMIT_PUBLICATION_UUID_INVALID", f"{field_name} must be a UUID"
        ) from error
    if str(parsed) != value:
        raise _fail("PRICE_LIMIT_PUBLICATION_UUID_INVALID", f"{field_name} must be canonical")
    return value


def _require_utc(value: object, field_name: str) -> datetime:
    """Require an aware timestamp whose UTC offset is exactly zero."""

    if type(value) is not datetime or value.tzinfo is None:
        raise _fail("PRICE_LIMIT_PUBLICATION_TIME_INVALID", f"{field_name} must be UTC-aware")
    offset = value.utcoffset()
    if offset is None or offset.total_seconds() != 0:
        raise _fail("PRICE_LIMIT_PUBLICATION_TIME_INVALID", f"{field_name} must be UTC")
    return value


def _require_activation_id(value: object, field_name: str) -> str:
    """Require an explicit bounded activation or audit event token."""

    token = _require_text(value, field_name)
    if _TOKEN.fullmatch(token) is None:
        raise _fail("PRICE_LIMIT_PUBLICATION_EVENT_ID_INVALID", f"{field_name} is invalid")
    return token


def _canonical_hash(payload: dict[str, object]) -> str:
    """Hash deterministic UTF-8 JSON and reject non-JSON numeric values."""

    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as error:
        raise _fail(
            "PRICE_LIMIT_PUBLICATION_PAYLOAD_INVALID", "publication payload is invalid"
        ) from error
    return hashlib.sha256(encoded).hexdigest()


def _dataset_key_payload(dataset: DatasetKey) -> dict[str, object]:
    """Serialize all version fields from one typed dataset key."""

    if type(dataset) is not DatasetKey:
        raise _fail("PRICE_LIMIT_PUBLICATION_DATASET_INVALID", "dataset key must be typed")
    try:
        dataset.__post_init__()
    except (AttributeError, TypeError, ValueError) as error:
        raise _fail("PRICE_LIMIT_PUBLICATION_DATASET_INVALID", "dataset key is invalid") from error
    return {
        "value": dataset.value,
        "contract_version": dataset.contract_version,
        "schema_version": dataset.schema_version,
    }


def _contract_optional_positive_int(value: object, field_name: str) -> int | None:
    """Validate one optional contract age or retention duration."""

    if value is None:
        return None
    if type(value) is not int or value <= 0:
        raise _fail("PRICE_LIMIT_PUBLICATION_CONTRACT_INVALID", f"{field_name} is invalid")
    return value


def _field_contract_payload(field: DatasetFieldContract) -> dict[str, object]:
    """Serialize every schema field rule in the dataset contract."""

    if type(field) is not DatasetFieldContract:
        raise _fail("PRICE_LIMIT_PUBLICATION_CONTRACT_INVALID", "dataset field is invalid")
    try:
        field.__post_init__()
    except (AttributeError, TypeError, ValueError) as error:
        raise _fail(
            "PRICE_LIMIT_PUBLICATION_CONTRACT_INVALID", "dataset field is invalid"
        ) from error
    if type(field.nullable) is not bool or type(field.zero_allowed) is not bool:
        raise _fail(
            "PRICE_LIMIT_PUBLICATION_CONTRACT_INVALID", "dataset field flags must be booleans"
        )
    for name, value in (("minimum", field.minimum), ("maximum", field.maximum)):
        if value is not None and (
            type(value) not in {int, float}
            or type(value) is bool
            or not math.isfinite(float(value))
        ):
            raise _fail(
                "PRICE_LIMIT_PUBLICATION_CONTRACT_INVALID", f"dataset field {name} is invalid"
            )
    if type(field.source_contracts) is not tuple:
        raise _fail("PRICE_LIMIT_PUBLICATION_CONTRACT_INVALID", "source contracts must be a tuple")
    return {
        "name": field.name,
        "value_type": field.value_type,
        "unit": field.unit,
        "nullable": field.nullable,
        "zero_allowed": field.zero_allowed,
        "minimum": field.minimum,
        "maximum": field.maximum,
        "source_contracts": [],
    }


def _dataset_contract_payload(contract: DatasetContract) -> dict[str, object]:
    """Serialize the full versioned dataset contract without lossy projection."""

    if type(contract) is not DatasetContract:
        raise _fail("PRICE_LIMIT_PUBLICATION_CONTRACT_INVALID", "dataset_contract must be typed")
    try:
        contract.__post_init__()
    except (AttributeError, TypeError, ValueError) as error:
        raise _fail(
            "PRICE_LIMIT_PUBLICATION_CONTRACT_INVALID", "dataset contract is invalid"
        ) from error
    if contract.key.value != _DATASET_KEY:
        raise _fail(
            "PRICE_LIMIT_PUBLICATION_DATASET_INVALID", "dataset contract is not price-limit"
        )
    if type(contract.fields) is not tuple:
        raise _fail(
            "PRICE_LIMIT_PUBLICATION_CONTRACT_INVALID", "dataset contract fields must be a tuple"
        )
    if type(contract.decision_critical) is not bool:
        raise _fail("PRICE_LIMIT_PUBLICATION_CONTRACT_INVALID", "decision_critical must be boolean")
    comparable_group = contract.comparable_group
    if comparable_group is not None:
        comparable_group = _require_text(comparable_group, "contract.comparable_group", maximum=150)
    return {
        "key": _dataset_key_payload(contract.key),
        "owner": _require_text(contract.owner, "contract.owner", maximum=150),
        "frequency": _require_text(contract.frequency, "contract.frequency", maximum=100),
        "decision_critical": contract.decision_critical,
        "fields": [_field_contract_payload(field) for field in contract.fields],
        "freshness_seconds": _contract_optional_positive_int(
            contract.freshness_seconds, "freshness_seconds"
        ),
        "comparable_group": comparable_group,
        "execution_freshness_seconds": _contract_optional_positive_int(
            contract.execution_freshness_seconds, "execution_freshness_seconds"
        ),
        "calendar_response_max_age_seconds": _contract_optional_positive_int(
            contract.calendar_response_max_age_seconds, "calendar_response_max_age_seconds"
        ),
    }


def _publication_policy_payload(policy: PublicationPolicy) -> dict[str, object]:
    """Serialize all decision content plus the policy's persisted identity."""

    if type(policy) is not PublicationPolicy:
        raise _fail("PRICE_LIMIT_PUBLICATION_POLICY_INVALID", "policy must be typed")
    try:
        policy.__post_init__()
    except (AttributeError, TypeError, ValueError) as error:
        raise _fail("PRICE_LIMIT_PUBLICATION_POLICY_INVALID", "policy is invalid") from error
    if (
        policy.dataset.value != _DATASET_KEY
        or type(policy.member_codec_version) is not PriceLimitNullableMemberCodecVersion
        or policy.member_codec_version is not PriceLimitNullableMemberCodecVersion.V1
        or not policy.uses_versioned_evidence
    ):
        raise _fail(
            "PRICE_LIMIT_PUBLICATION_POLICY_INVALID",
            "policy must bind the explicit price-limit nullable-member v1 codec",
        )
    if (
        type(policy.minimum_coverage_ratio) not in {int, float}
        or type(policy.minimum_coverage_ratio) is bool
        or not math.isfinite(float(policy.minimum_coverage_ratio))
        or type(policy.allow_partial) is not bool
        or type(policy.required_evidence) is not tuple
        or type(policy.retention_days) is not int
    ):
        raise _fail("PRICE_LIMIT_PUBLICATION_POLICY_INVALID", "policy coverage ratio is invalid")
    return {
        "dataset": _dataset_key_payload(policy.dataset),
        "minimum_coverage_ratio": float(policy.minimum_coverage_ratio),
        "allow_partial": policy.allow_partial,
        "conflict_action": policy.conflict_action,
        "required_evidence": list(policy.required_evidence),
        "retention_days": policy.retention_days,
        "policy_version": policy.policy_version,
        "member_codec_version": policy.member_codec_version.value,
        "content_hash": policy.content_hash,
        "identity": policy.identity,
    }


def price_limit_publication_key(snapshot_reference: PriceLimitSnapshotReference) -> str:
    """Return the pointer key for the exact provider, security, and trade date."""

    if type(snapshot_reference) is not PriceLimitSnapshotReference:
        raise _fail("PRICE_LIMIT_PUBLICATION_SCOPE_INVALID", "snapshot reference must be typed")
    try:
        snapshot_reference.__post_init__()
    except (AttributeError, TypeError, ValueError) as error:
        raise _fail(
            "PRICE_LIMIT_PUBLICATION_SCOPE_INVALID", "snapshot reference is invalid"
        ) from error
    return f"price-limit:{snapshot_reference.request_scope_sha256}"


@dataclass(frozen=True, slots=True)
class PriceLimitPublicationMemberEvidence:
    """Nullable-time member facts sealed separately from publication row IDs."""

    snapshot_reference: PriceLimitSnapshotReference
    codec_version: PriceLimitNullableMemberCodecVersion
    publication_key: str
    natural_key: str
    source: str
    source_record_id: str
    fact_table: str
    fact_pk: str
    observed_at: datetime | None
    raw_payload_hash: str
    quality_status: str
    revision_number: int
    available_at: datetime | None
    fetched_at: datetime
    source_published_at: datetime | None
    raw_payload_scope: str
    fact_content_hash: str

    def __post_init__(self) -> None:
        """Reject source-time invention, wrong table identity, or digest confusion."""

        self.validate()

    def validate(self) -> None:
        """Revalidate the member evidence before hashing or projection."""

        reference = self.snapshot_reference
        if type(reference) is not PriceLimitSnapshotReference:
            raise _fail("PRICE_LIMIT_PUBLICATION_MEMBER_INVALID", "snapshot reference is invalid")
        try:
            reference.__post_init__()
        except (AttributeError, TypeError, ValueError) as error:
            raise _fail(
                "PRICE_LIMIT_PUBLICATION_MEMBER_INVALID", "snapshot reference is invalid"
            ) from error
        if type(self.codec_version) is not PriceLimitNullableMemberCodecVersion:
            raise _fail("PRICE_LIMIT_PUBLICATION_CODEC_INVALID", "member codec must be typed")
        if self.codec_version is not PriceLimitNullableMemberCodecVersion.V1:
            raise _fail("PRICE_LIMIT_PUBLICATION_CODEC_INVALID", "member codec is unsupported")
        expected_key = price_limit_publication_key(reference)
        if self.publication_key != expected_key or self.natural_key != expected_key:
            raise _fail(
                "PRICE_LIMIT_PUBLICATION_SCOPE_MISMATCH", "member key differs from request scope"
            )
        if self.source != reference.provider_name:
            raise _fail("PRICE_LIMIT_PUBLICATION_MEMBER_INVALID", "member provider is mismatched")
        if self.source_record_id != reference.snapshot_id or self.fact_pk != reference.snapshot_id:
            raise _fail(
                "PRICE_LIMIT_PUBLICATION_MEMBER_INVALID", "member must identify the local snapshot"
            )
        _require_uuid(self.source_record_id, "member.source_record_id")
        _require_uuid(self.fact_pk, "member.fact_pk")
        if self.fact_table != _FACT_TABLE:
            raise _fail(
                "PRICE_LIMIT_PUBLICATION_MEMBER_INVALID", "member fact table is not price-limit"
            )
        for name, value in (
            ("natural_key", self.natural_key),
            ("source", self.source),
            ("source_record_id", self.source_record_id),
            ("fact_table", self.fact_table),
            ("fact_pk", self.fact_pk),
            ("quality_status", self.quality_status),
            ("raw_payload_scope", self.raw_payload_scope),
        ):
            _require_text(value, f"member.{name}")
        if (
            self.observed_at is not None
            or self.available_at is not None
            or self.source_published_at is not None
        ):
            raise _fail(
                "PRICE_LIMIT_PUBLICATION_SOURCE_CLOCK_UNKNOWN",
                "provider observation, availability, and publication clocks remain unknown",
            )
        if type(self.revision_number) is not int or self.revision_number != 1:
            raise _fail(
                "PRICE_LIMIT_PUBLICATION_REVISION_INVALID",
                "revision_number is the fixed local member ordinal, not a provider revision",
            )
        if self.raw_payload_scope != _RAW_PAYLOAD_SCOPE:
            raise _fail("PRICE_LIMIT_PUBLICATION_RAW_SCOPE_INVALID", "raw body scope is invalid")
        _require_digest(self.raw_payload_hash, "member.raw_payload_hash")
        _require_digest(self.fact_content_hash, "member.fact_content_hash")
        _require_utc(self.fetched_at, "member.fetched_at")

    def to_payload(self) -> dict[str, object]:
        """Return the hash payload, keeping ORM IDs out of content identity."""

        self.validate()
        return {
            "codec_version": self.codec_version.value,
            "dataset_key": _DATASET_KEY,
            "publication_key": self.publication_key,
            "member": {
                "natural_key": self.natural_key,
                "source": self.source,
                "source_record_id": self.source_record_id,
                "fact_table": self.fact_table,
                "fact_pk": self.fact_pk,
                "observed_at": None,
                "raw_payload_hash": self.raw_payload_hash,
                "quality_status": self.quality_status,
                "revision_number": self.revision_number,
                "available_at": None,
                "fetched_at": self.fetched_at.isoformat(),
                "source_published_at": None,
                "raw_payload_scope": self.raw_payload_scope,
                "fact_content_hash": self.fact_content_hash,
            },
            "snapshot_reference": self.snapshot_reference.to_payload(),
        }

    def to_publication_member(self, *, publication_id: str, member_id: str) -> PublicationMember:
        """Materialize the generic row DTO after its publication IDs are known."""

        self.validate()
        _require_uuid(publication_id, "publication_id")
        _require_uuid(member_id, "member_id")
        return PublicationMember(
            member_id=member_id,
            publication_id=publication_id,
            dataset_key=_DATASET_KEY,
            natural_key=self.natural_key,
            source=self.source,
            source_record_id=self.source_record_id,
            fact_table=self.fact_table,
            fact_pk=self.fact_pk,
            observed_at=None,
            raw_payload_hash=self.raw_payload_hash,
            quality_status=self.quality_status,
            revision_number=self.revision_number,
            available_at=None,
            fetched_at=self.fetched_at,
            source_published_at=None,
            raw_payload_scope=self.raw_payload_scope,
            fact_content_hash=self.fact_content_hash,
        )


def _member_evidence(
    snapshot: PriceLimitSnapshot,
    fact_content_hash: str,
) -> PriceLimitPublicationMemberEvidence:
    """Build the one-member evidence from the exact persisted snapshot row."""

    if type(snapshot) is not PriceLimitSnapshot:
        raise _fail("PRICE_LIMIT_PUBLICATION_SNAPSHOT_INVALID", "snapshot must be typed")
    try:
        snapshot.__post_init__()
    except (AttributeError, TypeError, ValueError) as error:
        raise _fail("PRICE_LIMIT_PUBLICATION_SNAPSHOT_INVALID", "snapshot is invalid") from error
    raw_reference = snapshot.candidate.raw_reference
    reference = snapshot.reference()
    key = price_limit_publication_key(reference)
    return PriceLimitPublicationMemberEvidence(
        snapshot_reference=reference,
        codec_version=PriceLimitNullableMemberCodecVersion.V1,
        publication_key=key,
        natural_key=key,
        source=snapshot.candidate.provider_name,
        source_record_id=snapshot.snapshot_id,
        fact_table=_FACT_TABLE,
        fact_pk=snapshot.snapshot_id,
        observed_at=None,
        raw_payload_hash=raw_reference.body_sha256,
        quality_status="reference_only",
        revision_number=1,
        available_at=None,
        fetched_at=snapshot.candidate.response_completed_at,
        source_published_at=None,
        raw_payload_scope=_RAW_PAYLOAD_SCOPE,
        fact_content_hash=fact_content_hash,
    )


def price_limit_member_manifest_hash(
    member_evidence: PriceLimitPublicationMemberEvidence,
    policy: PublicationPolicy,
) -> str:
    """Hash one exact nullable-time member and its bound policy identity."""

    if type(member_evidence) is not PriceLimitPublicationMemberEvidence:
        raise _fail("PRICE_LIMIT_PUBLICATION_MEMBER_INVALID", "member evidence must be typed")
    member_evidence.validate()
    policy_payload = _publication_policy_payload(policy)
    return _canonical_hash(
        {
            "encoding": _MEMBER_HASH_SCHEMA,
            "policy": policy_payload,
            "member_evidence": member_evidence.to_payload(),
        }
    )


@dataclass(frozen=True, slots=True)
class PriceLimitFormalPublicationSeal:
    """Immutable content/config seal for one exact price-limit publication."""

    dataset_contract: DatasetContract
    contract_recorded_at: datetime
    policy: PublicationPolicy
    policy_recorded_at: datetime
    snapshot: PriceLimitSnapshot
    snapshot_reference: PriceLimitSnapshotReference
    member_evidence: PriceLimitPublicationMemberEvidence
    member_manifest_hash: str
    publication_hash: str

    def __post_init__(self) -> None:
        """Verify full catalog contents, source binding, and both canonical hashes."""

        self.validate()

    @property
    def publication_key(self) -> str:
        """Return the exact provider/security/effective-date pointer scope."""

        self.validate()
        return self.member_evidence.publication_key

    @property
    def policy_identity(self) -> str:
        """Return the exact persisted policy identity sealed here."""

        self.validate()
        return self.policy.identity

    @property
    def policy_version(self) -> str:
        """Return the version token from the exact publication policy."""

        self.validate()
        return self.policy.policy_version

    @property
    def response_completed_at(self) -> datetime:
        """Return local exact-body completion without assigning source semantics."""

        self.validate()
        return self.snapshot.candidate.response_completed_at

    @property
    def recorded_at(self) -> datetime:
        """Return the immutable fact's first persistence time."""

        self.validate()
        return self.snapshot.recorded_at

    @property
    def currency(self) -> None:
        """Keep provider-native prices from implying a currency."""

        return None

    @property
    def observed_at(self) -> None:
        """Keep the unknown provider observation time unknown."""

        return None

    @property
    def source_available_at(self) -> None:
        """Keep the unknown provider availability time unknown."""

        return None

    @property
    def source_published_at(self) -> None:
        """Keep the unknown provider publication time unknown."""

        return None

    @property
    def must_not_use_for_decision(self) -> Literal[True]:
        """Publication preserves the reference-only decision block."""

        return True

    @property
    def must_not_execute(self) -> Literal[True]:
        """Publication never grants execution eligibility."""

        return True

    @property
    def coverage_scope(self) -> Literal["single_explicit_provider_security_date"]:
        """Limit this member's coverage claim to its one explicit request scope."""

        return "single_explicit_provider_security_date"

    def validate(self) -> None:
        """Rebuild all nested values and hashes to reject tampered DTOs."""

        contract_payload = _dataset_contract_payload(self.dataset_contract)
        policy_payload = _publication_policy_payload(self.policy)
        _require_utc(self.contract_recorded_at, "contract_recorded_at")
        _require_utc(self.policy_recorded_at, "policy_recorded_at")
        if self.policy.dataset != self.dataset_contract.key:
            raise _fail(
                "PRICE_LIMIT_PUBLICATION_CATALOG_MISMATCH", "policy and contract versions differ"
            )
        if type(self.snapshot) is not PriceLimitSnapshot:
            raise _fail("PRICE_LIMIT_PUBLICATION_SNAPSHOT_INVALID", "snapshot must be typed")
        try:
            self.snapshot.__post_init__()
        except (AttributeError, TypeError, ValueError) as error:
            raise _fail(
                "PRICE_LIMIT_PUBLICATION_SNAPSHOT_INVALID", "snapshot is invalid"
            ) from error
        if type(self.snapshot_reference) is not PriceLimitSnapshotReference:
            raise _fail(
                "PRICE_LIMIT_PUBLICATION_SNAPSHOT_INVALID", "snapshot reference must be typed"
            )
        try:
            self.snapshot_reference.__post_init__()
        except (AttributeError, TypeError, ValueError) as error:
            raise _fail(
                "PRICE_LIMIT_PUBLICATION_SNAPSHOT_INVALID", "snapshot reference is invalid"
            ) from error
        if self.snapshot_reference != self.snapshot.reference():
            raise _fail(
                "PRICE_LIMIT_PUBLICATION_SNAPSHOT_MISMATCH", "snapshot reference differs from fact"
            )
        if type(self.member_evidence) is not PriceLimitPublicationMemberEvidence:
            raise _fail("PRICE_LIMIT_PUBLICATION_MEMBER_INVALID", "member evidence must be typed")
        self.member_evidence.validate()
        expected_member = _member_evidence(self.snapshot, self.member_evidence.fact_content_hash)
        if self.member_evidence != expected_member:
            raise _fail(
                "PRICE_LIMIT_PUBLICATION_MEMBER_MISMATCH", "member does not match exact snapshot"
            )
        expected_member_hash = price_limit_member_manifest_hash(self.member_evidence, self.policy)
        _require_digest(self.member_manifest_hash, "member_manifest_hash")
        if self.member_manifest_hash != expected_member_hash:
            raise _fail(
                "PRICE_LIMIT_PUBLICATION_MEMBER_HASH_MISMATCH", "member manifest hash differs"
            )
        _require_digest(self.publication_hash, "publication_hash")
        expected_publication_hash = _publication_hash(
            dataset_contract_payload=contract_payload,
            contract_recorded_at=self.contract_recorded_at,
            policy_payload=policy_payload,
            policy_recorded_at=self.policy_recorded_at,
            snapshot=self.snapshot,
            snapshot_reference=self.snapshot_reference,
            member_evidence=self.member_evidence,
            member_manifest_hash=self.member_manifest_hash,
        )
        if self.publication_hash != expected_publication_hash:
            raise _fail(
                "PRICE_LIMIT_PUBLICATION_HASH_MISMATCH", "publication hash differs from evidence"
            )

    def to_payload(self) -> dict[str, object]:
        """Return the full immutable evidence payload used by publication hash."""

        self.validate()
        return _publication_payload(self)


def _publication_payload(
    seal: PriceLimitFormalPublicationSeal,
) -> dict[str, object]:
    """Build the explicit price-limit v1 publication hash payload."""

    return {
        "encoding": _HASH_SCHEMA,
        "dataset_contract": _dataset_contract_payload(seal.dataset_contract),
        "contract_recorded_at": seal.contract_recorded_at.isoformat(),
        "policy": _publication_policy_payload(seal.policy),
        "policy_recorded_at": seal.policy_recorded_at.isoformat(),
        "publication_key": seal.member_evidence.publication_key,
        "member_codec_version": seal.member_evidence.codec_version.value,
        "member_manifest_hash": seal.member_manifest_hash,
        "member_evidence": seal.member_evidence.to_payload(),
        "snapshot": seal.snapshot.to_payload(),
        "snapshot_reference": seal.snapshot_reference.to_payload(),
        "response_completed_at": seal.snapshot.candidate.response_completed_at.isoformat(),
        "recorded_at": seal.snapshot.recorded_at.isoformat(),
        "source_clocks": {
            "observed_at": None,
            "available_at": None,
            "published_at": None,
        },
        "currency": None,
        "must_not_use_for_decision": True,
        "must_not_execute": True,
        "coverage_scope": "single_explicit_provider_security_date",
    }


def _publication_hash(
    *,
    dataset_contract_payload: dict[str, object],
    contract_recorded_at: datetime,
    policy_payload: dict[str, object],
    policy_recorded_at: datetime,
    snapshot: PriceLimitSnapshot,
    snapshot_reference: PriceLimitSnapshotReference,
    member_evidence: PriceLimitPublicationMemberEvidence,
    member_manifest_hash: str,
) -> str:
    """Compute the exact publication digest without depending on ORM IDs."""

    payload: dict[str, object] = {
        "encoding": _HASH_SCHEMA,
        "dataset_contract": dataset_contract_payload,
        "contract_recorded_at": contract_recorded_at.isoformat(),
        "policy": policy_payload,
        "policy_recorded_at": policy_recorded_at.isoformat(),
        "publication_key": member_evidence.publication_key,
        "member_codec_version": member_evidence.codec_version.value,
        "member_manifest_hash": member_manifest_hash,
        "member_evidence": member_evidence.to_payload(),
        "snapshot": snapshot.to_payload(),
        "snapshot_reference": snapshot_reference.to_payload(),
        "response_completed_at": snapshot.candidate.response_completed_at.isoformat(),
        "recorded_at": snapshot.recorded_at.isoformat(),
        "source_clocks": {"observed_at": None, "available_at": None, "published_at": None},
        "currency": None,
        "must_not_use_for_decision": True,
        "must_not_execute": True,
        "coverage_scope": "single_explicit_provider_security_date",
    }
    return _canonical_hash(payload)


def create_price_limit_formal_publication_seal(
    *,
    dataset_contract: DatasetContract,
    contract_recorded_at: datetime,
    policy: PublicationPolicy,
    policy_recorded_at: datetime,
    snapshot: PriceLimitSnapshot,
    fact_content_hash: str,
) -> PriceLimitFormalPublicationSeal:
    """Seal a persisted exact fact with full catalog and one-row evidence."""

    _require_digest(fact_content_hash, "fact_content_hash")
    contract_payload = _dataset_contract_payload(dataset_contract)
    policy_payload = _publication_policy_payload(policy)
    _require_utc(contract_recorded_at, "contract_recorded_at")
    _require_utc(policy_recorded_at, "policy_recorded_at")
    if policy.dataset != dataset_contract.key:
        raise _fail(
            "PRICE_LIMIT_PUBLICATION_CATALOG_MISMATCH", "policy and contract versions differ"
        )
    if type(snapshot) is not PriceLimitSnapshot:
        raise _fail("PRICE_LIMIT_PUBLICATION_SNAPSHOT_INVALID", "snapshot must be typed")
    try:
        snapshot.__post_init__()
    except (AttributeError, TypeError, ValueError) as error:
        raise _fail("PRICE_LIMIT_PUBLICATION_SNAPSHOT_INVALID", "snapshot is invalid") from error
    snapshot_reference = snapshot.reference()
    member_evidence = _member_evidence(snapshot, fact_content_hash)
    member_hash = price_limit_member_manifest_hash(member_evidence, policy)
    publication_hash = _publication_hash(
        dataset_contract_payload=contract_payload,
        contract_recorded_at=contract_recorded_at,
        policy_payload=policy_payload,
        policy_recorded_at=policy_recorded_at,
        snapshot=snapshot,
        snapshot_reference=snapshot_reference,
        member_evidence=member_evidence,
        member_manifest_hash=member_hash,
    )
    return PriceLimitFormalPublicationSeal(
        dataset_contract=dataset_contract,
        contract_recorded_at=contract_recorded_at,
        policy=policy,
        policy_recorded_at=policy_recorded_at,
        snapshot=snapshot,
        snapshot_reference=snapshot_reference,
        member_evidence=member_evidence,
        member_manifest_hash=member_hash,
        publication_hash=publication_hash,
    )


@dataclass(frozen=True, slots=True)
class PriceLimitFormalPublicationRecord:
    """Immutable publication identity and its original forward activation."""

    seal: PriceLimitFormalPublicationSeal
    publication_id: str
    first_published_at: datetime
    first_activation_id: str

    def __post_init__(self) -> None:
        """Reject publication identities that predate their required evidence."""

        self.validate()

    def validate(self) -> None:
        """Revalidate seal, identity, and chronology."""

        if type(self.seal) is not PriceLimitFormalPublicationSeal:
            raise _fail("PRICE_LIMIT_PUBLICATION_RECORD_INVALID", "record seal must be typed")
        self.seal.validate()
        _require_uuid(self.publication_id, "publication_id")
        _require_utc(self.first_published_at, "first_published_at")
        _require_activation_id(self.first_activation_id, "first_activation_id")
        knowledge_times = (
            self.seal.snapshot.candidate.response_completed_at,
            self.seal.snapshot.recorded_at,
            self.seal.contract_recorded_at,
            self.seal.policy_recorded_at,
        )
        if self.first_published_at < max(knowledge_times):
            raise _fail(
                "PRICE_LIMIT_PUBLICATION_KNOWLEDGE_TIME_INVALID",
                "first publication precedes source or catalog knowledge",
            )

    @property
    def publication_hash(self) -> str:
        """Return the immutable content hash sealed by this record."""

        self.validate()
        return self.seal.publication_hash

    @property
    def must_not_use_for_decision(self) -> Literal[True]:
        """Keep published reference data blocked for decision use in this contract."""

        return True

    @property
    def must_not_execute(self) -> Literal[True]:
        """Keep this reference data blocked for execution use."""

        return True


@dataclass(frozen=True, slots=True)
class PriceLimitPublicationPointerExpectation:
    """Exact lock/CAS identity for one derived price-limit scope."""

    dataset_key: str
    publication_key: str
    pointer_id: str | None
    publication_id: str | None
    publication_hash: str | None
    activation_id: str | None
    updated_at: datetime | None

    def __post_init__(self) -> None:
        """Reject partial or cross-scope pointer identities."""

        self.validate()

    @property
    def is_absent(self) -> bool:
        """Return whether all pointer target fields are absent."""

        self.validate()
        return self.pointer_id is None

    def validate(self) -> None:
        """Revalidate the full pointer CAS token."""

        _require_text(self.dataset_key, "dataset_key", maximum=160)
        _require_text(self.publication_key, "publication_key")
        if self.dataset_key != _DATASET_KEY:
            raise _fail("PRICE_LIMIT_PUBLICATION_POINTER_SCOPE_INVALID", "pointer dataset differs")
        values = (
            self.pointer_id,
            self.publication_id,
            self.publication_hash,
            self.activation_id,
            self.updated_at,
        )
        if all(value is None for value in values):
            return
        if any(value is None for value in values):
            raise _fail("PRICE_LIMIT_PUBLICATION_POINTER_INVALID", "pointer identity is incomplete")
        _require_uuid(self.pointer_id, "pointer_id")
        _require_uuid(self.publication_id, "pointer.publication_id")
        _require_digest(self.publication_hash, "pointer.publication_hash")
        _require_activation_id(self.activation_id, "pointer.activation_id")
        _require_utc(self.updated_at, "pointer.updated_at")


class PriceLimitPublicationEventKind(StrEnum):
    """Explicit pointer event types represented by published rows or rollback facts."""

    FIRST_PUBLISH = "first_publish"
    FORWARD_PUBLISH = "forward_publish"
    ROLLBACK = "rollback"


@dataclass(frozen=True, slots=True)
class PriceLimitPublicationTimelineEvent:
    """Audit-verified pointer transition with explicit before/after identities."""

    kind: PriceLimitPublicationEventKind
    event_id: str
    dataset_key: str
    publication_key: str
    previous_publication_id: str | None
    previous_publication_hash: str | None
    target_publication_id: str
    target_publication_hash: str
    transitioned_at: datetime
    rollback: PublicationRollback | None = None

    def __post_init__(self) -> None:
        """Validate event shape before timeline continuity is checked."""

        self.validate()

    def validate(self) -> None:
        """Validate scope, both pointer identities, and rollback binding."""

        if type(self.kind) is not PriceLimitPublicationEventKind:
            raise _fail("PRICE_LIMIT_PUBLICATION_EVENT_INVALID", "event kind must be typed")
        _require_activation_id(self.event_id, "event_id")
        _require_text(self.dataset_key, "event.dataset_key", maximum=160)
        _require_text(self.publication_key, "event.publication_key")
        if self.dataset_key != _DATASET_KEY:
            raise _fail("PRICE_LIMIT_PUBLICATION_EVENT_SCOPE_INVALID", "event dataset differs")
        _require_uuid(self.target_publication_id, "event.target_publication_id")
        _require_digest(self.target_publication_hash, "event.target_publication_hash")
        _require_utc(self.transitioned_at, "event.transitioned_at")
        if (self.previous_publication_id is None) != (self.previous_publication_hash is None):
            raise _fail(
                "PRICE_LIMIT_PUBLICATION_EVENT_PREVIOUS_INVALID",
                "previous publication id and hash must be both present or absent",
            )
        if self.previous_publication_id is not None:
            _require_uuid(self.previous_publication_id, "event.previous_publication_id")
            _require_digest(self.previous_publication_hash, "event.previous_publication_hash")
        if self.kind is PriceLimitPublicationEventKind.ROLLBACK:
            if type(self.rollback) is not PublicationRollback:
                raise _fail(
                    "PRICE_LIMIT_PUBLICATION_ROLLBACK_INVALID", "rollback event needs rollback fact"
                )
            try:
                self.rollback.__post_init__()
            except (AttributeError, TypeError, ValueError) as error:
                raise _fail(
                    "PRICE_LIMIT_PUBLICATION_ROLLBACK_INVALID", "rollback fact is invalid"
                ) from error
            if (
                self.rollback.rollback_id != self.event_id
                or self.rollback.target_publication_id != self.target_publication_id
                or self.rollback.previous_publication_id != self.previous_publication_id
                or self.rollback.observed_at != self.transitioned_at
            ):
                raise _fail(
                    "PRICE_LIMIT_PUBLICATION_ROLLBACK_MISMATCH", "rollback event differs from fact"
                )
        elif self.rollback is not None:
            raise _fail(
                "PRICE_LIMIT_PUBLICATION_ROLLBACK_INVALID",
                "non-rollback event cannot carry a rollback fact",
            )


def validate_price_limit_publication_timeline(
    *,
    records: tuple[PriceLimitFormalPublicationRecord, ...],
    events: tuple[PriceLimitPublicationTimelineEvent, ...],
    current_pointer: PriceLimitPublicationPointerExpectation,
) -> PriceLimitFormalPublicationRecord | None:
    """Validate the complete scope-local publication transition chain."""

    from .formal_price_limit_publication_timeline import (
        validate_price_limit_publication_timeline as validate_timeline,
    )

    return validate_timeline(
        records=records,
        events=events,
        current_pointer=current_pointer,
    )


def resolve_price_limit_publication_at(
    *,
    records: tuple[PriceLimitFormalPublicationRecord, ...],
    events: tuple[PriceLimitPublicationTimelineEvent, ...],
    current_pointer: PriceLimitPublicationPointerExpectation,
    as_of: datetime,
    server_now: datetime,
) -> PriceLimitFormalPublicationRecord | None:
    """Resolve the verified price-limit pointer winner at an explicit cutoff."""

    from .formal_price_limit_publication_timeline import (
        resolve_price_limit_publication_at as resolve_timeline,
    )

    return resolve_timeline(
        records=records,
        events=events,
        current_pointer=current_pointer,
        as_of=as_of,
        server_now=server_now,
    )


__all__ = [
    "PriceLimitFormalPublicationRecord",
    "PriceLimitFormalPublicationSeal",
    "PriceLimitPublicationError",
    "PriceLimitPublicationEventKind",
    "PriceLimitPublicationMemberEvidence",
    "PriceLimitPublicationPointerExpectation",
    "PriceLimitPublicationTimelineEvent",
    "create_price_limit_formal_publication_seal",
    "price_limit_member_manifest_hash",
    "price_limit_publication_key",
    "resolve_price_limit_publication_at",
    "validate_price_limit_publication_timeline",
]
