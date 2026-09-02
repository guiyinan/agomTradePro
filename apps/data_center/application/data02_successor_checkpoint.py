"""Fail-closed DATA-02 successor production checkpoint evidence.

The parser consumes a candidate-bound, read-only checkpoint captured by an
external collector.  It never opens a database or network connection and it
cannot enable a backfill, publication switch, decision runtime, or production
readiness.  The checkpoint is intentionally stricter than the historical
reconciliation snapshot: every core dataset must carry its immutable
publication identity so that a later before/after report cannot silently
substitute a different publication.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Final, cast

DATA02_SUCCESSOR_SNAPSHOT_SCHEMA: Final[str] = "data02-successor-production-readonly-checkpoint.v1"
DATA02_SUCCESSOR_REPORT_SCHEMA: Final[str] = "data02-successor-checkpoint-readonly.v1"
DATA02_SUCCESSOR_DATASET_KEYS: Final[tuple[str, ...]] = (
    "equity.financial.fact",
    "equity.price.bar",
    "equity.quote.snapshot",
    "equity.valuation.fact",
)
DATA02_SUCCESSOR_ASSET_COUNT: Final[int] = 5_533
DATA02_SUCCESSOR_MAX_SAMPLES: Final[int] = 100

_COMMIT_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{40}$")
_RELEASE_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9]{14}$")
_SHA256_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_.:/-]{1,256}$")
_DATE_RE: Final[re.Pattern[str]] = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_UTC_TEXT_RE: Final[re.Pattern[str]] = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$"
)
_TOP_LEVEL_KEYS: Final[frozenset[str]] = frozenset(
    {
        "candidate",
        "connection_stability",
        "fact_repair_dry_run",
        "gate",
        "observed_at",
        "public_probe_window",
        "publication_rebuild_dry_run",
        "schema",
        "side_effects",
    }
)
_CANDIDATE_KEYS: Final[frozenset[str]] = frozenset(
    {"candidate_drift", "image_id", "release_id", "source_commit"}
)
_CONNECTION_KEYS: Final[frozenset[str]] = frozenset(
    {
        "client_backend_growth",
        "data04_successor_stability_verified",
        "idle_growth",
        "sample_interval_seconds",
        "samples",
        "scrape_interval_seconds",
    }
)
_CONNECTION_SAMPLE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "client_backend_count",
        "idle_count",
        "max_connections",
        "observed_at",
        "remote_client_count",
        "superuser_reserved_connections",
    }
)
_PROBE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "audit_health_200_count",
        "decision_must_not_use_for_decision",
        "decision_ready_503_count",
        "health_200_count",
        "ready_200_count",
        "response_sha256",
        "sample_count",
    }
)
_REPAIR_KEYS: Final[frozenset[str]] = frozenset(
    {
        "asset_count",
        "batch_size",
        "completed_session_prices",
        "exit_code",
        "financial_availability",
        "mode",
        "ready_without_provider_refresh",
        "session_date",
        "source",
    }
)
_FINANCIAL_KEYS: Final[frozenset[str]] = frozenset(
    {
        "eligible_asset_count",
        "eligible_row_count",
        "future_available_at_count",
        "future_report_date_count",
        "missing_row_count",
        "safe_to_execute",
        "unresolved_row_count",
    }
)
_PRICE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "eligible_asset_count",
        "invalid_asset_count",
        "missing_asset_count",
        "newest_snapshot_at",
        "oldest_snapshot_at",
        "ready",
        "requested_asset_count",
    }
)
_PUBLICATION_REBUILD_KEYS: Final[frozenset[str]] = frozenset(
    {"asset_count", "dataset_count", "datasets", "exit_code", "member_count", "mode", "ready"}
)
_DATASET_KEYS: Final[frozenset[str]] = frozenset(
    {
        "covered_asset_count",
        "missing_asset_count",
        "newest_observed_at",
        "publication_hash",
        "publication_id",
        "ready",
    }
)
_GATE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "data02_execution_ready",
        "data02_exit_gate_complete",
        "data03_activation_allowed",
        "data04_production_revalidation",
        "next_blocker",
    }
)
_SIDE_EFFECT_KEYS: Final[frozenset[str]] = frozenset(
    {
        "backfill_executed",
        "production_database_write",
        "production_ready",
        "publication_switched",
        "read_mode",
        "runtime_activated",
    }
)


class Data02SuccessorCheckpointError(ValueError):
    """Raised when a successor checkpoint violates its read-only contract."""


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    """Narrow one decoded JSON object and reject non-string keys."""

    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise Data02SuccessorCheckpointError(f"{field_name} must be an object")
    return cast(Mapping[str, object], value)


def _exact_keys(value: Mapping[str, object], expected: frozenset[str], field_name: str) -> None:
    """Reject omitted and smuggled keys at every envelope boundary."""

    actual = frozenset(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise Data02SuccessorCheckpointError(
            f"{field_name} keys changed (missing={missing}, extra={extra})"
        )


def _text(value: object, field_name: str, *, pattern: re.Pattern[str] | None = None) -> str:
    """Require bounded, non-secret text."""

    if type(value) is not str or not value or value.strip() != value or len(value) > 1024:
        raise Data02SuccessorCheckpointError(f"{field_name} must be bounded text")
    if pattern is not None and pattern.fullmatch(value) is None:
        raise Data02SuccessorCheckpointError(f"{field_name} has an invalid format")
    return value


def _token(value: object, field_name: str) -> str:
    """Require a bounded identity token."""

    return _text(value, field_name, pattern=_TOKEN_RE)


def _sha256(value: object, field_name: str) -> str:
    """Require a lowercase SHA-256 digest."""

    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise Data02SuccessorCheckpointError(f"{field_name} must be lowercase SHA-256")
    return value


def _integer(value: object, field_name: str, *, minimum: int = 0) -> int:
    """Require a non-boolean bounded integer."""

    if type(value) is not int or value < minimum:
        raise Data02SuccessorCheckpointError(f"{field_name} must be an integer >= {minimum}")
    return value


def _signed_integer(value: object, field_name: str) -> int:
    """Require a non-boolean signed integer for a delta field."""

    if type(value) is not int:
        raise Data02SuccessorCheckpointError(f"{field_name} must be an integer")
    return value


def _boolean(value: object, field_name: str) -> bool:
    """Require a JSON boolean."""

    if type(value) is not bool:
        raise Data02SuccessorCheckpointError(f"{field_name} must be boolean")
    return value


def _parse_utc(value: object, field_name: str, *, cutoff: datetime) -> datetime:
    """Parse canonical UTC-Z text and reject future observations."""

    if type(value) is not str or _UTC_TEXT_RE.fullmatch(value) is None:
        raise Data02SuccessorCheckpointError(f"{field_name} must be canonical UTC text")
    try:
        iso_value = value[:-1] + "+00:00" if value.endswith("Z") else value
        parsed = datetime.fromisoformat(iso_value)
    except ValueError as exc:
        raise Data02SuccessorCheckpointError(f"{field_name} is not a valid UTC timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise Data02SuccessorCheckpointError(f"{field_name} must use UTC")
    parsed = parsed.astimezone(UTC)
    if parsed > cutoff:
        raise Data02SuccessorCheckpointError(f"{field_name} is from the future")
    return parsed


def _utc_text(value: datetime) -> str:
    """Serialize a timestamp with canonical microsecond precision."""

    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _cutoff(value: datetime | None) -> datetime:
    """Validate an optional UTC evaluation clock."""

    result = value or datetime.now(UTC)
    if result.tzinfo is None or result.utcoffset() != timedelta(0):
        raise Data02SuccessorCheckpointError("as_of must use UTC")
    return result.astimezone(UTC)


def _candidate(value: object) -> dict[str, object]:
    """Validate one immutable deployed candidate identity."""

    raw = _mapping(value, "candidate")
    _exact_keys(raw, _CANDIDATE_KEYS, "candidate")
    source_commit = _text(raw["source_commit"], "candidate.source_commit", pattern=_COMMIT_RE)
    release_id = _text(raw["release_id"], "candidate.release_id", pattern=_RELEASE_RE)
    image_id = _text(raw["image_id"], "candidate.image_id")
    if not image_id.startswith("sha256:"):
        raise Data02SuccessorCheckpointError("candidate.image_id must use sha256: prefix")
    _sha256(image_id.removeprefix("sha256:"), "candidate.image_id")
    candidate_drift = _boolean(raw["candidate_drift"], "candidate.candidate_drift")
    if candidate_drift:
        raise Data02SuccessorCheckpointError("candidate drift must be false")
    return {
        "candidate_drift": False,
        "image_id": image_id,
        "release_id": release_id,
        "source_commit": source_commit,
    }


def _connection(value: object, *, observed_at: datetime) -> dict[str, object]:
    """Validate connection samples and derive their declared growth."""

    raw = _mapping(value, "connection_stability")
    _exact_keys(raw, _CONNECTION_KEYS, "connection_stability")
    scrape_interval = _integer(
        raw["scrape_interval_seconds"], "connection.scrape_interval_seconds", minimum=1
    )
    sample_interval = _integer(
        raw["sample_interval_seconds"], "connection.sample_interval_seconds", minimum=1
    )
    samples_raw = raw["samples"]
    if not isinstance(samples_raw, list) or not samples_raw:
        raise Data02SuccessorCheckpointError("connection.samples must be a non-empty array")
    if len(samples_raw) > DATA02_SUCCESSOR_MAX_SAMPLES:
        raise Data02SuccessorCheckpointError("connection.samples exceeds bounded maximum")
    samples: list[dict[str, object]] = []
    previous: datetime | None = None
    for index, item in enumerate(samples_raw):
        sample = _mapping(item, f"connection.samples[{index}]")
        _exact_keys(sample, _CONNECTION_SAMPLE_KEYS, f"connection.samples[{index}]")
        captured = _parse_utc(
            sample["observed_at"], f"connection.samples[{index}].observed_at", cutoff=observed_at
        )
        if previous is not None and captured <= previous:
            raise Data02SuccessorCheckpointError(
                "connection sample times must be strictly increasing"
            )
        previous = captured
        max_connections = _integer(
            sample["max_connections"], f"connection.samples[{index}].max_connections", minimum=1
        )
        reserved = _integer(
            sample["superuser_reserved_connections"],
            f"connection.samples[{index}].superuser_reserved_connections",
        )
        clients = _integer(
            sample["client_backend_count"], f"connection.samples[{index}].client_backend_count"
        )
        idle = _integer(sample["idle_count"], f"connection.samples[{index}].idle_count")
        remote = _integer(
            sample["remote_client_count"], f"connection.samples[{index}].remote_client_count"
        )
        if (
            reserved > max_connections
            or clients > max_connections
            or idle > clients
            or remote > clients
        ):
            raise Data02SuccessorCheckpointError(
                f"connection.samples[{index}] counts are inconsistent"
            )
        samples.append(
            {
                "client_backend_count": clients,
                "idle_count": idle,
                "max_connections": max_connections,
                "observed_at": _utc_text(captured),
                "remote_client_count": remote,
                "superuser_reserved_connections": reserved,
            }
        )
    declared_client_growth = _signed_integer(
        raw["client_backend_growth"], "connection.client_backend_growth"
    )
    declared_idle_growth = _signed_integer(raw["idle_growth"], "connection.idle_growth")
    derived_client_growth = cast(int, samples[-1]["client_backend_count"]) - cast(
        int, samples[0]["client_backend_count"]
    )
    derived_idle_growth = cast(int, samples[-1]["idle_count"]) - cast(int, samples[0]["idle_count"])
    if (
        declared_client_growth != derived_client_growth
        or declared_idle_growth != derived_idle_growth
    ):
        raise Data02SuccessorCheckpointError("connection growth does not match samples")
    stability = _boolean(
        raw["data04_successor_stability_verified"],
        "connection.data04_successor_stability_verified",
    )
    if stability and (declared_client_growth != 0 or declared_idle_growth != 0):
        raise Data02SuccessorCheckpointError("stable connection claim conflicts with growth")
    return {
        "client_backend_growth": declared_client_growth,
        "data04_successor_stability_verified": stability,
        "idle_growth": declared_idle_growth,
        "sample_interval_seconds": sample_interval,
        "samples": samples,
        "scrape_interval_seconds": scrape_interval,
    }


def _probe(value: object) -> dict[str, object]:
    """Validate bounded public probe counts and response digests."""

    raw = _mapping(value, "public_probe_window")
    _exact_keys(raw, _PROBE_KEYS, "public_probe_window")
    sample_count = _integer(raw["sample_count"], "probe.sample_count", minimum=1)
    if sample_count > DATA02_SUCCESSOR_MAX_SAMPLES:
        raise Data02SuccessorCheckpointError("probe.sample_count exceeds bounded maximum")
    counts: dict[str, int] = {}
    for key in (
        "health_200_count",
        "ready_200_count",
        "audit_health_200_count",
        "decision_ready_503_count",
    ):
        count = _integer(raw[key], f"probe.{key}")
        if count > sample_count:
            raise Data02SuccessorCheckpointError(f"probe.{key} exceeds sample_count")
        counts[key] = count
    must_not = _boolean(
        raw["decision_must_not_use_for_decision"], "probe.decision_must_not_use_for_decision"
    )
    if not must_not or counts["decision_ready_503_count"] != sample_count:
        raise Data02SuccessorCheckpointError(
            "decision probe must remain 503 and must_not_use_for_decision across the window"
        )
    response_raw = _mapping(raw["response_sha256"], "probe.response_sha256")
    expected_response_keys = frozenset({"audit_health", "decision_ready", "health", "ready"})
    _exact_keys(response_raw, expected_response_keys, "probe.response_sha256")
    responses: dict[str, list[str]] = {}
    for key in sorted(expected_response_keys):
        values = response_raw[key]
        if not isinstance(values, list) or len(values) != sample_count:
            raise Data02SuccessorCheckpointError(f"probe.response_sha256.{key} length mismatch")
        responses[key] = [_sha256(item, f"probe.response_sha256.{key}[]") for item in values]
    return {
        "audit_health_200_count": counts["audit_health_200_count"],
        "decision_must_not_use_for_decision": True,
        "decision_ready_503_count": counts["decision_ready_503_count"],
        "health_200_count": counts["health_200_count"],
        "ready_200_count": counts["ready_200_count"],
        "response_sha256": responses,
        "sample_count": sample_count,
    }


def _date_text(value: object, field_name: str, *, observed_at: datetime) -> str:
    """Validate a source session date and prevent future substitution."""

    if type(value) is not str or _DATE_RE.fullmatch(value) is None:
        raise Data02SuccessorCheckpointError(f"{field_name} must be YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise Data02SuccessorCheckpointError(f"{field_name} is not a valid date") from exc
    if parsed > observed_at.date():
        raise Data02SuccessorCheckpointError(f"{field_name} is from the future")
    return parsed.isoformat()


def _fact_repair(value: object, *, observed_at: datetime) -> dict[str, object]:
    """Validate the dry-run coverage and freshness projection."""

    raw = _mapping(value, "fact_repair_dry_run")
    _exact_keys(raw, _REPAIR_KEYS, "fact_repair_dry_run")
    if raw["mode"] != "dry_run":
        raise Data02SuccessorCheckpointError("fact_repair_dry_run.mode must be dry_run")
    source = _token(raw["source"], "fact_repair_dry_run.source")
    batch_size = _integer(raw["batch_size"], "fact_repair_dry_run.batch_size", minimum=1)
    asset_count = _integer(raw["asset_count"], "fact_repair_dry_run.asset_count")
    if asset_count != DATA02_SUCCESSOR_ASSET_COUNT:
        raise Data02SuccessorCheckpointError("fact_repair_dry_run.asset_count must equal 5533")
    session_date = _date_text(
        raw["session_date"], "fact_repair_dry_run.session_date", observed_at=observed_at
    )
    financial_raw = _mapping(
        raw["financial_availability"], "fact_repair_dry_run.financial_availability"
    )
    _exact_keys(financial_raw, _FINANCIAL_KEYS, "fact_repair_dry_run.financial_availability")
    eligible_assets = _integer(
        financial_raw["eligible_asset_count"], "financial.eligible_asset_count"
    )
    if eligible_assets > asset_count:
        raise Data02SuccessorCheckpointError("financial eligible assets exceed asset_count")
    financial = {
        "eligible_asset_count": eligible_assets,
        "eligible_row_count": _integer(
            financial_raw["eligible_row_count"], "financial.eligible_row_count"
        ),
        "future_available_at_count": _integer(
            financial_raw["future_available_at_count"], "financial.future_available_at_count"
        ),
        "future_report_date_count": _integer(
            financial_raw["future_report_date_count"], "financial.future_report_date_count"
        ),
        "missing_row_count": _integer(
            financial_raw["missing_row_count"], "financial.missing_row_count"
        ),
        "safe_to_execute": _boolean(financial_raw["safe_to_execute"], "financial.safe_to_execute"),
        "unresolved_row_count": _integer(
            financial_raw["unresolved_row_count"], "financial.unresolved_row_count"
        ),
    }
    prices_raw = _mapping(
        raw["completed_session_prices"], "fact_repair_dry_run.completed_session_prices"
    )
    _exact_keys(prices_raw, _PRICE_KEYS, "fact_repair_dry_run.completed_session_prices")
    requested = _integer(prices_raw["requested_asset_count"], "prices.requested_asset_count")
    if requested != asset_count:
        raise Data02SuccessorCheckpointError("prices.requested_asset_count must equal 5533")
    eligible = _integer(prices_raw["eligible_asset_count"], "prices.eligible_asset_count")
    invalid = _integer(prices_raw["invalid_asset_count"], "prices.invalid_asset_count")
    missing = _integer(prices_raw["missing_asset_count"], "prices.missing_asset_count")
    if eligible + invalid + missing != requested:
        raise Data02SuccessorCheckpointError("prices asset counts must partition requested assets")
    newest = _parse_utc(
        prices_raw["newest_snapshot_at"], "prices.newest_snapshot_at", cutoff=observed_at
    )
    oldest = _parse_utc(
        prices_raw["oldest_snapshot_at"], "prices.oldest_snapshot_at", cutoff=observed_at
    )
    if oldest > newest:
        raise Data02SuccessorCheckpointError("prices oldest snapshot exceeds newest snapshot")
    ready = _boolean(prices_raw["ready"], "prices.ready")
    expected_ready = eligible == requested and invalid == 0 and missing == 0
    if ready != expected_ready:
        raise Data02SuccessorCheckpointError("prices.ready conflicts with asset counts")
    ready_without_refresh = _boolean(
        raw["ready_without_provider_refresh"],
        "fact_repair_dry_run.ready_without_provider_refresh",
    )
    exit_code = _integer(raw["exit_code"], "fact_repair_dry_run.exit_code")
    if exit_code != 0:
        raise Data02SuccessorCheckpointError("fact_repair_dry_run.exit_code must be zero")
    return {
        "asset_count": asset_count,
        "batch_size": batch_size,
        "completed_session_prices": {
            "eligible_asset_count": eligible,
            "invalid_asset_count": invalid,
            "missing_asset_count": missing,
            "newest_snapshot_at": _utc_text(newest),
            "oldest_snapshot_at": _utc_text(oldest),
            "ready": ready,
            "requested_asset_count": requested,
        },
        "exit_code": exit_code,
        "financial_availability": financial,
        "mode": "dry_run",
        "ready_without_provider_refresh": ready_without_refresh,
        "session_date": session_date,
        "source": source,
    }


def _publication_rebuild(value: object, *, observed_at: datetime) -> dict[str, object]:
    """Validate four dataset coverage rows and immutable publication IDs."""

    raw = _mapping(value, "publication_rebuild_dry_run")
    _exact_keys(raw, _PUBLICATION_REBUILD_KEYS, "publication_rebuild_dry_run")
    if raw["mode"] != "dry_run":
        raise Data02SuccessorCheckpointError("publication_rebuild_dry_run.mode must be dry_run")
    asset_count = _integer(raw["asset_count"], "publication.asset_count")
    if asset_count != DATA02_SUCCESSOR_ASSET_COUNT:
        raise Data02SuccessorCheckpointError("publication.asset_count must equal 5533")
    member_count = _integer(raw["member_count"], "publication.member_count")
    exit_code = _integer(raw["exit_code"], "publication.exit_code")
    if exit_code != 0:
        raise Data02SuccessorCheckpointError("publication.exit_code must be zero")
    dataset_count = _integer(raw["dataset_count"], "publication.dataset_count")
    if dataset_count != len(DATA02_SUCCESSOR_DATASET_KEYS):
        raise Data02SuccessorCheckpointError(
            "publication.dataset_count must equal four core datasets"
        )
    datasets_raw = _mapping(raw["datasets"], "publication.datasets")
    if tuple(sorted(datasets_raw)) != tuple(sorted(DATA02_SUCCESSOR_DATASET_KEYS)):
        raise Data02SuccessorCheckpointError(
            "publication.datasets must contain the four core datasets"
        )
    datasets: dict[str, dict[str, object]] = {}
    publication_ids: set[str] = set()
    publication_hashes: set[str] = set()
    for dataset_key in DATA02_SUCCESSOR_DATASET_KEYS:
        dataset = _mapping(datasets_raw[dataset_key], f"publication.datasets.{dataset_key}")
        _exact_keys(dataset, _DATASET_KEYS, f"publication.datasets.{dataset_key}")
        covered = _integer(dataset["covered_asset_count"], f"{dataset_key}.covered_asset_count")
        missing = _integer(dataset["missing_asset_count"], f"{dataset_key}.missing_asset_count")
        if covered + missing != asset_count:
            raise Data02SuccessorCheckpointError(f"{dataset_key} asset counts must partition 5533")
        ready = _boolean(dataset["ready"], f"{dataset_key}.ready")
        if ready != (missing == 0):
            raise Data02SuccessorCheckpointError(
                f"{dataset_key}.ready conflicts with missing count"
            )
        newest = _parse_utc(
            dataset["newest_observed_at"], f"{dataset_key}.newest_observed_at", cutoff=observed_at
        )
        publication_id = _token(dataset["publication_id"], f"{dataset_key}.publication_id")
        publication_hash = _sha256(dataset["publication_hash"], f"{dataset_key}.publication_hash")
        if publication_id in publication_ids or publication_hash in publication_hashes:
            raise Data02SuccessorCheckpointError(
                "publication identities must be unique across datasets"
            )
        publication_ids.add(publication_id)
        publication_hashes.add(publication_hash)
        datasets[dataset_key] = {
            "covered_asset_count": covered,
            "missing_asset_count": missing,
            "newest_observed_at": _utc_text(newest),
            "publication_hash": publication_hash,
            "publication_id": publication_id,
            "ready": ready,
        }
    ready = _boolean(raw["ready"], "publication.ready")
    expected_ready = all(bool(dataset["ready"]) for dataset in datasets.values())
    if ready != expected_ready:
        raise Data02SuccessorCheckpointError("publication.ready conflicts with dataset readiness")
    return {
        "asset_count": asset_count,
        "dataset_count": dataset_count,
        "datasets": datasets,
        "exit_code": exit_code,
        "member_count": member_count,
        "mode": "dry_run",
        "ready": ready,
    }


def _gate(value: object) -> dict[str, object]:
    """Validate the fail-closed gate projection."""

    raw = _mapping(value, "gate")
    _exact_keys(raw, _GATE_KEYS, "gate")
    data04 = _token(raw["data04_production_revalidation"], "gate.data04_production_revalidation")
    if data04 not in {"passed", "blocked", "failed"}:
        raise Data02SuccessorCheckpointError(
            "gate.data04_production_revalidation has invalid status"
        )
    execution_ready = _boolean(raw["data02_execution_ready"], "gate.data02_execution_ready")
    exit_complete = _boolean(raw["data02_exit_gate_complete"], "gate.data02_exit_gate_complete")
    activation_allowed = _boolean(
        raw["data03_activation_allowed"], "gate.data03_activation_allowed"
    )
    if exit_complete and not execution_ready:
        raise Data02SuccessorCheckpointError(
            "DATA-02 exit gate cannot complete before execution readiness"
        )
    if activation_allowed and not exit_complete:
        raise Data02SuccessorCheckpointError("DATA-03 activation cannot precede DATA-02 exit")
    return {
        "data02_execution_ready": execution_ready,
        "data02_exit_gate_complete": exit_complete,
        "data03_activation_allowed": activation_allowed,
        "data04_production_revalidation": data04,
        "next_blocker": _text(raw["next_blocker"], "gate.next_blocker"),
    }


def _side_effects(value: object) -> dict[str, object]:
    """Require the snapshot to remain strictly read-only."""

    raw = _mapping(value, "side_effects")
    _exact_keys(raw, _SIDE_EFFECT_KEYS, "side_effects")
    read_mode = _token(raw["read_mode"], "side_effects.read_mode")
    if read_mode != "select_only_and_provider_read":
        raise Data02SuccessorCheckpointError(
            "side_effects.read_mode must be select_only_and_provider_read"
        )
    flags = {
        key: _boolean(raw[key], f"side_effects.{key}")
        for key in (
            "backfill_executed",
            "production_database_write",
            "production_ready",
            "publication_switched",
            "runtime_activated",
        )
    }
    if any(flags.values()):
        raise Data02SuccessorCheckpointError(
            "successor checkpoint must contain no production side effects"
        )
    return {**flags, "read_mode": read_mode}


@dataclass(frozen=True, slots=True)
class Data02SuccessorCheckpoint:
    """Canonical, non-enabling report derived from one successor checkpoint."""

    observed_at: datetime
    candidate: dict[str, object]
    connection_stability: dict[str, object]
    public_probe_window: dict[str, object]
    fact_repair_dry_run: dict[str, object]
    publication_rebuild_dry_run: dict[str, object]
    gate: dict[str, object]
    side_effects: dict[str, object]

    @property
    def production_ready(self) -> bool:
        """Read-only checkpoint evidence never enables production."""

        return False

    def to_dict(self) -> dict[str, object]:
        """Return deterministic JSON-safe report bytes as a mapping."""

        return {
            "candidate": self.candidate,
            "connection_stability": self.connection_stability,
            "evidence_scope": "data02_successor_production_readonly_checkpoint",
            "fact_repair_dry_run": self.fact_repair_dry_run,
            "gate": self.gate,
            "observed_at": _utc_text(self.observed_at),
            "production_claim": False,
            "production_ready": False,
            "public_probe_window": self.public_probe_window,
            "publication_rebuild_dry_run": self.publication_rebuild_dry_run,
            "runtime_enablement": "not_authorized",
            "schema_version": DATA02_SUCCESSOR_REPORT_SCHEMA,
            "side_effects": self.side_effects,
        }


def parse_data02_successor_checkpoint(
    payload: bytes,
    *,
    as_of: datetime | None = None,
) -> Data02SuccessorCheckpoint:
    """Parse one external checkpoint without touching production state."""

    if type(payload) is not bytes or not payload:
        raise Data02SuccessorCheckpointError("payload must be non-empty bytes")
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Data02SuccessorCheckpointError("payload must be UTF-8 JSON") from exc
    raw = _mapping(decoded, "checkpoint")
    _exact_keys(raw, _TOP_LEVEL_KEYS, "checkpoint")
    cutoff = _cutoff(as_of)
    if raw["schema"] != DATA02_SUCCESSOR_SNAPSHOT_SCHEMA:
        raise Data02SuccessorCheckpointError("checkpoint.schema is not canonical")
    observed_at = _parse_utc(raw["observed_at"], "observed_at", cutoff=cutoff)
    candidate = _candidate(raw["candidate"])
    connection = _connection(raw["connection_stability"], observed_at=observed_at)
    probe = _probe(raw["public_probe_window"])
    repair = _fact_repair(raw["fact_repair_dry_run"], observed_at=observed_at)
    publication = _publication_rebuild(raw["publication_rebuild_dry_run"], observed_at=observed_at)
    gate = _gate(raw["gate"])
    side_effects = _side_effects(raw["side_effects"])
    price_projection = _mapping(
        repair["completed_session_prices"], "fact_repair_dry_run.completed_session_prices"
    )
    if bool(gate["data02_execution_ready"]) and (
        not _boolean(price_projection["ready"], "prices.ready")
        or not _boolean(publication["ready"], "publication.ready")
    ):
        raise Data02SuccessorCheckpointError(
            "DATA-02 execution readiness conflicts with dry-run readiness"
        )
    return Data02SuccessorCheckpoint(
        observed_at=observed_at,
        candidate=candidate,
        connection_stability=connection,
        public_probe_window=probe,
        fact_repair_dry_run=repair,
        publication_rebuild_dry_run=publication,
        gate=gate,
        side_effects=side_effects,
    )


def serialize_data02_successor_checkpoint(report: Data02SuccessorCheckpoint) -> bytes:
    """Serialize one canonical successor report with stable JSON bytes."""

    return json.dumps(
        report.to_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def data02_successor_checkpoint_artifact_sha256(payload: bytes) -> str:
    """Return the content address for canonical successor evidence."""

    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "DATA02_SUCCESSOR_ASSET_COUNT",
    "DATA02_SUCCESSOR_DATASET_KEYS",
    "DATA02_SUCCESSOR_REPORT_SCHEMA",
    "DATA02_SUCCESSOR_SNAPSHOT_SCHEMA",
    "Data02SuccessorCheckpoint",
    "Data02SuccessorCheckpointError",
    "data02_successor_checkpoint_artifact_sha256",
    "parse_data02_successor_checkpoint",
    "serialize_data02_successor_checkpoint",
]
