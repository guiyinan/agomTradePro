"""Candidate financial publication state for an isolated consumer test.

This module provides isolated local test fixtures. It is not a production
publisher and not a DATA-02 authority path. The callable writes synthetic,
source-evidence-bearing ``FinancialFactModel`` rows and a fully bound current
publication directly through Django models. By default it keeps the original
single-revenue fixture; consumers that require a complete statement can pass
explicit metrics. It never invokes the generic or formal financial publisher.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Final
from uuid import UUID, uuid4

from django.db import transaction

from apps.data_center.application.publication_utils import (
    member_reference,
    publication_hash,
    publication_member_from_reference,
    publication_member_manifest_hash,
)
from apps.data_center.domain.contracts import DatasetContract, PublicationPolicy
from apps.data_center.domain.control_plane import PublicationMember, PublicationState
from apps.data_center.infrastructure.catalog_models import (
    DatasetContractModel,
    DatasetPublicationPolicyModel,
)
from apps.data_center.infrastructure.models import FinancialFactModel
from apps.data_center.infrastructure.publication_fact_evidence import (
    publication_fact_reference_for_dataset,
)
from apps.data_center.infrastructure.publication_models import (
    CanonicalPublicationModel,
    CanonicalPublicationPointerModel,
    CoverageSnapshotModel,
    PublicationMemberModel,
)

DATASET_KEY: Final[str] = "equity.financial.fact"
CONTRACT_VERSION: Final[str] = "1.0"
SCHEMA_VERSION: Final[str] = "1.0"
POLICY_VERSION: Final[str] = "3"
DEFAULT_ASSET_CODE: Final[str] = "600000.SH"
SOURCE_NAME: Final[str] = "synthetic-consumer-fixture"
RAW_PAYLOAD_SCOPE: Final[str] = "record_response_body"
FINANCIAL_PERIOD_TYPES: Final[frozenset[str]] = frozenset(
    {"annual", "semi_annual", "quarterly", "ttm"}
)

# This is the current governance entry for equity.financial.fact.  It remains
# versioned and retains the original-source keys; no legacy policy is created.
FINANCIAL_POLICY_EVIDENCE: Final[tuple[str, ...]] = (
    "source",
    "observed_at",
    "available_at",
    "fetched_at",
    "payload_hash",
    "fact_content_hash",
    "source_record_id",
    "published_at",
    "raw_payload_hash",
    "raw_payload_scope",
)

FINANCIAL_CONTRACT_FIELDS: Final[tuple[dict[str, object], ...]] = (
    {
        "name": "period_end",
        "type": "date",
        "unit": None,
        "nullable": False,
        "zero_allowed": False,
    },
    {
        "name": "metric_code",
        "type": "string",
        "unit": None,
        "nullable": False,
        "zero_allowed": False,
    },
    {
        "name": "value",
        "type": "decimal",
        "unit": "catalog",
        "nullable": False,
        "zero_allowed": True,
    },
)


class FinancialConsumerFixtureError(ValueError):
    """Raised when the candidate cannot produce a self-consistent state."""


@dataclass(frozen=True, slots=True)
class SyntheticFinancialSource:
    """The exact synthetic response body retained for this candidate row."""

    path: Path
    body_sha256: str
    body_size_bytes: int
    source_record_id: str


@dataclass(frozen=True, slots=True)
class FinancialMetricSeed:
    """One explicitly synthetic financial statement value for a consumer fixture."""

    metric_code: str
    value: Decimal
    unit: str


@dataclass(frozen=True, slots=True)
class RefreshedFinancialFact:
    """Normalized values read back after Django assigned ``fetched_at``."""

    row: FinancialFactModel
    value: Decimal
    announced_at: datetime
    available_at: datetime
    fetched_at: datetime


@dataclass(frozen=True, slots=True)
class FinancialMetricState:
    """One retained source/fact/member tuple within a selected publication."""

    seed: FinancialMetricSeed
    source: SyntheticFinancialSource
    fact: FinancialFactModel
    refreshed_fact: RefreshedFinancialFact
    member_model: PublicationMemberModel
    member: PublicationMember


@dataclass(frozen=True, slots=True)
class FinancialConsumerState:
    """All persisted objects needed by the current financial read gate."""

    contract_model: DatasetContractModel
    policy_model: DatasetPublicationPolicyModel
    contract: DatasetContract
    policy: PublicationPolicy
    source: SyntheticFinancialSource
    fact: FinancialFactModel
    refreshed_fact: RefreshedFinancialFact
    member_model: PublicationMemberModel
    member: PublicationMember
    coverage_model: CoverageSnapshotModel
    publication: CanonicalPublicationModel
    pointer: CanonicalPublicationPointerModel
    metric_states: tuple[FinancialMetricState, ...] = ()


@dataclass(frozen=True, slots=True)
class ConsumerNegativeAssertion:
    """A future mutation that must make the consumer gate fail closed."""

    name: str
    mutation: str
    candidate_blocked_reason: str | None = None


FINANCIAL_CONSUMER_NEGATIVE_ASSERTIONS: Final[tuple[ConsumerNegativeAssertion, ...]] = (
    ConsumerNegativeAssertion(
        name="fact-content-tamper",
        mutation="Change FinancialFactModel.value without changing the frozen member.",
        candidate_blocked_reason="publication_member_fact_changed",
    ),
    ConsumerNegativeAssertion(
        name="source-clock-tamper",
        mutation="Change FinancialFactModel.available_at or fetched_at after sealing.",
        candidate_blocked_reason="publication_member_evidence_missing",
    ),
    ConsumerNegativeAssertion(
        name="member-tamper",
        mutation="Change PublicationMemberModel.fact_content_hash or identity fields.",
        candidate_blocked_reason=None,
    ),
    ConsumerNegativeAssertion(
        name="pointer-tamper",
        mutation="Point the current pointer at a different publication id or hash.",
        candidate_blocked_reason="canonical_publication_missing",
    ),
)


def _aware_utc(value: datetime, field_name: str) -> datetime:
    """Require one aware timestamp and return its UTC-normalized value."""

    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise FinancialConsumerFixtureError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class _M5FixtureAdmission:
    """Carry the exact browser origin into each private fixture write."""

    base_url: str


def _require_tux08_sqlite_database(
    admission: _M5FixtureAdmission | None = None,
    *,
    allow_native_postgres_test: bool = False,
) -> Path | None:
    """Require an exact disposable database before writing synthetic facts."""

    if admission is None:
        from tests.support.tui_research.disposable import require_test_database

        return require_test_database(allow_native_postgres_test=allow_native_postgres_test)
    if allow_native_postgres_test:
        raise AssertionError("Native PostgreSQL admission cannot bypass the M5 database guard")
    from tests.support.tui_research.m5_playwright_fixture_guard import (
        require_m5_valuation_fixture_database,
    )

    return require_m5_valuation_fixture_database(base_url=admission.base_url)


def _validate_inputs(
    *,
    tmp_path: Path,
    asset_code: str,
    period_type: str,
    period_end: date,
    report_date: date,
    announced_at: datetime,
    available_at: datetime,
) -> tuple[str, str, date, date, datetime, datetime]:
    """Validate caller-owned dates and clocks before writing any model row."""

    if not tmp_path.is_dir():
        raise FinancialConsumerFixtureError("tmp_path must be an existing directory")
    if not isinstance(asset_code, str):
        raise TypeError("asset_code must be text")
    if not isinstance(period_type, str):
        raise TypeError("period_type must be text")
    normalized_asset_code = asset_code.strip().upper()
    if not normalized_asset_code:
        raise FinancialConsumerFixtureError("asset_code must be non-empty")
    if period_type not in FINANCIAL_PERIOD_TYPES:
        raise FinancialConsumerFixtureError("period_type is not a FinancialFactModel choice")
    if isinstance(period_end, datetime) or not isinstance(period_end, date):
        raise TypeError("period_end must be a date")
    if isinstance(report_date, datetime) or not isinstance(report_date, date):
        raise TypeError("report_date must be a date")
    normalized_announced = _aware_utc(announced_at, "announced_at")
    normalized_available = _aware_utc(available_at, "available_at")
    if normalized_announced > normalized_available:
        raise FinancialConsumerFixtureError("announced_at must not exceed available_at")
    if normalized_available > datetime.now(UTC):
        raise FinancialConsumerFixtureError("available_at must not be in the future")
    return (
        normalized_asset_code,
        period_type,
        period_end,
        report_date,
        normalized_announced,
        normalized_available,
    )


def _validate_metric_seed(seed: FinancialMetricSeed) -> FinancialMetricSeed:
    """Require explicit finite synthetic values and units for each metric."""

    if not isinstance(seed, FinancialMetricSeed):
        raise TypeError("metrics must contain FinancialMetricSeed values")
    metric_code = seed.metric_code.strip()
    unit = seed.unit.strip()
    if not metric_code or not unit:
        raise FinancialConsumerFixtureError("metric code and unit must be non-empty")
    if not isinstance(seed.value, Decimal) or not seed.value.is_finite():
        raise FinancialConsumerFixtureError("metric values must be finite Decimal values")
    return FinancialMetricSeed(metric_code, seed.value, unit)


def _catalog_state(
    *,
    admission: _M5FixtureAdmission | None,
    allow_native_postgres_test: bool,
) -> tuple[
    DatasetContractModel,
    DatasetPublicationPolicyModel,
    DatasetContract,
    PublicationPolicy,
]:
    """Install the exact active contract and v3 policy in an isolated DB."""

    _require_tux08_sqlite_database(
        admission,
        allow_native_postgres_test=allow_native_postgres_test,
    )
    DatasetContractModel._default_manager.filter(dataset_key=DATASET_KEY).update(active=False)
    contract_model, _created = DatasetContractModel._default_manager.update_or_create(
        dataset_key=DATASET_KEY,
        contract_version=CONTRACT_VERSION,
        schema_version=SCHEMA_VERSION,
        defaults={
            "owner": "data-platform",
            "frequency": "quarterly",
            "decision_critical": True,
            "fields": [dict(field) for field in FINANCIAL_CONTRACT_FIELDS],
            "freshness_seconds": 7_776_000,
            "execution_freshness_seconds": None,
            "calendar_response_max_age_seconds": None,
            "comparable_group": "",
            "active": True,
        },
    )

    DatasetPublicationPolicyModel._default_manager.filter(dataset_key=DATASET_KEY).update(
        active=False
    )
    policy_model, _created = DatasetPublicationPolicyModel._default_manager.update_or_create(
        dataset_key=DATASET_KEY,
        contract_version=CONTRACT_VERSION,
        schema_version=SCHEMA_VERSION,
        policy_version=POLICY_VERSION,
        defaults={
            "member_codec_version": None,
            "minimum_coverage_ratio": 1.0,
            "allow_partial": True,
            "conflict_action": "quarantine",
            "required_evidence": list(FINANCIAL_POLICY_EVIDENCE),
            "retention_days": 3650,
            "active": True,
        },
    )
    contract = contract_model.to_domain()
    policy = policy_model.to_domain()
    if policy.policy_version != POLICY_VERSION or not policy.uses_versioned_evidence:
        raise FinancialConsumerFixtureError("financial consumer policy did not remain versioned")
    return contract_model, policy_model, contract, policy


def _write_source_body(
    tmp_path: Path,
    *,
    asset_code: str,
    period_type: str,
    period_end: date,
    report_date: date,
    announced_at: datetime,
    available_at: datetime,
    source_record_id: str,
    source_name: str,
    metric: FinancialMetricSeed,
) -> SyntheticFinancialSource:
    """Persist deterministic synthetic JSON bytes and hash those exact bytes."""

    body_payload: dict[str, object] = {
        "fixture": "tux08-financial-consumer-synthetic",
        "dataset_key": DATASET_KEY,
        "asset_code": asset_code,
        "period_end": period_end.isoformat(),
        "period_type": period_type,
        "metric_code": metric.metric_code,
        "value": str(metric.value),
        "unit": metric.unit,
        "report_date": report_date.isoformat(),
        "announced_at": announced_at.astimezone(UTC).isoformat(),
        "available_at": available_at.astimezone(UTC).isoformat(),
        "source_record_id": source_record_id,
    }
    if source_name != SOURCE_NAME:
        body_payload["source"] = source_name
    body = json.dumps(
        body_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    metric_suffix = "" if metric.metric_code == "revenue" else f"-{metric.metric_code}"
    source_suffix = (
        ""
        if source_name == SOURCE_NAME
        else f"-{hashlib.sha256(source_name.encode('utf-8')).hexdigest()[:12]}"
    )
    path = (
        tmp_path
        / f"financial-consumer-{asset_code.replace('.', '_')}{metric_suffix}{source_suffix}.json"
    )
    path.write_bytes(body)
    return SyntheticFinancialSource(
        path=path,
        body_sha256=hashlib.sha256(body).hexdigest(),
        body_size_bytes=len(body),
        source_record_id=source_record_id,
    )


def _create_financial_fact(
    *,
    asset_code: str,
    period_type: str,
    period_end: date,
    report_date: date,
    announced_at: datetime,
    available_at: datetime,
    source: SyntheticFinancialSource,
    source_name: str,
    metric: FinancialMetricSeed,
    admission: _M5FixtureAdmission | None,
    allow_native_postgres_test: bool,
) -> FinancialFactModel:
    """Create one source-bearing fact and read it back before hashing."""

    _require_tux08_sqlite_database(
        admission,
        allow_native_postgres_test=allow_native_postgres_test,
    )
    row = FinancialFactModel._default_manager.create(
        asset_code=asset_code,
        period_end=period_end,
        period_type=period_type,
        metric_code=metric.metric_code,
        value=metric.value,
        unit=metric.unit,
        source=source_name,
        report_date=report_date,
        announced_at=announced_at,
        available_at=available_at,
        extra={
            "fixture_source": "synthetic",
            "raw_payload_scope": RAW_PAYLOAD_SCOPE,
        },
        source_record_id=source.source_record_id,
        raw_payload_hash=source.body_sha256,
        quality_status="accepted",
        revision_number=1,
        decision_evidence={},
    )
    row.refresh_from_db()
    return row


def _normalize_refreshed_fact(row: FinancialFactModel) -> RefreshedFinancialFact:
    """Narrow Decimal and timestamp values after the database round-trip."""

    value = row.value
    if not isinstance(value, Decimal):
        raise FinancialConsumerFixtureError("FinancialFactModel.value was not read as Decimal")
    value = Decimal(str(value))
    announced_at = _aware_utc(row.announced_at, "FinancialFactModel.announced_at")
    available_at = _aware_utc(row.available_at, "FinancialFactModel.available_at")
    fetched_at = _aware_utc(row.fetched_at, "FinancialFactModel.fetched_at")
    if not announced_at <= available_at <= fetched_at:
        raise FinancialConsumerFixtureError(
            "financial source clocks must satisfy announced_at <= available_at <= fetched_at"
        )
    return RefreshedFinancialFact(
        row=row,
        value=value,
        announced_at=announced_at,
        available_at=available_at,
        fetched_at=fetched_at,
    )


def _persist_publication_state(
    *,
    members: tuple[PublicationMember, ...],
    policy: PublicationPolicy,
    published_at: datetime,
    admission: _M5FixtureAdmission | None,
    allow_native_postgres_test: bool,
) -> tuple[
    tuple[PublicationMemberModel, ...],
    CoverageSnapshotModel,
    CanonicalPublicationModel,
    CanonicalPublicationPointerModel,
]:
    """Persist the exact publication/member/coverage/pointer consumer state."""

    _require_tux08_sqlite_database(
        admission,
        allow_native_postgres_test=allow_native_postgres_test,
    )
    if not members:
        raise FinancialConsumerFixtureError("financial consumer publication requires members")
    member_reference_values = tuple(member_reference(member) for member in members)
    publication_digest = publication_hash(
        member_reference_values,
        policy_identity=policy.identity,
    )
    manifest_digest = publication_member_manifest_hash(
        members,
        policy_identity=policy.identity,
    )
    publication_uuid = UUID(members[0].publication_id)
    member_count = len(members)
    publication_model = CanonicalPublicationModel._default_manager.create(
        publication_id=publication_uuid,
        dataset_key=DATASET_KEY,
        publication_key="current",
        policy_version=policy.identity,
        state=PublicationState.PUBLISHED.value,
        selected_source=members[0].source,
        publication_hash=publication_digest,
        member_manifest_hash=manifest_digest,
        member_count=member_count,
        conflict_count=0,
        coverage_requested_count=member_count,
        coverage_eligible_count=member_count,
        coverage_selected_count=member_count,
        coverage_missing_count=0,
        coverage_conflict_count=0,
        as_of=max(member.available_at for member in members),
        published_at=published_at,
        must_not_use_for_decision=False,
        blocked_reason="",
        created_by="tux08-financial-consumer-fixture",
        scope_blocks=[],
        members_sealed_at=published_at,
    )
    member_models = tuple(
        PublicationMemberModel._default_manager.create(
            member_id=UUID(member.member_id),
            publication_id=publication_uuid,
            dataset_key=member.dataset_key,
            natural_key=member.natural_key,
            source=member.source,
            source_record_id=member.source_record_id,
            fact_table=member.fact_table,
            fact_pk=member.fact_pk,
            observed_at=member.observed_at,
            raw_payload_hash=member.raw_payload_hash,
            quality_status=member.quality_status,
            revision_number=member.revision_number,
            available_at=member.available_at,
            fetched_at=member.fetched_at,
            source_published_at=member.source_published_at,
            raw_payload_scope=member.raw_payload_scope,
            fact_content_hash=member.fact_content_hash,
        )
        for member in members
    )
    coverage_model = CoverageSnapshotModel._default_manager.create(
        coverage_id=UUID(str(uuid4())),
        publication_id=publication_uuid,
        requested_count=member_count,
        eligible_count=member_count,
        selected_count=member_count,
        missing_count=0,
        conflict_count=0,
        generated_at=published_at,
    )
    pointer_model, _created = CanonicalPublicationPointerModel._default_manager.update_or_create(
        dataset_key=DATASET_KEY,
        publication_key="current",
        defaults={
            "publication_id": publication_uuid,
            "publication_hash": publication_digest,
            "activation_id": f"tux08-financial-consumer:{publication_uuid}",
        },
    )
    return member_models, coverage_model, publication_model, pointer_model


def _prepare_financial_consumer_state(
    tmp_path: Path,
    *,
    asset_code: str = DEFAULT_ASSET_CODE,
    period_type: str,
    period_end: date,
    report_date: date,
    announced_at: datetime,
    available_at: datetime,
    metrics: tuple[FinancialMetricSeed, ...] | None = None,
    source_name: str = SOURCE_NAME,
    admission: _M5FixtureAdmission | None,
    allow_native_postgres_test: bool = False,
) -> FinancialConsumerState:
    """Prepare a synthetic, activated financial consumer snapshot.

    The caller must provide an existing source directory, explicit financial
    dates/times, and an already configured isolated SQLite database. The
    optional ``metrics`` tuple defaults to the legacy single revenue fact.
    The function writes only fixture state; it does not grant source authority,
    invoke a producer, or claim that provider-health/readiness checks pass.
    """

    if not isinstance(tmp_path, Path):
        raise TypeError("tmp_path must be pathlib.Path")
    _require_tux08_sqlite_database(
        admission,
        allow_native_postgres_test=allow_native_postgres_test,
    )
    normalized_source_name = source_name.strip()
    if not normalized_source_name or len(normalized_source_name) > 50:
        raise FinancialConsumerFixtureError("source_name must fit FinancialFactModel.source")
    (
        normalized_asset_code,
        normalized_period_type,
        normalized_period_end,
        normalized_report_date,
        normalized_announced_at,
        normalized_available_at,
    ) = _validate_inputs(
        tmp_path=tmp_path,
        asset_code=asset_code,
        period_type=period_type,
        period_end=period_end,
        report_date=report_date,
        announced_at=announced_at,
        available_at=available_at,
    )
    metric_seeds = (
        (FinancialMetricSeed("revenue", Decimal("123.4500"), "CNY"),)
        if metrics is None
        else metrics
    )
    if not metric_seeds:
        raise FinancialConsumerFixtureError(
            "financial consumer fixture requires at least one metric"
        )
    normalized_metrics = tuple(
        sorted(
            (_validate_metric_seed(seed) for seed in metric_seeds),
            key=lambda seed: seed.metric_code,
        )
    )
    if len({seed.metric_code for seed in normalized_metrics}) != len(normalized_metrics):
        raise FinancialConsumerFixtureError("financial consumer metric codes must be unique")
    if "revenue" not in {seed.metric_code for seed in normalized_metrics}:
        raise FinancialConsumerFixtureError("financial consumer fixture must include revenue")
    metric_states_inputs: list[tuple[FinancialMetricSeed, SyntheticFinancialSource]] = []
    for metric in normalized_metrics:
        source_record_id = f"{normalized_source_name}:{normalized_asset_code}:{normalized_period_end.isoformat()}:{metric.metric_code}"
        source = _write_source_body(
            tmp_path,
            asset_code=normalized_asset_code,
            period_type=normalized_period_type,
            period_end=normalized_period_end,
            report_date=normalized_report_date,
            announced_at=normalized_announced_at,
            available_at=normalized_available_at,
            source_record_id=source_record_id,
            source_name=normalized_source_name,
            metric=metric,
        )
        metric_states_inputs.append((metric, source))
    with transaction.atomic(using="default"):
        contract_model, policy_model, contract, policy = _catalog_state(
            admission=admission,
            allow_native_postgres_test=allow_native_postgres_test,
        )
        facts = tuple(
            _create_financial_fact(
                asset_code=normalized_asset_code,
                period_type=normalized_period_type,
                period_end=normalized_period_end,
                report_date=normalized_report_date,
                announced_at=normalized_announced_at,
                available_at=normalized_available_at,
                source=source,
                source_name=normalized_source_name,
                metric=metric,
                admission=admission,
                allow_native_postgres_test=allow_native_postgres_test,
            )
            for metric, source in metric_states_inputs
        )
        refreshed_facts = tuple(_normalize_refreshed_fact(fact) for fact in facts)
        references = tuple(
            publication_fact_reference_for_dataset(
                fact,
                dataset_key=DATASET_KEY,
                require_verified_source_evidence=True,
            )
            for fact in facts
        )
        publication_id = str(uuid4())
        members = tuple(
            publication_member_from_reference(
                reference,
                member_id=str(uuid4()),
                publication_id=publication_id,
                dataset_key=DATASET_KEY,
            )
            for reference in references
        )
        published_at = datetime.now(UTC)
        if any(published_at < refreshed.fetched_at for refreshed in refreshed_facts):
            raise FinancialConsumerFixtureError(
                "database fetched_at is later than the publication clock"
            )
        member_models, coverage_model, publication_model, pointer_model = (
            _persist_publication_state(
                members=members,
                policy=policy,
                published_at=published_at,
                admission=admission,
                allow_native_postgres_test=allow_native_postgres_test,
            )
        )
    metric_states = tuple(
        FinancialMetricState(
            seed=seed,
            source=source,
            fact=fact,
            refreshed_fact=refreshed,
            member_model=member_model,
            member=member,
        )
        for (seed, source), fact, refreshed, member_model, member in zip(
            metric_states_inputs,
            facts,
            refreshed_facts,
            member_models,
            members,
            strict=True,
        )
    )
    revenue_state = next(state for state in metric_states if state.seed.metric_code == "revenue")
    return FinancialConsumerState(
        contract_model=contract_model,
        policy_model=policy_model,
        contract=contract,
        policy=policy,
        source=revenue_state.source,
        fact=revenue_state.fact,
        refreshed_fact=revenue_state.refreshed_fact,
        member_model=revenue_state.member_model,
        member=revenue_state.member,
        coverage_model=coverage_model,
        publication=publication_model,
        pointer=pointer_model,
        metric_states=metric_states,
    )


def prepare_financial_consumer_state(
    tmp_path: Path,
    *,
    asset_code: str = DEFAULT_ASSET_CODE,
    period_type: str,
    period_end: date,
    report_date: date,
    announced_at: datetime,
    available_at: datetime,
    metrics: tuple[FinancialMetricSeed, ...] | None = None,
    allow_native_postgres_test: bool = False,
) -> FinancialConsumerState:
    """Prepare synthetic facts under exact SQLite or explicit PostgreSQL test admission."""

    return _prepare_financial_consumer_state(
        tmp_path,
        asset_code=asset_code,
        period_type=period_type,
        period_end=period_end,
        report_date=report_date,
        announced_at=announced_at,
        available_at=available_at,
        metrics=metrics,
        admission=None,
        allow_native_postgres_test=allow_native_postgres_test,
    )


def prepare_m5_financial_consumer_state(
    tmp_path: Path,
    *,
    base_url: str,
    asset_code: str,
    source_name: str,
    period_type: str,
    period_end: date,
    report_date: date,
    announced_at: datetime,
    available_at: datetime,
    metrics: tuple[FinancialMetricSeed, ...],
) -> FinancialConsumerState:
    """Prepare explicit synthetic facts after strict M5 browser database admission."""

    return _prepare_financial_consumer_state(
        tmp_path,
        asset_code=asset_code,
        period_type=period_type,
        period_end=period_end,
        report_date=report_date,
        announced_at=announced_at,
        available_at=available_at,
        metrics=metrics,
        source_name=source_name,
        admission=_M5FixtureAdmission(base_url=base_url),
    )


__all__ = [
    "DATASET_KEY",
    "DEFAULT_ASSET_CODE",
    "FINANCIAL_CONSUMER_NEGATIVE_ASSERTIONS",
    "FINANCIAL_POLICY_EVIDENCE",
    "FinancialConsumerFixtureError",
    "FinancialMetricSeed",
    "FinancialConsumerState",
    "RefreshedFinancialFact",
    "SyntheticFinancialSource",
    "prepare_m5_financial_consumer_state",
    "prepare_financial_consumer_state",
]
