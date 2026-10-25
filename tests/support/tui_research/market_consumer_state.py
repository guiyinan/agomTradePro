"""Typed market facts for the isolated TUX-08 consumer-readiness fixture.

This candidate is intentionally narrower than a provider or market refresh
workflow.  It writes source-bound typed facts into the caller's disposable
SQLite database, publishes one price row, one valuation row, and one *batched*
current quote publication containing 510300.SH, 000300.SH, and 600000.SH.
The actual publication use cases calculate member hashes and the exact current
publication result; this module only supplies typed fixture inputs.

It never calls a provider, network, production market-health path, formal
financial producer, or full-market workflow.  The source JSON artifact is
retained for valuation evidence only.  A passing consumer gate remains
synthetic test evidence and cannot establish producer authority.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Final
from uuid import UUID

MARKET_DATASET_KEYS: Final[tuple[str, ...]] = (
    "equity.price.bar",
    "equity.quote.snapshot",
    "equity.valuation.fact",
    "equity.financial.fact",
)
DECISION_ASSET_CODES: Final[tuple[str, str]] = ("510300.SH", "000300.SH")
SNAPSHOT_ASSET_CODE: Final[str] = "600000.SH"
PUBLICATION_KEY: Final[str] = "current"
SOURCE_NAME: Final[str] = "synthetic-consumer-market"
CONTRACT_VERSIONS: Final[dict[str, str]] = {
    "equity.price.bar": "1.0",
    "equity.quote.snapshot": "2.0",
    "equity.valuation.fact": "1.0",
    "equity.financial.fact": "1.0",
}
SCHEMA_VERSIONS: Final[dict[str, str]] = {
    "equity.price.bar": "1.0",
    "equity.quote.snapshot": "2.0",
    "equity.valuation.fact": "1.0",
    "equity.financial.fact": "1.0",
}
POLICY_VERSIONS: Final[dict[str, str]] = {
    "equity.price.bar": "2",
    "equity.quote.snapshot": "2",
    "equity.valuation.fact": "2",
    "equity.financial.fact": "3",
}
RAW_PAYLOAD_SCOPE: Final[str] = "record_response_body"
_RAW_PAYLOAD_SCOPES: Final[frozenset[str]] = frozenset(
    {"batch_response_body", "record_response_body"}
)


class MarketConsumerStateError(RuntimeError):
    """Identify a missing typed or isolated-fixture precondition."""


@dataclass(frozen=True, slots=True)
class MarketConsumerClocks:
    """Caller-owned source clocks; publication time is sampled after readback."""

    closed_session: date
    price_observed_at: datetime
    valuation_observed_at: datetime
    quote_snapshot_at: datetime
    available_at: datetime
    fetched_at: datetime


@dataclass(frozen=True, slots=True)
class PriceSeed:
    """One typed 600000.SH price row for the resolver's closed session."""

    asset_code: str
    bar_date: date
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None
    amount: float | None = None


@dataclass(frozen=True, slots=True)
class QuoteSeed:
    """One typed quote value; all three rows publish in one batch."""

    asset_code: str
    current_price: float
    open: float | None = None
    high: float | None = None
    low: float | None = None
    prev_close: float | None = None
    volume: float | None = None
    amount: float | None = None
    bid: float | None = None
    ask: float | None = None


@dataclass(frozen=True, slots=True)
class ValuationSeed:
    """One typed 600000.SH valuation row and its source payload values."""

    asset_code: str
    val_date: date
    pe_ttm: float | None = None
    pe_static: float | None = None
    pb: float | None = None
    ps_ttm: float | None = None
    market_cap: float | None = None
    float_market_cap: float | None = None
    dv_ratio: float | None = None


@dataclass(frozen=True, slots=True)
class SourceArtifact:
    """Exact synthetic response bytes retained for an evidence-bearing row."""

    dataset_key: str
    path: Path
    source_record_id: str
    raw_payload_hash: str
    raw_payload_scope: str
    body_size_bytes: int


@dataclass(frozen=True, slots=True)
class MarketCatalogState:
    """Active exact catalog rows used by the three market publishers."""

    contract_versions: tuple[tuple[str, str, str], ...]
    policy_versions: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class MarketConsumerState:
    """Published market state and exact publisher results for one run."""

    catalog: MarketCatalogState
    price_publication_id: str
    price_publication_hash: str
    quote_publication_id: str
    quote_publication_hash: str
    valuation_publication_id: str
    valuation_publication_hash: str
    valuation_artifact: SourceArtifact
    publication_at: datetime


def _require_aware(value: datetime, *, field_name: str) -> datetime:
    """Require a caller clock and normalize only its timezone representation."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise MarketConsumerStateError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _require_uuid(value: str) -> str:
    """Require a canonical run UUID instead of inventing one in the fixture."""

    try:
        parsed = UUID(value)
    except (TypeError, ValueError) as error:
        raise MarketConsumerStateError("run_id must be a canonical UUID") from error
    normalized = str(parsed)
    if normalized != value.lower():
        raise MarketConsumerStateError("run_id must be a canonical UUID")
    return normalized


def _require_tux08_sqlite_database(
    *,
    base_url: str | None = None,
    allow_native_postgres_test: bool = False,
) -> Path | None:
    """Require an exact disposable database before writing synthetic facts."""

    if base_url is None:
        from tests.support.tui_research.disposable import require_test_database

        return require_test_database(allow_native_postgres_test=allow_native_postgres_test)
    if allow_native_postgres_test:
        raise AssertionError("Native PostgreSQL admission cannot bypass the M5 database guard")
    from tests.support.tui_research.m5_playwright_fixture_guard import (
        require_m5_valuation_fixture_database,
    )

    return require_m5_valuation_fixture_database(base_url=base_url)


def _require_tmp_path(tmp_path: Path) -> Path:
    """Constrain source artifacts to the repository's disposable tmp tree."""

    from django.conf import settings

    target = tmp_path.expanduser().resolve()
    repository_tmp = (Path(str(settings.BASE_DIR)).resolve() / ".tmp").resolve()
    try:
        target.relative_to(repository_tmp)
    except ValueError as error:
        raise MarketConsumerStateError(
            "source artifact path must be under settings.BASE_DIR/.tmp"
        ) from error
    target.mkdir(parents=True, exist_ok=True)
    return target


def _write_source_artifact(
    *,
    tmp_path: Path,
    dataset_key: str,
    source_record_id: str,
    payload: Mapping[str, object],
    raw_payload_scope: str,
) -> SourceArtifact:
    """Persist canonical synthetic bytes and their exact SHA-256 digest."""

    if raw_payload_scope not in _RAW_PAYLOAD_SCOPES:
        raise MarketConsumerStateError("unsupported raw payload scope")
    body = json.dumps(
        dict(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    safe_dataset = dataset_key.replace(".", "_")
    safe_record = source_record_id.replace(":", "_").replace("/", "_")
    path = _require_tmp_path(tmp_path) / f"{safe_dataset}-{safe_record}.json"
    path.write_bytes(body)
    return SourceArtifact(
        dataset_key=dataset_key,
        path=path,
        source_record_id=source_record_id,
        raw_payload_hash=hashlib.sha256(body).hexdigest(),
        raw_payload_scope=raw_payload_scope,
        body_size_bytes=len(body),
    )


def _activate_consumer_pointer(
    *,
    dataset_key: str,
    publication_key: str,
    publication_id: str,
    publication_hash: str,
) -> None:
    """Bind exactly the publication result returned by the owner publisher."""

    if publication_key != PUBLICATION_KEY:
        raise MarketConsumerStateError("market consumer pointer must use the current publication")
    if not dataset_key.strip() or not publication_id.strip() or not publication_hash.strip():
        raise MarketConsumerStateError("publication pointer values cannot be empty")
    from apps.data_center.infrastructure.publication_models import (
        CanonicalPublicationPointerModel,
    )

    CanonicalPublicationPointerModel._default_manager.update_or_create(
        dataset_key=dataset_key,
        publication_key=publication_key,
        defaults={
            "publication_id": publication_id,
            "publication_hash": publication_hash,
            "activation_id": f"market-consumer:{publication_id}",
        },
    )


def _normalize_clocks(
    clocks: MarketConsumerClocks,
    *,
    actual_now: datetime,
) -> MarketConsumerClocks:
    """Validate source chronology/future values without inventing publication time."""

    from apps.data_center.domain.market_time import cn_market_session_close_utc

    normalized = MarketConsumerClocks(
        closed_session=clocks.closed_session,
        price_observed_at=_require_aware(clocks.price_observed_at, field_name="price_observed_at"),
        valuation_observed_at=_require_aware(
            clocks.valuation_observed_at,
            field_name="valuation_observed_at",
        ),
        quote_snapshot_at=_require_aware(
            clocks.quote_snapshot_at,
            field_name="quote_snapshot_at",
        ),
        available_at=_require_aware(clocks.available_at, field_name="available_at"),
        fetched_at=_require_aware(clocks.fetched_at, field_name="fetched_at"),
    )
    expected_price_observation = cn_market_session_close_utc(normalized.closed_session)
    if normalized.price_observed_at != expected_price_observation:
        raise MarketConsumerStateError(
            "price_observed_at must equal cn_market_session_close_utc(closed_session)"
        )
    if normalized.valuation_observed_at > normalized.fetched_at:
        raise MarketConsumerStateError("valuation_observed_at cannot follow fetched_at")
    if normalized.price_observed_at > normalized.fetched_at:
        raise MarketConsumerStateError("price_observed_at cannot follow fetched_at")
    if normalized.available_at > normalized.fetched_at:
        raise MarketConsumerStateError("available_at cannot follow fetched_at")
    if normalized.quote_snapshot_at > normalized.fetched_at:
        raise MarketConsumerStateError("quote_snapshot_at cannot follow fetched_at")
    reference = _require_aware(actual_now, field_name="actual_now")
    if any(
        value > reference
        for value in (
            normalized.price_observed_at,
            normalized.valuation_observed_at,
            normalized.quote_snapshot_at,
            normalized.available_at,
            normalized.fetched_at,
        )
    ):
        raise MarketConsumerStateError("source clocks cannot be in the future")
    return normalized


def _matches_expected_market_contract_version(
    dataset_key: str,
    contract_version: str,
    schema_version: str,
) -> bool:
    """Return whether a market contract matches its exact fixture version."""

    expected_contract_version = CONTRACT_VERSIONS.get(dataset_key)
    expected_schema_version = SCHEMA_VERSIONS.get(dataset_key)
    return (
        expected_contract_version is not None
        and expected_schema_version is not None
        and contract_version == expected_contract_version
        and schema_version == expected_schema_version
    )


def _catalog_state_from_active_rows(
    *,
    contracts: Mapping[str, object],
    policies: Mapping[str, object],
) -> MarketCatalogState:
    """Narrow active catalog values after the owner synchronization path."""

    from apps.data_center.domain.contracts import DatasetContract, PublicationPolicy

    contract_versions: list[tuple[str, str, str]] = []
    policy_versions: list[tuple[str, str]] = []
    for dataset_key in MARKET_DATASET_KEYS:
        contract = contracts.get(dataset_key)
        policy = policies.get(dataset_key)
        if not isinstance(contract, DatasetContract):
            raise MarketConsumerStateError(f"active contract missing: {dataset_key}")
        if not isinstance(policy, PublicationPolicy):
            raise MarketConsumerStateError(f"active policy missing: {dataset_key}")
        if not _matches_expected_market_contract_version(
            dataset_key=dataset_key,
            contract_version=contract.key.contract_version,
            schema_version=contract.key.schema_version,
        ):
            raise MarketConsumerStateError(f"unexpected active contract version: {dataset_key}")
        expected_policy_version = POLICY_VERSIONS[dataset_key]
        if policy.policy_version != expected_policy_version or policy.policy_version == "legacy":
            raise MarketConsumerStateError(f"unexpected active policy version: {dataset_key}")
        contract_versions.append(
            (dataset_key, contract.key.contract_version, contract.key.schema_version)
        )
        policy_versions.append((dataset_key, policy.policy_version))
    return MarketCatalogState(tuple(contract_versions), tuple(policy_versions))


def ensure_market_catalog(*, governance_root: Path) -> MarketCatalogState:
    """Use the reviewed catalog owner parser/synchronizer when market rows are absent.

    The command's typed loaders consume the exact fixed governance projections;
    this helper never recreates contract or policy field shapes.  Synchronizing
    the selected market rows is safe only in the caller's isolated TUX-08 DB.
    """

    from apps.data_center.application.catalog_use_cases import (
        SynchronizeDataCenterCatalogUseCase,
    )
    from apps.data_center.domain.contracts import DatasetContract, PublicationPolicy
    from apps.data_center.infrastructure.catalog_runtime_repositories import (
        DataOwnerRegistryRepository,
        DatasetContractRepository,
        ProviderBindingRepository,
    )
    from apps.data_center.infrastructure.publication_policy_repository import (
        PublicationPolicyRepository,
    )
    from apps.data_center.management.commands.initialize_data_center_catalog import (
        _load_bindings,
        _load_contracts,
        _load_owners,
        _load_policies,
    )

    root = governance_root.expanduser().resolve()
    contract_rows = _load_contracts(root / "dataset_contracts.json")
    all_contracts = {contract.key.value: contract for contract in contract_rows}
    policy_rows = _load_policies(root / "publication_policies.json", all_contracts)
    binding_rows = _load_bindings(root / "provider_bindings.json", all_contracts)
    owner_rows = _load_owners(root / "data_ownership_contracts.json", all_contracts)
    expected_contracts = {
        contract.key.value: contract
        for contract in contract_rows
        if _matches_expected_market_contract_version(
            dataset_key=contract.key.value,
            contract_version=contract.key.contract_version,
            schema_version=contract.key.schema_version,
        )
    }
    expected_policies = {
        policy.dataset.value: policy
        for policy in policy_rows
        if (
            policy.dataset.value in MARKET_DATASET_KEYS
            and policy.policy_version == POLICY_VERSIONS[policy.dataset.value]
        )
    }
    expected_bindings = [
        binding for binding in binding_rows if binding.dataset.value in MARKET_DATASET_KEYS
    ]
    expected_owners = [owner for owner in owner_rows if owner.dataset_key in MARKET_DATASET_KEYS]
    if set(expected_contracts) != set(MARKET_DATASET_KEYS) or set(expected_policies) != set(
        MARKET_DATASET_KEYS
    ):
        raise MarketConsumerStateError(
            "fixed governance projections lack a required market catalog"
        )

    contract_repository = DatasetContractRepository()
    policy_repository = PublicationPolicyRepository()
    active_contracts = {
        dataset_key: contract_repository.get_active(dataset_key)
        for dataset_key in MARKET_DATASET_KEYS
    }
    active_policies = {
        dataset_key: policy_repository.get_active(dataset_key)
        for dataset_key in MARKET_DATASET_KEYS
    }
    if any(active_contracts[key] != expected_contracts[key] for key in MARKET_DATASET_KEYS) or any(
        active_policies[key] != expected_policies[key] for key in MARKET_DATASET_KEYS
    ):
        SynchronizeDataCenterCatalogUseCase(
            contracts=contract_repository,
            bindings=ProviderBindingRepository(),
            policies=policy_repository,
            owners=DataOwnerRegistryRepository(),
        ).execute(
            contracts=tuple(expected_contracts.values()),
            bindings=tuple(expected_bindings),
            policies=tuple(expected_policies.values()),
            owners=tuple(expected_owners),
        )
        active_contracts = {
            dataset_key: contract_repository.get_active(dataset_key)
            for dataset_key in MARKET_DATASET_KEYS
        }
        active_policies = {
            dataset_key: policy_repository.get_active(dataset_key)
            for dataset_key in MARKET_DATASET_KEYS
        }
    typed_contracts = {
        key: value for key, value in active_contracts.items() if isinstance(value, DatasetContract)
    }
    typed_policies = {
        key: value for key, value in active_policies.items() if isinstance(value, PublicationPolicy)
    }
    return _catalog_state_from_active_rows(contracts=typed_contracts, policies=typed_policies)


def _prepare_market_consumer_state(
    *,
    tmp_path: Path,
    governance_root: Path,
    clocks: MarketConsumerClocks,
    price: PriceSeed,
    quotes: tuple[QuoteSeed, ...],
    valuation: ValuationSeed,
    run_id: str,
    publication_clock: Callable[[], datetime],
    base_url: str | None,
    snapshot_asset_code: str,
    source_name: str,
    allow_native_postgres_test: bool = False,
) -> MarketConsumerState:
    """Persist and publish the minimum typed market consumer state.

    ``quotes`` must contain exactly one row for each unchanged readiness asset
    and the explicitly selected snapshot asset. They are sent to one publisher
    call, so the current quote publication retains all three members instead of
    overwriting the pointer with three one-member publications.
    """

    _require_tux08_sqlite_database(
        base_url=base_url,
        allow_native_postgres_test=allow_native_postgres_test,
    )
    normalized_snapshot_asset_code = snapshot_asset_code.strip().upper()
    normalized_source_name = source_name.strip()
    if not normalized_snapshot_asset_code:
        raise MarketConsumerStateError("snapshot_asset_code must be non-empty")
    if not normalized_source_name or len(normalized_source_name) > 50:
        raise MarketConsumerStateError("source_name must fit market fact source fields")
    artifact_root = _require_tmp_path(tmp_path)
    normalized_clocks = _normalize_clocks(
        clocks,
        actual_now=_require_aware(datetime.now(UTC), field_name="actual_now"),
    )
    normalized_run_id = _require_uuid(run_id)
    if (
        price.asset_code != normalized_snapshot_asset_code
        or price.bar_date != normalized_clocks.closed_session
    ):
        raise MarketConsumerStateError(
            f"price seed must be {normalized_snapshot_asset_code} on the explicit closed session"
        )
    if valuation.asset_code != normalized_snapshot_asset_code:
        raise MarketConsumerStateError(f"valuation seed must be {normalized_snapshot_asset_code}")
    if valuation.val_date != normalized_clocks.closed_session:
        raise MarketConsumerStateError("valuation val_date must equal the closed session")
    quote_by_code = {quote.asset_code: quote for quote in quotes}
    expected_quote_codes = {*DECISION_ASSET_CODES, normalized_snapshot_asset_code}
    if set(quote_by_code) != expected_quote_codes or len(quote_by_code) != len(quotes):
        raise MarketConsumerStateError(
            f"quotes must contain exactly {', '.join((*DECISION_ASSET_CODES, normalized_snapshot_asset_code))} once each"
        )
    catalog = ensure_market_catalog(governance_root=governance_root)
    valuation_record_id = f"{normalized_source_name}:valuation:{valuation.asset_code}:{valuation.val_date.isoformat()}"
    valuation_artifact = _write_source_artifact(
        tmp_path=artifact_root,
        dataset_key="equity.valuation.fact",
        source_record_id=valuation_record_id,
        raw_payload_scope=RAW_PAYLOAD_SCOPE,
        payload={
            "asset_code": valuation.asset_code,
            "val_date": valuation.val_date.isoformat(),
            "pe_ttm": valuation.pe_ttm,
            "pe_static": valuation.pe_static,
            "pb": valuation.pb,
            "ps_ttm": valuation.ps_ttm,
            "market_cap": valuation.market_cap,
            "float_market_cap": valuation.float_market_cap,
            "dv_ratio": valuation.dv_ratio,
            "source": normalized_source_name,
            "observed_at": normalized_clocks.valuation_observed_at.isoformat(),
            "available_at": normalized_clocks.available_at.isoformat(),
            "fetched_at": normalized_clocks.fetched_at.isoformat(),
            "source_record_id": valuation_record_id,
            "raw_payload_scope": RAW_PAYLOAD_SCOPE,
        },
    )

    from django.db import transaction

    from apps.data_center.application.publication_sync_market import (
        PublishPriceBarBatchUseCase,
        PublishQuoteSnapshotBatchUseCase,
    )
    from apps.data_center.application.valuation_publication import (
        PublishValuationBatchUseCase,
    )
    from apps.data_center.domain.entities import PriceBar, QuoteSnapshot, ValuationFact
    from apps.data_center.domain.enums import PriceAdjustment
    from apps.data_center.domain.market_time import cn_market_date_from_observation
    from apps.data_center.infrastructure.control_plane_repositories import (
        CanonicalPublicationRepository,
    )
    from apps.data_center.infrastructure.price_bar_repository import PriceBarRepository
    from apps.data_center.infrastructure.publication_policy_repository import (
        PublicationPolicyRepository,
    )
    from apps.data_center.infrastructure.quote_snapshot_repository import QuoteSnapshotRepository
    from apps.data_center.infrastructure.valuation_fact_repository import ValuationFactRepository

    price_fact = PriceBar(
        asset_code=price.asset_code,
        bar_date=price.bar_date,
        open=price.open,
        high=price.high,
        low=price.low,
        close=price.close,
        freq="1d",
        adjustment=PriceAdjustment.NONE,
        volume=price.volume,
        amount=price.amount,
        source=normalized_source_name,
        fetched_at=normalized_clocks.fetched_at,
        ingested_run_id=normalized_run_id,
    )
    quote_facts = tuple(
        QuoteSnapshot(
            asset_code=quote.asset_code,
            snapshot_at=normalized_clocks.quote_snapshot_at,
            current_price=quote.current_price,
            source=normalized_source_name,
            fetched_at=normalized_clocks.fetched_at,
            open=quote.open,
            high=quote.high,
            low=quote.low,
            prev_close=quote.prev_close,
            volume=quote.volume,
            amount=quote.amount,
            bid=quote.bid,
            ask=quote.ask,
            change_pct=None,
            contract_version=CONTRACT_VERSIONS["equity.quote.snapshot"],
            schema_version=SCHEMA_VERSIONS["equity.quote.snapshot"],
            extra={
                "fixture_source": "synthetic-consumer",
                "raw_payload_scope": "batch_response_body",
            },
            ingested_run_id=normalized_run_id,
        )
        for quote in quotes
    )
    valuation_fact = ValuationFact(
        asset_code=valuation.asset_code,
        val_date=valuation.val_date,
        pe_ttm=valuation.pe_ttm,
        pe_static=valuation.pe_static,
        pb=valuation.pb,
        ps_ttm=valuation.ps_ttm,
        market_cap=valuation.market_cap,
        float_market_cap=valuation.float_market_cap,
        dv_ratio=valuation.dv_ratio,
        source=normalized_source_name,
        available_at=normalized_clocks.available_at,
        fetched_at=normalized_clocks.fetched_at,
        extra={
            "fixture_source": "synthetic-consumer",
            "raw_payload_scope": valuation_artifact.raw_payload_scope,
        },
        observed_at=normalized_clocks.valuation_observed_at,
        source_record_id=valuation_artifact.source_record_id,
        raw_payload_hash=valuation_artifact.raw_payload_hash,
        ingested_run_id=normalized_run_id,
    )

    with transaction.atomic():
        price_repository = PriceBarRepository()
        quote_repository = QuoteSnapshotRepository()
        valuation_repository = ValuationFactRepository()
        if price_repository.bulk_upsert([price_fact]) != 1:
            raise MarketConsumerStateError("price repository did not store one typed row")
        if quote_repository.bulk_upsert(list(quote_facts)) != len(quote_facts):
            raise MarketConsumerStateError("quote repository did not store the complete batch")
        if valuation_repository.bulk_upsert([valuation_fact]) != 1:
            raise MarketConsumerStateError("valuation repository did not store one typed row")
        stored_price_rows = price_repository.get_bars(
            normalized_snapshot_asset_code,
            start=normalized_clocks.closed_session,
            end=normalized_clocks.closed_session,
            limit=1,
        )
        if len(stored_price_rows) != 1:
            raise MarketConsumerStateError(
                "stored price row cannot be resolved by typed repository"
            )
        stored_price = stored_price_rows[0]
        stored_quote_rows = tuple(
            quote_repository.get_series(
                quote.asset_code,
                snapshot_date=cn_market_date_from_observation(normalized_clocks.quote_snapshot_at),
                limit=1,
            )
            for quote in quote_facts
        )
        if any(len(rows) != 1 for rows in stored_quote_rows):
            raise MarketConsumerStateError(
                "stored quote batch cannot be resolved by typed repository"
            )
        stored_quotes = tuple(rows[0] for rows in stored_quote_rows)
        stored_valuation_rows = valuation_repository.get_series(
            normalized_snapshot_asset_code,
            start=valuation.val_date,
            end=valuation.val_date,
        )
        if len(stored_valuation_rows) != 1:
            raise MarketConsumerStateError(
                "stored valuation row cannot be resolved by typed repository"
            )
        stored_valuation = stored_valuation_rows[0]
        stored_fetched_times = [
            stored_price.fetched_at,
            *(quote.fetched_at for quote in stored_quotes if quote.fetched_at is not None),
            stored_valuation.fetched_at,
        ]
        publication_at = _require_aware(
            publication_clock(),
            field_name="publication_clock()",
        )
        current_now = _require_aware(datetime.now(UTC), field_name="actual_now")
        if publication_at > current_now:
            raise MarketConsumerStateError("publication_clock() cannot be in the future")
        if any(value > publication_at for value in stored_fetched_times):
            raise MarketConsumerStateError(
                "database-assigned/source fetched_at is after publication_clock(); do not rewrite it"
            )
        publication_repository = CanonicalPublicationRepository()
        policy_repository = PublicationPolicyRepository()
        price_publication = PublishPriceBarBatchUseCase(
            fact_repository=price_repository,
            publication_repository=publication_repository,
            policy_repository=policy_repository,
        ).execute(
            [stored_price],
            provider_name=normalized_source_name,
            publication_key=PUBLICATION_KEY,
            run_id=normalized_run_id,
            published_at=publication_at,
        )
        quote_publication = PublishQuoteSnapshotBatchUseCase(
            fact_repository=quote_repository,
            publication_repository=publication_repository,
            policy_repository=policy_repository,
        ).execute(
            stored_quotes,
            provider_name=normalized_source_name,
            publication_key=PUBLICATION_KEY,
            run_id=normalized_run_id,
            published_at=publication_at,
        )
        valuation_publication = PublishValuationBatchUseCase(
            fact_repository=valuation_repository,
            publication_repository=publication_repository,
            policy_repository=policy_repository,
        ).execute(
            [stored_valuation],
            provider_name=normalized_source_name,
            publication_key=PUBLICATION_KEY,
            run_id=normalized_run_id,
            published_at=publication_at,
        )
        if price_publication is None:
            raise MarketConsumerStateError("price publisher returned no publication")
        if quote_publication is None:
            raise MarketConsumerStateError("batched quote publisher returned no publication")
        if valuation_publication is None:
            raise MarketConsumerStateError("valuation publisher returned no publication")
        _activate_consumer_pointer(
            dataset_key="equity.price.bar",
            publication_key=PUBLICATION_KEY,
            publication_id=price_publication.publication_id,
            publication_hash=price_publication.publication_hash,
        )
        _activate_consumer_pointer(
            dataset_key="equity.quote.snapshot",
            publication_key=PUBLICATION_KEY,
            publication_id=quote_publication.publication_id,
            publication_hash=quote_publication.publication_hash,
        )
        _activate_consumer_pointer(
            dataset_key="equity.valuation.fact",
            publication_key=PUBLICATION_KEY,
            publication_id=valuation_publication.publication_id,
            publication_hash=valuation_publication.publication_hash,
        )

    return MarketConsumerState(
        catalog=catalog,
        price_publication_id=price_publication.publication_id,
        price_publication_hash=price_publication.publication_hash,
        quote_publication_id=quote_publication.publication_id,
        quote_publication_hash=quote_publication.publication_hash,
        valuation_publication_id=valuation_publication.publication_id,
        valuation_publication_hash=valuation_publication.publication_hash,
        valuation_artifact=valuation_artifact,
        publication_at=publication_at,
    )


def prepare_market_consumer_state(
    *,
    tmp_path: Path,
    governance_root: Path,
    clocks: MarketConsumerClocks,
    price: PriceSeed,
    quotes: tuple[QuoteSeed, ...],
    valuation: ValuationSeed,
    run_id: str,
    publication_clock: Callable[[], datetime],
    allow_native_postgres_test: bool = False,
) -> MarketConsumerState:
    """Prepare the legacy consumer fixture under explicit test DB admission."""

    return _prepare_market_consumer_state(
        tmp_path=tmp_path,
        governance_root=governance_root,
        clocks=clocks,
        price=price,
        quotes=quotes,
        valuation=valuation,
        run_id=run_id,
        publication_clock=publication_clock,
        base_url=None,
        snapshot_asset_code=SNAPSHOT_ASSET_CODE,
        source_name=SOURCE_NAME,
        allow_native_postgres_test=allow_native_postgres_test,
    )


def prepare_m5_market_consumer_state(
    *,
    tmp_path: Path,
    governance_root: Path,
    clocks: MarketConsumerClocks,
    price: PriceSeed,
    quotes: tuple[QuoteSeed, ...],
    valuation: ValuationSeed,
    run_id: str,
    publication_clock: Callable[[], datetime],
    base_url: str,
    snapshot_asset_code: str,
    source_name: str,
) -> MarketConsumerState:
    """Prepare explicit M5 market facts under strict browser DB admission."""

    return _prepare_market_consumer_state(
        tmp_path=tmp_path,
        governance_root=governance_root,
        clocks=clocks,
        price=price,
        quotes=quotes,
        valuation=valuation,
        run_id=run_id,
        publication_clock=publication_clock,
        base_url=base_url,
        snapshot_asset_code=snapshot_asset_code,
        source_name=source_name,
    )


__all__ = [
    "CONTRACT_VERSIONS",
    "DECISION_ASSET_CODES",
    "MARKET_DATASET_KEYS",
    "MarketCatalogState",
    "MarketConsumerClocks",
    "MarketConsumerState",
    "MarketConsumerStateError",
    "POLICY_VERSIONS",
    "PriceSeed",
    "QuoteSeed",
    "SCHEMA_VERSIONS",
    "SNAPSHOT_ASSET_CODE",
    "SourceArtifact",
    "ValuationSeed",
    "ensure_market_catalog",
    "prepare_m5_market_consumer_state",
    "prepare_market_consumer_state",
]
