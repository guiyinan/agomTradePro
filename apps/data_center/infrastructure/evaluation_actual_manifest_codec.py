"""Strict canonical JSON codec for evaluation actual ledgers."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

from apps.data_center.domain.evaluation_actual_manifest import (
    ActualEvidenceIdentity,
    CanonicalEvaluationActualFact,
    EvaluationActualCoveragePolicy,
    EvaluationActualSourceDefinition,
    ExpectedActualMemberRule,
    MaterializedEvaluationActualManifest,
    PersistedEvaluationActualSourceDefinition,
)


class EvaluationActualCodecError(ValueError):
    """Canonical payload shape, type or live seal is invalid."""


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _decimal_text(value: Decimal) -> str:
    normalized = value.normalize()
    text = format(normalized, "f")
    return "0" if text in {"-0", ""} else text


def _mapping(
    value: object,
    *,
    keys: frozenset[str],
    label: str,
) -> dict[str, object]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise EvaluationActualCodecError(f"{label} must be an object")
    narrowed = dict(value)
    if frozenset(narrowed) != keys:
        raise EvaluationActualCodecError(f"{label} has an invalid shape")
    return narrowed


def _list(value: object, label: str) -> list[object]:
    if type(value) is not list:
        raise EvaluationActualCodecError(f"{label} must be a list")
    return list(value)


def _string(value: object, label: str) -> str:
    if type(value) is not str:
        raise EvaluationActualCodecError(f"{label} must be a string")
    return value


def _digest(value: object, label: str) -> str:
    text = _string(value, label)
    if text != text.lower():
        raise EvaluationActualCodecError(f"{label} must use canonical lowercase hex")
    return text


def _bool(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise EvaluationActualCodecError(f"{label} must be a bool")
    return value


def _int(value: object, label: str) -> int:
    if type(value) is not int:
        raise EvaluationActualCodecError(f"{label} must be an integer")
    return value


def _datetime(value: object, label: str) -> datetime:
    text = _string(value, label)
    if not text.endswith("Z"):
        raise EvaluationActualCodecError(f"{label} must be canonical UTC")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as error:
        raise EvaluationActualCodecError(f"{label} is not a datetime") from error
    if _utc_text(parsed) != text:
        raise EvaluationActualCodecError(f"{label} is not canonical UTC")
    return parsed


def _date(value: object, label: str) -> date:
    text = _string(value, label)
    try:
        parsed = date.fromisoformat(text)
    except ValueError as error:
        raise EvaluationActualCodecError(f"{label} is not a date") from error
    if parsed.isoformat() != text:
        raise EvaluationActualCodecError(f"{label} is not canonical")
    return parsed


def _decimal(value: object, label: str) -> Decimal:
    text = _string(value, label)
    try:
        parsed = Decimal(text)
    except InvalidOperation as error:
        raise EvaluationActualCodecError(f"{label} is not a Decimal") from error
    if not parsed.is_finite() or _decimal_text(parsed) != text:
        raise EvaluationActualCodecError(f"{label} is not canonical")
    return parsed


_IDENTITY_KEYS = frozenset({"stable_id", "version", "content_hash"})


def _encode_identity(identity: ActualEvidenceIdentity) -> dict[str, object]:
    identity = identity.validated_copy()
    return {
        "stable_id": identity.stable_id,
        "version": identity.version,
        "content_hash": identity.content_hash.lower(),
    }


def _decode_identity(value: object, label: str) -> ActualEvidenceIdentity:
    payload = _mapping(value, keys=_IDENTITY_KEYS, label=label)
    try:
        return ActualEvidenceIdentity(
            stable_id=_string(payload["stable_id"], f"{label}.stable_id"),
            version=_string(payload["version"], f"{label}.version"),
            content_hash=_digest(payload["content_hash"], f"{label}.content_hash"),
        )
    except (TypeError, ValueError) as error:
        raise EvaluationActualCodecError(f"{label} is invalid") from error


_DEFINITION_ROOT_KEYS = frozenset({"schema", "definition", "ledger_recorded_at", "record_hash"})
_DEFINITION_KEYS = frozenset(
    {
        "source_id",
        "source_version",
        "source_content_hash",
        "owner",
        "dataset",
        "subject_code",
        "industry_code",
        "calendar",
        "knowledge_scope",
        "expected_members",
        "coverage_policy",
        "registered_at",
        "valid_until",
        "research_only",
        "must_not_publish_current",
        "must_not_use_for_decision",
        "must_not_execute",
    }
)
_RULE_KEYS = frozenset({"period_end", "metric_code", "member", "vintage"})
_POLICY_KEYS = frozenset(
    {
        "require_verified",
        "minimum_coverage_ratio",
        "maximum_missing_count",
        "maximum_estimated_count",
        "maximum_unknown_count",
    }
)


def encode_persisted_evaluation_actual_source_definition(
    record: PersistedEvaluationActualSourceDefinition,
) -> dict[str, object]:
    """Encode one live-validated source-definition record."""

    if type(record) is not PersistedEvaluationActualSourceDefinition:
        raise EvaluationActualCodecError("source record must use the exact domain type")
    record = record.validated_copy()
    definition = record.definition
    return {
        "schema": "data-center.evaluation-actual-source-record.v1",
        "definition": {
            "source_id": definition.source_id,
            "source_version": definition.source_version,
            "source_content_hash": definition.source_content_hash.lower(),
            "owner": definition.owner,
            "dataset": definition.dataset,
            "subject_code": definition.subject_code,
            "industry_code": definition.industry_code,
            "calendar": _encode_identity(definition.calendar),
            "knowledge_scope": definition.knowledge_scope,
            "expected_members": [
                {
                    "period_end": item.period_end.isoformat(),
                    "metric_code": item.metric_code,
                    "member": _encode_identity(item.member),
                    "vintage": _encode_identity(item.vintage),
                }
                for item in definition.expected_members
            ],
            "coverage_policy": {
                "require_verified": definition.coverage_policy.require_verified,
                "minimum_coverage_ratio": _decimal_text(
                    definition.coverage_policy.minimum_coverage_ratio
                ),
                "maximum_missing_count": (definition.coverage_policy.maximum_missing_count),
                "maximum_estimated_count": (definition.coverage_policy.maximum_estimated_count),
                "maximum_unknown_count": (definition.coverage_policy.maximum_unknown_count),
            },
            "registered_at": _utc_text(definition.registered_at),
            "valid_until": _utc_text(definition.valid_until),
            "research_only": definition.research_only,
            "must_not_publish_current": definition.must_not_publish_current,
            "must_not_use_for_decision": definition.must_not_use_for_decision,
            "must_not_execute": definition.must_not_execute,
        },
        "ledger_recorded_at": _utc_text(record.ledger_recorded_at),
        "record_hash": record.record_hash.lower(),
    }


def decode_persisted_evaluation_actual_source_definition(
    value: object,
) -> PersistedEvaluationActualSourceDefinition:
    """Strictly decode and live-reseal one source-definition record."""

    try:
        root = _mapping(value, keys=_DEFINITION_ROOT_KEYS, label="source record")
        if root["schema"] != "data-center.evaluation-actual-source-record.v1":
            raise EvaluationActualCodecError("source record schema is unsupported")
        payload = _mapping(root["definition"], keys=_DEFINITION_KEYS, label="source definition")
        rules = tuple(
            _decode_rule(item, index)
            for index, item in enumerate(_list(payload["expected_members"], "expected_members"))
        )
        policy_payload = _mapping(
            payload["coverage_policy"], keys=_POLICY_KEYS, label="coverage_policy"
        )
        policy = EvaluationActualCoveragePolicy(
            require_verified=_bool(policy_payload["require_verified"], "require_verified"),
            minimum_coverage_ratio=_decimal(
                policy_payload["minimum_coverage_ratio"], "minimum_coverage_ratio"
            ),
            maximum_missing_count=_int(
                policy_payload["maximum_missing_count"], "maximum_missing_count"
            ),
            maximum_estimated_count=_int(
                policy_payload["maximum_estimated_count"], "maximum_estimated_count"
            ),
            maximum_unknown_count=_int(
                policy_payload["maximum_unknown_count"], "maximum_unknown_count"
            ),
        )
        definition = EvaluationActualSourceDefinition.create(
            source_id=_string(payload["source_id"], "source_id"),
            source_version=_string(payload["source_version"], "source_version"),
            owner=_string(payload["owner"], "owner"),
            dataset=_string(payload["dataset"], "dataset"),
            subject_code=_string(payload["subject_code"], "subject_code"),
            industry_code=_string(payload["industry_code"], "industry_code"),
            calendar=_decode_identity(payload["calendar"], "calendar"),
            knowledge_scope=_string(payload["knowledge_scope"], "knowledge_scope"),
            expected_members=rules,
            coverage_policy=policy,
            registered_at=_datetime(payload["registered_at"], "registered_at"),
            valid_until=_datetime(payload["valid_until"], "valid_until"),
        )
        if (
            definition.source_content_hash.lower()
            != _digest(payload["source_content_hash"], "source_content_hash")
            or definition.research_only != _bool(payload["research_only"], "research_only")
            or definition.must_not_publish_current
            != _bool(payload["must_not_publish_current"], "must_not_publish_current")
            or definition.must_not_use_for_decision
            != _bool(payload["must_not_use_for_decision"], "must_not_use_for_decision")
            or definition.must_not_execute != _bool(payload["must_not_execute"], "must_not_execute")
        ):
            raise EvaluationActualCodecError("source definition seal differs")
        record = PersistedEvaluationActualSourceDefinition.create(
            definition=definition,
            ledger_recorded_at=_datetime(root["ledger_recorded_at"], "ledger_recorded_at"),
        )
        if record.record_hash.lower() != _digest(root["record_hash"], "record_hash"):
            raise EvaluationActualCodecError("source record hash differs")
        return record
    except EvaluationActualCodecError:
        raise
    except (KeyError, TypeError, ValueError) as error:
        raise EvaluationActualCodecError("source record is invalid") from error


def _decode_rule(value: object, index: int) -> ExpectedActualMemberRule:
    label = f"expected_members[{index}]"
    payload = _mapping(value, keys=_RULE_KEYS, label=label)
    return ExpectedActualMemberRule(
        period_end=_date(payload["period_end"], f"{label}.period_end"),
        metric_code=_string(payload["metric_code"], f"{label}.metric_code"),
        member=_decode_identity(payload["member"], f"{label}.member"),
        vintage=_decode_identity(payload["vintage"], f"{label}.vintage"),
    )


_MANIFEST_KEYS = frozenset(
    {
        "schema",
        "manifest_id",
        "manifest_version",
        "manifest_content_hash",
        "source_definition",
        "owner",
        "dataset",
        "subject_code",
        "industry_code",
        "calendar",
        "as_of_time",
        "produced_at",
        "valid_until",
        "knowledge_scope",
        "is_verified",
        "coverage_ratio",
        "missing_count",
        "estimated_count",
        "unknown_count",
        "facts",
        "selected_versions_hash",
        "research_only",
        "must_not_publish_current",
        "must_not_use_for_decision",
        "must_not_execute",
        "receipt_hash",
    }
)
_FACT_KEYS = frozenset(
    {
        "dataset",
        "subject_code",
        "industry_code",
        "period_end",
        "metric_code",
        "value",
        "unit",
        "source_fact",
        "revision_number",
        "effective_at",
        "available_at",
        "member",
        "vintage",
        "quality",
    }
)


def encode_materialized_evaluation_actual_manifest(
    manifest: MaterializedEvaluationActualManifest,
) -> dict[str, object]:
    """Encode one complete live-validated materialization receipt."""

    if type(manifest) is not MaterializedEvaluationActualManifest:
        raise EvaluationActualCodecError("actual manifest must use the exact domain type")
    manifest = manifest.validated_copy()
    return {
        "schema": "data-center.evaluation-actual-manifest-receipt.v1",
        "manifest_id": manifest.manifest_id,
        "manifest_version": manifest.manifest_version,
        "manifest_content_hash": manifest.manifest_content_hash.lower(),
        "source_definition": _encode_identity(manifest.source_definition),
        "owner": manifest.owner,
        "dataset": manifest.dataset,
        "subject_code": manifest.subject_code,
        "industry_code": manifest.industry_code,
        "calendar": _encode_identity(manifest.calendar),
        "as_of_time": _utc_text(manifest.as_of_time),
        "produced_at": _utc_text(manifest.produced_at),
        "valid_until": _utc_text(manifest.valid_until),
        "knowledge_scope": manifest.knowledge_scope,
        "is_verified": manifest.is_verified,
        "coverage_ratio": _decimal_text(manifest.coverage_ratio),
        "missing_count": manifest.missing_count,
        "estimated_count": manifest.estimated_count,
        "unknown_count": manifest.unknown_count,
        "facts": [_encode_fact(item) for item in manifest.facts],
        "selected_versions_hash": manifest.selected_versions_hash.lower(),
        "research_only": manifest.research_only,
        "must_not_publish_current": manifest.must_not_publish_current,
        "must_not_use_for_decision": manifest.must_not_use_for_decision,
        "must_not_execute": manifest.must_not_execute,
        "receipt_hash": manifest.receipt_hash.lower(),
    }


def decode_materialized_evaluation_actual_manifest(
    value: object,
) -> MaterializedEvaluationActualManifest:
    """Strictly decode and live-reseal one materialization receipt."""

    try:
        payload = _mapping(value, keys=_MANIFEST_KEYS, label="actual manifest")
        if payload["schema"] != "data-center.evaluation-actual-manifest-receipt.v1":
            raise EvaluationActualCodecError("actual manifest schema is unsupported")
        facts = tuple(
            _decode_fact(item, index) for index, item in enumerate(_list(payload["facts"], "facts"))
        )
        manifest = MaterializedEvaluationActualManifest(
            manifest_id=_string(payload["manifest_id"], "manifest_id"),
            manifest_version=_string(payload["manifest_version"], "manifest_version"),
            manifest_content_hash=_digest(
                payload["manifest_content_hash"], "manifest_content_hash"
            ),
            source_definition=_decode_identity(payload["source_definition"], "source_definition"),
            owner=_string(payload["owner"], "owner"),
            dataset=_string(payload["dataset"], "dataset"),
            subject_code=_string(payload["subject_code"], "subject_code"),
            industry_code=_string(payload["industry_code"], "industry_code"),
            calendar=_decode_identity(payload["calendar"], "calendar"),
            as_of_time=_datetime(payload["as_of_time"], "as_of_time"),
            produced_at=_datetime(payload["produced_at"], "produced_at"),
            valid_until=_datetime(payload["valid_until"], "valid_until"),
            knowledge_scope=_string(payload["knowledge_scope"], "knowledge_scope"),
            is_verified=_bool(payload["is_verified"], "is_verified"),
            coverage_ratio=_decimal(payload["coverage_ratio"], "coverage_ratio"),
            missing_count=_int(payload["missing_count"], "missing_count"),
            estimated_count=_int(payload["estimated_count"], "estimated_count"),
            unknown_count=_int(payload["unknown_count"], "unknown_count"),
            facts=facts,
            selected_versions_hash=_digest(
                payload["selected_versions_hash"], "selected_versions_hash"
            ),
            research_only=_bool(payload["research_only"], "research_only"),
            must_not_publish_current=_bool(
                payload["must_not_publish_current"], "must_not_publish_current"
            ),
            must_not_use_for_decision=_bool(
                payload["must_not_use_for_decision"], "must_not_use_for_decision"
            ),
            must_not_execute=_bool(payload["must_not_execute"], "must_not_execute"),
        )
        if manifest.receipt_hash.lower() != _digest(payload["receipt_hash"], "receipt_hash"):
            raise EvaluationActualCodecError("actual manifest receipt hash differs")
        return manifest
    except EvaluationActualCodecError:
        raise
    except (KeyError, TypeError, ValueError) as error:
        raise EvaluationActualCodecError("actual manifest is invalid") from error


def _encode_fact(fact: CanonicalEvaluationActualFact) -> dict[str, object]:
    fact = fact.validated_copy()
    if fact.member is None or fact.vintage is None:
        raise EvaluationActualCodecError("materialized fact identities are incomplete")
    return {
        "dataset": fact.dataset,
        "subject_code": fact.subject_code,
        "industry_code": fact.industry_code,
        "period_end": fact.period_end.isoformat(),
        "metric_code": fact.metric_code,
        "value": _decimal_text(fact.value),
        "unit": fact.unit,
        "source_fact": _encode_identity(fact.source_fact),
        "revision_number": fact.revision_number,
        "effective_at": _utc_text(fact.effective_at),
        "available_at": _utc_text(fact.available_at),
        "member": _encode_identity(fact.member),
        "vintage": _encode_identity(fact.vintage),
        "quality": fact.quality,
    }


def _decode_fact(value: object, index: int) -> CanonicalEvaluationActualFact:
    label = f"facts[{index}]"
    payload = _mapping(value, keys=_FACT_KEYS, label=label)
    return CanonicalEvaluationActualFact(
        dataset=_string(payload["dataset"], f"{label}.dataset"),
        subject_code=_string(payload["subject_code"], f"{label}.subject_code"),
        industry_code=_string(payload["industry_code"], f"{label}.industry_code"),
        period_end=_date(payload["period_end"], f"{label}.period_end"),
        metric_code=_string(payload["metric_code"], f"{label}.metric_code"),
        value=_decimal(payload["value"], f"{label}.value"),
        unit=_string(payload["unit"], f"{label}.unit"),
        source_fact=_decode_identity(payload["source_fact"], f"{label}.source_fact"),
        revision_number=_int(payload["revision_number"], f"{label}.revision_number"),
        effective_at=_datetime(payload["effective_at"], f"{label}.effective_at"),
        available_at=_datetime(payload["available_at"], f"{label}.available_at"),
        member=_decode_identity(payload["member"], f"{label}.member"),
        vintage=_decode_identity(payload["vintage"], f"{label}.vintage"),
        quality=_string(payload["quality"], f"{label}.quality"),
    )


__all__ = [
    "EvaluationActualCodecError",
    "decode_materialized_evaluation_actual_manifest",
    "decode_persisted_evaluation_actual_source_definition",
    "encode_materialized_evaluation_actual_manifest",
    "encode_persisted_evaluation_actual_source_definition",
]
