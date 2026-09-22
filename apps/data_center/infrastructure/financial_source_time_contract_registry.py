"""Strict loader for owner-approved financial source-time match contracts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from apps.data_center.domain.financial_source_time_contract import (
    FinancialSourceTimeJoinField,
    FinancialSourceTimeJoinSemantic,
    FinancialSourceTimeMatchContract,
)

REGISTRY_SCHEMA_VERSION = "financial-source-time-match-contract-registry.v2"
_ROOT_KEYS = frozenset({"schema_version", "status", "contracts", "approval"})
_APPROVAL_KEYS = frozenset({"approved_at", "approved_by", "receipt_sha256", "contract_set_sha256"})
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
class FinancialSourceTimeContractApproval:
    """Bind one claimed owner receipt digest to the exact active contract digest set."""

    approved_at: datetime
    approved_by: str
    receipt_sha256: str
    contract_set_sha256: str

    def __post_init__(self) -> None:
        """Reject malformed direct approval construction."""

        if (
            not isinstance(self.approved_at, datetime)
            or self.approved_at.tzinfo is None
            or self.approved_at.utcoffset() != timedelta(0)
        ):
            raise FinancialSourceTimeContractRegistryError(
                "financial source-time approval approved_at must be UTC"
            )
        try:
            _bounded_token(self.approved_by, "approved_by", 128)
            _sha256(self.receipt_sha256, "receipt_sha256")
            _sha256(self.contract_set_sha256, "contract_set_sha256")
        except (TypeError, ValueError) as exc:
            raise FinancialSourceTimeContractRegistryError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class FinancialSourceTimeContractRegistry:
    """Immutable exact-identity lookup for one validated registry snapshot."""

    status: str
    contracts: tuple[FinancialSourceTimeMatchContract, ...]
    approval: FinancialSourceTimeContractApproval | None

    def __post_init__(self) -> None:
        """Keep direct construction as strict as the JSON loader boundary."""

        if not isinstance(self.contracts, tuple):
            raise FinancialSourceTimeContractRegistryError(
                "financial source-time registry contracts must be an immutable tuple"
            )
        if self.status == "awaiting_owner_approval":
            if self.contracts or self.approval is not None:
                raise FinancialSourceTimeContractRegistryError(
                    "pending financial source-time registry must be empty and unapproved"
                )
            return
        if self.status != "active":
            raise FinancialSourceTimeContractRegistryError(
                "financial source-time contract registry status is invalid"
            )
        if not self.contracts or not all(
            isinstance(contract, FinancialSourceTimeMatchContract) for contract in self.contracts
        ):
            raise FinancialSourceTimeContractRegistryError(
                "active financial source-time contract registry requires typed contracts"
            )
        if not isinstance(self.approval, FinancialSourceTimeContractApproval):
            raise FinancialSourceTimeContractRegistryError(
                "active financial source-time registry approval is required"
            )
        logical_identities = tuple(
            (contract.provider_name, contract.contract_id, contract.contract_version)
            for contract in self.contracts
        )
        if len(logical_identities) != len(set(logical_identities)):
            raise FinancialSourceTimeContractRegistryError(
                "financial source-time registry contains a duplicate contract identity"
            )
        expected_set_sha256 = financial_source_time_contract_set_sha256(
            [contract.contract_sha256 for contract in self.contracts]
        )
        if self.approval.contract_set_sha256 != expected_set_sha256:
            raise FinancialSourceTimeContractRegistryError(
                "financial source-time approval contract set does not match"
            )

    def get(
        self,
        *,
        provider_name: str,
        contract_id: str,
        contract_version: str,
        contract_sha256: str,
    ) -> FinancialSourceTimeMatchContract | None:
        """Return only a fully matching active contract identity."""

        if self.status != "active" or self.approval is None:
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
    raw_approval = decoded.get("approval")
    if not isinstance(raw_contracts, list):
        raise FinancialSourceTimeContractRegistryError(
            "financial source-time contract registry contracts must be a list"
        )
    if status == "awaiting_owner_approval":
        if raw_contracts:
            raise FinancialSourceTimeContractRegistryError(
                "unapproved financial source-time contracts cannot be registered"
            )
        if raw_approval is not None:
            raise FinancialSourceTimeContractRegistryError(
                "pending financial source-time registry cannot contain approval"
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
    approval: FinancialSourceTimeContractApproval | None = None
    if status == "active":
        if raw_approval is None:
            raise FinancialSourceTimeContractRegistryError(
                "active financial source-time registry approval is required"
            )
        approval = _decode_approval(raw_approval, contracts=contracts)
    return FinancialSourceTimeContractRegistry(
        status=status,
        contracts=contracts,
        approval=approval,
    )


def financial_source_time_contract_set_sha256(contract_sha256s: Sequence[str]) -> str:
    """Hash one exact sorted set of independently content-addressed contracts."""

    claimed_values = tuple(contract_sha256s)
    if any(not _is_sha256(value) for value in claimed_values):
        raise ValueError("financial source-time contract digest set is invalid")
    values = tuple(sorted(claimed_values))
    if len(values) != len(set(values)):
        raise ValueError("financial source-time contract digest set is invalid")
    encoded = json.dumps(values, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(
        b"agomtradepro:financial-source-time-contract-set:v1\0" + encoded
    ).hexdigest()


def _decode_approval(
    raw: object,
    *,
    contracts: Sequence[FinancialSourceTimeMatchContract],
) -> FinancialSourceTimeContractApproval:
    """Decode owner approval and bind it to the decoded contract content set."""

    if not isinstance(raw, Mapping) or frozenset(raw) != _APPROVAL_KEYS:
        raise FinancialSourceTimeContractRegistryError(
            "financial source-time registry approval keys are invalid"
        )
    try:
        approved_at_text = _text(raw, "approved_at")
        if not approved_at_text.endswith("Z"):
            raise ValueError("financial source-time approval approved_at must be canonical UTC")
        approved_at = datetime.fromisoformat(approved_at_text[:-1] + "+00:00")
        if approved_at.utcoffset() != timedelta(0):
            raise ValueError("financial source-time approval approved_at must be UTC")
        if approved_at.isoformat(timespec="seconds").replace("+00:00", "Z") != approved_at_text:
            raise ValueError("financial source-time approval approved_at must be canonical UTC")
        approved_by = _bounded_token(_text(raw, "approved_by"), "approved_by", 128)
        receipt_sha256 = _sha256(_text(raw, "receipt_sha256"), "receipt_sha256")
        contract_set_sha256 = _sha256(_text(raw, "contract_set_sha256"), "contract_set_sha256")
        expected_set_sha256 = financial_source_time_contract_set_sha256(
            [contract.contract_sha256 for contract in contracts]
        )
        if contract_set_sha256 != expected_set_sha256:
            raise ValueError("financial source-time approval contract set does not match")
        return FinancialSourceTimeContractApproval(
            approved_at=approved_at,
            approved_by=approved_by,
            receipt_sha256=receipt_sha256,
            contract_set_sha256=contract_set_sha256,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise FinancialSourceTimeContractRegistryError(str(exc)) from exc


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


def _bounded_token(value: object, field_name: str, maximum: int) -> str:
    """Require one exact bounded owner token without whitespace or controls."""

    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > maximum
        or any(character.isspace() or ord(character) < 32 for character in value)
    ):
        raise ValueError(f"financial source-time approval {field_name} is invalid")
    return value


def _sha256(value: str, field_name: str) -> str:
    """Require one lowercase SHA-256 approval anchor."""

    if not _is_sha256(value):
        raise ValueError(f"financial source-time approval {field_name} is invalid")
    return value


def _is_sha256(value: object) -> bool:
    """Return whether a value is one lowercase SHA-256 digest."""

    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


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
    "FinancialSourceTimeContractApproval",
    "FinancialSourceTimeContractRegistry",
    "FinancialSourceTimeContractRegistryError",
    "financial_source_time_contract_set_sha256",
    "load_financial_source_time_contract_registry",
]
