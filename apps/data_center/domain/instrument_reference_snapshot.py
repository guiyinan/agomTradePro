"""Immutable, source-only snapshots of versioned instrument references."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import UUID

from .entities import RawAuditReference
from .instrument_reference_source import (
    InstrumentReferenceCandidate,
    InstrumentReferenceExchangeSuffixCrosswalk,
    InstrumentReferenceOccurrence,
    InstrumentReferenceProviderContract,
    InstrumentReferenceRecord,
)

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SCHEMA = "instrument-reference-snapshot.v1"


class InstrumentReferenceSnapshotError(ValueError):
    """A stable validation error for a malformed or inconsistent snapshot."""

    def __init__(self, code: str) -> None:
        """Create an error carrying a stable machine-readable reason."""

        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class InstrumentReferenceMappingContent:
    """Versioned explicit mappings from source identity to canonical labels."""

    mapping_id: str
    mapping_version: str
    source_crosswalk: InstrumentReferenceExchangeSuffixCrosswalk
    exchange_rule_market_pairs: tuple[tuple[str, str], ...]
    exchange_source_market_board_pairs: tuple[tuple[str, str, str], ...]

    def __post_init__(self) -> None:
        """Require immutable, unambiguous mapping tuples and exact source identity."""

        _require_token(self.mapping_id, "INSTRUMENT_REFERENCE_MAPPING_INVALID")
        _require_token(self.mapping_version, "INSTRUMENT_REFERENCE_MAPPING_INVALID")
        if not isinstance(self.source_crosswalk, InstrumentReferenceExchangeSuffixCrosswalk):
            raise InstrumentReferenceSnapshotError("INSTRUMENT_REFERENCE_MAPPING_INVALID")
        _validate_pair_rows(self.exchange_rule_market_pairs, 2)
        _validate_pair_rows(self.exchange_source_market_board_pairs, 3)
        crosswalk_exchanges = {
            exchange for exchange, _suffix in self.source_crosswalk.exchange_suffix_pairs
        }
        rule_exchanges = [exchange for exchange, _market in self.exchange_rule_market_pairs]
        board_keys = [
            (exchange, source_market)
            for exchange, source_market, _board in self.exchange_source_market_board_pairs
        ]
        if (
            len(rule_exchanges) != len(set(rule_exchanges))
            or len(board_keys) != len(set(board_keys))
            or not set(rule_exchanges).issubset(crosswalk_exchanges)
            or any(exchange not in crosswalk_exchanges for exchange, _market in board_keys)
        ):
            raise InstrumentReferenceSnapshotError("INSTRUMENT_REFERENCE_MAPPING_AMBIGUOUS")

    @property
    def source_crosswalk_id(self) -> str:
        """Return the exact source crosswalk identifier embedded in this mapping."""

        return self.source_crosswalk.crosswalk_id

    @property
    def source_crosswalk_version(self) -> str:
        """Return the exact source crosswalk version embedded in this mapping."""

        return self.source_crosswalk.crosswalk_version

    @property
    def source_crosswalk_hash(self) -> str:
        """Return the source crosswalk digest, distinct from this mapping's digest."""

        return self.source_crosswalk.content_hash

    @property
    def content_hash(self) -> str:
        """Return the canonical content digest, excluding database knowledge time."""

        return _digest(self.to_payload())

    def rule_market_for(self, source_exchange: str) -> str | None:
        """Resolve a Rule.market only through the explicit exchange mapping."""

        return _lookup_pair(self.exchange_rule_market_pairs, source_exchange)

    def board_for(self, source_exchange: str, source_market: str | None) -> str | None:
        """Resolve a board from the exact exchange and unmodified source market."""

        if source_market is None:
            return None
        for exchange, market, board in self.exchange_source_market_board_pairs:
            if exchange == source_exchange and market == source_market:
                return board
        return None

    def to_payload(self) -> dict[str, object]:
        """Return canonical JSON-compatible mapping content, including source identity."""

        return {
            "schema": "instrument-reference-mapping.v1",
            "mapping_id": self.mapping_id,
            "mapping_version": self.mapping_version,
            "source_crosswalk": {
                "crosswalk_id": self.source_crosswalk.crosswalk_id,
                "crosswalk_version": self.source_crosswalk.crosswalk_version,
                "content_hash": self.source_crosswalk.content_hash,
                "exchange_suffix_pairs": [
                    [exchange, suffix]
                    for exchange, suffix in self.source_crosswalk.exchange_suffix_pairs
                ],
            },
            "exchange_rule_market_pairs": [list(pair) for pair in self.exchange_rule_market_pairs],
            "exchange_source_market_board_pairs": [
                list(triple) for triple in self.exchange_source_market_board_pairs
            ],
        }


@dataclass(frozen=True, slots=True)
class InstrumentReferenceMappingRecord:
    """Persisted mapping receipt sealed with its first repository knowledge time."""

    mapping_record_id: UUID
    content: InstrumentReferenceMappingContent
    recorded_at: datetime
    content_hash: str
    record_digest: str

    def __post_init__(self) -> None:
        """Verify the exact content and immutable first-record seal."""

        if not isinstance(self.mapping_record_id, UUID) or not isinstance(
            self.content, InstrumentReferenceMappingContent
        ):
            raise InstrumentReferenceSnapshotError("INSTRUMENT_REFERENCE_MAPPING_RECORD_INVALID")
        _require_utc(self.recorded_at)
        if self.content_hash != self.content.content_hash or not _valid_digest(self.record_digest):
            raise InstrumentReferenceSnapshotError("INSTRUMENT_REFERENCE_MAPPING_RECORD_INVALID")
        if self.record_digest != _mapping_record_digest(
            self.mapping_record_id, self.content, self.recorded_at
        ):
            raise InstrumentReferenceSnapshotError("INSTRUMENT_REFERENCE_MAPPING_RECORD_INVALID")

    @property
    def source_crosswalk_hash(self) -> str:
        """Return the separately sealed provider crosswalk digest."""

        return self.content.source_crosswalk_hash


def make_instrument_reference_mapping_record(
    content: InstrumentReferenceMappingContent,
    *,
    mapping_record_id: UUID,
    recorded_at: datetime,
) -> InstrumentReferenceMappingRecord:
    """Build a sealed mapping receipt from an actual repository timestamp."""

    _require_utc(recorded_at)
    digest = _mapping_record_digest(mapping_record_id, content, recorded_at)
    return InstrumentReferenceMappingRecord(
        mapping_record_id=mapping_record_id,
        content=content,
        recorded_at=recorded_at,
        content_hash=content.content_hash,
        record_digest=digest,
    )


@dataclass(frozen=True, slots=True)
class InstrumentReferenceFetchRound:
    """One complete provider candidate within a multi-fetch source snapshot."""

    fetch_round_id: UUID
    candidate: InstrumentReferenceCandidate

    def __post_init__(self) -> None:
        """Require a stable round identity and an already validated source candidate."""

        if not isinstance(self.fetch_round_id, UUID) or not isinstance(
            self.candidate, InstrumentReferenceCandidate
        ):
            raise InstrumentReferenceSnapshotError("INSTRUMENT_REFERENCE_FETCH_ROUND_INVALID")


@dataclass(frozen=True, slots=True)
class InstrumentReferenceClassification:
    """A non-authoritative mapping result for one exact provider security code."""

    ts_code: str
    source_exchange: str
    source_market: str | None
    source_list_status: str
    list_date: date | None
    delist_date: date | None
    rule_market: str | None
    board: str | None
    blocked_reason: str | None


@dataclass(frozen=True, slots=True)
class InstrumentReferenceSnapshotContent:
    """Complete source batch content, excluding all repository-owned time and IDs."""

    run_id: UUID
    mapping_record: InstrumentReferenceMappingRecord
    fetch_rounds: tuple[InstrumentReferenceFetchRound, ...]

    def __post_init__(self) -> None:
        """Validate complete rounds, exact RawAudit run identity, and mapping bindings."""

        if not isinstance(self.run_id, UUID) or not isinstance(
            self.mapping_record, InstrumentReferenceMappingRecord
        ):
            raise InstrumentReferenceSnapshotError("INSTRUMENT_REFERENCE_SNAPSHOT_INVALID")
        if type(self.fetch_rounds) is not tuple or not self.fetch_rounds:
            raise InstrumentReferenceSnapshotError("INSTRUMENT_REFERENCE_SNAPSHOT_INVALID")
        if any(not isinstance(item, InstrumentReferenceFetchRound) for item in self.fetch_rounds):
            raise InstrumentReferenceSnapshotError("INSTRUMENT_REFERENCE_SNAPSHOT_INVALID")
        round_ids = [item.fetch_round_id for item in self.fetch_rounds]
        if len(round_ids) != len(set(round_ids)):
            raise InstrumentReferenceSnapshotError("INSTRUMENT_REFERENCE_FETCH_ROUND_DUPLICATE")

        expected_crosswalk = self.mapping_record.content.source_crosswalk
        contract_hashes: set[str] = set()
        occurrence_ids: set[UUID] = set()
        raw_audit_ids: set[str] = set()
        all_records: list[InstrumentReferenceRecord] = []
        last_capture = self.mapping_record.recorded_at
        for fetch_round in self.fetch_rounds:
            candidate = fetch_round.candidate
            if not _same_crosswalk(candidate.crosswalk, expected_crosswalk):
                raise InstrumentReferenceSnapshotError(
                    "INSTRUMENT_REFERENCE_CROSSWALK_IDENTITY_MISMATCH"
                )
            contract_hashes.add(candidate.provider_contract.content_hash)
            for occurrence in candidate.occurrences:
                if occurrence.occurrence_id in occurrence_ids:
                    raise InstrumentReferenceSnapshotError(
                        "INSTRUMENT_REFERENCE_OCCURRENCE_DUPLICATE"
                    )
                occurrence_ids.add(occurrence.occurrence_id)
                audit_id = occurrence.raw_audit_reference.raw_audit_id
                if audit_id in raw_audit_ids:
                    raise InstrumentReferenceSnapshotError(
                        "INSTRUMENT_REFERENCE_AUDIT_ID_DUPLICATE"
                    )
                raw_audit_ids.add(audit_id)
                if occurrence.raw_audit_reference.run_id != str(self.run_id):
                    raise InstrumentReferenceSnapshotError("INSTRUMENT_REFERENCE_RUN_ID_MISMATCH")
                if occurrence.response_completed_at > last_capture:
                    last_capture = occurrence.response_completed_at
            all_records.extend(candidate.records)
        if len(contract_hashes) != 1:
            raise InstrumentReferenceSnapshotError(
                "INSTRUMENT_REFERENCE_PROVIDER_CONTRACT_MISMATCH"
            )
        identity_by_code: dict[str, tuple[str, str]] = {}
        for record in all_records:
            identity = (record.source_exchange, record.exchange_suffix)
            previous = identity_by_code.setdefault(record.ts_code, identity)
            if previous != identity:
                raise InstrumentReferenceSnapshotError(
                    "INSTRUMENT_REFERENCE_SECURITY_IDENTITY_CONFLICT"
                )

    @property
    def content_hash(self) -> str:
        """Hash all source rounds, mapping content identity, empty scopes and records."""

        return _digest(self.to_payload())

    @property
    def occurrence_count(self) -> int:
        """Return the number of distinct exact source response occurrences."""

        return sum(len(fetch_round.candidate.occurrences) for fetch_round in self.fetch_rounds)

    @property
    def record_count(self) -> int:
        """Return the total number of source records across every fetch round."""

        return sum(len(fetch_round.candidate.records) for fetch_round in self.fetch_rounds)

    @property
    def empty_occurrence_count(self) -> int:
        """Return the number of explicitly retained zero-row requests."""

        return sum(
            occurrence.row_count == 0
            for fetch_round in self.fetch_rounds
            for occurrence in fetch_round.candidate.occurrences
        )

    @property
    def last_response_completed_at(self) -> datetime:
        """Return the latest local response completion, never an upstream timestamp."""

        return max(
            occurrence.response_completed_at
            for fetch_round in self.fetch_rounds
            for occurrence in fetch_round.candidate.occurrences
        )

    @property
    def source_observed_at(self) -> None:
        """Return unknown because the provider contract has no source observation time."""

        return None

    @property
    def source_available_at(self) -> None:
        """Return unknown because the provider contract has no source publication time."""

        return None

    @property
    def must_not_use_for_decision(self) -> bool:
        """Declare that this reference snapshot is not a decision input."""

        return True

    @property
    def must_not_execute(self) -> bool:
        """Declare that this reference snapshot is not an execution authorization."""

        return True

    @property
    def blocked_reason(self) -> str:
        """Return the stable source-only restriction reason."""

        return "INSTRUMENT_REFERENCE_SOURCE_ONLY_NOT_DECISION_READY"

    @property
    def board_classification_complete(self) -> bool:
        """Return whether every exact security lookup has one mapped board result."""

        codes = {
            record.ts_code
            for fetch_round in self.fetch_rounds
            for record in fetch_round.candidate.records
        }
        return all(
            (classification := self.classify_security(code)) is not None
            and classification.board is not None
            and classification.blocked_reason is None
            for code in codes
        )

    def classify(self, record: InstrumentReferenceRecord) -> InstrumentReferenceClassification:
        """Map one record using explicit mapping rows, retaining unknown source market."""

        if not isinstance(record, InstrumentReferenceRecord):
            raise InstrumentReferenceSnapshotError("INSTRUMENT_REFERENCE_RECORD_INVALID")
        if not any(
            record == item
            for fetch_round in self.fetch_rounds
            for item in fetch_round.candidate.records
        ):
            raise InstrumentReferenceSnapshotError("INSTRUMENT_REFERENCE_RECORD_OUTSIDE_SNAPSHOT")
        rule_market = self.mapping_record.content.rule_market_for(record.source_exchange)
        board = self.mapping_record.content.board_for(record.source_exchange, record.source_market)
        reason = None
        if rule_market is None:
            reason = "INSTRUMENT_REFERENCE_RULE_MARKET_MAPPING_UNKNOWN"
        elif board is None:
            reason = "INSTRUMENT_REFERENCE_BOARD_MAPPING_UNKNOWN"
        return InstrumentReferenceClassification(
            ts_code=record.ts_code,
            source_exchange=record.source_exchange,
            source_market=record.source_market,
            source_list_status=record.source_list_status,
            list_date=record.list_date,
            delist_date=record.delist_date,
            rule_market=rule_market,
            board=board,
            blocked_reason=reason,
        )

    def classify_security(self, ts_code: str) -> InstrumentReferenceClassification | None:
        """Return an exact-code classification, blocking conflicting multi-round facts."""

        if not isinstance(ts_code, str):
            raise InstrumentReferenceSnapshotError("INSTRUMENT_REFERENCE_SECURITY_CODE_INVALID")
        matches = [
            record
            for fetch_round in self.fetch_rounds
            for record in fetch_round.candidate.records
            if record.ts_code == ts_code
        ]
        if not matches:
            return None
        classifications = [self.classify(record) for record in matches]
        values = {
            (
                item.source_exchange,
                item.source_market,
                item.source_list_status,
                item.list_date,
                item.delist_date,
                item.rule_market,
                item.board,
            )
            for item in classifications
        }
        first = classifications[0]
        if len(values) > 1:
            return InstrumentReferenceClassification(
                ts_code=ts_code,
                source_exchange=first.source_exchange,
                source_market=first.source_market,
                source_list_status=first.source_list_status,
                list_date=first.list_date,
                delist_date=first.delist_date,
                rule_market=first.rule_market,
                board=None,
                blocked_reason="INSTRUMENT_REFERENCE_CLASSIFICATION_AMBIGUOUS",
            )
        return first

    def to_payload(self) -> dict[str, object]:
        """Return all source candidates and explicit mapping content as JSON data."""

        return {
            "schema": _SCHEMA,
            "run_id": str(self.run_id),
            "mapping": {
                "mapping_id": self.mapping_record.content.mapping_id,
                "mapping_version": self.mapping_record.content.mapping_version,
                "content_hash": self.mapping_record.content_hash,
            },
            "fetch_rounds": [
                {
                    "fetch_round_id": str(fetch_round.fetch_round_id),
                    "candidate": _candidate_payload(fetch_round.candidate),
                }
                for fetch_round in self.fetch_rounds
            ],
        }


@dataclass(frozen=True, slots=True)
class InstrumentReferenceSnapshotRecord:
    """Persisted complete source snapshot with exact first-knowledge seal."""

    snapshot_id: UUID
    content: InstrumentReferenceSnapshotContent
    recorded_at: datetime
    content_hash: str
    record_digest: str

    def __post_init__(self) -> None:
        """Recompute source content and seal the snapshot plus exact mapping receipt."""

        if not isinstance(self.snapshot_id, UUID) or not isinstance(
            self.content, InstrumentReferenceSnapshotContent
        ):
            raise InstrumentReferenceSnapshotError("INSTRUMENT_REFERENCE_SNAPSHOT_RECORD_INVALID")
        _require_utc(self.recorded_at)
        if self.recorded_at < self.content.last_response_completed_at:
            raise InstrumentReferenceSnapshotError("INSTRUMENT_REFERENCE_RECORDED_BEFORE_CAPTURE")
        if self.recorded_at < self.content.mapping_record.recorded_at:
            raise InstrumentReferenceSnapshotError("INSTRUMENT_REFERENCE_RECORDED_BEFORE_MAPPING")
        if self.content_hash != self.content.content_hash or not _valid_digest(self.record_digest):
            raise InstrumentReferenceSnapshotError("INSTRUMENT_REFERENCE_SNAPSHOT_RECORD_INVALID")
        if self.record_digest != _snapshot_record_digest(
            self.snapshot_id, self.content_hash, self.recorded_at, self.content.mapping_record
        ):
            raise InstrumentReferenceSnapshotError("INSTRUMENT_REFERENCE_SNAPSHOT_RECORD_INVALID")

    @property
    def mapping_record(self) -> InstrumentReferenceMappingRecord:
        """Return the exact mapping receipt sealed into this snapshot record."""

        return self.content.mapping_record


def make_instrument_reference_snapshot_record(
    content: InstrumentReferenceSnapshotContent,
    *,
    snapshot_id: UUID,
    recorded_at: datetime,
) -> InstrumentReferenceSnapshotRecord:
    """Build a sealed snapshot receipt using an actual repository timestamp."""

    _require_utc(recorded_at)
    if recorded_at < content.last_response_completed_at:
        raise InstrumentReferenceSnapshotError("INSTRUMENT_REFERENCE_RECORDED_BEFORE_CAPTURE")
    if recorded_at < content.mapping_record.recorded_at:
        raise InstrumentReferenceSnapshotError("INSTRUMENT_REFERENCE_RECORDED_BEFORE_MAPPING")
    digest = _snapshot_record_digest(
        snapshot_id, content.content_hash, recorded_at, content.mapping_record
    )
    return InstrumentReferenceSnapshotRecord(
        snapshot_id=snapshot_id,
        content=content,
        recorded_at=recorded_at,
        content_hash=content.content_hash,
        record_digest=digest,
    )


def mapping_content_from_payload(payload: object) -> InstrumentReferenceMappingContent:
    """Rebuild mapping content from its stored JSON representation strictly."""

    if not isinstance(payload, dict) or set(payload) != {
        "schema",
        "mapping_id",
        "mapping_version",
        "source_crosswalk",
        "exchange_rule_market_pairs",
        "exchange_source_market_board_pairs",
    }:
        raise InstrumentReferenceSnapshotError("INSTRUMENT_REFERENCE_MAPPING_PAYLOAD_INVALID")
    crosswalk_payload = payload["source_crosswalk"]
    if not isinstance(crosswalk_payload, dict) or set(crosswalk_payload) != {
        "crosswalk_id",
        "crosswalk_version",
        "content_hash",
        "exchange_suffix_pairs",
    }:
        raise InstrumentReferenceSnapshotError("INSTRUMENT_REFERENCE_MAPPING_PAYLOAD_INVALID")
    crosswalk = InstrumentReferenceExchangeSuffixCrosswalk(
        crosswalk_id=_string(crosswalk_payload["crosswalk_id"]),
        crosswalk_version=_string(crosswalk_payload["crosswalk_version"]),
        exchange_suffix_pairs=_tuple_pairs2(crosswalk_payload["exchange_suffix_pairs"]),
    )
    if crosswalk.content_hash != crosswalk_payload["content_hash"]:
        raise InstrumentReferenceSnapshotError("INSTRUMENT_REFERENCE_CROSSWALK_HASH_MISMATCH")
    result = InstrumentReferenceMappingContent(
        mapping_id=_string(payload["mapping_id"]),
        mapping_version=_string(payload["mapping_version"]),
        source_crosswalk=crosswalk,
        exchange_rule_market_pairs=_tuple_pairs2(payload["exchange_rule_market_pairs"]),
        exchange_source_market_board_pairs=_tuple_triples(
            payload["exchange_source_market_board_pairs"]
        ),
    )
    if payload["schema"] != "instrument-reference-mapping.v1":
        raise InstrumentReferenceSnapshotError("INSTRUMENT_REFERENCE_MAPPING_PAYLOAD_INVALID")
    return result


def snapshot_content_from_payload(
    payload: object,
    *,
    mapping_record: InstrumentReferenceMappingRecord,
) -> InstrumentReferenceSnapshotContent:
    """Rebuild every stored source round and verify its exact mapping binding."""

    value = _object(payload, {"schema", "run_id", "mapping", "fetch_rounds"})
    mapping = _object(value["mapping"], {"mapping_id", "mapping_version", "content_hash"})
    if (
        value["schema"] != _SCHEMA
        or mapping["mapping_id"] != mapping_record.content.mapping_id
        or mapping["mapping_version"] != mapping_record.content.mapping_version
        or mapping["content_hash"] != mapping_record.content_hash
        or not isinstance(value["fetch_rounds"], list)
    ):
        raise InstrumentReferenceSnapshotError("INSTRUMENT_REFERENCE_SNAPSHOT_PAYLOAD_INVALID")
    rounds: list[InstrumentReferenceFetchRound] = []
    for raw_round in value["fetch_rounds"]:
        round_value = _object(raw_round, {"fetch_round_id", "candidate"})
        rounds.append(
            InstrumentReferenceFetchRound(
                fetch_round_id=_uuid_text(round_value["fetch_round_id"]),
                candidate=_candidate_from_payload(round_value["candidate"]),
            )
        )
    try:
        result = InstrumentReferenceSnapshotContent(
            run_id=_uuid_text(value["run_id"]),
            mapping_record=mapping_record,
            fetch_rounds=tuple(rounds),
        )
    except (TypeError, ValueError) as exc:
        if isinstance(exc, InstrumentReferenceSnapshotError):
            raise
        raise InstrumentReferenceSnapshotError(
            "INSTRUMENT_REFERENCE_SNAPSHOT_PAYLOAD_INVALID"
        ) from exc
    if result.to_payload() != payload:
        raise InstrumentReferenceSnapshotError("INSTRUMENT_REFERENCE_SNAPSHOT_PAYLOAD_INVALID")
    return result


def _candidate_payload(candidate: InstrumentReferenceCandidate) -> dict[str, object]:
    """Serialize one already validated source candidate without dropping empty scopes."""

    contract = candidate.provider_contract
    crosswalk = candidate.crosswalk
    return {
        "provider_contract": {
            "contract_id": contract.contract_id,
            "contract_version": contract.contract_version,
            "provider_name": contract.provider_name,
            "dataset_key": contract.dataset_key,
            "api_name": contract.api_name,
            "fields": list(contract.fields),
            "exchange_scope": list(contract.exchange_scope),
            "list_status_scope": list(contract.list_status_scope),
            "content_hash": contract.content_hash,
        },
        "crosswalk": {
            "crosswalk_id": crosswalk.crosswalk_id,
            "crosswalk_version": crosswalk.crosswalk_version,
            "exchange_suffix_pairs": [list(pair) for pair in crosswalk.exchange_suffix_pairs],
            "content_hash": crosswalk.content_hash,
        },
        "occurrences": [_occurrence_payload(item) for item in candidate.occurrences],
        "records": [_record_payload(item) for item in candidate.records],
    }


def _candidate_from_payload(value: object) -> InstrumentReferenceCandidate:
    """Strictly reconstruct one provider candidate from retained snapshot JSON."""

    candidate = _object(value, {"provider_contract", "crosswalk", "occurrences", "records"})
    contract_value = _object(
        candidate["provider_contract"],
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
        contract_id=_string(contract_value["contract_id"]),
        contract_version=_string(contract_value["contract_version"]),
        provider_name=_string(contract_value["provider_name"]),
        dataset_key=_string(contract_value["dataset_key"]),
        api_name=_string(contract_value["api_name"]),
        fields=_string_tuple(contract_value["fields"]),
        exchange_scope=_string_tuple(contract_value["exchange_scope"]),
        list_status_scope=_string_tuple(contract_value["list_status_scope"]),
    )
    if contract.content_hash != contract_value["content_hash"]:
        raise InstrumentReferenceSnapshotError("INSTRUMENT_REFERENCE_PROVIDER_HASH_MISMATCH")
    crosswalk_value = _object(
        candidate["crosswalk"],
        {"crosswalk_id", "crosswalk_version", "exchange_suffix_pairs", "content_hash"},
    )
    crosswalk = InstrumentReferenceExchangeSuffixCrosswalk(
        crosswalk_id=_string(crosswalk_value["crosswalk_id"]),
        crosswalk_version=_string(crosswalk_value["crosswalk_version"]),
        exchange_suffix_pairs=_tuple_pairs2(crosswalk_value["exchange_suffix_pairs"]),
    )
    if crosswalk.content_hash != crosswalk_value["content_hash"]:
        raise InstrumentReferenceSnapshotError("INSTRUMENT_REFERENCE_CROSSWALK_HASH_MISMATCH")
    raw_occurrences = candidate["occurrences"]
    raw_records = candidate["records"]
    if not isinstance(raw_occurrences, list) or not isinstance(raw_records, list):
        raise InstrumentReferenceSnapshotError("INSTRUMENT_REFERENCE_SNAPSHOT_PAYLOAD_INVALID")
    occurrences = tuple(_occurrence_from_payload(item) for item in raw_occurrences)
    records = tuple(_record_from_payload(item) for item in raw_records)
    try:
        return InstrumentReferenceCandidate(
            provider_contract=contract,
            crosswalk=crosswalk,
            occurrences=occurrences,
            records=records,
        )
    except (TypeError, ValueError) as exc:
        if isinstance(exc, InstrumentReferenceSnapshotError):
            raise
        raise InstrumentReferenceSnapshotError(
            "INSTRUMENT_REFERENCE_SNAPSHOT_PAYLOAD_INVALID"
        ) from exc


def _occurrence_from_payload(value: object) -> InstrumentReferenceOccurrence:
    """Restore one exact RawAudit-linked request occurrence from JSON."""

    occurrence = _object(
        value,
        {
            "occurrence_id",
            "exchange",
            "list_status",
            "raw_audit_reference",
            "raw_payload_id",
            "raw_payload_hash",
            "response_body_sha256",
            "response_completed_at",
            "row_count",
        },
    )
    return InstrumentReferenceOccurrence(
        occurrence_id=_uuid_text(occurrence["occurrence_id"]),
        exchange=_string(occurrence["exchange"]),
        list_status=_string(occurrence["list_status"]),
        raw_audit_reference=_raw_audit_reference(occurrence["raw_audit_reference"]),
        raw_payload_id=_string(occurrence["raw_payload_id"]),
        raw_payload_hash=_string(occurrence["raw_payload_hash"]),
        response_body_sha256=_string(occurrence["response_body_sha256"]),
        response_completed_at=_datetime_value(occurrence["response_completed_at"]),
        row_count=_integer(occurrence["row_count"]),
    )


def _record_from_payload(value: object) -> InstrumentReferenceRecord:
    """Restore one immutable provider row without inferring missing source dates."""

    record = _object(
        value,
        {
            "ts_code",
            "name",
            "source_exchange",
            "source_market",
            "source_list_status",
            "list_date_raw",
            "list_date",
            "delist_date_raw",
            "delist_date",
            "exchange_suffix",
            "occurrence_id",
            "raw_audit_reference",
            "raw_payload_id",
            "raw_payload_hash",
        },
    )
    source_market = record["source_market"]
    if source_market is not None and not isinstance(source_market, str):
        raise InstrumentReferenceSnapshotError("INSTRUMENT_REFERENCE_SNAPSHOT_PAYLOAD_INVALID")
    list_date_raw = _optional_string(record["list_date_raw"])
    delist_date_raw = _optional_string(record["delist_date_raw"])
    return InstrumentReferenceRecord(
        ts_code=_string(record["ts_code"]),
        name=_string(record["name"]),
        source_exchange=_string(record["source_exchange"]),
        source_market=source_market,
        source_list_status=_string(record["source_list_status"]),
        list_date_raw=list_date_raw,
        list_date=_optional_date(record["list_date"]),
        delist_date_raw=delist_date_raw,
        delist_date=_optional_date(record["delist_date"]),
        exchange_suffix=_string(record["exchange_suffix"]),
        occurrence_id=_uuid_text(record["occurrence_id"]),
        raw_audit_reference=_raw_audit_reference(record["raw_audit_reference"]),
        raw_payload_id=_string(record["raw_payload_id"]),
        raw_payload_hash=_string(record["raw_payload_hash"]),
    )


def _raw_audit_reference(value: object) -> RawAuditReference:
    """Strictly narrow the exact five-field RawAudit reference."""

    reference = _object(
        value,
        {"raw_audit_id", "version", "content_hash", "run_id", "ingested_run_id"},
    )
    return RawAuditReference(
        raw_audit_id=_string(reference["raw_audit_id"]),
        version=_string(reference["version"]),
        content_hash=_string(reference["content_hash"]),
        run_id=_string(reference["run_id"]),
        ingested_run_id=_string(reference["ingested_run_id"]),
    )


def _occurrence_payload(occurrence: InstrumentReferenceOccurrence) -> dict[str, object]:
    """Serialize exact response occurrence identity and local capture metadata."""

    reference = occurrence.raw_audit_reference
    return {
        "occurrence_id": str(occurrence.occurrence_id),
        "exchange": occurrence.exchange,
        "list_status": occurrence.list_status,
        "raw_audit_reference": {
            "raw_audit_id": reference.raw_audit_id,
            "version": reference.version,
            "content_hash": reference.content_hash,
            "run_id": reference.run_id,
            "ingested_run_id": reference.ingested_run_id,
        },
        "raw_payload_id": occurrence.raw_payload_id,
        "raw_payload_hash": occurrence.raw_payload_hash,
        "response_body_sha256": occurrence.response_body_sha256,
        "response_completed_at": _datetime_text(occurrence.response_completed_at),
        "row_count": occurrence.row_count,
    }


def _record_payload(record: InstrumentReferenceRecord) -> dict[str, object]:
    """Serialize all raw and parsed source fields without inferred timestamps."""

    reference = record.raw_audit_reference
    return {
        "ts_code": record.ts_code,
        "name": record.name,
        "source_exchange": record.source_exchange,
        "source_market": record.source_market,
        "source_list_status": record.source_list_status,
        "list_date_raw": record.list_date_raw,
        "list_date": record.list_date.isoformat() if record.list_date is not None else None,
        "delist_date_raw": record.delist_date_raw,
        "delist_date": record.delist_date.isoformat() if record.delist_date is not None else None,
        "exchange_suffix": record.exchange_suffix,
        "occurrence_id": str(record.occurrence_id),
        "raw_audit_reference": {
            "raw_audit_id": reference.raw_audit_id,
            "version": reference.version,
            "content_hash": reference.content_hash,
            "run_id": reference.run_id,
            "ingested_run_id": reference.ingested_run_id,
        },
        "raw_payload_id": record.raw_payload_id,
        "raw_payload_hash": record.raw_payload_hash,
    }


def _mapping_record_digest(
    mapping_record_id: UUID,
    content: InstrumentReferenceMappingContent,
    recorded_at: datetime,
) -> str:
    """Seal a mapping row identity, content and first persisted knowledge time."""

    return _digest(
        {
            "mapping_record_id": str(mapping_record_id),
            "mapping_id": content.mapping_id,
            "mapping_version": content.mapping_version,
            "content_hash": content.content_hash,
            "recorded_at": _datetime_text(recorded_at),
        }
    )


def _snapshot_record_digest(
    snapshot_id: UUID,
    content_hash: str,
    recorded_at: datetime,
    mapping_record: InstrumentReferenceMappingRecord,
) -> str:
    """Seal the snapshot's first knowledge time to the exact mapping receipt."""

    return _digest(
        {
            "snapshot_id": str(snapshot_id),
            "content_hash": content_hash,
            "recorded_at": _datetime_text(recorded_at),
            "mapping_record": {
                "mapping_record_id": str(mapping_record.mapping_record_id),
                "mapping_id": mapping_record.content.mapping_id,
                "mapping_version": mapping_record.content.mapping_version,
                "content_hash": mapping_record.content_hash,
                "recorded_at": _datetime_text(mapping_record.recorded_at),
                "record_digest": mapping_record.record_digest,
            },
        }
    )


def _digest(value: object) -> str:
    """Return SHA-256 over canonical ASCII JSON."""

    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _validate_pair_rows(value: object, length: int) -> None:
    """Require immutable, uniquely keyed exact mapping rows."""

    if type(value) is not tuple or not value:
        raise InstrumentReferenceSnapshotError("INSTRUMENT_REFERENCE_MAPPING_INVALID")
    seen: set[tuple[str, ...]] = set()
    for row in value:
        if type(row) is not tuple or len(row) != length:
            raise InstrumentReferenceSnapshotError("INSTRUMENT_REFERENCE_MAPPING_INVALID")
        if any(not isinstance(item, str) or not item or item != item.strip() for item in row):
            raise InstrumentReferenceSnapshotError("INSTRUMENT_REFERENCE_MAPPING_INVALID")
        key = row[:-1]
        if key in seen:
            raise InstrumentReferenceSnapshotError("INSTRUMENT_REFERENCE_MAPPING_AMBIGUOUS")
        seen.add(key)


def _tuple_pairs(value: object, length: int) -> tuple[tuple[str, ...], ...]:
    """Narrow stored JSON arrays to immutable fixed-width text tuples."""

    if not isinstance(value, list):
        raise InstrumentReferenceSnapshotError("INSTRUMENT_REFERENCE_MAPPING_PAYLOAD_INVALID")
    rows: list[tuple[str, ...]] = []
    for row in value:
        if (
            not isinstance(row, list)
            or len(row) != length
            or any(not isinstance(item, str) for item in row)
        ):
            raise InstrumentReferenceSnapshotError("INSTRUMENT_REFERENCE_MAPPING_PAYLOAD_INVALID")
        rows.append(tuple(row))
    return tuple(rows)


def _tuple_pairs2(value: object) -> tuple[tuple[str, str], ...]:
    """Narrow stored JSON rows to immutable pairs of exact strings."""

    return tuple((row[0], row[1]) for row in _tuple_pairs(value, 2))


def _tuple_triples(value: object) -> tuple[tuple[str, str, str], ...]:
    """Narrow stored JSON rows to immutable triples of exact strings."""

    return tuple((row[0], row[1], row[2]) for row in _tuple_pairs(value, 3))


def _lookup_pair(pairs: tuple[tuple[str, str], ...], key: str) -> str | None:
    """Return one exact mapping value without applying a default."""

    for source, value in pairs:
        if source == key:
            return value
    return None


def _object(value: object, keys: set[str]) -> dict[str, object]:
    """Require a JSON object with precisely the expected string keys."""

    if (
        not isinstance(value, dict)
        or set(value) != keys
        or any(not isinstance(key, str) for key in value)
    ):
        raise InstrumentReferenceSnapshotError("INSTRUMENT_REFERENCE_SNAPSHOT_PAYLOAD_INVALID")
    return value


def _string_tuple(value: object) -> tuple[str, ...]:
    """Narrow a stored JSON array to a tuple of exact strings."""

    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise InstrumentReferenceSnapshotError("INSTRUMENT_REFERENCE_SNAPSHOT_PAYLOAD_INVALID")
    return tuple(value)


def _optional_string(value: object) -> str | None:
    """Narrow one nullable source text value without coercion."""

    if value is None:
        return None
    if not isinstance(value, str):
        raise InstrumentReferenceSnapshotError("INSTRUMENT_REFERENCE_SNAPSHOT_PAYLOAD_INVALID")
    return value


def _integer(value: object) -> int:
    """Require a JSON integer rather than a bool or fractional number."""

    if type(value) is not int:
        raise InstrumentReferenceSnapshotError("INSTRUMENT_REFERENCE_SNAPSHOT_PAYLOAD_INVALID")
    return value


def _uuid_text(value: object) -> UUID:
    """Parse only canonical lowercase UUID text from a stored payload."""

    if not isinstance(value, str):
        raise InstrumentReferenceSnapshotError("INSTRUMENT_REFERENCE_SNAPSHOT_PAYLOAD_INVALID")
    try:
        parsed = UUID(value)
    except (AttributeError, TypeError, ValueError) as exc:
        raise InstrumentReferenceSnapshotError(
            "INSTRUMENT_REFERENCE_SNAPSHOT_PAYLOAD_INVALID"
        ) from exc
    if str(parsed) != value:
        raise InstrumentReferenceSnapshotError("INSTRUMENT_REFERENCE_SNAPSHOT_PAYLOAD_INVALID")
    return parsed


def _datetime_value(value: object) -> datetime:
    """Parse canonical UTC instant text from the immutable JSON snapshot."""

    if not isinstance(value, str) or not value.endswith("Z"):
        raise InstrumentReferenceSnapshotError("INSTRUMENT_REFERENCE_SNAPSHOT_PAYLOAD_INVALID")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise InstrumentReferenceSnapshotError(
            "INSTRUMENT_REFERENCE_SNAPSHOT_PAYLOAD_INVALID"
        ) from exc
    _require_utc(parsed)
    if _datetime_text(parsed) != value:
        raise InstrumentReferenceSnapshotError("INSTRUMENT_REFERENCE_SNAPSHOT_PAYLOAD_INVALID")
    return parsed


def _optional_date(value: object) -> date | None:
    """Parse a strict ISO date or preserve an explicit null."""

    if value is None:
        return None
    if not isinstance(value, str):
        raise InstrumentReferenceSnapshotError("INSTRUMENT_REFERENCE_SNAPSHOT_PAYLOAD_INVALID")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise InstrumentReferenceSnapshotError(
            "INSTRUMENT_REFERENCE_SNAPSHOT_PAYLOAD_INVALID"
        ) from exc
    if parsed.isoformat() != value:
        raise InstrumentReferenceSnapshotError("INSTRUMENT_REFERENCE_SNAPSHOT_PAYLOAD_INVALID")
    return parsed


def _same_crosswalk(
    left: InstrumentReferenceExchangeSuffixCrosswalk,
    right: InstrumentReferenceExchangeSuffixCrosswalk,
) -> bool:
    """Compare crosswalk identity and full pairs, not only coincident content hashes."""

    return (
        left.crosswalk_id == right.crosswalk_id
        and left.crosswalk_version == right.crosswalk_version
        and left.exchange_suffix_pairs == right.exchange_suffix_pairs
        and left.content_hash == right.content_hash
    )


def _require_token(value: object, code: str) -> None:
    """Require exact bounded ASCII token text for mapping identity fields."""

    if not isinstance(value, str) or not _TOKEN.fullmatch(value):
        raise InstrumentReferenceSnapshotError(code)


def _require_utc(value: object) -> None:
    """Require aware UTC instants; callers must not silently normalize offsets."""

    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
        or value.utcoffset() != UTC.utcoffset(value)
    ):
        raise InstrumentReferenceSnapshotError("INSTRUMENT_REFERENCE_TIMESTAMP_INVALID")


def _datetime_text(value: datetime) -> str:
    """Return stable UTC RFC3339 text for an already validated instant."""

    _require_utc(value)
    return value.isoformat().replace("+00:00", "Z")


def _valid_digest(value: object) -> bool:
    """Check the prefixed digest wire format."""

    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _string(value: object) -> str:
    """Narrow a JSON value to an exact string or reject the stored payload."""

    if not isinstance(value, str):
        raise InstrumentReferenceSnapshotError("INSTRUMENT_REFERENCE_MAPPING_PAYLOAD_INVALID")
    return value


__all__ = [
    "InstrumentReferenceClassification",
    "InstrumentReferenceFetchRound",
    "InstrumentReferenceMappingContent",
    "InstrumentReferenceMappingRecord",
    "InstrumentReferenceSnapshotContent",
    "InstrumentReferenceSnapshotError",
    "InstrumentReferenceSnapshotRecord",
    "make_instrument_reference_mapping_record",
    "make_instrument_reference_snapshot_record",
    "mapping_content_from_payload",
]
