"""Offline four-Publication numeric tolerance evidence for DATA-02.

The parser accepts a caller-captured ``select_only`` envelope.  It binds the
frozen universe, immutable Publication identities, publication policy content,
numeric tolerance policy content, units and every member/field comparison.  It
does not discover thresholds, query storage, call providers or authorize a
production action.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final
from uuid import NAMESPACE_URL, uuid5

from apps.data_center.domain.contracts import DatasetKey, PublicationPolicy
from apps.data_center.domain.control_plane import PublicationFactReference
from apps.data_center.domain.numeric_tolerance import (
    NumericToleranceComparison,
    NumericToleranceField,
    NumericTolerancePolicy,
    compare_numeric_value,
)
from apps.data_center.domain.publication_evidence import validate_publication_evidence

from .publication_utils import publication_hash


class Data02PublicationToleranceEvidenceError(ValueError):
    """Raised when four-Publication numeric evidence is incomplete or altered."""


_CORE_DATASETS: Final[tuple[str, ...]] = (
    "equity.financial.fact",
    "equity.price.bar",
    "equity.quote.snapshot",
    "equity.valuation.fact",
)
_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_.:/|-]{1,256}$")
_NATURAL_KEY_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_.:/|=-]{1,512}$")
_COMMIT_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_TOP_LEVEL_KEYS: Final[frozenset[str]] = frozenset(
    {"candidate", "captured_at", "datasets", "read_mode", "schema_version", "universe"}
)
_CANDIDATE_KEYS: Final[frozenset[str]] = frozenset(
    {"commit", "matrix_sha256", "oci_revision", "version"}
)
_UNIVERSE_KEYS: Final[frozenset[str]] = frozenset({"denominator", "universe_hash"})
_DATASET_KEYS: Final[frozenset[str]] = frozenset(
    {
        "comparisons",
        "dataset_key",
        "members",
        "observed_at",
        "observed_snapshot_hash",
        "observed_source",
        "publication",
        "publication_policy",
        "reference_snapshot_hash",
        "reference_source",
        "tolerance_policy",
    }
)
_PUBLICATION_KEYS: Final[frozenset[str]] = frozenset(
    {
        "covered_asset_count",
        "member_count",
        "policy_identity",
        "published_at",
        "publication_hash",
        "publication_id",
    }
)
_PUBLICATION_POLICY_KEYS: Final[frozenset[str]] = frozenset(
    {
        "allow_partial",
        "conflict_action",
        "content_hash",
        "contract_version",
        "minimum_coverage_ratio",
        "policy_version",
        "required_evidence",
        "retention_days",
        "schema_version",
    }
)
_TOLERANCE_POLICY_KEYS: Final[frozenset[str]] = frozenset(
    {"content_hash", "fields", "identity", "policy_version", "rule"}
)
_TOLERANCE_FIELD_KEYS: Final[frozenset[str]] = frozenset(
    {"absolute_tolerance", "field_name", "relative_tolerance", "unit"}
)
_COMPARISON_KEYS: Final[frozenset[str]] = frozenset(
    {"canonical_value", "field_name", "natural_key", "observed_value", "unit"}
)
_MEMBER_KEYS: Final[frozenset[str]] = frozenset(
    {
        "available_at",
        "fact_content_hash",
        "fact_pk",
        "fact_table",
        "fetched_at",
        "natural_key",
        "observed_at",
        "quality_status",
        "raw_payload_hash",
        "raw_payload_scope",
        "revision_number",
        "source",
        "source_published_at",
        "source_record_id",
    }
)
_REGISTRY_KEYS: Final[frozenset[str]] = frozenset({"policies", "schema_version", "status"})
_REGISTRY_POLICY_KEYS: Final[frozenset[str]] = frozenset(
    set(_TOLERANCE_POLICY_KEYS) | {"approval", "dataset_key"}
)
_APPROVAL_KEYS: Final[frozenset[str]] = frozenset({"approved_at", "approved_by", "receipt_sha256"})


def _decode_strict_json(payload: bytes, *, label: str) -> object:
    """Decode UTF-8 JSON while rejecting duplicate keys and non-finite constants."""

    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        decoded: dict[str, object] = {}
        for key, value in pairs:
            if key in decoded:
                raise Data02PublicationToleranceEvidenceError(
                    f"{label} contains duplicate object key: {key}"
                )
            decoded[key] = value
        return decoded

    def reject_constant(value: str) -> object:
        raise Data02PublicationToleranceEvidenceError(
            f"{label} contains non-finite numeric constant: {value}"
        )

    try:
        return json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=unique_object,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Data02PublicationToleranceEvidenceError(f"{label} must be UTF-8 JSON") from exc


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise Data02PublicationToleranceEvidenceError(f"{field_name} must be an object")
    return value


def _sequence(value: object, field_name: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise Data02PublicationToleranceEvidenceError(f"{field_name} must be an array")
    return value


def _exact_keys(value: Mapping[str, object], expected: frozenset[str], field_name: str) -> None:
    actual = frozenset(value)
    if actual != expected:
        raise Data02PublicationToleranceEvidenceError(
            f"{field_name} keys changed "
            f"(missing={sorted(expected - actual)}, extra={sorted(actual - expected)})"
        )


def _token(value: object, field_name: str) -> str:
    if type(value) is not str or _TOKEN_RE.fullmatch(value) is None:
        raise Data02PublicationToleranceEvidenceError(f"{field_name} must be a bounded token")
    return value


def _natural_key(value: object, field_name: str) -> str:
    if type(value) is not str or _NATURAL_KEY_RE.fullmatch(value) is None:
        raise Data02PublicationToleranceEvidenceError(f"{field_name} must be a bounded natural key")
    return value


def _digest(value: object, field_name: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise Data02PublicationToleranceEvidenceError(f"{field_name} must be a lowercase SHA-256")
    return value


def _decimal_input(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise Data02PublicationToleranceEvidenceError(f"{field_name} must be a decimal string")
    return value


def _positive_int(value: object, field_name: str) -> int:
    if type(value) is not int or value <= 0:
        raise Data02PublicationToleranceEvidenceError(f"{field_name} must be a positive integer")
    return value


def _utc(value: object, field_name: str) -> datetime:
    if type(value) is not str or not value.endswith("Z"):
        raise Data02PublicationToleranceEvidenceError(f"{field_name} must use UTC-Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise Data02PublicationToleranceEvidenceError(
            f"{field_name} must be ISO-8601 UTC-Z"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise Data02PublicationToleranceEvidenceError(f"{field_name} must use UTC-Z")
    return parsed.astimezone(UTC)


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _member_time(value: object, field_name: str, *, optional: bool = False) -> datetime | None:
    if value is None and optional:
        return None
    if type(value) is not str:
        raise Data02PublicationToleranceEvidenceError(f"{field_name} must be UTC ISO-8601")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise Data02PublicationToleranceEvidenceError(f"{field_name} must be UTC ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise Data02PublicationToleranceEvidenceError(f"{field_name} must use UTC")
    return parsed.astimezone(UTC)


def _optional_time_text(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _reference_to_dict(reference: PublicationFactReference) -> dict[str, object]:
    return {
        "available_at": _optional_time_text(reference.available_at),
        "fact_content_hash": reference.fact_content_hash,
        "fact_pk": reference.fact_pk,
        "fact_table": reference.fact_table,
        "fetched_at": _optional_time_text(reference.fetched_at),
        "natural_key": reference.natural_key,
        "observed_at": reference.observed_at.isoformat(),
        "quality_status": reference.quality_status,
        "raw_payload_hash": reference.raw_payload_hash,
        "raw_payload_scope": reference.raw_payload_scope,
        "revision_number": reference.revision_number,
        "source": reference.source,
        "source_published_at": _optional_time_text(reference.source_published_at),
        "source_record_id": reference.source_record_id,
    }


def _parse_members(value: object, *, dataset_key: str) -> tuple[PublicationFactReference, ...]:
    raw_members = _sequence(value, f"{dataset_key}.members")
    members: list[PublicationFactReference] = []
    for index, member_value in enumerate(raw_members):
        raw = _mapping(member_value, f"{dataset_key}.members[{index}]")
        _exact_keys(raw, _MEMBER_KEYS, f"{dataset_key}.members[{index}]")
        revision_number = raw["revision_number"]
        if type(revision_number) is not int or revision_number <= 0:
            raise Data02PublicationToleranceEvidenceError(
                "member.revision_number must be a positive integer"
            )
        observed_at = _member_time(raw["observed_at"], "member.observed_at")
        if observed_at is None:
            raise Data02PublicationToleranceEvidenceError("member.observed_at is required")
        try:
            members.append(
                PublicationFactReference(
                    natural_key=_natural_key(raw["natural_key"], "member.natural_key"),
                    source=_token(raw["source"], "member.source"),
                    source_record_id=_token(raw["source_record_id"], "member.source_record_id"),
                    fact_table=_token(raw["fact_table"], "member.fact_table"),
                    fact_pk=_token(raw["fact_pk"], "member.fact_pk"),
                    observed_at=observed_at,
                    raw_payload_hash=_digest(raw["raw_payload_hash"], "member.raw_payload_hash"),
                    quality_status=_token(raw["quality_status"], "member.quality_status"),
                    revision_number=revision_number,
                    available_at=_member_time(
                        raw["available_at"], "member.available_at", optional=True
                    ),
                    fetched_at=_member_time(raw["fetched_at"], "member.fetched_at", optional=True),
                    source_published_at=_member_time(
                        raw["source_published_at"],
                        "member.source_published_at",
                        optional=True,
                    ),
                    raw_payload_scope=_token(raw["raw_payload_scope"], "member.raw_payload_scope"),
                    fact_content_hash=_digest(raw["fact_content_hash"], "member.fact_content_hash"),
                )
            )
        except (TypeError, ValueError) as exc:
            raise Data02PublicationToleranceEvidenceError(str(exc)) from exc
    ordered = tuple(sorted(members, key=lambda member: member.natural_key))
    natural_keys = [member.natural_key for member in ordered]
    if not ordered or len(natural_keys) != len(set(natural_keys)):
        raise Data02PublicationToleranceEvidenceError(
            f"{dataset_key} Publication member natural keys must be non-empty and unique"
        )
    return ordered


def _member_identity_hash(members: tuple[PublicationFactReference, ...]) -> str:
    payload = [_reference_to_dict(member) for member in members]
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _numeric_snapshot_hash(
    *,
    dataset_key: str,
    source: str,
    value_kind: str,
    comparisons: Sequence[NumericToleranceComparison],
) -> str:
    """Bind one source snapshot digest to the exact compared values."""

    values = [
        {
            "field_name": comparison.field_name,
            "natural_key": comparison.natural_key,
            "unit": comparison.unit,
            "value": (
                comparison.canonical_value
                if value_kind == "canonical"
                else comparison.observed_value
            ),
        }
        for comparison in comparisons
    ]
    encoded = json.dumps(
        {
            "dataset_key": dataset_key,
            "encoding": "data02-numeric-snapshot-v1",
            "source": source,
            "value_kind": value_kind,
            "values": values,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _current_publication_id(dataset_key: str, publication_hash_value: str) -> str:
    """Rebuild the canonical current Publication UUID from its content hash."""

    return str(
        uuid5(
            NAMESPACE_URL,
            f"agomtradepro:{dataset_key}:current:{publication_hash_value}",
        )
    )


def _covered_asset_codes_hash(asset_codes: set[str]) -> str:
    """Hash the exact normalized covered-asset set with the backfill schema."""

    encoded = json.dumps(
        {
            "asset_codes": sorted(asset_codes),
            "schema": "active-a-share-universe.v1",
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class Data02PublicationToleranceDataset:
    """One Publication and its complete numeric reconciliation evidence."""

    dataset_key: str
    observed_at: datetime
    reference_source: str
    observed_source: str
    reference_snapshot_hash: str
    observed_snapshot_hash: str
    publication_id: str
    publication_hash: str
    published_at: datetime
    member_count: int
    covered_asset_count: int
    covered_asset_codes_hash: str
    publication_policy: PublicationPolicy
    tolerance_policy: NumericTolerancePolicy
    tolerance_approval: dict[str, str]
    members: tuple[PublicationFactReference, ...]
    member_identity_hash: str
    comparisons: tuple[NumericToleranceComparison, ...]

    @property
    def breach_count(self) -> int:
        """Return the number of field comparisons outside both tolerances."""

        return sum(comparison.breached for comparison in self.comparisons)

    def to_dict(self) -> dict[str, object]:
        """Return deterministic, source- and policy-bound dataset evidence."""

        return {
            "breach_count": self.breach_count,
            "comparisons": [comparison.to_dict() for comparison in self.comparisons],
            "dataset_key": self.dataset_key,
            "covered_asset_codes_hash": self.covered_asset_codes_hash,
            "member_identity_hash": self.member_identity_hash,
            "members": [_reference_to_dict(member) for member in self.members],
            "observed_at": _utc_text(self.observed_at),
            "observed_snapshot_hash": self.observed_snapshot_hash,
            "observed_source": self.observed_source,
            "publication": {
                "covered_asset_count": self.covered_asset_count,
                "member_count": self.member_count,
                "policy_identity": self.publication_policy.identity,
                "published_at": _utc_text(self.published_at),
                "publication_hash": self.publication_hash,
                "publication_id": self.publication_id,
            },
            "publication_policy": {
                "content_hash": self.publication_policy.content_hash,
                "identity": self.publication_policy.identity,
            },
            "reconciliation_passed": self.breach_count == 0,
            "reference_snapshot_hash": self.reference_snapshot_hash,
            "reference_source": self.reference_source,
            "tolerance_policy": {
                "content_hash": self.tolerance_policy.content_hash,
                "fields": [field.to_dict() for field in self.tolerance_policy.fields],
                "identity": self.tolerance_policy.identity,
                "policy_version": self.tolerance_policy.policy_version,
                "rule": self.tolerance_policy.rule,
                "approval": dict(self.tolerance_approval),
            },
        }


@dataclass(frozen=True, slots=True)
class Data02PublicationToleranceEvidence:
    """Exact four-Publication report that cannot authorize production."""

    candidate: dict[str, str]
    captured_at: datetime
    denominator: int
    universe_hash: str
    policy_registry_sha256: str
    datasets: tuple[Data02PublicationToleranceDataset, ...]

    @property
    def breach_count(self) -> int:
        """Return the total number of governed field breaches."""

        return sum(dataset.breach_count for dataset in self.datasets)

    @property
    def reconciliation_passed(self) -> bool:
        """Return whether every comparison is within its bound policy."""

        return self.breach_count == 0

    def to_dict(self) -> dict[str, object]:
        """Return canonical evidence without implying runtime enablement."""

        return {
            "breach_count": self.breach_count,
            "candidate": dict(self.candidate),
            "captured_at": _utc_text(self.captured_at),
            "datasets": [dataset.to_dict() for dataset in self.datasets],
            "evidence_scope": "data02_four_publication_numeric_tolerance",
            "production_claim": False,
            "production_ready": False,
            "policy_registry_sha256": self.policy_registry_sha256,
            "read_mode": "select_only",
            "reconciliation_passed": self.reconciliation_passed,
            "runtime_enablement": "not_authorized",
            "schema_version": "data02-four-publication-tolerance-evidence.v1",
            "universe": {
                "denominator": self.denominator,
                "universe_hash": self.universe_hash,
            },
        }


def _parse_candidate(value: object) -> dict[str, str]:
    raw = _mapping(value, "candidate")
    _exact_keys(raw, _CANDIDATE_KEYS, "candidate")
    commit = raw["commit"]
    if type(commit) is not str or _COMMIT_RE.fullmatch(commit) is None:
        raise Data02PublicationToleranceEvidenceError("candidate.commit must be a 40-character SHA")
    return {
        "commit": commit,
        "matrix_sha256": _digest(raw["matrix_sha256"], "candidate.matrix_sha256"),
        "oci_revision": _token(raw["oci_revision"], "candidate.oci_revision"),
        "version": _token(raw["version"], "candidate.version"),
    }


def _parse_publication_policy(
    value: object, *, dataset_key: str, expected_identity: str
) -> PublicationPolicy:
    raw = _mapping(value, f"{dataset_key}.publication_policy")
    _exact_keys(raw, _PUBLICATION_POLICY_KEYS, f"{dataset_key}.publication_policy")
    required_raw = _sequence(raw["required_evidence"], "publication_policy.required_evidence")
    required = tuple(
        _token(item, "publication_policy.required_evidence[]") for item in required_raw
    )
    ratio = raw["minimum_coverage_ratio"]
    if isinstance(ratio, bool) or not isinstance(ratio, (int, float)):
        raise Data02PublicationToleranceEvidenceError(
            "publication_policy.minimum_coverage_ratio must be numeric"
        )
    allow_partial = raw["allow_partial"]
    retention_days = raw["retention_days"]
    if type(allow_partial) is not bool or type(retention_days) is not int:
        raise Data02PublicationToleranceEvidenceError(
            "publication policy boolean/integer fields are invalid"
        )
    try:
        policy = PublicationPolicy(
            dataset=DatasetKey(
                dataset_key,
                _token(raw["contract_version"], "publication_policy.contract_version"),
                _token(raw["schema_version"], "publication_policy.schema_version"),
            ),
            minimum_coverage_ratio=float(ratio),
            allow_partial=allow_partial,
            conflict_action=_token(raw["conflict_action"], "publication_policy.conflict_action"),
            required_evidence=required,
            retention_days=retention_days,
            policy_version=_token(raw["policy_version"], "publication_policy.policy_version"),
        )
    except (TypeError, ValueError) as exc:
        raise Data02PublicationToleranceEvidenceError(str(exc)) from exc
    supplied_hash = _digest(raw["content_hash"], "publication_policy.content_hash")
    if supplied_hash != policy.content_hash:
        raise Data02PublicationToleranceEvidenceError("publication policy content_hash mismatch")
    if not policy.uses_versioned_evidence or expected_identity != policy.identity:
        raise Data02PublicationToleranceEvidenceError("publication policy identity mismatch")
    return policy


def _parse_tolerance_policy(value: object, *, dataset_key: str) -> NumericTolerancePolicy:
    raw = _mapping(value, f"{dataset_key}.tolerance_policy")
    _exact_keys(raw, _TOLERANCE_POLICY_KEYS, f"{dataset_key}.tolerance_policy")
    fields_raw = _sequence(raw["fields"], "tolerance_policy.fields")
    fields: list[NumericToleranceField] = []
    for index, field_value in enumerate(fields_raw):
        field = _mapping(field_value, f"tolerance_policy.fields[{index}]")
        _exact_keys(field, _TOLERANCE_FIELD_KEYS, f"tolerance_policy.fields[{index}]")
        try:
            fields.append(
                NumericToleranceField(
                    field_name=_token(field["field_name"], "tolerance field_name"),
                    unit=_token(field["unit"], "tolerance unit"),
                    absolute_tolerance=_decimal_input(
                        field["absolute_tolerance"], "tolerance absolute_tolerance"
                    ),
                    relative_tolerance=_decimal_input(
                        field["relative_tolerance"], "tolerance relative_tolerance"
                    ),
                )
            )
        except (TypeError, ValueError) as exc:
            raise Data02PublicationToleranceEvidenceError(str(exc)) from exc
    try:
        policy = NumericTolerancePolicy(
            dataset_key=dataset_key,
            policy_version=_token(raw["policy_version"], "tolerance_policy.policy_version"),
            rule=_token(raw["rule"], "tolerance_policy.rule"),
            fields=tuple(fields),
        )
    except (TypeError, ValueError) as exc:
        raise Data02PublicationToleranceEvidenceError(str(exc)) from exc
    supplied_hash = _digest(raw["content_hash"], "tolerance_policy.content_hash")
    if supplied_hash != policy.content_hash:
        raise Data02PublicationToleranceEvidenceError("tolerance policy content_hash mismatch")
    supplied_identity = _token(raw["identity"], "tolerance_policy.identity")
    if supplied_identity != policy.identity:
        raise Data02PublicationToleranceEvidenceError("tolerance policy identity mismatch")
    return policy


def _parse_policy_registry(
    payload: bytes,
    *,
    captured_at: datetime,
) -> tuple[dict[str, tuple[NumericTolerancePolicy, dict[str, str]]], str]:
    if type(payload) is not bytes or not payload:
        raise Data02PublicationToleranceEvidenceError(
            "policy_registry_payload must be non-empty bytes"
        )
    decoded = _decode_strict_json(payload, label="numeric tolerance policy registry")
    raw = _mapping(decoded, "policy_registry")
    _exact_keys(raw, _REGISTRY_KEYS, "policy_registry")
    if raw["schema_version"] != "data02-numeric-tolerance-policy-registry.v1":
        raise Data02PublicationToleranceEvidenceError(
            "numeric tolerance policy registry schema_version is unsupported"
        )
    if raw["status"] != "active":
        raise Data02PublicationToleranceEvidenceError(
            "numeric tolerance policy registry must be active"
        )
    registered: dict[str, tuple[NumericTolerancePolicy, dict[str, str]]] = {}
    for index, policy_value in enumerate(_sequence(raw["policies"], "policy_registry.policies")):
        policy_raw = _mapping(policy_value, f"policy_registry.policies[{index}]")
        _exact_keys(policy_raw, _REGISTRY_POLICY_KEYS, f"policy_registry.policies[{index}]")
        dataset_key = _token(policy_raw["dataset_key"], "policy_registry.dataset_key")
        if dataset_key in registered:
            raise Data02PublicationToleranceEvidenceError(
                "numeric tolerance policy registry datasets must be unique"
            )
        tolerance_payload = {key: policy_raw[key] for key in _TOLERANCE_POLICY_KEYS}
        policy = _parse_tolerance_policy(tolerance_payload, dataset_key=dataset_key)
        approval_raw = _mapping(policy_raw["approval"], "policy_registry.approval")
        _exact_keys(approval_raw, _APPROVAL_KEYS, "policy_registry.approval")
        approved_at = _utc(approval_raw["approved_at"], "policy_registry.approved_at")
        if approved_at > captured_at:
            raise Data02PublicationToleranceEvidenceError(
                "numeric tolerance policy approval is after captured_at"
            )
        approval = {
            "approved_at": _utc_text(approved_at),
            "approved_by": _token(approval_raw["approved_by"], "policy_registry.approved_by"),
            "receipt_sha256": _digest(
                approval_raw["receipt_sha256"], "policy_registry.receipt_sha256"
            ),
        }
        registered[dataset_key] = (policy, approval)
    if tuple(sorted(registered)) != _CORE_DATASETS:
        raise Data02PublicationToleranceEvidenceError(
            "numeric tolerance policy registry must contain exactly the four core datasets"
        )
    return registered, hashlib.sha256(payload).hexdigest()


def _parse_dataset(
    value: object,
    *,
    denominator: int,
    universe_hash: str,
    captured_at: datetime,
    registered_policies: Mapping[str, tuple[NumericTolerancePolicy, dict[str, str]]],
) -> Data02PublicationToleranceDataset:
    raw = _mapping(value, "datasets[]")
    _exact_keys(raw, _DATASET_KEYS, "datasets[]")
    dataset_key = _token(raw["dataset_key"], "dataset_key")
    observed_at = _utc(raw["observed_at"], f"{dataset_key}.observed_at")
    if observed_at > captured_at:
        raise Data02PublicationToleranceEvidenceError(
            f"{dataset_key}.observed_at cannot be after captured_at"
        )
    reference_source = _token(raw["reference_source"], "reference_source")
    observed_source = _token(raw["observed_source"], "observed_source")
    if reference_source == observed_source:
        raise Data02PublicationToleranceEvidenceError(
            f"{dataset_key} reference and observed sources must differ"
        )
    publication_raw = _mapping(raw["publication"], f"{dataset_key}.publication")
    _exact_keys(publication_raw, _PUBLICATION_KEYS, f"{dataset_key}.publication")
    member_count = _positive_int(publication_raw["member_count"], "publication.member_count")
    covered_asset_count = _positive_int(
        publication_raw["covered_asset_count"], "publication.covered_asset_count"
    )
    if covered_asset_count != denominator:
        raise Data02PublicationToleranceEvidenceError(
            f"{dataset_key} publication does not cover the frozen denominator"
        )
    policy_identity = _token(publication_raw["policy_identity"], "publication.policy_identity")
    published_at = _utc(publication_raw["published_at"], "publication.published_at")
    if published_at > captured_at:
        raise Data02PublicationToleranceEvidenceError(
            f"{dataset_key} publication.published_at cannot be after captured_at"
        )
    publication_policy = _parse_publication_policy(
        raw["publication_policy"],
        dataset_key=dataset_key,
        expected_identity=policy_identity,
    )
    tolerance_policy = _parse_tolerance_policy(raw["tolerance_policy"], dataset_key=dataset_key)
    registered = registered_policies.get(dataset_key)
    if registered is None or registered[0] != tolerance_policy:
        raise Data02PublicationToleranceEvidenceError(
            f"{dataset_key} tolerance policy is not the approved registry policy"
        )
    tolerance_approval = registered[1]
    members = _parse_members(raw["members"], dataset_key=dataset_key)
    if len(members) != member_count:
        raise Data02PublicationToleranceEvidenceError(
            f"{dataset_key} Publication member_count does not match member identities"
        )
    fact_identities = [(member.fact_table, member.fact_pk) for member in members]
    if len(fact_identities) != len(set(fact_identities)):
        raise Data02PublicationToleranceEvidenceError(
            f"{dataset_key} Publication fact identities must be unique"
        )
    try:
        validate_publication_evidence(
            publication_policy,
            members,
            published_at=published_at,
            knowledge_cutoff=captured_at,
        )
    except (TypeError, ValueError) as exc:
        raise Data02PublicationToleranceEvidenceError(str(exc)) from exc
    covered_assets = {member.natural_key.split(":", 1)[0].strip().upper() for member in members}
    if len(covered_assets) != covered_asset_count:
        raise Data02PublicationToleranceEvidenceError(
            f"{dataset_key} covered_asset_count does not match member identities"
        )
    covered_asset_codes_hash = _covered_asset_codes_hash(covered_assets)
    if covered_asset_codes_hash != universe_hash:
        raise Data02PublicationToleranceEvidenceError(
            f"{dataset_key} covered assets do not match the frozen universe hash"
        )
    supplied_publication_hash = _digest(
        publication_raw["publication_hash"], "publication.publication_hash"
    )
    if (
        publication_hash(members, policy_identity=publication_policy.identity)
        != supplied_publication_hash
    ):
        raise Data02PublicationToleranceEvidenceError(
            f"{dataset_key} Publication hash does not match member identities"
        )
    publication_id = _token(publication_raw["publication_id"], "publication.publication_id")
    if publication_id != _current_publication_id(dataset_key, supplied_publication_hash):
        raise Data02PublicationToleranceEvidenceError(
            f"{dataset_key} Publication id does not match its canonical current identity"
        )
    tolerance_by_field = {field.field_name: field for field in tolerance_policy.fields}
    comparisons_raw = _sequence(raw["comparisons"], f"{dataset_key}.comparisons")
    comparisons: list[NumericToleranceComparison] = []
    identities: set[tuple[str, str]] = set()
    fields_by_natural_key: dict[str, set[str]] = {}
    for index, comparison_value in enumerate(comparisons_raw):
        comparison_raw = _mapping(comparison_value, f"comparisons[{index}]")
        _exact_keys(comparison_raw, _COMPARISON_KEYS, f"comparisons[{index}]")
        natural_key = _natural_key(comparison_raw["natural_key"], "comparison.natural_key")
        field_name = _token(comparison_raw["field_name"], "comparison.field_name")
        tolerance = tolerance_by_field.get(field_name)
        if tolerance is None:
            raise Data02PublicationToleranceEvidenceError(
                f"comparison field {field_name} is absent from tolerance policy"
            )
        identity = (natural_key, field_name)
        if identity in identities:
            raise Data02PublicationToleranceEvidenceError(
                "comparison natural_key/field identities must be unique"
            )
        identities.add(identity)
        fields_by_natural_key.setdefault(natural_key, set()).add(field_name)
        try:
            comparisons.append(
                compare_numeric_value(
                    natural_key=natural_key,
                    tolerance=tolerance,
                    unit=_token(comparison_raw["unit"], "comparison.unit"),
                    canonical_value=_decimal_input(
                        comparison_raw["canonical_value"], "comparison.canonical_value"
                    ),
                    observed_value=_decimal_input(
                        comparison_raw["observed_value"], "comparison.observed_value"
                    ),
                )
            )
        except (TypeError, ValueError) as exc:
            raise Data02PublicationToleranceEvidenceError(str(exc)) from exc
    expected_fields = set(tolerance_by_field)
    if len(fields_by_natural_key) != member_count or any(
        fields != expected_fields for fields in fields_by_natural_key.values()
    ):
        raise Data02PublicationToleranceEvidenceError(
            f"{dataset_key} comparison coverage must include every member and governed field"
        )
    if set(fields_by_natural_key) != {member.natural_key for member in members}:
        raise Data02PublicationToleranceEvidenceError(
            f"{dataset_key} comparison identities do not match Publication members"
        )
    ordered_comparisons = tuple(
        sorted(comparisons, key=lambda item: (item.natural_key, item.field_name))
    )
    expected_reference_snapshot_hash = _numeric_snapshot_hash(
        dataset_key=dataset_key,
        source=reference_source,
        value_kind="canonical",
        comparisons=ordered_comparisons,
    )
    expected_observed_snapshot_hash = _numeric_snapshot_hash(
        dataset_key=dataset_key,
        source=observed_source,
        value_kind="observed",
        comparisons=ordered_comparisons,
    )
    if (
        _digest(raw["reference_snapshot_hash"], "reference_snapshot_hash")
        != expected_reference_snapshot_hash
    ):
        raise Data02PublicationToleranceEvidenceError(
            f"{dataset_key} reference snapshot hash does not match compared values"
        )
    if (
        _digest(raw["observed_snapshot_hash"], "observed_snapshot_hash")
        != expected_observed_snapshot_hash
    ):
        raise Data02PublicationToleranceEvidenceError(
            f"{dataset_key} observed snapshot hash does not match compared values"
        )
    return Data02PublicationToleranceDataset(
        dataset_key=dataset_key,
        observed_at=observed_at,
        reference_source=reference_source,
        observed_source=observed_source,
        reference_snapshot_hash=expected_reference_snapshot_hash,
        observed_snapshot_hash=expected_observed_snapshot_hash,
        publication_id=publication_id,
        publication_hash=supplied_publication_hash,
        published_at=published_at,
        member_count=member_count,
        covered_asset_count=covered_asset_count,
        covered_asset_codes_hash=covered_asset_codes_hash,
        publication_policy=publication_policy,
        tolerance_policy=tolerance_policy,
        tolerance_approval=tolerance_approval,
        members=members,
        member_identity_hash=_member_identity_hash(members),
        comparisons=ordered_comparisons,
    )


def parse_data02_publication_tolerance_snapshot(
    payload: bytes,
    *,
    policy_registry_payload: bytes,
    as_of: datetime | None = None,
) -> Data02PublicationToleranceEvidence:
    """Parse one external four-Publication snapshot without touching storage."""

    if type(payload) is not bytes or not payload:
        raise Data02PublicationToleranceEvidenceError("payload must be non-empty bytes")
    decoded = _decode_strict_json(payload, label="payload")
    raw = _mapping(decoded, "evidence")
    _exact_keys(raw, _TOP_LEVEL_KEYS, "evidence")
    if raw["schema_version"] != "data02-four-publication-tolerance-input.v1":
        raise Data02PublicationToleranceEvidenceError("schema_version is unsupported")
    if raw["read_mode"] != "select_only":
        raise Data02PublicationToleranceEvidenceError("read_mode must be select_only")
    cutoff = as_of or datetime.now(UTC)
    if cutoff.tzinfo is None or cutoff.utcoffset() != timedelta(0):
        raise Data02PublicationToleranceEvidenceError("as_of must use UTC")
    captured_at = _utc(raw["captured_at"], "captured_at")
    if captured_at > cutoff:
        raise Data02PublicationToleranceEvidenceError("captured_at is from the future")
    universe_raw = _mapping(raw["universe"], "universe")
    _exact_keys(universe_raw, _UNIVERSE_KEYS, "universe")
    denominator = _positive_int(universe_raw["denominator"], "universe.denominator")
    universe_hash = _digest(universe_raw["universe_hash"], "universe.universe_hash")
    registered_policies, policy_registry_sha256 = _parse_policy_registry(
        policy_registry_payload,
        captured_at=captured_at,
    )
    datasets = tuple(
        sorted(
            (
                _parse_dataset(
                    item,
                    denominator=denominator,
                    universe_hash=universe_hash,
                    captured_at=captured_at,
                    registered_policies=registered_policies,
                )
                for item in _sequence(raw["datasets"], "datasets")
            ),
            key=lambda item: item.dataset_key,
        )
    )
    dataset_keys = tuple(dataset.dataset_key for dataset in datasets)
    if dataset_keys != _CORE_DATASETS:
        raise Data02PublicationToleranceEvidenceError(
            "datasets must contain exactly the four core datasets"
        )
    for field_name, values in (
        ("publication_id", [dataset.publication_id for dataset in datasets]),
        ("publication_hash", [dataset.publication_hash for dataset in datasets]),
        (
            "publication_policy identity",
            [dataset.publication_policy.identity for dataset in datasets],
        ),
        (
            "tolerance_policy identity",
            [dataset.tolerance_policy.identity for dataset in datasets],
        ),
    ):
        if len(values) != len(set(values)):
            raise Data02PublicationToleranceEvidenceError(
                f"four-Publication {field_name} values must be unique"
            )
    return Data02PublicationToleranceEvidence(
        candidate=_parse_candidate(raw["candidate"]),
        captured_at=captured_at,
        denominator=denominator,
        universe_hash=universe_hash,
        policy_registry_sha256=policy_registry_sha256,
        datasets=datasets,
    )


def serialize_data02_publication_tolerance_evidence(
    report: Data02PublicationToleranceEvidence,
) -> bytes:
    """Serialize canonical four-Publication tolerance evidence bytes."""

    return json.dumps(
        report.to_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def data02_publication_tolerance_artifact_sha256(payload: bytes) -> str:
    """Return the content address for canonical tolerance evidence."""

    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "Data02PublicationToleranceDataset",
    "Data02PublicationToleranceEvidence",
    "Data02PublicationToleranceEvidenceError",
    "data02_publication_tolerance_artifact_sha256",
    "parse_data02_publication_tolerance_snapshot",
    "serialize_data02_publication_tolerance_evidence",
]
