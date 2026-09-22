"""Governed contract for matching financial rows to provider source-time rows."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

FINANCIAL_FACT_DATASET_KEY = "equity.financial.fact"
FINANCIAL_SOURCE_TIME_DATASET_KEY = "equity.financial.source-time"


class FinancialSourceTimeJoinSemantic(StrEnum):
    """Required meanings that must participate in an exact source-time join."""

    ASSET_CODE = "asset_code"
    PERIOD_END = "period_end"
    ANNOUNCEMENT_DATE = "announcement_date"


@dataclass(frozen=True, slots=True)
class FinancialSourceTimeJoinField:
    """Map one required financial-row meaning to one provider source-time field."""

    semantic: FinancialSourceTimeJoinSemantic
    financial_field: str
    source_field: str

    def __post_init__(self) -> None:
        """Reject untyped meanings and ambiguous field names."""

        if not isinstance(self.semantic, FinancialSourceTimeJoinSemantic):
            raise ValueError("financial source-time join semantic must be typed")
        _bounded_text(self.financial_field, "financial_field", 128)
        _bounded_text(self.source_field, "source_field", 128)

    def to_dict(self) -> dict[str, str]:
        """Return the canonical join-field projection."""

        return {
            "semantic": self.semantic.value,
            "financial_field": self.financial_field,
            "source_field": self.source_field,
        }


@dataclass(frozen=True, slots=True)
class FinancialSourceTimeMatchContract:
    """Bind one approved provider parser to an exact, hash-addressed row join."""

    provider_name: str
    financial_dataset_key: str
    source_time_dataset_key: str
    endpoint: str
    contract_id: str
    contract_version: str
    parser_version: str
    source_timezone: str
    join_fields: tuple[FinancialSourceTimeJoinField, ...]
    source_row_id_field: str
    announced_at_field: str
    available_at_field: str
    projection_fields: tuple[str, ...]
    contract_sha256: str

    def __post_init__(self) -> None:
        """Require complete join semantics and a matching canonical content hash."""

        for field_name, value, maximum in (
            ("provider_name", self.provider_name, 128),
            ("financial_dataset_key", self.financial_dataset_key, 128),
            ("source_time_dataset_key", self.source_time_dataset_key, 128),
            ("endpoint", self.endpoint, 128),
            ("contract_id", self.contract_id, 128),
            ("contract_version", self.contract_version, 64),
            ("parser_version", self.parser_version, 128),
            ("source_timezone", self.source_timezone, 128),
            ("source_row_id_field", self.source_row_id_field, 128),
            ("announced_at_field", self.announced_at_field, 128),
            ("available_at_field", self.available_at_field, 128),
        ):
            _bounded_text(value, field_name, maximum)
        if self.financial_dataset_key != FINANCIAL_FACT_DATASET_KEY:
            raise ValueError("financial source-time financial dataset is invalid")
        if self.source_time_dataset_key != FINANCIAL_SOURCE_TIME_DATASET_KEY:
            raise ValueError("financial source-time dataset is invalid")
        try:
            ZoneInfo(self.source_timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("financial source-time contract timezone is unknown") from exc
        if not self.join_fields or not all(
            isinstance(item, FinancialSourceTimeJoinField) for item in self.join_fields
        ):
            raise ValueError("financial source-time join fields must be typed")
        semantics = tuple(item.semantic for item in self.join_fields)
        required_semantics = frozenset(FinancialSourceTimeJoinSemantic)
        if len(semantics) != len(set(semantics)) or frozenset(semantics) != required_semantics:
            raise ValueError("financial source-time contract requires exact join semantics")
        financial_fields = tuple(item.financial_field for item in self.join_fields)
        source_fields = tuple(item.source_field for item in self.join_fields)
        if len(financial_fields) != len(set(financial_fields)) or len(source_fields) != len(
            set(source_fields)
        ):
            raise ValueError("financial source-time join fields must be unique")
        if not self.projection_fields or any(
            not isinstance(item, str) for item in self.projection_fields
        ):
            raise ValueError("financial source-time projection fields must be text")
        for field_name in self.projection_fields:
            _bounded_text(field_name, "projection_field", 128)
        if len(self.projection_fields) != len(set(self.projection_fields)):
            raise ValueError("financial source-time projection fields must be unique")
        required_projection = frozenset(
            (
                *source_fields,
                self.source_row_id_field,
                self.announced_at_field,
                self.available_at_field,
            )
        )
        if not required_projection.issubset(self.projection_fields):
            raise ValueError("financial source-time projection fields are incomplete")
        prohibited_time_fields = {"response_completed_at", "fetched_at", "period_end"}
        if self.announced_at_field in prohibited_time_fields or self.available_at_field in (
            prohibited_time_fields
        ):
            raise ValueError("financial source-time contract uses a synthetic time field")
        evidence_fields = (
            self.source_row_id_field,
            self.announced_at_field,
            self.available_at_field,
        )
        if len(evidence_fields) != len(set(evidence_fields)) or set(evidence_fields) & set(
            source_fields
        ):
            raise ValueError("financial source-time evidence fields must be distinct")
        if not _is_sha256(self.contract_sha256):
            raise ValueError("financial source-time contract_sha256 is invalid")
        if self.contract_sha256 != financial_source_time_contract_sha256(self.to_dict()):
            raise ValueError("financial source-time contract_sha256 does not match content")

    @property
    def identity(self) -> tuple[str, str, str, str]:
        """Return the exact lookup identity including the content digest."""

        return (
            self.provider_name,
            self.contract_id,
            self.contract_version,
            self.contract_sha256,
        )

    def to_dict(self) -> dict[str, object]:
        """Return the canonical governance projection."""

        return {
            "provider_name": self.provider_name,
            "financial_dataset_key": self.financial_dataset_key,
            "source_time_dataset_key": self.source_time_dataset_key,
            "endpoint": self.endpoint,
            "contract_id": self.contract_id,
            "contract_version": self.contract_version,
            "parser_version": self.parser_version,
            "source_timezone": self.source_timezone,
            "join_fields": [item.to_dict() for item in self.join_fields],
            "source_row_id_field": self.source_row_id_field,
            "announced_at_field": self.announced_at_field,
            "available_at_field": self.available_at_field,
            "projection_fields": list(self.projection_fields),
            "contract_sha256": self.contract_sha256,
        }


def financial_source_time_contract_sha256(payload: Mapping[str, object]) -> str:
    """Hash the canonical contract content while excluding its claimed digest."""

    unsigned = {str(key): value for key, value in payload.items() if key != "contract_sha256"}
    encoded = json.dumps(
        unsigned,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(
        b"agomtradepro:financial-source-time-match-contract:v1\0" + encoded
    ).hexdigest()


def _bounded_text(value: object, field_name: str, maximum: int) -> None:
    """Require bounded unpadded text without control characters."""

    if not isinstance(value, str) or not value or value != value.strip() or len(value) > maximum:
        raise ValueError(f"financial source-time contract {field_name} is invalid")
    if any(ord(character) < 32 for character in value):
        raise ValueError(f"financial source-time contract {field_name} has control characters")


def _is_sha256(value: object) -> bool:
    """Return whether a value is one lowercase SHA-256 digest."""

    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


__all__ = [
    "FINANCIAL_FACT_DATASET_KEY",
    "FINANCIAL_SOURCE_TIME_DATASET_KEY",
    "FinancialSourceTimeJoinField",
    "FinancialSourceTimeJoinSemantic",
    "FinancialSourceTimeMatchContract",
    "financial_source_time_contract_sha256",
]
