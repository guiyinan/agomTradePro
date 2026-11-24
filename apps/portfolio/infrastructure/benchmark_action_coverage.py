"""Verify external effective-date coverage under the exact source approved by Portfolio."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from datetime import UTC, datetime
from io import BytesIO
from zipfile import BadZipFile, ZipFile

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from apps.portfolio.domain.policy_benchmark_corporate_action import (
    PolicyBenchmarkCorporateActionSourceRef,
)
from apps.portfolio.domain.policy_benchmark_daily_valuation import BenchmarkDayUnavailable

MEMBER = "action-coverage.json"
SOURCE_SCHEMA = "portfolio.benchmark.action-source.v1"
REPORT_SCHEMA = "portfolio.benchmark.no-action-coverage.v1"
COVERAGE_BASIS = "all_entitlement_effective_events_in_open_closed_interval"


def _canonical(value: dict[str, object]) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate signed coverage field")
        result[key] = value
    return result


def _text(record: dict[str, object], key: str) -> str:
    value = record[key]
    if type(value) is not str or not value or value != value.strip() or len(value) > 256:
        raise ValueError("invalid coverage field")
    return value


def _utc(value: datetime) -> str:
    if value.utcoffset() is None:
        raise ValueError("coverage requires an absolute timestamp")
    return value.astimezone(UTC).isoformat()


def _blob(value: str, length: int) -> bytes:
    raw = base64.b64decode(value, validate=True)
    if len(raw) != length or base64.b64encode(raw).decode("ascii") != value:
        raise ValueError("invalid signature encoding")
    return raw


def verify_no_action_coverage(
    *,
    raw_packet: bytes,
    source_ref: PolicyBenchmarkCorporateActionSourceRef,
    asset: str,
    covered_from: datetime,
    cutoff: datetime,
    as_of: datetime,
) -> str:
    """Validate an independent signer's explicit zero over the exact security and holding interval."""
    try:
        if not source_ref.recorded_at <= covered_from < cutoff <= as_of < source_ref.valid_until:
            raise ValueError("coverage lies outside the approved source window")
        if not raw_packet or len(raw_packet) > 2_000_000:
            raise ValueError("invalid day packet size")
        with ZipFile(BytesIO(raw_packet)) as archive:
            members = [entry for entry in archive.infolist() if entry.filename == MEMBER]
            if (
                len(members) != 1
                or not 0 < members[0].file_size <= 16384
                or members[0].flag_bits & 1
            ):
                raise ValueError("one bounded coverage record is required")
            document = json.loads(
                archive.read(members[0]).decode("utf-8"), object_pairs_hook=_unique
            )
        if not isinstance(document, dict) or set(document) != {
            "source_definition",
            "statement",
            "signature",
        }:
            raise ValueError("invalid coverage document")
        source, statement = document["source_definition"], document["statement"]
        if not isinstance(source, dict) or set(source) != {
            "schema",
            "owner",
            "artifact_type",
            "artifact_id",
            "artifact_version",
            "coverage_basis",
            "public_key",
        }:
            raise ValueError("invalid source definition")
        if (
            source["schema"],
            source["owner"],
            source["artifact_type"],
            source["artifact_id"],
            source["artifact_version"],
            source["coverage_basis"],
        ) != (
            SOURCE_SCHEMA,
            source_ref.owner,
            source_ref.artifact_type,
            source_ref.artifact_id,
            source_ref.artifact_version,
            COVERAGE_BASIS,
        ) or hashlib.sha256(
            _canonical(source)
        ).hexdigest() != source_ref.content_hash:
            raise ValueError("source definition does not match the approved reference")
        if not isinstance(statement, dict) or set(statement) != {
            "schema",
            "source_content_hash",
            "asset",
            "covered_from",
            "cutoff",
            "issued_at",
            "revision_id",
            "complete",
            "event_count",
        }:
            raise ValueError("incomplete coverage statement")
        if (
            (
                statement["schema"],
                statement["source_content_hash"],
                statement["asset"],
                statement["covered_from"],
                statement["cutoff"],
            )
            != (
                REPORT_SCHEMA,
                source_ref.content_hash,
                asset,
                _utc(covered_from),
                _utc(cutoff),
            )
            or statement["complete"] is not True
            or type(statement["event_count"]) is not int
            or statement["event_count"] != 0
        ):
            raise ValueError("statement does not certify zero over this exact interval")
        _text(statement, "revision_id")
        issued = datetime.fromisoformat(_text(statement, "issued_at"))
        if _utc(issued) != statement["issued_at"] or not cutoff <= issued <= as_of:
            raise ValueError("statement was not knowable at the valuation cutoff")
        key = Ed25519PublicKey.from_public_bytes(_blob(_text(source, "public_key"), 32))
        key.verify(_blob(_text(document, "signature"), 64), _canonical(statement))
        return hashlib.sha256(_canonical(document)).hexdigest()
    except (
        BadZipFile,
        OSError,
        RuntimeError,
        KeyError,
        TypeError,
        ValueError,
        binascii.Error,
        InvalidSignature,
    ) as error:
        raise BenchmarkDayUnavailable(
            "approved effective-date corporate-action coverage unavailable"
        ) from error
