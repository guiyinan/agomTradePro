"""Optional market publications for an isolated TUX-08 consumer fixture.

This ignored candidate prepares one synthetic asset-bound news fact and one
zero-valued capital-flow fact.  It uses the existing typed repositories and
official publication use cases.  It never calls a provider, creates or
rewrites a policy, changes the four core market pointers, or claims source
authority.
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

OPTIONAL_DATASET_KEYS: Final[tuple[str, str]] = (
    "market.news",
    "market.capital_flow",
)
CONTRACT_VERSION: Final[str] = "1.0"
SCHEMA_VERSION: Final[str] = "1.0"
DEFAULT_ASSET_CODE: Final[str] = "600000.SH"
PUBLICATION_KEY: Final[str] = "current"
SOURCE_NAME: Final[str] = "synthetic-optional-consumer"
RAW_PAYLOAD_SCOPE: Final[str] = "record_response_body"
_RAW_PAYLOAD_SCOPES: Final[frozenset[str]] = frozenset(
    {"batch_response_body", "record_response_body"}
)


class OptionalConsumerStateError(ValueError):
    """Identify a missing or unsafe optional-publication precondition."""


@dataclass(frozen=True, slots=True)
class OptionalConsumerClocks:
    """Caller-owned source clocks; publication time is sampled after readback."""

    closed_session: date
    news_published_at: datetime
    available_at: datetime
    fetched_at: datetime


@dataclass(frozen=True, slots=True)
class SourceArtifact:
    """Exact synthetic response bytes retained as source evidence."""

    dataset_key: str
    path: Path
    source_record_id: str
    raw_payload_hash: str
    raw_payload_scope: str
    body_size_bytes: int


@dataclass(frozen=True, slots=True)
class OptionalCatalogState:
    """The active exact catalog rows used by the optional publishers."""

    contract_versions: tuple[tuple[str, str, str], ...]
    policy_versions: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class OptionalConsumerState:
    """Exact optional publication identities and source artifacts for one run."""

    catalog: OptionalCatalogState
    news_publication_id: str
    news_publication_hash: str
    capital_flow_publication_id: str
    capital_flow_publication_hash: str
    news_artifact: SourceArtifact
    capital_flow_artifact: SourceArtifact
    publication_at: datetime


def _aware_utc(value: datetime, *, field_name: str) -> datetime:
    """Require an aware timestamp and normalize only its timezone display."""

    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise OptionalConsumerStateError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _require_uuid(value: str) -> str:
    """Require a canonical run UUID supplied by the caller."""

    try:
        parsed = UUID(value)
    except (TypeError, ValueError) as error:
        raise OptionalConsumerStateError("run_id must be a canonical UUID") from error
    normalized = str(parsed)
    if normalized != value.lower():
        raise OptionalConsumerStateError("run_id must be a canonical UUID")
    return normalized


def _require_tux08_sqlite_database() -> None:
    """Require the exact disposable research test database before writing."""

    from tests.support.tui_research.disposable import require_test_database

    require_test_database()


def _require_tmp_path(tmp_path: Path) -> Path:
    """Constrain retained response bytes to the repository disposable tree."""

    from django.conf import settings

    target = tmp_path.expanduser().resolve()
    repository_tmp = (Path(str(settings.BASE_DIR)).resolve() / ".tmp").resolve()
    try:
        target.relative_to(repository_tmp)
    except ValueError as error:
        raise OptionalConsumerStateError(
            "optional source artifacts must be under settings.BASE_DIR/.tmp"
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
    """Write canonical synthetic bytes and retain their exact SHA-256 digest."""

    if raw_payload_scope not in _RAW_PAYLOAD_SCOPES:
        raise OptionalConsumerStateError("unsupported raw payload scope")
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
    stored_body = path.read_bytes()
    if stored_body != body:
        raise OptionalConsumerStateError("source artifact bytes changed during write")
    return SourceArtifact(
        dataset_key=dataset_key,
        path=path,
        source_record_id=source_record_id,
        raw_payload_hash=hashlib.sha256(stored_body).hexdigest(),
        raw_payload_scope=raw_payload_scope,
        body_size_bytes=len(stored_body),
    )


def _normalize_clocks(
    clocks: OptionalConsumerClocks,
    *,
    actual_now: datetime,
) -> OptionalConsumerClocks:
    """Validate caller source chronology without inferring any source time."""

    from apps.data_center.domain.market_time import cn_market_date_start_utc

    if isinstance(clocks.closed_session, datetime) or not isinstance(clocks.closed_session, date):
        raise TypeError("closed_session must be a date")
    normalized = OptionalConsumerClocks(
        closed_session=clocks.closed_session,
        news_published_at=_aware_utc(clocks.news_published_at, field_name="news_published_at"),
        available_at=_aware_utc(clocks.available_at, field_name="available_at"),
        fetched_at=_aware_utc(clocks.fetched_at, field_name="fetched_at"),
    )
    if normalized.news_published_at > normalized.available_at:
        raise OptionalConsumerStateError("news_published_at cannot follow available_at")
    if normalized.available_at > normalized.fetched_at:
        raise OptionalConsumerStateError("available_at cannot follow fetched_at")
    flow_observed_at = cn_market_date_start_utc(normalized.closed_session)
    if flow_observed_at > normalized.fetched_at:
        raise OptionalConsumerStateError("closed_session cannot follow fetched_at")
    reference = _aware_utc(actual_now, field_name="actual_now")
    if any(
        value > reference
        for value in (
            normalized.news_published_at,
            normalized.available_at,
            normalized.fetched_at,
            flow_observed_at,
        )
    ):
        raise OptionalConsumerStateError("source clocks cannot be in the future")
    return normalized


def _activate_pointer(
    *,
    dataset_key: str,
    publication_id: str,
    publication_hash: str,
) -> None:
    """Bind one optional current pointer to the exact publisher result."""

    if dataset_key not in OPTIONAL_DATASET_KEYS:
        raise OptionalConsumerStateError("optional pointer dataset is not allowed")
    if not publication_id.strip() or not publication_hash.strip():
        raise OptionalConsumerStateError("optional publication pointer values cannot be empty")
    from apps.data_center.infrastructure.publication_models import (
        CanonicalPublicationPointerModel,
    )

    CanonicalPublicationPointerModel._default_manager.update_or_create(
        dataset_key=dataset_key,
        publication_key=PUBLICATION_KEY,
        defaults={
            "publication_id": publication_id,
            "publication_hash": publication_hash,
            "activation_id": f"optional-consumer:{publication_id}",
        },
    )


def _binding_key(binding: object) -> tuple[object, ...]:
    """Build a stable comparison key for one typed ProviderBinding."""

    from apps.data_center.domain.contracts import ProviderBinding

    if not isinstance(binding, ProviderBinding):
        raise OptionalConsumerStateError("provider binding was not narrowed to its domain type")
    return (
        binding.dataset.value,
        binding.dataset.contract_version,
        binding.dataset.schema_version,
        binding.provider,
        binding.capability,
        binding.priority,
        binding.freshness_seconds,
        binding.validator_key,
        binding.enabled,
    )


def _owner_key(owner: object) -> tuple[object, ...]:
    """Build a stable comparison key for one typed owner registration."""

    from apps.data_center.domain.contracts import DataOwnerRegistration

    if not isinstance(owner, DataOwnerRegistration):
        raise OptionalConsumerStateError("owner registration was not narrowed to its domain type")
    return (
        owner.dataset_key,
        owner.data_platform_owner,
        owner.business_owner,
        owner.acceptance_owner,
        owner.active,
    )


def ensure_optional_catalog(*, governance_root: Path) -> OptionalCatalogState:
    """Load exact optional governance and preserve existing active catalog rows.

    The current fixed export declares legacy policies for these optional
    datasets.  They are loaded and compared exactly; this helper never creates
    or rewrites a policy merely to make an optional publication appear fresh.
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
        if contract.key.value in OPTIONAL_DATASET_KEYS
        and contract.key.contract_version == CONTRACT_VERSION
        and contract.key.schema_version == SCHEMA_VERSION
    }
    expected_policies = {
        policy.dataset.value: policy
        for policy in policy_rows
        if policy.dataset.value in OPTIONAL_DATASET_KEYS
    }
    expected_bindings = [
        binding for binding in binding_rows if binding.dataset.value in OPTIONAL_DATASET_KEYS
    ]
    expected_owners = [owner for owner in owner_rows if owner.dataset_key in OPTIONAL_DATASET_KEYS]
    if set(expected_contracts) != set(OPTIONAL_DATASET_KEYS) or set(expected_policies) != set(
        OPTIONAL_DATASET_KEYS
    ):
        raise OptionalConsumerStateError("fixed governance lacks an optional catalog row")
    contract_repository = DatasetContractRepository()
    policy_repository = PublicationPolicyRepository()
    binding_repository = ProviderBindingRepository()
    owner_repository = DataOwnerRegistryRepository()
    active_contracts = {key: contract_repository.get_active(key) for key in OPTIONAL_DATASET_KEYS}
    active_policies = {key: policy_repository.get_active(key) for key in OPTIONAL_DATASET_KEYS}
    active_bindings = [
        binding
        for binding in binding_repository.list_active()
        if binding.dataset.value in OPTIONAL_DATASET_KEYS
    ]
    active_owners = [
        owner
        for owner in owner_repository.list_active()
        if owner.dataset_key in OPTIONAL_DATASET_KEYS
    ]
    expected_binding_keys = sorted(_binding_key(binding) for binding in expected_bindings)
    active_binding_keys = sorted(_binding_key(binding) for binding in active_bindings)
    expected_owner_keys = sorted(_owner_key(owner) for owner in expected_owners)
    active_owner_keys = sorted(_owner_key(owner) for owner in active_owners)
    needs_sync = (
        any(active_contracts[key] != expected_contracts[key] for key in OPTIONAL_DATASET_KEYS)
        or any(active_policies[key] != expected_policies[key] for key in OPTIONAL_DATASET_KEYS)
        or active_binding_keys != expected_binding_keys
        or active_owner_keys != expected_owner_keys
    )
    if needs_sync:
        existing_contracts = {
            contract.key.value: contract
            for contract in contract_repository.list_active()
            if contract.key.value not in OPTIONAL_DATASET_KEYS
        }
        existing_contracts.update(expected_contracts)
        existing_policies = {
            policy.dataset.value: policy
            for policy in policy_repository.list_active()
            if policy.dataset.value not in OPTIONAL_DATASET_KEYS
        }
        existing_policies.update(expected_policies)
        existing_bindings = [
            binding
            for binding in binding_repository.list_active()
            if binding.dataset.value not in OPTIONAL_DATASET_KEYS
        ]
        existing_bindings.extend(expected_bindings)
        existing_owners = [
            owner
            for owner in owner_repository.list_active()
            if owner.dataset_key not in OPTIONAL_DATASET_KEYS
        ]
        existing_owners.extend(expected_owners)
        SynchronizeDataCenterCatalogUseCase(
            contracts=contract_repository,
            bindings=binding_repository,
            policies=policy_repository,
            owners=owner_repository,
        ).execute(
            contracts=tuple(existing_contracts.values()),
            bindings=tuple(existing_bindings),
            policies=tuple(existing_policies.values()),
            owners=tuple(existing_owners),
        )
        active_contracts = {
            key: contract_repository.get_active(key) for key in OPTIONAL_DATASET_KEYS
        }
        active_policies = {key: policy_repository.get_active(key) for key in OPTIONAL_DATASET_KEYS}
    typed_contracts = {
        key: value for key, value in active_contracts.items() if isinstance(value, DatasetContract)
    }
    typed_policies = {
        key: value for key, value in active_policies.items() if isinstance(value, PublicationPolicy)
    }
    if any(typed_contracts.get(key) != expected_contracts[key] for key in OPTIONAL_DATASET_KEYS):
        raise OptionalConsumerStateError("active optional contract differs from governance")
    if any(typed_policies.get(key) != expected_policies[key] for key in OPTIONAL_DATASET_KEYS):
        raise OptionalConsumerStateError("active optional policy differs from governance")
    return OptionalCatalogState(
        contract_versions=tuple(
            (
                key,
                expected_contracts[key].key.contract_version,
                expected_contracts[key].key.schema_version,
            )
            for key in OPTIONAL_DATASET_KEYS
        ),
        policy_versions=tuple(
            (key, expected_policies[key].policy_version) for key in OPTIONAL_DATASET_KEYS
        ),
    )


def _news_model_for_fact(*, source: str, external_id: str) -> object:
    """Resolve one exact persisted NewsFactModel without generic row access."""

    from apps.data_center.infrastructure.models import NewsFactModel

    row = (
        NewsFactModel._default_manager.filter(source=source, external_id=external_id)
        .order_by("id")
        .first()
    )
    if not isinstance(row, NewsFactModel):
        raise OptionalConsumerStateError("synthetic news row was not persisted")
    return row


def _capital_flow_model_for_fact(*, asset_code: str, flow_date: date, source: str) -> object:
    """Resolve one exact persisted CapitalFlowFactModel without duck typing."""

    from apps.data_center.infrastructure.models import CapitalFlowFactModel

    row = (
        CapitalFlowFactModel._default_manager.filter(
            asset_code=asset_code,
            flow_date=flow_date,
            source=source,
        )
        .order_by("id")
        .first()
    )
    if not isinstance(row, CapitalFlowFactModel):
        raise OptionalConsumerStateError("synthetic capital-flow row was not persisted")
    return row


def prepare_optional_consumer_state(
    *,
    tmp_path: Path,
    governance_root: Path,
    clocks: OptionalConsumerClocks,
    run_id: str,
    publication_clock: Callable[[], datetime],
) -> OptionalConsumerState:
    """Persist and publish one typed optional news/flow consumer snapshot.

    The caller supplies the calendar-resolved ``closed_session`` and source
    clocks.  ``publication_clock`` is sampled only after both repositories have
    persisted and reread their typed facts.  All writes and publisher calls are
    inside one transaction so a publisher failure rolls back both facts and
    optional publication pointers.
    """

    _require_tux08_sqlite_database()
    artifact_root = _require_tmp_path(tmp_path)
    normalized_clocks = _normalize_clocks(
        clocks,
        actual_now=_aware_utc(datetime.now(UTC), field_name="actual_now"),
    )
    normalized_run_id = _require_uuid(run_id)
    catalog = ensure_optional_catalog(governance_root=governance_root)
    news_record_id = (
        f"{SOURCE_NAME}:news:{DEFAULT_ASSET_CODE}:{normalized_clocks.closed_session.isoformat()}"
    )
    flow_record_id = (
        f"{SOURCE_NAME}:capital-flow:{DEFAULT_ASSET_CODE}:"
        f"{normalized_clocks.closed_session.isoformat()}"
    )
    news_artifact = _write_source_artifact(
        tmp_path=artifact_root,
        dataset_key="market.news",
        source_record_id=news_record_id,
        raw_payload_scope=RAW_PAYLOAD_SCOPE,
        payload={
            "fixture": "synthetic-optional-consumer",
            "dataset_key": "market.news",
            "asset_code": DEFAULT_ASSET_CODE,
            "title": "[SYNTHETIC TEST] optional market-news record",
            "summary": "Synthetic test evidence; no investment opinion.",
            "published_at": normalized_clocks.news_published_at.isoformat(),
            "available_at": normalized_clocks.available_at.isoformat(),
            "fetched_at": normalized_clocks.fetched_at.isoformat(),
            "source": SOURCE_NAME,
            "external_id": news_record_id,
            "source_record_id": news_record_id,
            "raw_payload_scope": RAW_PAYLOAD_SCOPE,
        },
    )
    flow_artifact = _write_source_artifact(
        tmp_path=artifact_root,
        dataset_key="market.capital_flow",
        source_record_id=flow_record_id,
        raw_payload_scope=RAW_PAYLOAD_SCOPE,
        payload={
            "fixture": "synthetic-optional-consumer",
            "dataset_key": "market.capital_flow",
            "asset_code": DEFAULT_ASSET_CODE,
            "flow_date": normalized_clocks.closed_session.isoformat(),
            "available_at": normalized_clocks.available_at.isoformat(),
            "fetched_at": normalized_clocks.fetched_at.isoformat(),
            "main_net": 0.0,
            "retail_net": 0.0,
            "super_large_net": 0.0,
            "large_net": 0.0,
            "medium_net": 0.0,
            "small_net": 0.0,
            "source": SOURCE_NAME,
            "source_record_id": flow_record_id,
            "raw_payload_scope": RAW_PAYLOAD_SCOPE,
        },
    )

    from django.db import transaction

    from apps.data_center.application.publication_sync import (
        PublishCapitalFlowBatchUseCase,
        PublishNewsBatchUseCase,
    )
    from apps.data_center.domain.entities import CapitalFlowFact, NewsFact
    from apps.data_center.infrastructure.catalog_runtime_repositories import (
        DatasetContractRepository,
    )
    from apps.data_center.infrastructure.control_plane_repositories import (
        CanonicalPublicationRepository,
    )
    from apps.data_center.infrastructure.market_breadth_repositories import CapitalFlowRepository
    from apps.data_center.infrastructure.models import CapitalFlowFactModel, NewsFactModel
    from apps.data_center.infrastructure.news_repository import NewsRepository
    from apps.data_center.infrastructure.publication_policy_repository import (
        PublicationPolicyRepository,
    )

    news_fact = NewsFact(
        asset_code=DEFAULT_ASSET_CODE,
        title="[SYNTHETIC TEST] optional market-news record",
        summary="Synthetic test evidence; no investment opinion.",
        published_at=normalized_clocks.news_published_at,
        source=SOURCE_NAME,
        external_id=news_record_id,
        sentiment_score=0.0,
        extra={"fixture_source": "synthetic", "raw_payload_scope": RAW_PAYLOAD_SCOPE},
        fetched_at=normalized_clocks.fetched_at,
    )
    flow_fact = CapitalFlowFact(
        asset_code=DEFAULT_ASSET_CODE,
        flow_date=normalized_clocks.closed_session,
        main_net=0.0,
        retail_net=0.0,
        super_large_net=0.0,
        large_net=0.0,
        medium_net=0.0,
        small_net=0.0,
        source=SOURCE_NAME,
        fetched_at=normalized_clocks.fetched_at,
        extra={"fixture_source": "synthetic", "raw_payload_scope": RAW_PAYLOAD_SCOPE},
    )

    with transaction.atomic():
        news_repository = NewsRepository()
        flow_repository = CapitalFlowRepository()
        inserted_news = news_repository.bulk_insert([news_fact])
        if inserted_news not in (0, 1):
            raise OptionalConsumerStateError("news repository stored an unexpected row count")
        if flow_repository.bulk_upsert([flow_fact]) != 1:
            raise OptionalConsumerStateError("capital-flow repository did not store one typed row")
        news_model = _news_model_for_fact(source=SOURCE_NAME, external_id=news_record_id)
        flow_model = _capital_flow_model_for_fact(
            asset_code=DEFAULT_ASSET_CODE,
            flow_date=normalized_clocks.closed_session,
            source=SOURCE_NAME,
        )
        if not isinstance(news_model, NewsFactModel) or not isinstance(
            flow_model, CapitalFlowFactModel
        ):
            raise OptionalConsumerStateError("optional rows were not narrowed to typed models")
        news_extra = dict(news_model.extra or {})
        news_extra["fixture_source"] = "synthetic"
        news_extra["raw_payload_scope"] = RAW_PAYLOAD_SCOPE
        NewsFactModel._default_manager.filter(pk=news_model.pk).update(
            source_record_id=news_record_id,
            raw_payload_hash=news_artifact.raw_payload_hash,
            available_at=normalized_clocks.available_at,
            extra=news_extra,
        )
        flow_extra = dict(flow_model.extra or {})
        flow_extra["fixture_source"] = "synthetic"
        flow_extra["raw_payload_scope"] = RAW_PAYLOAD_SCOPE
        CapitalFlowFactModel._default_manager.filter(pk=flow_model.pk).update(
            source_record_id=flow_record_id,
            raw_payload_hash=flow_artifact.raw_payload_hash,
            extra=flow_extra,
        )
        news_model.refresh_from_db()
        flow_model.refresh_from_db()
        if (
            news_model.source_record_id != news_record_id
            or news_model.raw_payload_hash != news_artifact.raw_payload_hash
            or news_model.available_at is None
            or news_model.contract_version != CONTRACT_VERSION
            or news_model.schema_version != SCHEMA_VERSION
            or news_model.extra.get("raw_payload_scope") != RAW_PAYLOAD_SCOPE
        ):
            raise OptionalConsumerStateError("news source evidence did not persist exactly")
        if (
            flow_model.source_record_id != flow_record_id
            or flow_model.raw_payload_hash != flow_artifact.raw_payload_hash
            or flow_model.contract_version != CONTRACT_VERSION
            or flow_model.schema_version != SCHEMA_VERSION
            or flow_model.extra.get("raw_payload_scope") != RAW_PAYLOAD_SCOPE
        ):
            raise OptionalConsumerStateError("capital-flow source evidence did not persist exactly")
        stored_news_rows = news_repository.get_recent(
            DEFAULT_ASSET_CODE,
            limit=1,
            fact_pks=[str(news_model.pk)],
        )
        stored_flow_rows = flow_repository.get_series(
            DEFAULT_ASSET_CODE,
            start=normalized_clocks.closed_session,
            end=normalized_clocks.closed_session,
            limit=1,
            fact_pks=[str(flow_model.pk)],
        )
        if len(stored_news_rows) != 1 or len(stored_flow_rows) != 1:
            raise OptionalConsumerStateError("optional typed readback did not resolve one row each")
        stored_news = stored_news_rows[0]
        stored_flow = stored_flow_rows[0]
        news_published_at = _aware_utc(
            stored_news.published_at,
            field_name="news.published_at",
        )
        news_available_at = _aware_utc(
            news_model.available_at,
            field_name="NewsFactModel.available_at",
        )
        if news_published_at != normalized_clocks.news_published_at:
            raise OptionalConsumerStateError("news published_at changed during typed readback")
        if news_available_at != normalized_clocks.available_at:
            raise OptionalConsumerStateError("news available_at changed during typed readback")
        if stored_flow.flow_date != normalized_clocks.closed_session:
            raise OptionalConsumerStateError("capital-flow flow_date changed during typed readback")
        news_fetched_at = _aware_utc(stored_news.fetched_at, field_name="news.fetched_at")
        flow_fetched_at = _aware_utc(stored_flow.fetched_at, field_name="capital_flow.fetched_at")
        stored_fetched_times = [news_fetched_at, flow_fetched_at]
        publication_at = _aware_utc(
            publication_clock(),
            field_name="publication_clock()",
        )
        current_now = _aware_utc(datetime.now(UTC), field_name="actual_now")
        if publication_at > current_now:
            raise OptionalConsumerStateError("publication_clock() cannot be in the future")
        if any(value > publication_at for value in stored_fetched_times):
            raise OptionalConsumerStateError(
                "database-assigned/source fetched_at is after publication_clock(); do not rewrite it"
            )
        from apps.data_center.domain.market_time import cn_market_date_start_utc

        flow_observed_at = cn_market_date_start_utc(normalized_clocks.closed_session)
        if any(
            value > publication_at
            for value in (
                news_published_at,
                news_available_at,
                flow_observed_at,
            )
        ):
            raise OptionalConsumerStateError(
                "optional source evidence is after publication_clock()"
            )
        publication_repository = CanonicalPublicationRepository()
        policy_repository = PublicationPolicyRepository()
        contract_repository = DatasetContractRepository()
        news_publication = PublishNewsBatchUseCase(
            fact_repository=news_repository,
            publication_repository=publication_repository,
            policy_repository=policy_repository,
            contract_repository=contract_repository,
        ).execute(
            [stored_news],
            provider_name=SOURCE_NAME,
            publication_key=PUBLICATION_KEY,
            run_id=normalized_run_id,
            published_at=publication_at,
        )
        flow_publication = PublishCapitalFlowBatchUseCase(
            fact_repository=flow_repository,
            publication_repository=publication_repository,
            policy_repository=policy_repository,
        ).execute(
            [stored_flow],
            provider_name=SOURCE_NAME,
            publication_key=PUBLICATION_KEY,
            run_id=normalized_run_id,
            published_at=publication_at,
        )
        if news_publication is None:
            raise OptionalConsumerStateError("news publisher returned no publication")
        if flow_publication is None:
            raise OptionalConsumerStateError("capital-flow publisher returned no publication")
        _activate_pointer(
            dataset_key="market.news",
            publication_id=news_publication.publication_id,
            publication_hash=news_publication.publication_hash,
        )
        _activate_pointer(
            dataset_key="market.capital_flow",
            publication_id=flow_publication.publication_id,
            publication_hash=flow_publication.publication_hash,
        )

    return OptionalConsumerState(
        catalog=catalog,
        news_publication_id=news_publication.publication_id,
        news_publication_hash=news_publication.publication_hash,
        capital_flow_publication_id=flow_publication.publication_id,
        capital_flow_publication_hash=flow_publication.publication_hash,
        news_artifact=news_artifact,
        capital_flow_artifact=flow_artifact,
        publication_at=publication_at,
    )


__all__ = [
    "CONTRACT_VERSION",
    "DEFAULT_ASSET_CODE",
    "OPTIONAL_DATASET_KEYS",
    "OptionalCatalogState",
    "OptionalConsumerClocks",
    "OptionalConsumerState",
    "OptionalConsumerStateError",
    "RAW_PAYLOAD_SCOPE",
    "SourceArtifact",
    "ensure_optional_catalog",
    "prepare_optional_consumer_state",
]
