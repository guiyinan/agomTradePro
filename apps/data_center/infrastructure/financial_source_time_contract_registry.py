"""Strict loader for owner-approved financial source-time match contracts."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from apps.data_center.domain.financial_source_time_contract import (
    FinancialSourceTimeJoinField,
    FinancialSourceTimeJoinSemantic,
    FinancialSourceTimeMatchContract,
)

REGISTRY_SCHEMA_VERSION = "financial-source-time-match-contract-registry.v1"
_ROOT_KEYS = frozenset({"schema_version", "status", "contracts"})
_CONTRACT_KEYS = frozenset(
    {
        "provider_name",
        "financial_dataset_key",
        "source_time_dataset_key",
        "endpoint",
        "contract_id",
        "contract_version",
        "parser_version",
        "source_timezone",
        "join_fields",
        "source_row_id_field",
        "announced_at_field",
        "available_at_field",
        "projection_fields",
        "contract_sha256",
    }
)
_JOIN_FIELD_KEYS = frozenset({"semantic", "financial_field", "source_field"})


class FinancialSourceTimeContractRegistryError(ValueError):
    """Reject ambiguous, unapproved, or content-inconsistent contract registries."""


@dataclass(frozen=True, slots=True)
class FinancialSourceTimeContractRegistry:
    """Immutable exact-identity lookup for one validated registry snapshot."""

    status: str
    contracts: tuple[FinancialSourceTimeMatchContract, ...]

    def get(
        self,
        *,
        provider_name: str,
        contract_id: str,
        contract_version: str,
        contract_sha256: str,
    ) -> FinancialSourceTimeMatchContract | None:
        """Return only a fully matching active contract identity."""

        if self.status != "active":
            return None
        identity = (provider_name, contract_id, contract_version, contract_sha256)
        return next((item for item in self.contracts if item.identity == identity), None)


def load_financial_source_time_contract_registry(
    path: Path,
) -> FinancialSourceTimeContractRegistry:
    """Load one strict registry without promoting pending owner policy."""

    try:
        raw = path.read_text(encoding="utf-8")
        decoded = json.loads(
            raw,
            object_pairs_hook=_object_pairs_no_duplicates,
            parse_constant=_reject_json_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FinancialSourceTimeContractRegistryError(
            "financial source-time contract registry is unreadable"
        ) from exc
    if not isinstance(decoded, Mapping) or frozenset(decoded) != _ROOT_KEYS:
        raise FinancialSourceTimeContractRegistryError(
            "financial source-time contract registry keys are invalid"
        )
    if decoded.get("schema_version") != REGISTRY_SCHEMA_VERSION:
        raise FinancialSourceTimeContractRegistryError(
            "financial source-time contract registry schema is unsupported"
        )
    status = decoded.get("status")
    if status not in {"awaiting_owner_approval", "active"}:
        raise FinancialSourceTimeContractRegistryError(
            "financial source-time contract registry status is invalid"
        )
    raw_contracts = decoded.get("contracts")
    if not isinstance(raw_contracts, list):
        raise FinancialSourceTimeContractRegistryError(
            "financial source-time contract registry contracts must be a list"
        )
    if status == "awaiting_owner_approval" and raw_contracts:
        raise FinancialSourceTimeContractRegistryError(
            "unapproved financial source-time contracts cannot be registered"
        )
    if status == "active" and not raw_contracts:
        raise FinancialSourceTimeContractRegistryError(
            "active financial source-time contract registry cannot be empty"
        )
    contracts = tuple(_decode_contract(item) for item in raw_contracts)
    logical_identities = [
        (item.provider_name, item.contract_id, item.contract_version) for item in contracts
    ]
    if len(logical_identities) != len(set(logical_identities)):
        raise FinancialSourceTimeContractRegistryError(
            "financial source-time registry contains a duplicate contract identity"
        )
    return FinancialSourceTimeContractRegistry(status=status, contracts=contracts)


def _decode_contract(raw: object) -> FinancialSourceTimeMatchContract:
    """Decode one exact contract projection at the Infrastructure boundary."""

    if not isinstance(raw, Mapping) or frozenset(raw) != _CONTRACT_KEYS:
        raise FinancialSourceTimeContractRegistryError(
            "financial source-time contract keys are invalid"
        )
    join_fields = raw.get("join_fields")
    projection_fields = raw.get("projection_fields")
    if not isinstance(join_fields, list) or not isinstance(projection_fields, list):
        raise FinancialSourceTimeContractRegistryError(
            "financial source-time contract field lists are invalid"
        )
    try:
        decoded_join_fields = tuple(_decode_join_field(item) for item in join_fields)
        if not all(isinstance(item, str) for item in projection_fields):
            raise ValueError("projection fields must be text")
        return FinancialSourceTimeMatchContract(
            provider_name=_text(raw, "provider_name"),
            financial_dataset_key=_text(raw, "financial_dataset_key"),
            source_time_dataset_key=_text(raw, "source_time_dataset_key"),
            endpoint=_text(raw, "endpoint"),
            contract_id=_text(raw, "contract_id"),
            contract_version=_text(raw, "contract_version"),
            parser_version=_text(raw, "parser_version"),
            source_timezone=_text(raw, "source_timezone"),
            join_fields=decoded_join_fields,
            source_row_id_field=_text(raw, "source_row_id_field"),
            announced_at_field=_text(raw, "announced_at_field"),
            available_at_field=_text(raw, "available_at_field"),
            projection_fields=tuple(projection_fields),
            contract_sha256=_text(raw, "contract_sha256"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise FinancialSourceTimeContractRegistryError(str(exc)) from exc


def _decode_join_field(raw: object) -> FinancialSourceTimeJoinField:
    """Decode one strict semantic field mapping."""

    if not isinstance(raw, Mapping) or frozenset(raw) != _JOIN_FIELD_KEYS:
        raise ValueError("financial source-time join field keys are invalid")
    return FinancialSourceTimeJoinField(
        semantic=FinancialSourceTimeJoinSemantic(_text(raw, "semantic")),
        financial_field=_text(raw, "financial_field"),
        source_field=_text(raw, "source_field"),
    )


def _text(raw: Mapping[object, object], key: str) -> str:
    """Narrow one JSON value to text without coercion."""

    value = raw[key]
    if not isinstance(value, str):
        raise ValueError(f"financial source-time contract {key} must be text")
    return value


def _object_pairs_no_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject duplicate JSON keys before they can overwrite trusted values."""

    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise FinancialSourceTimeContractRegistryError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> object:
    """Reject NaN and infinity values accepted by Python's JSON decoder."""

    raise FinancialSourceTimeContractRegistryError(f"non-finite JSON constant: {value}")


__all__ = [
    "REGISTRY_SCHEMA_VERSION",
    "FinancialSourceTimeContractRegistry",
    "FinancialSourceTimeContractRegistryError",
    "load_financial_source_time_contract_registry",
]
