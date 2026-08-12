"""Strict JSON codec for canonical historical Regime assignment evidence."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import cast

from apps.regime.domain.historical_assignment import (
    CanonicalRegimeSourceFact,
    HistoricalRegimeAssignment,
    HistoricalRegimeAssignmentDefinition,
    HistoricalRegimeAssignmentReceipt,
    PersistedHistoricalRegimeAssignmentDefinition,
    RegimeAssignmentCell,
    RegimeAssignmentExpectedRow,
    RegimeAssignmentFactRole,
    RegimeAssignmentPolicy,
    RegimeAssignmentSourceRule,
)


class HistoricalRegimeAssignmentCodecError(ValueError):
    """A persisted payload is malformed, non-canonical, or tampered."""


def encode_definition(
    value: PersistedHistoricalRegimeAssignmentDefinition,
) -> dict[str, object]:
    """Encode one complete persisted definition receipt."""

    value = value.validated_copy()
    definition = value.definition
    return {
        "schema": "regime-historical-assignment-definition-receipt.v1",
        "definition": {
            "definition_id": definition.definition_id,
            "definition_version": definition.definition_version,
            "artifact_id": definition.artifact_id,
            "artifact_hash": definition.artifact_hash,
            "pit_manifest_id": definition.pit_manifest_id,
            "pit_manifest_hash": definition.pit_manifest_hash,
            "policy": _encode_policy(definition.policy),
            "rows": [_encode_row(item) for item in definition.rows],
            "registered_at": _datetime_text(definition.registered_at),
            "valid_until": _datetime_text(definition.valid_until),
            "owner": "regime",
            "research_only": True,
            "must_not_publish_current": True,
            "must_not_use_for_decision": True,
            "must_not_execute": True,
            "content_hash": definition.content_hash,
        },
        "ledger_recorded_at": _datetime_text(value.ledger_recorded_at),
        "content_hash": value.content_hash,
    }


def decode_definition(
    payload: object,
) -> PersistedHistoricalRegimeAssignmentDefinition:
    """Strictly restore one complete definition and verify every seal."""

    try:
        root = _mapping(
            payload,
            "definition receipt",
            {"schema", "definition", "ledger_recorded_at", "content_hash"},
        )
        if root["schema"] != "regime-historical-assignment-definition-receipt.v1":
            raise ValueError("definition receipt schema differs")
        raw = _mapping(
            root["definition"],
            "definition",
            {
                "definition_id",
                "definition_version",
                "artifact_id",
                "artifact_hash",
                "pit_manifest_id",
                "pit_manifest_hash",
                "policy",
                "rows",
                "registered_at",
                "valid_until",
                "owner",
                "research_only",
                "must_not_publish_current",
                "must_not_use_for_decision",
                "must_not_execute",
                "content_hash",
            },
        )
        if (
            raw["owner"] != "regime"
            or raw["research_only"] is not True
            or raw["must_not_publish_current"] is not True
            or raw["must_not_use_for_decision"] is not True
            or raw["must_not_execute"] is not True
        ):
            raise ValueError("definition safety flags differ")
        rows_raw = _list(raw["rows"], "definition rows")
        definition = HistoricalRegimeAssignmentDefinition.create(
            definition_id=_text(raw["definition_id"], "definition_id"),
            definition_version=_text(raw["definition_version"], "definition_version"),
            artifact_id=_text(raw["artifact_id"], "artifact_id"),
            artifact_hash=_text(raw["artifact_hash"], "artifact_hash"),
            pit_manifest_id=_text(raw["pit_manifest_id"], "pit_manifest_id"),
            pit_manifest_hash=_text(raw["pit_manifest_hash"], "pit_manifest_hash"),
            policy=_decode_policy(raw["policy"]),
            rows=tuple(_decode_row(item) for item in rows_raw),
            registered_at=_datetime(raw["registered_at"], "registered_at"),
            valid_until=_datetime(raw["valid_until"], "valid_until"),
        )
        if definition.content_hash != _text(raw["content_hash"], "definition content_hash"):
            raise ValueError("definition content hash differs")
        value = PersistedHistoricalRegimeAssignmentDefinition.create(
            definition=definition,
            ledger_recorded_at=_datetime(root["ledger_recorded_at"], "ledger_recorded_at"),
        )
        if value.content_hash != _text(root["content_hash"], "receipt content_hash"):
            raise ValueError("definition receipt content hash differs")
        if encode_definition(value) != payload:
            raise ValueError("definition receipt payload is non-canonical")
        return value
    except (KeyError, TypeError, ValueError) as error:
        raise HistoricalRegimeAssignmentCodecError(
            "historical assignment definition payload is invalid"
        ) from error


def encode_receipt(value: HistoricalRegimeAssignmentReceipt) -> dict[str, object]:
    """Encode one exhaustive historical assignment receipt."""

    value = value.validated_copy()
    return {
        "schema": "regime-historical-assignment-receipt.v1",
        "receipt_id": value.receipt_id,
        "receipt_version": value.receipt_version,
        "definition_id": value.definition_id,
        "definition_version": value.definition_version,
        "definition_content_hash": value.definition_content_hash,
        "artifact_id": value.artifact_id,
        "artifact_hash": value.artifact_hash,
        "source_result_hash": value.source_result_hash,
        "pit_manifest_id": value.pit_manifest_id,
        "pit_manifest_hash": value.pit_manifest_hash,
        "pit_as_of": _datetime_text(value.pit_as_of),
        "recorded_at": _datetime_text(value.recorded_at),
        "assignments": [_encode_assignment(item) for item in value.assignments],
        "owner": "regime",
        "research_only": True,
        "must_not_publish_current": True,
        "must_not_use_for_decision": True,
        "must_not_execute": True,
        "content_hash": value.content_hash,
    }


def decode_receipt(payload: object) -> HistoricalRegimeAssignmentReceipt:
    """Strictly restore one assignment receipt and every nested source fact."""

    try:
        root = _mapping(
            payload,
            "assignment receipt",
            {
                "schema",
                "receipt_id",
                "receipt_version",
                "definition_id",
                "definition_version",
                "definition_content_hash",
                "artifact_id",
                "artifact_hash",
                "source_result_hash",
                "pit_manifest_id",
                "pit_manifest_hash",
                "pit_as_of",
                "recorded_at",
                "assignments",
                "owner",
                "research_only",
                "must_not_publish_current",
                "must_not_use_for_decision",
                "must_not_execute",
                "content_hash",
            },
        )
        if root["schema"] != "regime-historical-assignment-receipt.v1":
            raise ValueError("assignment receipt schema differs")
        if (
            root["owner"] != "regime"
            or root["research_only"] is not True
            or root["must_not_publish_current"] is not True
            or root["must_not_use_for_decision"] is not True
            or root["must_not_execute"] is not True
        ):
            raise ValueError("assignment receipt safety flags differ")
        assignments_raw = _list(root["assignments"], "receipt assignments")
        value = HistoricalRegimeAssignmentReceipt(
            receipt_id=_text(root["receipt_id"], "receipt_id"),
            receipt_version=_text(root["receipt_version"], "receipt_version"),
            definition_id=_text(root["definition_id"], "definition_id"),
            definition_version=_text(root["definition_version"], "definition_version"),
            definition_content_hash=_text(
                root["definition_content_hash"], "definition_content_hash"
            ),
            artifact_id=_text(root["artifact_id"], "artifact_id"),
            artifact_hash=_text(root["artifact_hash"], "artifact_hash"),
            source_result_hash=_text(root["source_result_hash"], "source_result_hash"),
            pit_manifest_id=_text(root["pit_manifest_id"], "pit_manifest_id"),
            pit_manifest_hash=_text(root["pit_manifest_hash"], "pit_manifest_hash"),
            pit_as_of=_datetime(root["pit_as_of"], "pit_as_of"),
            recorded_at=_datetime(root["recorded_at"], "recorded_at"),
            assignments=tuple(_decode_assignment(item) for item in assignments_raw),
        )
        if value.content_hash != _text(root["content_hash"], "receipt content_hash"):
            raise ValueError("assignment receipt content hash differs")
        if encode_receipt(value) != payload:
            raise ValueError("assignment receipt payload is non-canonical")
        return value
    except (KeyError, TypeError, ValueError) as error:
        raise HistoricalRegimeAssignmentCodecError(
            "historical assignment receipt payload is invalid"
        ) from error


def _encode_policy(value: RegimeAssignmentPolicy) -> dict[str, object]:
    value = value.validated_copy()
    return {
        "policy_id": value.policy_id,
        "policy_version": value.policy_version,
        "source_contract_id": value.source_contract_id,
        "source_contract_version": value.source_contract_version,
        "source_contract_hash": value.source_contract_hash,
        "growth_threshold": _decimal_text(value.growth_threshold),
        "inflation_threshold": _decimal_text(value.inflation_threshold),
        "cells": [
            {
                "growth_above_threshold": item.growth_above_threshold,
                "inflation_above_threshold": item.inflation_above_threshold,
                "regime_code": item.regime_code,
                "content_hash": item.content_hash,
            }
            for item in value.cells
        ],
        "content_hash": value.content_hash,
    }


def _decode_policy(payload: object) -> RegimeAssignmentPolicy:
    root = _mapping(
        payload,
        "policy",
        {
            "policy_id",
            "policy_version",
            "source_contract_id",
            "source_contract_version",
            "source_contract_hash",
            "growth_threshold",
            "inflation_threshold",
            "cells",
            "content_hash",
        },
    )
    cells: list[RegimeAssignmentCell] = []
    for raw_cell in _list(root["cells"], "policy cells"):
        raw = _mapping(
            raw_cell,
            "policy cell",
            {
                "growth_above_threshold",
                "inflation_above_threshold",
                "regime_code",
                "content_hash",
            },
        )
        growth = _bool(raw["growth_above_threshold"], "growth_above_threshold")
        inflation = _bool(raw["inflation_above_threshold"], "inflation_above_threshold")
        cell = RegimeAssignmentCell(
            growth_above_threshold=growth,
            inflation_above_threshold=inflation,
            regime_code=_text(raw["regime_code"], "regime_code"),
        )
        if cell.content_hash != _text(raw["content_hash"], "cell content_hash"):
            raise ValueError("policy cell content hash differs")
        cells.append(cell)
    value = RegimeAssignmentPolicy.create(
        policy_id=_text(root["policy_id"], "policy_id"),
        policy_version=_text(root["policy_version"], "policy_version"),
        source_contract_id=_text(root["source_contract_id"], "source_contract_id"),
        source_contract_version=_text(root["source_contract_version"], "source_contract_version"),
        source_contract_hash=_text(root["source_contract_hash"], "source_contract_hash"),
        growth_threshold=_decimal(root["growth_threshold"], "growth_threshold"),
        inflation_threshold=_decimal(root["inflation_threshold"], "inflation_threshold"),
        cells=tuple(cells),
    )
    if value.content_hash != _text(root["content_hash"], "policy content_hash"):
        raise ValueError("policy content hash differs")
    return value


def _encode_row(value: RegimeAssignmentExpectedRow) -> dict[str, object]:
    return {
        "fold_id": value.fold_id,
        "row_id": value.row_id,
        "observation_at": _datetime_text(value.observation_at),
        "source_rules": [
            {
                "role": item.role.value,
                "dataset_key": item.dataset_key,
                "business_key": item.business_key,
                "expected_unit": item.expected_unit,
                "content_hash": item.content_hash,
            }
            for item in value.source_rules
        ],
        "content_hash": value.content_hash,
    }


def _decode_row(payload: object) -> RegimeAssignmentExpectedRow:
    root = _mapping(
        payload,
        "definition row",
        {"fold_id", "row_id", "observation_at", "source_rules", "content_hash"},
    )
    rules: list[RegimeAssignmentSourceRule] = []
    for raw_rule in _list(root["source_rules"], "source rules"):
        raw = _mapping(
            raw_rule,
            "source rule",
            {"role", "dataset_key", "business_key", "expected_unit", "content_hash"},
        )
        rule = RegimeAssignmentSourceRule(
            role=RegimeAssignmentFactRole(_text(raw["role"], "source role")),
            dataset_key=_text(raw["dataset_key"], "dataset_key"),
            business_key=_text(raw["business_key"], "business_key"),
            expected_unit=_text(raw["expected_unit"], "expected_unit"),
        )
        if rule.content_hash != _text(raw["content_hash"], "source rule content_hash"):
            raise ValueError("source rule content hash differs")
        rules.append(rule)
    value = RegimeAssignmentExpectedRow(
        fold_id=_text(root["fold_id"], "fold_id"),
        row_id=_text(root["row_id"], "row_id"),
        observation_at=_datetime(root["observation_at"], "observation_at"),
        source_rules=tuple(rules),
    )
    if value.content_hash != _text(root["content_hash"], "row content_hash"):
        raise ValueError("definition row content hash differs")
    return value


def _encode_assignment(value: HistoricalRegimeAssignment) -> dict[str, object]:
    return {
        "fold_id": value.fold_id,
        "row_id": value.row_id,
        "observation_at": _datetime_text(value.observation_at),
        "predicted_value": _decimal_text(value.predicted_value),
        "actual_value": _decimal_text(value.actual_value),
        "actual_fact": _encode_fact(value.actual_fact),
        "growth_fact": _encode_fact(value.growth_fact),
        "inflation_fact": _encode_fact(value.inflation_fact),
        "regime_code": value.regime_code,
        "regime_version": value.regime_version,
        "regime_content_hash": value.regime_content_hash,
        "content_hash": value.content_hash,
    }


def _decode_assignment(payload: object) -> HistoricalRegimeAssignment:
    root = _mapping(
        payload,
        "assignment",
        {
            "fold_id",
            "row_id",
            "observation_at",
            "predicted_value",
            "actual_value",
            "actual_fact",
            "growth_fact",
            "inflation_fact",
            "regime_code",
            "regime_version",
            "regime_content_hash",
            "content_hash",
        },
    )
    value = HistoricalRegimeAssignment(
        fold_id=_text(root["fold_id"], "fold_id"),
        row_id=_text(root["row_id"], "row_id"),
        observation_at=_datetime(root["observation_at"], "observation_at"),
        predicted_value=_decimal(root["predicted_value"], "predicted_value"),
        actual_value=_decimal(root["actual_value"], "actual_value"),
        actual_fact=_decode_fact(root["actual_fact"]),
        growth_fact=_decode_fact(root["growth_fact"]),
        inflation_fact=_decode_fact(root["inflation_fact"]),
        regime_code=_text(root["regime_code"], "regime_code"),
        regime_version=_text(root["regime_version"], "regime_version"),
        regime_content_hash=_text(root["regime_content_hash"], "regime_content_hash"),
    )
    if value.content_hash != _text(root["content_hash"], "assignment content_hash"):
        raise ValueError("assignment content hash differs")
    return value


def _encode_fact(value: CanonicalRegimeSourceFact) -> dict[str, object]:
    return {
        "role": value.role.value,
        "dataset_key": value.dataset_key,
        "business_key": value.business_key,
        "fact_id": value.fact_id,
        "fact_version": value.fact_version,
        "content_hash": value.content_hash,
        "pit_manifest_id": value.pit_manifest_id,
        "pit_manifest_hash": value.pit_manifest_hash,
        "effective_at": _datetime_text(value.effective_at),
        "available_at": _datetime_text(value.available_at),
        "owner_recorded_at": _datetime_text(value.owner_recorded_at),
        "value": _decimal_text(value.value),
        "unit": value.unit,
        "verified": True,
        "evidence_hash": value.evidence_hash,
    }


def _decode_fact(payload: object) -> CanonicalRegimeSourceFact:
    root = _mapping(
        payload,
        "source fact",
        {
            "role",
            "dataset_key",
            "business_key",
            "fact_id",
            "fact_version",
            "content_hash",
            "pit_manifest_id",
            "pit_manifest_hash",
            "effective_at",
            "available_at",
            "owner_recorded_at",
            "value",
            "unit",
            "verified",
            "evidence_hash",
        },
    )
    value = CanonicalRegimeSourceFact(
        role=RegimeAssignmentFactRole(_text(root["role"], "fact role")),
        dataset_key=_text(root["dataset_key"], "dataset_key"),
        business_key=_text(root["business_key"], "business_key"),
        fact_id=_text(root["fact_id"], "fact_id"),
        fact_version=_text(root["fact_version"], "fact_version"),
        content_hash=_text(root["content_hash"], "fact content_hash"),
        pit_manifest_id=_text(root["pit_manifest_id"], "pit_manifest_id"),
        pit_manifest_hash=_text(root["pit_manifest_hash"], "pit_manifest_hash"),
        effective_at=_datetime(root["effective_at"], "effective_at"),
        available_at=_datetime(root["available_at"], "available_at"),
        owner_recorded_at=_datetime(root["owner_recorded_at"], "owner_recorded_at"),
        value=_decimal(root["value"], "fact value"),
        unit=_text(root["unit"], "unit"),
        verified=_bool(root["verified"], "verified"),
    )
    if value.evidence_hash != _text(root["evidence_hash"], "fact evidence_hash"):
        raise ValueError("source fact evidence hash differs")
    return value


def _mapping(
    value: object,
    label: str,
    expected_keys: set[str],
) -> dict[str, object]:
    if type(value) is not dict or set(value) != expected_keys:
        raise ValueError(f"{label} keys differ")
    return cast(dict[str, object], value)


def _list(value: object, label: str) -> list[object]:
    if type(value) is not list:
        raise ValueError(f"{label} must be a list")
    return cast(list[object], value)


def _text(value: object, label: str) -> str:
    if type(value) is not str:
        raise ValueError(f"{label} must be text")
    return value


def _bool(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{label} must be boolean")
    return value


def _decimal(value: object, label: str) -> Decimal:
    if type(value) is not str:
        raise ValueError(f"{label} must be canonical decimal text")
    parsed = Decimal(value)
    if not parsed.is_finite() or _decimal_text(parsed) != value:
        raise ValueError(f"{label} must be canonical decimal text")
    return parsed


def _datetime(value: object, label: str) -> datetime:
    if type(value) is not str:
        raise ValueError(f"{label} must be datetime text")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None or _datetime_text(parsed) != value:
        raise ValueError(f"{label} must be canonical UTC datetime text")
    return parsed


def _datetime_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


__all__ = [
    "HistoricalRegimeAssignmentCodecError",
    "decode_definition",
    "decode_receipt",
    "encode_definition",
    "encode_receipt",
]
