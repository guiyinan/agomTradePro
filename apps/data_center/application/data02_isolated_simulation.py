"""Provider-free historical simulation contracts for DATA-02.

The use case accepts an already restored, disposable PostgreSQL snapshot through
an injected port.  It never restores a dump, connects to production, invokes a
provider, writes facts/publications, or promotes the resulting evidence into a
production gate.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Protocol

_COMMIT_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_.:/-]{1,256}$")
_DATABASE_RE: Final[re.Pattern[str]] = re.compile(r"^agom_data02_sim_[a-z0-9]{8,32}$")
_CORE_DATASET_TABLES: Final[dict[str, str]] = {
    "equity.financial.fact": "data_center_financial_fact",
    "equity.price.bar": "data_center_price_bar",
    "equity.quote.snapshot": "data_center_quote_snapshot",
    "equity.valuation.fact": "data_center_valuation_fact",
}


def _aware_utc(value: datetime, field_name: str) -> datetime:
    """Require an aware timestamp and normalize it to UTC."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _utc_text(value: datetime | None) -> str | None:
    """Serialize an optional timestamp using stable UTC-Z text."""

    if value is None:
        return None
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _hash_json(value: object) -> str:
    """Return a stable SHA-256 for a JSON-safe value."""

    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class Data02IsolatedSimulationCandidate:
    """Immutable repository candidate identity used by one simulation."""

    commit: str
    version: str
    source_tree_sha256: str

    def __post_init__(self) -> None:
        if _COMMIT_RE.fullmatch(self.commit) is None:
            raise ValueError("candidate commit must be a lowercase 40-character SHA")
        if _TOKEN_RE.fullmatch(self.version) is None:
            raise ValueError("candidate version must be a bounded token")
        if _SHA256_RE.fullmatch(self.source_tree_sha256) is None:
            raise ValueError("candidate source_tree_sha256 must be a lowercase SHA-256")

    def to_dict(self) -> dict[str, str]:
        """Return the canonical candidate identity."""

        return {
            "commit": self.commit,
            "source_tree_sha256": self.source_tree_sha256,
            "version": self.version,
        }


@dataclass(frozen=True, slots=True)
class Data02IsolatedSimulationRequest:
    """Bounded immutable inputs for one historical simulation."""

    candidate: Data02IsolatedSimulationCandidate
    dump_sha256: str
    dump_size: int
    dump_name: str
    restored_database: str
    as_of: datetime

    def __post_init__(self) -> None:
        if _SHA256_RE.fullmatch(self.dump_sha256) is None:
            raise ValueError("dump_sha256 must be a lowercase SHA-256")
        if isinstance(self.dump_size, bool) or self.dump_size < 1:
            raise ValueError("dump_size must be a positive integer")
        if _TOKEN_RE.fullmatch(self.dump_name) is None or "/" in self.dump_name:
            raise ValueError("dump_name must be one bounded filename")
        if _DATABASE_RE.fullmatch(self.restored_database) is None:
            raise ValueError("restored_database must use the controlled simulation prefix")
        object.__setattr__(self, "as_of", _aware_utc(self.as_of, "as_of"))


@dataclass(frozen=True, slots=True)
class Data02HistoricalFactReference:
    """Exact immutable fact or publication-member reference."""

    natural_key: str
    asset_code: str
    fact_table: str
    fact_pk: str
    source: str
    observed_at: datetime
    quality_status: str

    def __post_init__(self) -> None:
        for field_name in (
            "natural_key",
            "asset_code",
            "fact_table",
            "fact_pk",
            "source",
            "quality_status",
        ):
            value = getattr(self, field_name)
            if not value.strip():
                raise ValueError(f"{field_name} cannot be empty")
        object.__setattr__(self, "observed_at", _aware_utc(self.observed_at, "observed_at"))

    def comparison_dict(self) -> dict[str, object]:
        """Return fields used for exact reconciliation and hashing."""

        return {
            "asset_code": self.asset_code,
            "fact_pk": self.fact_pk,
            "fact_table": self.fact_table,
            "natural_key": self.natural_key,
            "observed_at": _utc_text(self.observed_at),
            "quality_status": self.quality_status,
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class Data02HistoricalPublicationSnapshot:
    """Current publication identity and exact member references."""

    publication_id: str
    publication_hash: str
    state: str
    must_not_use_for_decision: bool
    blocked_reason: str
    members: tuple[Data02HistoricalFactReference, ...]

    def __post_init__(self) -> None:
        if not self.publication_id.strip():
            raise ValueError("publication_id cannot be empty")
        if _SHA256_RE.fullmatch(self.publication_hash) is None:
            raise ValueError("publication_hash must be a lowercase SHA-256")
        if not self.state.strip():
            raise ValueError("publication state cannot be empty")


@dataclass(frozen=True, slots=True)
class Data02HistoricalDatasetSnapshot:
    """Selected latest facts and the current publication for one dataset."""

    dataset_key: str
    fact_table: str
    fact_row_count: int
    freshness_seconds: int | None
    facts: tuple[Data02HistoricalFactReference, ...]
    publication: Data02HistoricalPublicationSnapshot | None

    def __post_init__(self) -> None:
        expected_table = _CORE_DATASET_TABLES.get(self.dataset_key)
        if expected_table is None or self.fact_table != expected_table:
            raise ValueError("dataset_key and fact_table must match the core DATA-02 catalog")
        if isinstance(self.fact_row_count, bool) or self.fact_row_count < len(self.facts):
            raise ValueError("fact_row_count cannot be smaller than selected facts")
        if self.freshness_seconds is not None and (
            isinstance(self.freshness_seconds, bool) or self.freshness_seconds < 1
        ):
            raise ValueError("freshness_seconds must be positive when configured")
        references = self.facts + (self.publication.members if self.publication is not None else ())
        if any(reference.fact_table != self.fact_table for reference in references):
            raise ValueError("dataset references must use the declared fact_table")


@dataclass(frozen=True, slots=True)
class Data02HistoricalDatabaseSnapshot:
    """One repeatable-read, read-only view of the restored database."""

    database_name: str
    captured_at: datetime
    transaction_read_only: bool
    data_center_migrations: tuple[str, ...]
    universe_id: str
    universe_codes: tuple[str, ...]
    datasets: tuple[Data02HistoricalDatasetSnapshot, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "captured_at", _aware_utc(self.captured_at, "captured_at"))
        if not self.database_name.strip() or not self.universe_id.strip():
            raise ValueError("database_name and universe_id cannot be empty")
        if not self.data_center_migrations:
            raise ValueError("data_center_migrations cannot be empty")
        if not self.universe_codes:
            raise ValueError("universe_codes cannot be empty")
        if self.universe_codes != tuple(sorted(set(self.universe_codes))):
            raise ValueError("universe_codes must be sorted and unique")
        actual_datasets = {dataset.dataset_key for dataset in self.datasets}
        if actual_datasets != set(_CORE_DATASET_TABLES):
            raise ValueError("historical snapshot must contain all four core DATA-02 datasets")


class Data02HistoricalSnapshotPort(Protocol):
    """Port collecting one isolated, repeatable-read database snapshot."""

    def collect(self) -> Data02HistoricalDatabaseSnapshot:
        """Return an exact read-only snapshot without mutating the database."""


@dataclass(frozen=True, slots=True)
class Data02HistoricalDatasetAnalysis:
    """Deterministic coverage, freshness and reconciliation for one dataset."""

    dataset_key: str
    fact_table: str
    fact_row_count: int
    requested_asset_count: int
    candidate_asset_count: int
    candidate_member_count: int
    publication_id: str | None
    publication_hash: str | None
    publication_state: str | None
    publication_must_not_use_for_decision: bool | None
    publication_blocked_reason: str | None
    publication_asset_count: int
    publication_member_count: int
    missing_asset_count: int
    unexpected_asset_count: int
    source_only_count: int
    target_only_count: int
    exact_match_count: int
    fact_reference_mismatch_count: int
    timestamp_mismatch_count: int
    quality_mismatch_count: int
    future_observation_count: int
    stale_observation_count: int
    freshness_status: str
    max_age_seconds: int | None
    age_seconds: float | None
    oldest_observed_at: datetime | None
    newest_observed_at: datetime | None
    source_snapshot_sha256: str
    target_snapshot_sha256: str | None

    @property
    def historical_gate_allow(self) -> bool:
        """Return whether this historical snapshot is exact and self-consistent."""

        return (
            self.requested_asset_count > 0
            and self.candidate_asset_count == self.requested_asset_count
            and self.publication_asset_count == self.requested_asset_count
            and self.missing_asset_count == 0
            and self.unexpected_asset_count == 0
            and self.source_only_count == 0
            and self.target_only_count == 0
            and self.fact_reference_mismatch_count == 0
            and self.timestamp_mismatch_count == 0
            and self.quality_mismatch_count == 0
            and self.future_observation_count == 0
            and self.freshness_status == "fresh"
            and self.publication_state == "published"
            and self.publication_must_not_use_for_decision is False
        )

    def to_dict(self) -> dict[str, object]:
        """Return deterministic JSON-safe analysis fields."""

        return {
            "candidate_asset_count": self.candidate_asset_count,
            "candidate_member_count": self.candidate_member_count,
            "dataset_key": self.dataset_key,
            "exact_match_count": self.exact_match_count,
            "fact_reference_mismatch_count": self.fact_reference_mismatch_count,
            "fact_row_count": self.fact_row_count,
            "fact_table": self.fact_table,
            "freshness_status": self.freshness_status,
            "future_observation_count": self.future_observation_count,
            "historical_gate": "ALLOW" if self.historical_gate_allow else "DENY",
            "missing_asset_count": self.missing_asset_count,
            "max_age_seconds": self.max_age_seconds,
            "age_seconds": self.age_seconds,
            "newest_observed_at": _utc_text(self.newest_observed_at),
            "oldest_observed_at": _utc_text(self.oldest_observed_at),
            "publication_asset_count": self.publication_asset_count,
            "publication_blocked_reason": self.publication_blocked_reason,
            "publication_hash": self.publication_hash,
            "publication_id": self.publication_id,
            "publication_member_count": self.publication_member_count,
            "publication_must_not_use_for_decision": self.publication_must_not_use_for_decision,
            "publication_state": self.publication_state,
            "quality_mismatch_count": self.quality_mismatch_count,
            "requested_asset_count": self.requested_asset_count,
            "source_only_count": self.source_only_count,
            "source_snapshot_sha256": self.source_snapshot_sha256,
            "stale_observation_count": self.stale_observation_count,
            "target_only_count": self.target_only_count,
            "target_snapshot_sha256": self.target_snapshot_sha256,
            "timestamp_mismatch_count": self.timestamp_mismatch_count,
            "unexpected_asset_count": self.unexpected_asset_count,
        }


@dataclass(frozen=True, slots=True)
class Data02IsolatedSimulationReport:
    """Candidate-bound report that can never claim production acceptance."""

    request: Data02IsolatedSimulationRequest
    snapshot: Data02HistoricalDatabaseSnapshot
    datasets: tuple[Data02HistoricalDatasetAnalysis, ...]
    analysis_sha256: str

    def to_dict(self) -> dict[str, object]:
        """Return the stable public simulation evidence envelope."""

        historical_allow = all(dataset.historical_gate_allow for dataset in self.datasets)
        return {
            "analysis_sha256": self.analysis_sha256,
            "as_of": _utc_text(self.request.as_of),
            "candidate": self.request.candidate.to_dict(),
            "captured_at": _utc_text(self.snapshot.captured_at),
            "data_center_migration_count": len(self.snapshot.data_center_migrations),
            "data_center_migration_head": self.snapshot.data_center_migrations[-1],
            "datasets": [dataset.to_dict() for dataset in self.datasets],
            "dump": {
                "name": self.request.dump_name,
                "sha256": self.request.dump_sha256,
                "size": self.request.dump_size,
            },
            "evidence_scope": "data02_isolated_historical_simulation",
            "historical_data_gate": "ALLOW" if historical_allow else "DENY",
            "production_claim": False,
            "production_ready": False,
            "restored_database": self.snapshot.database_name,
            "runtime_enablement": "not_authorized",
            "schema_version": "data02-isolated-simulation.v1",
            "simulation_outcome": "completed",
            "transaction_read_only": self.snapshot.transaction_read_only,
            "universe": {
                "asset_count": len(self.snapshot.universe_codes),
                "asset_codes_sha256": _hash_json(list(self.snapshot.universe_codes)),
                "universe_id": self.snapshot.universe_id,
            },
        }


def _analyze_dataset(
    dataset: Data02HistoricalDatasetSnapshot,
    *,
    universe_codes: tuple[str, ...],
    as_of: datetime,
) -> Data02HistoricalDatasetAnalysis:
    """Classify one selected-fact/current-publication pair."""

    source = {reference.natural_key: reference for reference in dataset.facts}
    if len(source) != len(dataset.facts):
        raise ValueError(f"duplicate source natural key for {dataset.dataset_key}")
    publication = dataset.publication
    members = publication.members if publication is not None else ()
    target = {reference.natural_key: reference for reference in members}
    if len(target) != len(members):
        raise ValueError(f"duplicate publication natural key for {dataset.dataset_key}")
    universe = set(universe_codes)
    source_assets = {reference.asset_code for reference in source.values()}
    target_assets = {reference.asset_code for reference in target.values()}
    shared_keys = set(source) & set(target)
    exact = 0
    fact_reference_mismatch = 0
    timestamp_mismatch = 0
    quality_mismatch = 0
    for key in shared_keys:
        source_reference = source[key]
        target_reference = target[key]
        if source_reference.comparison_dict() == target_reference.comparison_dict():
            exact += 1
        if (
            source_reference.fact_table != target_reference.fact_table
            or source_reference.fact_pk != target_reference.fact_pk
            or source_reference.source != target_reference.source
        ):
            fact_reference_mismatch += 1
        if source_reference.observed_at != target_reference.observed_at:
            timestamp_mismatch += 1
        if source_reference.quality_status != target_reference.quality_status:
            quality_mismatch += 1
    observations = [reference.observed_at for reference in source.values()]
    max_age_seconds = dataset.freshness_seconds
    stale_observation_count = (
        sum((as_of - value).total_seconds() > max_age_seconds for value in observations)
        if max_age_seconds is not None
        else 0
    )
    if max_age_seconds is None:
        freshness_status = "unverified"
    elif not observations:
        freshness_status = "missing"
    elif stale_observation_count:
        freshness_status = "stale"
    else:
        freshness_status = "fresh"
    oldest_observed_at = min(observations) if observations else None
    source_payload = [source[key].comparison_dict() for key in sorted(source)]
    target_payload = [target[key].comparison_dict() for key in sorted(target)]
    return Data02HistoricalDatasetAnalysis(
        dataset_key=dataset.dataset_key,
        fact_table=dataset.fact_table,
        fact_row_count=dataset.fact_row_count,
        requested_asset_count=len(universe),
        candidate_asset_count=len(source_assets & universe),
        candidate_member_count=len(source),
        publication_id=publication.publication_id if publication is not None else None,
        publication_hash=publication.publication_hash if publication is not None else None,
        publication_state=publication.state if publication is not None else None,
        publication_must_not_use_for_decision=(
            publication.must_not_use_for_decision if publication is not None else None
        ),
        publication_blocked_reason=(
            publication.blocked_reason if publication is not None else None
        ),
        publication_asset_count=len(target_assets & universe),
        publication_member_count=len(target),
        missing_asset_count=len(universe - source_assets),
        unexpected_asset_count=len(source_assets - universe),
        source_only_count=len(set(source) - set(target)),
        target_only_count=len(set(target) - set(source)),
        exact_match_count=exact,
        fact_reference_mismatch_count=fact_reference_mismatch,
        timestamp_mismatch_count=timestamp_mismatch,
        quality_mismatch_count=quality_mismatch,
        future_observation_count=sum(value > as_of for value in observations),
        stale_observation_count=stale_observation_count,
        freshness_status=freshness_status,
        max_age_seconds=max_age_seconds,
        age_seconds=(
            max((as_of - oldest_observed_at).total_seconds(), 0.0)
            if oldest_observed_at is not None
            else None
        ),
        oldest_observed_at=oldest_observed_at,
        newest_observed_at=max(observations) if observations else None,
        source_snapshot_sha256=_hash_json(source_payload),
        target_snapshot_sha256=_hash_json(target_payload) if publication is not None else None,
    )


class RunData02IsolatedSimulationUseCase:
    """Derive deterministic non-production evidence from one isolated snapshot."""

    def __init__(self, *, snapshot_port: Data02HistoricalSnapshotPort) -> None:
        self._snapshot_port = snapshot_port

    def execute(self, request: Data02IsolatedSimulationRequest) -> Data02IsolatedSimulationReport:
        """Collect and classify one historical snapshot without changing state."""

        snapshot = self._snapshot_port.collect()
        if snapshot.database_name != request.restored_database:
            raise ValueError("restored database identity changed during simulation")
        if not snapshot.transaction_read_only:
            raise ValueError("historical snapshot transaction was not read-only")
        datasets = tuple(
            _analyze_dataset(
                dataset,
                universe_codes=snapshot.universe_codes,
                as_of=request.as_of,
            )
            for dataset in sorted(snapshot.datasets, key=lambda item: item.dataset_key)
        )
        deterministic_payload = {
            "as_of": _utc_text(request.as_of),
            "candidate": request.candidate.to_dict(),
            "datasets": [dataset.to_dict() for dataset in datasets],
            "dump": {
                "name": request.dump_name,
                "sha256": request.dump_sha256,
                "size": request.dump_size,
            },
            "migration_head": snapshot.data_center_migrations[-1],
            "universe_codes": list(snapshot.universe_codes),
            "universe_id": snapshot.universe_id,
        }
        return Data02IsolatedSimulationReport(
            request=request,
            snapshot=snapshot,
            datasets=datasets,
            analysis_sha256=_hash_json(deterministic_payload),
        )


def serialize_data02_isolated_simulation_report(
    report: Data02IsolatedSimulationReport,
) -> bytes:
    """Serialize canonical UTF-8 JSON evidence bytes."""

    return json.dumps(
        report.to_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


__all__ = [
    "Data02HistoricalDatabaseSnapshot",
    "Data02HistoricalDatasetSnapshot",
    "Data02HistoricalFactReference",
    "Data02HistoricalPublicationSnapshot",
    "Data02HistoricalSnapshotPort",
    "Data02IsolatedSimulationCandidate",
    "Data02IsolatedSimulationReport",
    "Data02IsolatedSimulationRequest",
    "RunData02IsolatedSimulationUseCase",
    "serialize_data02_isolated_simulation_report",
]
