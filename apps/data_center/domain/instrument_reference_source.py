"""Strict source-reference contracts for Tushare stock-basic responses.

These values retain what a provider said about security identity and listing
lifecycle. They do not establish a decision-ready, point-in-time or executable
instrument master.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import UUID

from .entities import RawAuditReference

_REQUIRED_STOCK_BASIC_FIELDS = frozenset(
    {
        "ts_code",
        "name",
        "exchange",
        "market",
        "list_status",
        "list_date",
        "delist_date",
    }
)
_STOCK_BASIC_FIELDS_WITH_CURRENCY = _REQUIRED_STOCK_BASIC_FIELDS | {"curr_type"}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_RAW_PAYLOAD_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")


class InstrumentReferenceSourceContractError(ValueError):
    """Stable validation error for an untrustworthy source-reference value."""

    def __init__(self, code: str) -> None:
        """Create a typed contract error with a stable machine-readable code."""

        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class InstrumentReferenceProviderContract:
    """Versioned, caller-supplied request scope for one stock-basic source."""

    contract_id: str
    contract_version: str
    provider_name: str
    dataset_key: str
    api_name: str
    fields: tuple[str, ...]
    exchange_scope: tuple[str, ...]
    list_status_scope: tuple[str, ...]

    def __post_init__(self) -> None:
        """Reject incomplete contracts and scopes before any provider call."""

        for name in ("contract_id", "contract_version", "provider_name", "dataset_key"):
            _require_text(getattr(self, name), name)
        if self.api_name != "stock_basic":
            raise InstrumentReferenceSourceContractError(
                "INSTRUMENT_REFERENCE_PROVIDER_CONTRACT_INVALID"
            )
        _require_unique_texts(self.fields, "fields")
        if set(self.fields) not in (
            _REQUIRED_STOCK_BASIC_FIELDS,
            _STOCK_BASIC_FIELDS_WITH_CURRENCY,
        ):
            raise InstrumentReferenceSourceContractError(
                "INSTRUMENT_REFERENCE_PROVIDER_CONTRACT_INVALID"
            )
        _require_unique_texts(self.exchange_scope, "exchange_scope")
        _require_unique_texts(self.list_status_scope, "list_status_scope")

    @property
    def content_hash(self) -> str:
        """Return the canonical digest of the complete provider contract."""

        return _canonical_sha256(
            {
                "contract_id": self.contract_id,
                "contract_version": self.contract_version,
                "provider_name": self.provider_name,
                "dataset_key": self.dataset_key,
                "api_name": self.api_name,
                "fields": list(self.fields),
                "exchange_scope": list(self.exchange_scope),
                "list_status_scope": list(self.list_status_scope),
            }
        )

    @property
    def fields_csv(self) -> str:
        """Return the exact provider field request in contract order."""

        return ",".join(self.fields)


@dataclass(frozen=True, slots=True)
class InstrumentReferenceExchangeSuffixCrosswalk:
    """Explicit versioned source-exchange to full-code-suffix mapping."""

    crosswalk_id: str
    crosswalk_version: str
    exchange_suffix_pairs: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        """Reject missing, duplicate or ambiguous mapping rows."""

        _require_text(self.crosswalk_id, "crosswalk_id")
        _require_text(self.crosswalk_version, "crosswalk_version")
        if type(self.exchange_suffix_pairs) is not tuple or not self.exchange_suffix_pairs:
            raise InstrumentReferenceSourceContractError("INSTRUMENT_REFERENCE_CROSSWALK_INVALID")
        exchanges: list[str] = []
        suffixes: list[str] = []
        for pair in self.exchange_suffix_pairs:
            if not isinstance(pair, tuple) or len(pair) != 2:
                raise InstrumentReferenceSourceContractError(
                    "INSTRUMENT_REFERENCE_CROSSWALK_INVALID"
                )
            exchange, suffix = pair
            _require_text(exchange, "source exchange")
            _require_text(suffix, "source suffix")
            if "." in suffix:
                raise InstrumentReferenceSourceContractError(
                    "INSTRUMENT_REFERENCE_CROSSWALK_INVALID"
                )
            exchanges.append(exchange)
            suffixes.append(suffix)
        if len(set(exchanges)) != len(exchanges) or len(set(suffixes)) != len(suffixes):
            raise InstrumentReferenceSourceContractError("INSTRUMENT_REFERENCE_CROSSWALK_INVALID")

    @property
    def content_hash(self) -> str:
        """Return the canonical digest of the exact, versioned mapping."""

        return _canonical_sha256(
            {
                "crosswalk_id": self.crosswalk_id,
                "crosswalk_version": self.crosswalk_version,
                "exchange_suffix_pairs": [
                    [exchange, suffix] for exchange, suffix in self.exchange_suffix_pairs
                ],
            }
        )

    def suffix_for(self, exchange: str) -> str | None:
        """Return only a deliberately configured suffix for this exact exchange."""

        for source_exchange, suffix in self.exchange_suffix_pairs:
            if source_exchange == exchange:
                return suffix
        return None

    def matches(self, ts_code: str, exchange: str) -> bool:
        """Check the full provider code suffix against the configured mapping."""

        expected_suffix = self.suffix_for(exchange)
        if (
            expected_suffix is None
            or not isinstance(ts_code, str)
            or ts_code != ts_code.strip()
            or any(ord(character) < 33 for character in ts_code)
        ):
            return False
        if ts_code.count(".") != 1:
            return False
        code, suffix = ts_code.rsplit(".", maxsplit=1)
        return bool(code) and suffix == expected_suffix


@dataclass(frozen=True, slots=True)
class InstrumentReferenceOccurrence:
    """Bind one exact exchange/status request to a stored raw response."""

    occurrence_id: UUID
    exchange: str
    list_status: str
    raw_audit_reference: RawAuditReference
    raw_payload_id: str
    raw_payload_hash: str
    response_body_sha256: str
    response_completed_at: datetime
    row_count: int

    def __post_init__(self) -> None:
        """Require an exact audit ID, body digest and local completion time."""

        if not isinstance(self.occurrence_id, UUID):
            raise InstrumentReferenceSourceContractError("INSTRUMENT_REFERENCE_OCCURRENCE_INVALID")
        _require_text(self.exchange, "exchange")
        _require_text(self.list_status, "list_status")
        if not isinstance(self.raw_audit_reference, RawAuditReference):
            raise InstrumentReferenceSourceContractError("INSTRUMENT_REFERENCE_OCCURRENCE_INVALID")
        _require_text(self.raw_payload_id, "raw_payload_id")
        if not isinstance(self.raw_payload_hash, str) or not _RAW_PAYLOAD_HASH.fullmatch(
            self.raw_payload_hash
        ):
            raise InstrumentReferenceSourceContractError("INSTRUMENT_REFERENCE_OCCURRENCE_INVALID")
        if not isinstance(self.response_body_sha256, str) or not _SHA256.fullmatch(
            self.response_body_sha256
        ):
            raise InstrumentReferenceSourceContractError("INSTRUMENT_REFERENCE_OCCURRENCE_INVALID")
        _validate_raw_audit_identity(self.raw_audit_reference)
        _require_aware_utc(self.response_completed_at)
        if type(self.row_count) is not int or self.row_count < 0:
            raise InstrumentReferenceSourceContractError("INSTRUMENT_REFERENCE_OCCURRENCE_INVALID")


@dataclass(frozen=True, slots=True)
class InstrumentReferenceRecord:
    """One raw stock-basic row with explicit identity and occurrence binding."""

    ts_code: str
    name: str
    source_exchange: str
    source_market: str | None
    source_list_status: str
    list_date_raw: str | None
    list_date: date | None
    delist_date_raw: str | None
    delist_date: date | None
    exchange_suffix: str
    occurrence_id: UUID
    raw_audit_reference: RawAuditReference
    raw_payload_id: str
    raw_payload_hash: str
    source_currency: str | None = None

    def __post_init__(self) -> None:
        """Validate preserved provider values and prohibit inferred source times."""

        for name in ("ts_code", "source_exchange", "source_list_status", "exchange_suffix"):
            _require_text(getattr(self, name), name)
        if not isinstance(self.name, str):
            raise InstrumentReferenceSourceContractError(
                "INSTRUMENT_REFERENCE_RESPONSE_SCHEMA_INVALID"
            )
        _require_optional_raw_text(self.source_market, "source_market")
        _require_optional_raw_text(self.source_currency, "source_currency")
        _require_optional_raw_text(self.list_date_raw, "list_date_raw")
        _require_optional_raw_text(self.delist_date_raw, "delist_date_raw")
        if self.list_date is not None and type(self.list_date) is not date:
            raise InstrumentReferenceSourceContractError(
                "INSTRUMENT_REFERENCE_RESPONSE_SCHEMA_INVALID"
            )
        if self.list_date != _normalized_source_date(self.list_date_raw):
            raise InstrumentReferenceSourceContractError(
                "INSTRUMENT_REFERENCE_RESPONSE_SCHEMA_INVALID"
            )
        if self.delist_date is not None and type(self.delist_date) is not date:
            raise InstrumentReferenceSourceContractError(
                "INSTRUMENT_REFERENCE_RESPONSE_SCHEMA_INVALID"
            )
        if self.delist_date != _normalized_source_date(self.delist_date_raw):
            raise InstrumentReferenceSourceContractError(
                "INSTRUMENT_REFERENCE_RESPONSE_SCHEMA_INVALID"
            )
        if not isinstance(self.occurrence_id, UUID):
            raise InstrumentReferenceSourceContractError("INSTRUMENT_REFERENCE_OCCURRENCE_INVALID")
        if not isinstance(self.raw_audit_reference, RawAuditReference):
            raise InstrumentReferenceSourceContractError("INSTRUMENT_REFERENCE_OCCURRENCE_INVALID")
        _require_text(self.raw_payload_id, "raw_payload_id")
        if not isinstance(self.raw_payload_hash, str) or not _RAW_PAYLOAD_HASH.fullmatch(
            self.raw_payload_hash
        ):
            raise InstrumentReferenceSourceContractError("INSTRUMENT_REFERENCE_OCCURRENCE_INVALID")

    @property
    def source_observed_at(self) -> None:
        """Return unknown because stock_basic supplies no upstream observation time."""

        return None

    @property
    def source_available_at(self) -> None:
        """Return unknown because stock_basic supplies no upstream publication time."""

        return None


@dataclass(frozen=True, slots=True)
class InstrumentReferenceCandidate:
    """Unpublished source-reference batch that is blocked from decision use."""

    provider_contract: InstrumentReferenceProviderContract
    crosswalk: InstrumentReferenceExchangeSuffixCrosswalk
    occurrences: tuple[InstrumentReferenceOccurrence, ...]
    records: tuple[InstrumentReferenceRecord, ...]

    def __post_init__(self) -> None:
        """Require complete explicit request scope and exact row provenance."""

        if not isinstance(self.provider_contract, InstrumentReferenceProviderContract):
            raise InstrumentReferenceSourceContractError(
                "INSTRUMENT_REFERENCE_PROVIDER_CONTRACT_INVALID"
            )
        if not isinstance(self.crosswalk, InstrumentReferenceExchangeSuffixCrosswalk):
            raise InstrumentReferenceSourceContractError("INSTRUMENT_REFERENCE_CROSSWALK_INVALID")
        if type(self.occurrences) is not tuple or type(self.records) is not tuple:
            raise InstrumentReferenceSourceContractError("INSTRUMENT_REFERENCE_CANDIDATE_INVALID")
        if any(
            not isinstance(item, InstrumentReferenceOccurrence) for item in self.occurrences
        ) or any(not isinstance(item, InstrumentReferenceRecord) for item in self.records):
            raise InstrumentReferenceSourceContractError("INSTRUMENT_REFERENCE_CANDIDATE_INVALID")
        expected_scopes = {
            (exchange, status)
            for exchange in self.provider_contract.exchange_scope
            for status in self.provider_contract.list_status_scope
        }
        actual_scopes = [(item.exchange, item.list_status) for item in self.occurrences]
        if len(actual_scopes) != len(expected_scopes) or set(actual_scopes) != expected_scopes:
            raise InstrumentReferenceSourceContractError(
                "INSTRUMENT_REFERENCE_OCCURRENCE_SCOPE_INCOMPLETE"
            )
        occurrence_ids = [item.occurrence_id for item in self.occurrences]
        raw_audit_ids = [item.raw_audit_reference.raw_audit_id for item in self.occurrences]
        if len(set(occurrence_ids)) != len(occurrence_ids) or len(set(raw_audit_ids)) != len(
            raw_audit_ids
        ):
            raise InstrumentReferenceSourceContractError(
                "INSTRUMENT_REFERENCE_OCCURRENCE_DUPLICATE"
            )
        occurrence_by_id = {item.occurrence_id: item for item in self.occurrences}
        record_counts = {item.occurrence_id: 0 for item in self.occurrences}
        currency_requested = "curr_type" in self.provider_contract.fields
        for record in self.records:
            occurrence = occurrence_by_id.get(record.occurrence_id)
            if (
                occurrence is None
                or occurrence.exchange != record.source_exchange
                or occurrence.list_status != record.source_list_status
                or occurrence.raw_audit_reference != record.raw_audit_reference
                or occurrence.raw_payload_id != record.raw_payload_id
                or occurrence.raw_payload_hash != record.raw_payload_hash
                or not self.crosswalk.matches(record.ts_code, record.source_exchange)
                or record.exchange_suffix != self.crosswalk.suffix_for(record.source_exchange)
                or record.source_exchange not in self.provider_contract.exchange_scope
                or record.source_list_status not in self.provider_contract.list_status_scope
                or (not currency_requested and record.source_currency is not None)
            ):
                raise InstrumentReferenceSourceContractError(
                    "INSTRUMENT_REFERENCE_RECORD_BINDING_INVALID"
                )
            record_counts[occurrence.occurrence_id] += 1
        if any(record_counts[item.occurrence_id] != item.row_count for item in self.occurrences):
            raise InstrumentReferenceSourceContractError(
                "INSTRUMENT_REFERENCE_RECORD_COUNT_MISMATCH"
            )

    @property
    def contract_hash(self) -> str:
        """Return the exact provider contract digest carried by this batch."""

        return self.provider_contract.content_hash

    @property
    def crosswalk_hash(self) -> str:
        """Return the exact identity crosswalk digest carried by this batch."""

        return self.crosswalk.content_hash

    @property
    def source_observed_at(self) -> None:
        """Return unknown because the provider does not expose upstream time."""

        return None

    @property
    def source_available_at(self) -> None:
        """Return unknown because the provider does not expose publication time."""

        return None

    @property
    def must_not_use_for_decision(self) -> bool:
        """Mark this source-only object as unavailable to decision consumers."""

        return True

    @property
    def must_not_execute(self) -> bool:
        """Mark this source-only object as unavailable to order execution."""

        return True

    @property
    def blocked_reason(self) -> str:
        """Return the stable reason that prevents decision and execution use."""

        return "INSTRUMENT_REFERENCE_SOURCE_ONLY_NOT_DECISION_READY"


def _canonical_sha256(value: object) -> str:
    """Hash the exact canonical JSON representation of a source contract."""

    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require_text(value: object, field_name: str) -> None:
    """Require exact nonempty bounded text without trimming or coercion."""

    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 512
        or any(ord(character) < 32 for character in value)
    ):
        raise InstrumentReferenceSourceContractError("INSTRUMENT_REFERENCE_RESPONSE_SCHEMA_INVALID")


def _require_unique_texts(values: tuple[str, ...], field_name: str) -> None:
    """Require a nonempty, ordered tuple of unique source-scope strings."""

    if type(values) is not tuple or not values:
        raise InstrumentReferenceSourceContractError(
            "INSTRUMENT_REFERENCE_PROVIDER_CONTRACT_INVALID"
        )
    for value in values:
        _require_text(value, field_name)
    if len(set(values)) != len(values):
        raise InstrumentReferenceSourceContractError(
            "INSTRUMENT_REFERENCE_PROVIDER_CONTRACT_INVALID"
        )


def _require_optional_raw_text(value: object, field_name: str) -> None:
    """Preserve null or exact raw text, including a provider-supplied empty value."""

    if value is not None and (
        not isinstance(value, str)
        or len(value) > 512
        or any(ord(character) < 32 for character in value)
    ):
        raise InstrumentReferenceSourceContractError("INSTRUMENT_REFERENCE_RESPONSE_SCHEMA_INVALID")


def _normalized_source_date(value: str | None) -> date | None:
    """Check that a raw source date and its date-only interpretation agree."""

    if value is None or value == "":
        return None
    if not re.fullmatch(r"[0-9]{8}", value):
        raise InstrumentReferenceSourceContractError("INSTRUMENT_REFERENCE_RESPONSE_SCHEMA_INVALID")
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError as exc:
        raise InstrumentReferenceSourceContractError(
            "INSTRUMENT_REFERENCE_RESPONSE_SCHEMA_INVALID"
        ) from exc


def _require_aware_utc(value: datetime) -> None:
    """Require exact UTC-aware local response completion time."""

    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
        or value.utcoffset() != UTC.utcoffset(value)
    ):
        raise InstrumentReferenceSourceContractError("INSTRUMENT_REFERENCE_OCCURRENCE_INVALID")


def _validate_raw_audit_identity(reference: RawAuditReference) -> None:
    """Require database-generated numeric ID and owner-issued canonical UUIDs."""

    audit_id = reference.raw_audit_id
    if (
        not isinstance(audit_id, str)
        or not audit_id.isascii()
        or not audit_id.isdecimal()
        or int(audit_id) <= 0
    ):
        raise InstrumentReferenceSourceContractError("INSTRUMENT_REFERENCE_OCCURRENCE_INVALID")
    for value in (reference.run_id, reference.ingested_run_id):
        try:
            if str(UUID(value)) != value:
                raise ValueError("noncanonical UUID")
        except (AttributeError, TypeError, ValueError) as exc:
            raise InstrumentReferenceSourceContractError(
                "INSTRUMENT_REFERENCE_OCCURRENCE_INVALID"
            ) from exc


__all__ = [
    "InstrumentReferenceCandidate",
    "InstrumentReferenceExchangeSuffixCrosswalk",
    "InstrumentReferenceOccurrence",
    "InstrumentReferenceProviderContract",
    "InstrumentReferenceRecord",
    "InstrumentReferenceSourceContractError",
]
