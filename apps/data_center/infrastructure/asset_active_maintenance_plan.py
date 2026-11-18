"""Strict hash-bound JSON decoding for one explicit AssetMaster maintenance plan."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import date, datetime
from typing import cast

from apps.data_center.domain.asset_active_maintenance import (
    AssetActiveMaintenanceContractError,
    AssetMaintenanceTarget,
    AssetMasterMaintenancePlan,
    SourceOccurrencePin,
)
from apps.data_center.domain.entities import RawAuditReference
from apps.data_center.domain.instrument_reference_source import (
    InstrumentReferenceExchangeSuffixCrosswalk,
    InstrumentReferenceProviderContract,
)


def decode_plan(raw: bytes, *, expected_sha256: str) -> AssetMasterMaintenancePlan:
    """Decode one exact JSON plan after verifying its externally pinned file hash."""

    try:
        return _decode_plan(raw, expected_sha256=expected_sha256)
    except AssetActiveMaintenanceContractError:
        raise
    except (TypeError, ValueError) as error:
        raise AssetActiveMaintenanceContractError("plan_contract_invalid") from error


def _decode_plan(raw: bytes, *, expected_sha256: str) -> AssetMasterMaintenancePlan:
    """Validate the complete wire shape before constructing typed plan values."""

    if type(raw) is not bytes or not raw or len(raw) > 64 * 1024:
        raise AssetActiveMaintenanceContractError("plan_file_size_invalid")
    actual_sha256 = hashlib.sha256(raw).hexdigest()
    if actual_sha256 != expected_sha256:
        raise AssetActiveMaintenanceContractError("plan_file_hash_mismatch")
    try:
        parsed = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise AssetActiveMaintenanceContractError("plan_json_invalid") from error
    root = _object(
        parsed,
        {
            "schema",
            "target_date",
            "targets",
            "provider_contract",
            "crosswalk",
            "source_occurrences",
        },
    )
    if root["schema"] != "data-center.asset-active-maintenance-plan.v1":
        raise AssetActiveMaintenanceContractError("plan_schema_unsupported")
    contract_value = _object(
        root["provider_contract"],
        {
            "contract_id",
            "contract_version",
            "provider_name",
            "dataset_key",
            "api_name",
            "fields",
            "exchange_scope",
            "list_status_scope",
            "content_hash",
        },
    )
    contract = InstrumentReferenceProviderContract(
        contract_id=_text(contract_value["contract_id"]),
        contract_version=_text(contract_value["contract_version"]),
        provider_name=_text(contract_value["provider_name"]),
        dataset_key=_text(contract_value["dataset_key"]),
        api_name=_text(contract_value["api_name"]),
        fields=_text_tuple(contract_value["fields"]),
        exchange_scope=_text_tuple(contract_value["exchange_scope"]),
        list_status_scope=_text_tuple(contract_value["list_status_scope"]),
    )
    if contract.content_hash != _text(contract_value["content_hash"]):
        raise AssetActiveMaintenanceContractError("provider_contract_hash_mismatch")
    crosswalk_value = _object(
        root["crosswalk"],
        {"crosswalk_id", "crosswalk_version", "exchange_suffix_pairs", "content_hash"},
    )
    crosswalk = InstrumentReferenceExchangeSuffixCrosswalk(
        crosswalk_id=_text(crosswalk_value["crosswalk_id"]),
        crosswalk_version=_text(crosswalk_value["crosswalk_version"]),
        exchange_suffix_pairs=_pair_tuple(crosswalk_value["exchange_suffix_pairs"]),
    )
    if crosswalk.content_hash != _text(crosswalk_value["content_hash"]):
        raise AssetActiveMaintenanceContractError("source_crosswalk_hash_mismatch")
    targets_value = _array(root["targets"])
    targets = tuple(_target(item) for item in targets_value)
    occurrences_value = _array(root["source_occurrences"])
    occurrences = tuple(_occurrence(item) for item in occurrences_value)
    try:
        target_date = date.fromisoformat(_text(root["target_date"]))
        return AssetMasterMaintenancePlan(
            plan_file_sha256=actual_sha256,
            target_date=target_date,
            targets=targets,
            provider_contract=contract,
            crosswalk=crosswalk,
            source_occurrences=occurrences,
        )
    except (TypeError, ValueError) as error:
        if isinstance(error, AssetActiveMaintenanceContractError):
            raise
        raise AssetActiveMaintenanceContractError("plan_contract_invalid") from error


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject duplicate JSON properties rather than silently taking the last value."""

    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    """Reject non-standard JSON NaN and Infinity tokens."""

    raise ValueError(f"invalid_json_constant:{value}")


def _object(value: object, expected_keys: set[str]) -> Mapping[str, object]:
    """Narrow one JSON object and reject missing or additional keys."""

    if type(value) is not dict or set(cast(dict[str, object], value)) != expected_keys:
        raise AssetActiveMaintenanceContractError("plan_object_shape_invalid")
    return cast(dict[str, object], value)


def _array(value: object) -> list[object]:
    """Narrow a JSON array without accepting tuples or text sequences."""

    if type(value) is not list:
        raise AssetActiveMaintenanceContractError("plan_array_invalid")
    return cast(list[object], value)


def _text(value: object) -> str:
    """Require exact nonempty text without trimming or coercion."""

    if type(value) is not str or not value or value.strip() != value:
        raise AssetActiveMaintenanceContractError("plan_text_invalid")
    return value


def _integer(value: object) -> int:
    """Require a JSON integer while rejecting booleans."""

    if type(value) is not int:
        raise AssetActiveMaintenanceContractError("plan_integer_invalid")
    return value


def _text_tuple(value: object) -> tuple[str, ...]:
    """Narrow a list of exact strings to the contract's ordered tuple."""

    return tuple(_text(item) for item in _array(value))


def _pair_tuple(value: object) -> tuple[tuple[str, str], ...]:
    """Narrow exact two-string exchange/suffix pairs."""

    pairs: list[tuple[str, str]] = []
    for item in _array(value):
        pair = _array(item)
        if len(pair) != 2:
            raise AssetActiveMaintenanceContractError("plan_crosswalk_pair_invalid")
        pairs.append((_text(pair[0]), _text(pair[1])))
    return tuple(pairs)


def _target(value: object) -> AssetMaintenanceTarget:
    """Decode one exact planned asset row and current delist-date expectation."""

    item = _object(
        value,
        {
            "code",
            "asset_pk",
            "exchange",
            "expected_delist_date",
            "expected_updated_at",
            "expected_preserved_state_sha256",
        },
    )
    raw_date = item["expected_delist_date"]
    if raw_date is not None and type(raw_date) is not str:
        raise AssetActiveMaintenanceContractError("plan_target_date_invalid")
    if raw_date == "":
        raise AssetActiveMaintenanceContractError("plan_target_date_invalid")
    return AssetMaintenanceTarget(
        code=_text(item["code"]),
        asset_pk=_integer(item["asset_pk"]),
        exchange=_text(item["exchange"]),
        expected_delist_date=date.fromisoformat(raw_date) if raw_date else None,
        expected_updated_at=datetime.fromisoformat(_text(item["expected_updated_at"])),
        expected_preserved_state_sha256=_text(item["expected_preserved_state_sha256"]),
    )


def _occurrence(value: object) -> SourceOccurrencePin:
    """Decode one exact RawAudit/RawPayload response identity and local clock."""

    item = _object(
        value,
        {
            "exchange",
            "raw_audit_id",
            "raw_audit_version",
            "raw_audit_content_hash",
            "raw_audit_run_id",
            "raw_audit_ingested_run_id",
            "raw_payload_id",
            "raw_payload_hash",
            "response_body_sha256",
            "response_completed_at",
            "row_count",
        },
    )
    try:
        completed_at = datetime.fromisoformat(_text(item["response_completed_at"]))
        audit_reference = RawAuditReference(
            raw_audit_id=_text(item["raw_audit_id"]),
            version=_text(item["raw_audit_version"]),
            content_hash=_text(item["raw_audit_content_hash"]),
            run_id=_text(item["raw_audit_run_id"]),
            ingested_run_id=_text(item["raw_audit_ingested_run_id"]),
        )
        return SourceOccurrencePin(
            exchange=_text(item["exchange"]),
            raw_audit_reference=audit_reference,
            raw_payload_id=_text(item["raw_payload_id"]),
            raw_payload_hash=_text(item["raw_payload_hash"]),
            response_body_sha256=_text(item["response_body_sha256"]),
            response_completed_at=completed_at,
            row_count=_integer(item["row_count"]),
        )
    except (TypeError, ValueError) as error:
        if isinstance(error, AssetActiveMaintenanceContractError):
            raise
        raise AssetActiveMaintenanceContractError("plan_occurrence_invalid") from error


__all__ = ["decode_plan"]
