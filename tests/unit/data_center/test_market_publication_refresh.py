"""Full-market snapshots must never publish an intermediate or failed batch."""

import hashlib
import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from threading import Event, Lock
from time import sleep
from types import SimpleNamespace
from uuid import uuid4

import pytest
from celery.exceptions import SoftTimeLimitExceeded
from django.core.cache.backends.locmem import LocMemCache

from apps.data_center.application.market_publication_refresh import (
    MarketPricePreparationResult,
    MarketPriceSuspensionEvidence,
    MarketPublicationRefreshBlocked,
    MarketPublicationRefreshPorts,
    refresh_market_price_inputs,
    refresh_market_publications,
)
from apps.data_center.application.model_history_preparation import ModelHistoryRawAuditBinding
from apps.data_center.domain.entities import RawAuditReference
from apps.data_center.domain.target_date_universe import (
    NotYetListedAsset,
    TargetDateAssetUniverseScope,
)
from core.exceptions import DataFetchError


@pytest.fixture(autouse=True)
def _isolate_full_market_refresh_cache(monkeypatch) -> None:
    """Keep full-market task lease tests away from the configured Redis cache."""

    from apps.data_center.application import tasks

    isolated_cache = LocMemCache(f"full-market-refresh-tests:{uuid4().hex}", {})
    isolated_cache.clear()
    monkeypatch.setattr(tasks, "cache", isolated_cache)


class _PriceAuditEvidence:
    """Provide one stable exact reference for focused refresh contract fakes."""

    def __init__(self) -> None:
        self.reference = RawAuditReference(
            raw_audit_id="price-test-audit",
            version="raw-audit-v1",
            content_hash="b" * 64,
            run_id="price-test-run",
            ingested_run_id="price-test-ingested",
        )
        self.binding = ModelHistoryRawAuditBinding(self.reference, "tushare")

    def model_history_audit_references(self, rows):
        return (self.reference,) if rows else ()

    def take_model_history_audit_references(self):
        return (self.reference,)

    def model_history_audit_bindings(self, rows):
        return (self.binding,) if rows else ()

    def take_model_history_audit_bindings(self):
        return (self.binding,)


def _market_price_result_with_member_binding(
    *,
    raw_audit_id: str = "price-test-audit",
    source_type: str = "tushare",
) -> MarketPricePreparationResult:
    """Provide explicit source-bound member lineage for task publication tests."""

    reference = RawAuditReference(
        raw_audit_id=raw_audit_id,
        version="raw-audit-v1",
        content_hash=hashlib.sha256(raw_audit_id.encode("utf-8")).hexdigest(),
        run_id=f"{raw_audit_id}-run",
        ingested_run_id=f"{raw_audit_id}-ingested",
    )
    binding = ModelHistoryRawAuditBinding(reference, source_type)
    return MarketPricePreparationResult(
        suspended_codes=(),
        raw_audit_references=(reference,),
        raw_audit_bindings=(binding,),
        member_owning_raw_audit_bindings=(binding,),
    )


def test_price_preparation_keeps_failover_source_type_per_exact_reference():
    from types import SimpleNamespace

    target = date(2026, 9, 18)
    source_types = ("akshare", "tushare")

    def binding(source_type: str) -> ModelHistoryRawAuditBinding:
        audit_id = f"price-{source_type}"
        return ModelHistoryRawAuditBinding(
            RawAuditReference(
                raw_audit_id=audit_id,
                version="raw-audit-v1",
                content_hash=hashlib.sha256(audit_id.encode("utf-8")).hexdigest(),
                run_id=f"run-{source_type}",
                ingested_run_id=f"ingested-{source_type}",
            ),
            source_type,
        )

    class FailoverEvidence(_PriceAuditEvidence):
        def __init__(self):
            super().__init__()
            self.by_source = {source: binding(source) for source in source_types}

        def stock_history(self, asset_code, _start_date, _end_date):
            source_type = "akshare" if asset_code == "000001.SZ" else "tushare"
            return (SimpleNamespace(trade_date=target, source=source_type),)

        def model_history_audit_bindings(self, rows):
            return tuple(self.by_source[row.source] for row in rows)

        def take_model_history_audit_bindings(self):
            return tuple(self.by_source[source] for source in source_types)

    result = refresh_market_price_inputs(FailoverEvidence(), ["000001.SZ", "000002.SZ"], target)

    assert tuple(binding.source_type for binding in result.raw_audit_bindings) == source_types
    assert result.raw_audit_references == tuple(
        binding.reference for binding in result.raw_audit_bindings
    )
    assert result.member_owning_raw_audit_bindings == result.raw_audit_bindings


def test_price_preparation_keeps_stale_primary_diagnostic_out_of_member_lineage():
    target = date(2026, 9, 18)
    primary = ModelHistoryRawAuditBinding(
        RawAuditReference(
            raw_audit_id="price-primary-stale",
            version="raw-audit-v1",
            content_hash="d" * 64,
            run_id="primary-run",
            ingested_run_id="primary-ingested",
        ),
        "akshare",
    )
    fallback = ModelHistoryRawAuditBinding(
        RawAuditReference(
            raw_audit_id="price-fallback-current",
            version="raw-audit-v1",
            content_hash="e" * 64,
            run_id="fallback-run",
            ingested_run_id="fallback-ingested",
        ),
        "tushare",
    )

    class StalePrimaryThenFallback(_PriceAuditEvidence):
        def __init__(self):
            super().__init__()
            self.calls = 0

        def stock_history(self, _asset_code, _start_date, _end_date):
            self.calls += 1
            if self.calls == 1:
                return (SimpleNamespace(trade_date=target - timedelta(days=1), source="akshare"),)
            return (SimpleNamespace(trade_date=target, source="tushare"),)

        def model_history_audit_bindings(self, rows):
            return (fallback,) if rows and rows[0].source == "tushare" else (primary,)

        def take_model_history_audit_bindings(self):
            return (primary, fallback)

    result = refresh_market_price_inputs(StalePrimaryThenFallback(), ["000001.SZ"], target)

    assert result.raw_audit_bindings == (fallback, primary)
    assert result.raw_audit_references == (fallback.reference, primary.reference)
    assert result.member_owning_raw_audit_bindings == (fallback,)


def test_price_preparation_fails_closed_on_duplicate_reference_source_type_conflict():
    from types import SimpleNamespace

    target = date(2026, 9, 18)
    reference = RawAuditReference(
        raw_audit_id="same-price-audit",
        version="raw-audit-v1",
        content_hash="c" * 64,
        run_id="same-run",
        ingested_run_id="same-ingested",
    )

    class ConflictingEvidence(_PriceAuditEvidence):
        def stock_history(self, _asset_code, _start_date, _end_date):
            return (SimpleNamespace(trade_date=target, source="tushare"),)

        def model_history_audit_bindings(self, _rows):
            return (
                ModelHistoryRawAuditBinding(reference, "tushare"),
                ModelHistoryRawAuditBinding(reference, "akshare"),
            )

        def take_model_history_audit_bindings(self):
            return ()

    with pytest.raises(DataFetchError) as caught:
        refresh_market_price_inputs(ConflictingEvidence(), ["000001.SZ"], target)

    assert caught.value.code == "MODEL_MARKET_AUDIT_SOURCE_TYPE_CONFLICT"


def test_price_result_fails_closed_when_member_binding_is_absent_from_diagnostics():
    evidence = _PriceAuditEvidence()

    with pytest.raises(DataFetchError) as caught:
        MarketPricePreparationResult(
            suspended_codes=(),
            raw_audit_references=(),
            member_owning_raw_audit_bindings=(evidence.binding,),
        )

    assert caught.value.code == "MODEL_MARKET_AUDIT_EVIDENCE_MISSING"


def test_price_result_fails_closed_when_member_source_conflicts_with_diagnostics():
    evidence = _PriceAuditEvidence()
    conflicting_member_binding = ModelHistoryRawAuditBinding(evidence.reference, "akshare")

    with pytest.raises(DataFetchError) as caught:
        MarketPricePreparationResult(
            suspended_codes=(),
            raw_audit_references=(evidence.reference,),
            raw_audit_bindings=(evidence.binding,),
            member_owning_raw_audit_bindings=(conflicting_member_binding,),
        )

    assert caught.value.code == "MODEL_MARKET_AUDIT_SOURCE_TYPE_CONFLICT"


def test_price_suspension_evidence_requires_exact_sorted_unique_asset_scope():
    target = date(2026, 9, 18)
    evidence = MarketPriceSuspensionEvidence(
        asset_code="000016.SZ",
        target_trade_date=target,
        evidence_source="akshare",
    )

    with pytest.raises(ValueError, match="suspension evidence must exactly match"):
        MarketPricePreparationResult(
            suspended_codes=("000016.SZ",),
            raw_audit_references=(),
        )

    with pytest.raises(ValueError, match="suspension evidence must be sorted and unique"):
        MarketPricePreparationResult(
            suspended_codes=("000016.SZ",),
            raw_audit_references=(),
            suspension_evidence=(evidence, evidence),
        )


def test_price_stage_rejects_target_suspension_without_canonical_source():
    target = date(2026, 9, 18)

    class Port:
        def stock_history(self, asset_code, _start_date, _end_date):
            raise DataFetchError(
                "suspended",
                code="MODEL_MARKET_SUSPENDED",
                details={"asset_code": asset_code, "suspended_through": target.isoformat()},
            )

    with pytest.raises(DataFetchError) as caught:
        refresh_market_price_inputs(Port(), ["000016.SZ"], target)

    assert caught.value.code == "MODEL_MARKET_SUSPENSION_EVIDENCE_INVALID"


def _prefetched_quote_sync(
    execute: Callable[[object], object], *, include_audit_reference: bool = True
) -> SimpleNamespace:
    """Build a quote-sync test double that exposes the frozen-session contract."""

    prepared = object()
    prepare_calls: list[dict[str, object]] = []

    def prepare_session(**kwargs: object) -> object:
        prepare_calls.append(dict(kwargs))
        return prepared

    def execute_batch(request: object, session: object) -> object:
        if session is not prepared:
            pytest.fail("quote batch used a different prepared session")
        result = execute(request)
        if not include_audit_reference:
            return _with_raw_audit_reference(
                result, "quote-missing-reference", include_reference=False
            )
        return _with_raw_audit_reference(result, "quote-test-audit")

    return SimpleNamespace(
        prepare_session=prepare_session,
        execute_prefetched_session_batch=lambda request, session: execute_batch(request, session),
        prepare_calls=prepare_calls,
    )


def _with_raw_audit_reference(
    result: object,
    audit_id: str,
    *,
    include_reference: bool = True,
) -> SimpleNamespace:
    """Add exact audit lineage to test sync results when the case is not about absence."""

    payload = dict(vars(result))
    run_id = str(payload.get("run_id") or f"{audit_id}-run")
    ingested_run_id = str(payload.get("ingested_run_id") or f"{audit_id}-ingested")
    payload.update(run_id=run_id, ingested_run_id=ingested_run_id)
    if include_reference:
        payload["raw_audit_reference"] = RawAuditReference(
            raw_audit_id=audit_id,
            version="raw-audit-v1",
            content_hash=hashlib.sha256(audit_id.encode("utf-8")).hexdigest(),
            run_id=run_id,
            ingested_run_id=ingested_run_id,
        )
    else:
        payload["raw_audit_reference"] = None
    return SimpleNamespace(**payload)


def _audited_valuation_sync(
    execute: Callable[..., object], *, include_audit_reference: bool = True
) -> SimpleNamespace:
    """Build a valuation test double with exact seed audit lineage."""

    return SimpleNamespace(
        execute=lambda **kwargs: _with_raw_audit_reference(
            execute(**kwargs),
            "valuation-test-audit",
            include_reference=include_audit_reference,
        )
    )


def _universe_report(codes: list[str], *, active_count: int | None = None) -> dict[str, object]:
    """Return provider-bound universe evidence for task-path tests."""

    normalized = sorted(codes)
    return {
        "active_count": len(normalized) if active_count is None else active_count,
        "touched_count": len(normalized),
        "active_codes_sha256": hashlib.sha256(
            json.dumps(
                normalized,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
    }


def _unknown_listing_date_scope(
    target_date: date,
    asset_codes: list[str],
) -> TargetDateAssetUniverseScope:
    """Preserve every active test asset when its listing date is unknown."""

    canonical_codes = tuple(sorted(str(code).strip().upper() for code in asset_codes))
    return TargetDateAssetUniverseScope(
        target_date=target_date,
        candidate_codes=canonical_codes,
        requested_codes=canonical_codes,
        excluded_not_yet_listed=(),
        unknown_listing_date_codes=canonical_codes,
    )


def _fake_market_publication_bundle(coordinator):
    """Adapt legacy task-test doubles to the staged three-publication contract."""

    from dataclasses import replace
    from hashlib import sha256
    from uuid import NAMESPACE_URL, uuid5

    from apps.data_center.application.current_publication_staging import (
        CurrentPublicationStagedCandidate,
    )
    from apps.data_center.application.publication_activation import (
        CurrentPublicationPointerSnapshot,
    )
    from apps.data_center.domain.control_plane import (
        CanonicalPublication,
        CoverageSnapshot,
        PublicationScopeBlock,
        PublicationState,
    )

    preview_by_dataset = {}
    staged_by_dataset = {}
    commands_by_dataset = {}
    legacy_payload = {}
    bundle_events = []
    activation_requests = []
    base_preview = getattr(coordinator, "preview", lambda **_: SimpleNamespace(datasets=()))

    def preview(**kwargs):
        bundle_events.append("preview")
        result = base_preview(**kwargs)
        preview_by_dataset.clear()
        preview_by_dataset.update({item.dataset_key: item for item in result.datasets})
        return result

    def stage(command):
        dataset_key = next(
            key
            for key in (
                "equity.quote.snapshot",
                "equity.price.bar",
                "equity.valuation.fact",
            )
            if key not in commands_by_dataset
        )
        commands_by_dataset[dataset_key] = command
        bundle_events.append(f"stage:{dataset_key}")
        preview_item = preview_by_dataset.get(dataset_key)
        requested_count = int(
            getattr(preview_item, "requested_asset_count", len(command.asset_codes))
        )
        covered_count = int(getattr(preview_item, "covered_asset_count", requested_count))
        member_count = max(1, int(getattr(preview_item, "member_count", covered_count)))
        eligible_count = max(covered_count, member_count)
        publication_id = str(
            uuid5(NAMESPACE_URL, f"test:{command.run_id}:{command.task_attempt_id}:{dataset_key}")
        )
        publication_hash = sha256(
            f"{command.run_id}:{command.task_attempt_id}:{dataset_key}".encode()
        ).hexdigest()
        source_type = (
            command.raw_audit_bindings[0].expected_source_type
            if command.raw_audit_bindings
            else "tushare"
        )
        coverage = CoverageSnapshot(
            coverage_id=str(uuid5(NAMESPACE_URL, f"coverage:{publication_id}")),
            publication_id=publication_id,
            requested_count=max(requested_count, eligible_count),
            eligible_count=eligible_count,
            selected_count=member_count,
            missing_count=max(0, requested_count - covered_count),
            generated_at=command.published_at,
        )
        publication = CanonicalPublication(
            publication_id=publication_id,
            dataset_key=dataset_key,
            publication_key="current",
            policy_version="p2:test-current-policy",
            state=PublicationState.CANDIDATE,
            selected_source=source_type,
            publication_hash=publication_hash,
            coverage=coverage,
            member_count=member_count,
            as_of=command.published_at,
            published_at=None,
            run_id=command.run_id,
        )
        manifest = SimpleNamespace(
            publication_id=publication_id,
            publication_hash=publication_hash,
            dataset_key=dataset_key,
            publication_key="current",
            run_id=command.run_id,
            task_attempt_id=command.task_attempt_id,
            raw_audits=tuple(item.reference for item in command.raw_audit_bindings),
        )
        staged = CurrentPublicationStagedCandidate(publication, manifest)
        staged_by_dataset[dataset_key] = staged
        return staged

    def activate(request, **_kwargs):
        bundle_events.append("activation")
        activation_requests.append(request)
        execute = getattr(coordinator, "execute", None)
        if callable(execute):
            command = commands_by_dataset["equity.quote.snapshot"]
            outcome = execute(
                asset_codes=list(command.asset_codes),
                published_at=command.published_at,
                run_id=command.run_id,
                scope_exclusions_by_dataset={
                    key: value.scope_exclusions
                    for key, value in commands_by_dataset.items()
                    if value.scope_exclusions
                },
                required_observation_dates={
                    key: value.required_observation_date
                    for key, value in commands_by_dataset.items()
                    if value.required_observation_date is not None
                },
            )
            to_dict = getattr(outcome, "to_dict", None)
            if callable(to_dict):
                legacy_payload.update(to_dict())
        result = []
        serialized_by_dataset = {
            item.get("dataset_key"): item
            for item in legacy_payload.get("datasets", [])
            if isinstance(item, dict)
        }
        for candidate in request.candidates:
            staged = staged_by_dataset[candidate.dataset_key]
            publication = staged.publication
            serialized = serialized_by_dataset.get(candidate.dataset_key, {})
            scope_blocks = tuple(
                PublicationScopeBlock(
                    asset_code=item["asset_code"],
                    reason_code=item["reason_code"],
                    target_trade_date=(
                        date.fromisoformat(item["target_trade_date"])
                        if item.get("target_trade_date")
                        else None
                    ),
                    source=item.get("source", ""),
                    publication_run_id=item.get("publication_run_id", publication.run_id),
                    policy_version=item.get("policy_version", publication.policy_version),
                    publication_id=publication.publication_id,
                    evidence_source=item.get("evidence_source", ""),
                )
                for item in serialized.get("scope_blocks", [])
            )
            policy_version = (
                scope_blocks[0].policy_version if scope_blocks else publication.policy_version
            )
            selected_source = (
                scope_blocks[0].source
                if scope_blocks and scope_blocks[0].source
                else publication.selected_source
            )
            result.append(
                replace(
                    publication,
                    policy_version=policy_version,
                    state=PublicationState.PUBLISHED,
                    selected_source=selected_source,
                    member_count=max(1, publication.member_count),
                    published_at=datetime.now(UTC),
                    scope_blocks=scope_blocks,
                )
            )
        return tuple(result)

    def build_audit_writer():
        bundle_events.append("audit_writer")
        return SimpleNamespace(database_alias="default")

    def capture_authority(**_kwargs):
        bundle_events.append("authority_capture")
        return SimpleNamespace(
            database_alias="default",
            authority_fence=object(),
            authority_proof=object(),
        )

    def read_pointer(*_args):
        bundle_events.append("current_pointer")
        return CurrentPublicationPointerSnapshot(None, None)

    return SimpleNamespace(
        database_alias="default",
        previewer=SimpleNamespace(preview=preview),
        quote_staging=SimpleNamespace(execute=stage),
        price_staging=SimpleNamespace(execute=stage),
        valuation_staging=SimpleNamespace(execute=stage),
        activate_group=SimpleNamespace(execute=activate),
        audit_writer_factory=build_audit_writer,
        authority_capture=capture_authority,
        current_pointer_reader=read_pointer,
        staged_commands=commands_by_dataset,
        bundle_events=bundle_events,
        activation_requests=activation_requests,
    )


def _direct_current_market_staging_bundle():
    """Build one fully typed in-memory bundle for staging/activation fault tests."""

    from types import SimpleNamespace

    coordinator = SimpleNamespace(
        preview=lambda **_: SimpleNamespace(datasets=()),
        execute=lambda **_: None,
    )
    bundle = _fake_market_publication_bundle(coordinator)
    from apps.data_center.application.current_publication_staging import (
        CurrentPublicationStageRawAuditBinding,
    )

    bindings = {
        "equity.quote.snapshot": (
            CurrentPublicationStageRawAuditBinding(
                RawAuditReference(
                    "quote-stage-raw",
                    "raw-audit-v1",
                    "a" * 64,
                    "quote-run",
                    "quote-ingested",
                ),
                "tushare",
            ),
        ),
        "equity.price.bar": (
            CurrentPublicationStageRawAuditBinding(
                RawAuditReference(
                    "price-stage-raw",
                    "raw-audit-v1",
                    "b" * 64,
                    "price-run",
                    "price-ingested",
                ),
                "tushare",
            ),
        ),
        "equity.valuation.fact": (
            CurrentPublicationStageRawAuditBinding(
                RawAuditReference(
                    "valuation-stage-raw",
                    "raw-audit-v1",
                    "c" * 64,
                    "valuation-run",
                    "valuation-ingested",
                ),
                "akshare",
            ),
        ),
    }
    return bundle, bindings


def _run_direct_current_market_staging(bundle, bindings):
    """Stage a fixed three-dataset request with one deterministic test identity."""

    from types import SimpleNamespace

    from apps.data_center.application.current_market_publication_activation import (
        stage_and_activate_current_market_group,
    )

    return stage_and_activate_current_market_group(
        bundle=bundle,
        asset_codes=["000001.SZ"],
        published_at=datetime(2026, 9, 18, 8, tzinfo=UTC),
        run_id="00000000-0000-4000-8000-000000000001",
        task_attempt_id="unit-attempt-1",
        required_observation_date=date(2026, 9, 18),
        scope_exclusions_by_dataset={},
        raw_audit_bindings_by_dataset=bindings,
        preflight_context=SimpleNamespace(actor_id="service:test"),
    )


def test_group_staging_reads_cas_before_stage_and_captures_authority_last():
    """One captured fence immediately precedes the exact three-candidate activation."""

    from apps.data_center.domain.control_plane import PublicationState

    bundle, bindings = _direct_current_market_staging_bundle()
    result = _run_direct_current_market_staging(bundle, bindings)

    assert bundle.bundle_events[:3] == ["current_pointer"] * 3
    assert bundle.bundle_events[3:6] == [
        "stage:equity.quote.snapshot",
        "stage:equity.price.bar",
        "stage:equity.valuation.fact",
    ]
    assert bundle.bundle_events[-3:] == [
        "audit_writer",
        "authority_capture",
        "activation",
    ]
    assert len(bundle.activation_requests) == 1
    candidates = bundle.activation_requests[0].candidates
    assert len(candidates) == 3
    assert {item.dataset_key for item in candidates} == {
        "equity.quote.snapshot",
        "equity.price.bar",
        "equity.valuation.fact",
    }
    assert all(item.expected_current_publication_id is None for item in candidates)
    assert all(item.expected_current_publication_hash is None for item in candidates)
    assert result.published_count == 3
    assert result.run_id == "00000000-0000-4000-8000-000000000001"
    assert len(result.publications) == 3
    assert all(item.state is PublicationState.PUBLISHED for item in result.publications)
    assert {item.publication_id for item in result.publications} == {
        item.candidate_publication_id for item in candidates
    }


@pytest.fixture(autouse=True)
def _patch_current_authority(monkeypatch):
    """Bind task-path tests to one current server-issued authority."""

    from types import SimpleNamespace

    from apps.data_center.application import tasks
    from core.integration.task_monitor_runtime import CurrentTaskAttemptIdentity

    context = SimpleNamespace(
        authority_source_id="config-center",
        actor_id="service:market-refresh",
        user_id=1,
        tenant_id="tenant:production",
        owner_id="owner:production",
        is_authenticated=True,
        is_staff=True,
        role="system_owner",
        authority_content_hash="b" * 64,
        authority_valid_until=datetime.now(UTC) + timedelta(hours=2),
    )
    monkeypatch.setattr(
        tasks.audit_integration,
        "preflight_data_reliability_audit_runtime",
        lambda **_: context,
    )
    monkeypatch.setattr(
        tasks,
        "sync_active_a_share_universe",
        lambda: _universe_report(tasks.list_active_stock_codes_for_backfill()),
    )
    monkeypatch.setattr(
        tasks,
        "get_current_task_attempt_identity",
        lambda: CurrentTaskAttemptIdentity(
            task_id="test-full-market-task",
            attempt_id="test-full-market-attempt",
        ),
    )
    monkeypatch.setattr(
        tasks,
        "build_production_current_market_publication_bundle",
        lambda *, using="default", created_by="ops.current_publication_rebuild": (
            _fake_market_publication_bundle(
                tasks.make_core_current_publication_rebuild_use_case(
                    created_by=created_by,
                    dataset_keys=(
                        "equity.price.bar",
                        "equity.quote.snapshot",
                        "equity.valuation.fact",
                    ),
                )
            )
        ),
    )
    monkeypatch.setattr(
        tasks,
        "build_target_date_a_share_universe_scope",
        lambda target_date: _unknown_listing_date_scope(
            target_date,
            tasks.list_active_stock_codes_for_backfill(),
        ),
    )
    return context


def run(*, quote_count=None, publish_error=False, empty=False):
    published = []

    def publish(codes):
        if publish_error:
            raise ValueError("missing policy evidence")
        published.append(codes)
        return len(codes) * 2

    ports = MarketPublicationRefreshPorts(
        list_codes=lambda: [] if empty else ["000001.SZ", "000002.SZ", "000003.SZ"],
        sync_quotes=lambda codes: len(codes) if quote_count is None else quote_count,
        sync_valuations=lambda codes, day: len(codes),
        publish=publish,
    )
    return (
        refresh_market_publications(ports=ports, as_of_date=date(2026, 9, 18), batch_size=2),
        published,
    )


def test_complete_market_refresh_publishes_full_scope_once():
    result, published = run()
    assert result["outcome"] == "success"
    assert result["requested"] == result["succeeded"] == 5
    assert result["failed"] == 0
    assert result["stored"] == result["published_members"] == 6
    assert published == [["000001.SZ", "000002.SZ", "000003.SZ"]]


def test_partial_market_refresh_keeps_previous_publication():
    result, published = run(quote_count=0)
    assert result["outcome"] == "partial"
    assert result["requested"] == result["succeeded"] + result["failed"]
    assert result["published_members"] == 0
    assert published == []


def test_terminal_authority_block_stops_remaining_batches() -> None:
    """A task-wide authority loss is recorded once without replaying every batch."""

    quote_calls: list[list[str]] = []

    def blocked_quote(codes: list[str]) -> int:
        quote_calls.append(codes)
        raise MarketPublicationRefreshBlocked(
            "Audit authority is temporarily unavailable",
            code="system_audit_authority_unavailable",
        )

    ports = MarketPublicationRefreshPorts(
        list_codes=lambda: ["000001.SZ", "000002.SZ", "000003.SZ"],
        sync_quotes=blocked_quote,
        sync_valuations=lambda _codes, _day: pytest.fail("valuation batch executed"),
        publish=lambda _codes: pytest.fail("publication executed"),
    )

    result = refresh_market_publications(
        ports=ports,
        as_of_date=date(2026, 9, 18),
        batch_size=2,
    )

    assert quote_calls == [["000001.SZ", "000002.SZ"]]
    assert result["requested"] == 5
    assert result["succeeded"] == 0
    assert result["failed"] == 5
    assert result["errors"] == ["system_audit_authority_unavailable"]
    assert result["phase_results"] == [
        {"phase": "quote", "requested": 2, "succeeded": 0, "failed": 2, "stored": 0},
        {"phase": "valuation", "requested": 2, "succeeded": 0, "failed": 2, "stored": 0},
        {"phase": "publication", "requested": 1, "succeeded": 0, "failed": 1, "stored": 0},
    ]


def test_publication_authority_block_returns_normalized_partial_result() -> None:
    """A final publication authority denial preserves fact counts and blocks current state."""

    def blocked_publish(_codes: list[str]) -> int:
        raise MarketPublicationRefreshBlocked(
            "Audit authority is temporarily unavailable",
            code="system_audit_authority_unavailable",
        )

    result = refresh_market_publications(
        ports=MarketPublicationRefreshPorts(
            list_codes=lambda: ["000001.SZ", "000002.SZ", "000003.SZ"],
            sync_quotes=lambda codes: len(codes),
            sync_valuations=lambda codes, _day: len(codes),
            publish=blocked_publish,
        ),
        as_of_date=date(2026, 9, 18),
        batch_size=2,
    )

    assert result["outcome"] == "partial"
    assert result["phase"] == "publication"
    assert result["requested"] == 5
    assert result["succeeded"] == 4
    assert result["failed"] == 1
    assert result["stored"] == 6
    assert result["error_code"] == "system_audit_authority_unavailable"
    assert result["blocked_reason"] == "system_audit_authority_unavailable"
    assert result["publication_updated"] is False
    assert result["must_not_use_for_decision"] is True


@pytest.mark.parametrize(
    ("stored", "expected_outcome"),
    [(6, "partial"), (0, "blocked")],
)
def test_late_authority_latch_preserves_completed_fact_writes(
    stored: int,
    expected_outcome: str,
) -> None:
    """A late authority failure cannot erase completed write evidence."""

    from apps.data_center.application.full_market_task_support import (
        apply_full_market_authority_block,
    )

    result = apply_full_market_authority_block(
        {
            "outcome": "failed",
            "success": False,
            "requested": 5,
            "succeeded": 4,
            "failed": 1,
            "stored": stored,
            "publication_updated": False,
            "published_members": 0,
        },
        reason_code="system_audit_authority_unavailable",
    )

    assert result["outcome"] == expected_outcome
    assert result["requested"] == 5
    assert result["succeeded"] == 4
    assert result["failed"] == 1
    assert result["stored"] == stored
    assert result["error_code"] == "system_audit_authority_unavailable"
    assert result["blocked_reason"] == "system_audit_authority_unavailable"
    assert result["must_not_use_for_decision"] is True


@pytest.mark.parametrize(
    ("reason_code", "expected_code"),
    [
        ("authority_unavailable", "system_audit_authority_unavailable"),
        ("system_audit_authority_unavailable", "system_audit_authority_unavailable"),
    ],
)
def test_publication_composition_maps_audit_authority_error_to_data_center_block(
    monkeypatch,
    reason_code: str,
    expected_code: str,
) -> None:
    """The Data Center composition root exposes a stable domain-facing exception."""

    from apps.audit.application.system_audit_composition import SystemAuditCompositionUnavailable
    from apps.data_center import publication_rebuild_composition

    monkeypatch.setattr(
        publication_rebuild_composition,
        "preflight_data_reliability_audit_runtime",
        lambda **_: (_ for _ in ()).throw(
            SystemAuditCompositionUnavailable(
                "authority unavailable",
                reason_code=reason_code,
            )
        ),
    )
    coordinator = publication_rebuild_composition.build_current_publication_rebuild(
        dataset_keys=("equity.quote.snapshot",)
    )

    with pytest.raises(MarketPublicationRefreshBlocked) as caught:
        coordinator.execute(
            asset_codes=["000001.SZ"],
            published_at=datetime(2026, 9, 18, 8, tzinfo=UTC),
        )

    assert caught.value.code == expected_code


def test_authority_revalidation_retries_transient_unavailability(
    monkeypatch,
    _patch_current_authority,
) -> None:
    """One lock-contention read cannot poison the remainder of a long refresh."""

    from apps.audit.application.system_audit_composition import SystemAuditCompositionUnavailable
    from apps.data_center.application import tasks
    from apps.data_center.application.data02_task_authority import (
        revalidate_data02_task_authority,
    )

    calls = 0

    def transient_then_current(**_):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise SystemAuditCompositionUnavailable(
                "lock contention",
                reason_code="authority_unavailable",
            )
        return _patch_current_authority

    waits: list[float] = []
    monkeypatch.setattr(
        tasks.audit_integration,
        "preflight_data_reliability_audit_runtime",
        transient_then_current,
    )
    observed_at = datetime.now(UTC)

    result = revalidate_data02_task_authority(
        _patch_current_authority,
        as_of=observed_at,
        max_attempts=2,
        retry_delay_seconds=0.25,
        sleeper=waits.append,
        clock=lambda: observed_at + timedelta(seconds=1),
    )

    assert result.current is True
    assert result.reason_code == "authority_current"
    assert result.attempts == 2
    assert waits == [0.25]


def test_initial_authority_preflight_retries_only_transient_unavailability(
    monkeypatch,
    _patch_current_authority,
) -> None:
    """A short authority writer lock cannot abort a zero-write task preflight."""

    from apps.audit.application.system_audit_composition import SystemAuditCompositionUnavailable
    from apps.data_center.application import tasks
    from apps.data_center.application.data02_task_authority import (
        preflight_data02_task_authority,
    )

    observed_at = datetime.now(UTC)
    fresh_as_of = observed_at + timedelta(seconds=2)
    calls: list[datetime] = []

    def transient_then_current(*, as_of: datetime, **_: object) -> object:
        calls.append(as_of)
        if len(calls) == 1:
            raise SystemAuditCompositionUnavailable(
                "authority writer holds the canonical tables",
                reason_code="authority_unavailable",
            )
        return _patch_current_authority

    waits: list[float] = []
    monkeypatch.setattr(
        tasks.audit_integration,
        "preflight_data_reliability_audit_runtime",
        transient_then_current,
    )

    authority, failure = preflight_data02_task_authority(
        as_of=observed_at,
        minimum_window=timedelta(minutes=30),
        max_attempts=2,
        retry_delay_seconds=0.25,
        sleeper=waits.append,
        clock=lambda: fresh_as_of,
    )

    assert authority is _patch_current_authority
    assert failure is None
    assert calls == [observed_at, fresh_as_of]
    assert waits == [0.25]


def test_initial_authority_preflight_does_not_retry_nontransient_failure(
    monkeypatch,
) -> None:
    """Missing runtime wiring remains an immediate fail-closed denial."""

    from apps.audit.application.system_audit_composition import SystemAuditCompositionUnavailable
    from apps.data_center.application import tasks
    from apps.data_center.application.data02_task_authority import (
        preflight_data02_task_authority,
    )

    calls = 0

    def not_wired(**_: object) -> object:
        nonlocal calls
        calls += 1
        raise SystemAuditCompositionUnavailable(
            "authority bundle is absent",
            reason_code="authority_not_wired",
        )

    monkeypatch.setattr(
        tasks.audit_integration,
        "preflight_data_reliability_audit_runtime",
        not_wired,
    )

    authority, failure = preflight_data02_task_authority(
        as_of=datetime.now(UTC),
        minimum_window=timedelta(minutes=30),
        sleeper=lambda _: pytest.fail("nontransient authority failure was retried"),
    )

    assert authority is None
    assert failure is not None
    assert failure["blocked_reason"] == "system_audit_authority_not_wired"
    assert failure["stored"] == 0
    assert calls == 1


def test_initial_authority_preflight_exhaustion_stays_zero_write(
    monkeypatch,
) -> None:
    """Bounded transient retries exhaust into one normalized zero-write result."""

    from apps.audit.application.system_audit_composition import SystemAuditCompositionUnavailable
    from apps.data_center.application import tasks
    from apps.data_center.application.data02_task_authority import (
        preflight_data02_task_authority,
    )

    calls = 0

    def unavailable(**_: object) -> object:
        nonlocal calls
        calls += 1
        raise SystemAuditCompositionUnavailable(
            "authority tables remain contended",
            reason_code="authority_unavailable",
        )

    waits: list[float] = []
    observed_at = datetime.now(UTC)
    monkeypatch.setattr(
        tasks.audit_integration,
        "preflight_data_reliability_audit_runtime",
        unavailable,
    )

    authority, failure = preflight_data02_task_authority(
        as_of=observed_at,
        minimum_window=timedelta(minutes=30),
        sleeper=waits.append,
        clock=lambda: observed_at + timedelta(seconds=sum(waits)),
    )

    assert authority is None
    assert failure is not None
    assert failure["outcome"] == "blocked"
    assert failure["blocked_reason"] == "system_audit_authority_unavailable"
    assert failure["requested"] == 0
    assert failure["succeeded"] == 0
    assert failure["failed"] == 0
    assert failure["stored"] == 0
    assert calls == 6
    assert waits == [1.0, 2.0, 3.0, 4.0, 5.0]


def test_initial_authority_preflight_rejects_identity_drift_after_transient_retry(
    monkeypatch,
    _patch_current_authority,
) -> None:
    """A recovered read still fails closed when its actor identity changed."""

    from apps.audit.application.system_audit_composition import SystemAuditCompositionUnavailable
    from apps.data_center.application import tasks
    from apps.data_center.application.data02_task_authority import (
        preflight_data02_task_authority,
    )

    calls = 0
    changed = SimpleNamespace(
        **{**vars(_patch_current_authority), "actor_id": "service:other-refresh"}
    )

    def transient_then_changed(**_: object) -> object:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise SystemAuditCompositionUnavailable(
                "short writer lock",
                reason_code="authority_unavailable",
            )
        return changed

    waits: list[float] = []
    monkeypatch.setattr(
        tasks.audit_integration,
        "preflight_data_reliability_audit_runtime",
        transient_then_changed,
    )

    authority, failure = preflight_data02_task_authority(
        as_of=datetime.now(UTC),
        minimum_window=timedelta(minutes=30),
        expected_actor=_patch_current_authority.actor_id,
        sleeper=waits.append,
    )

    assert authority is None
    assert failure is not None
    assert failure["blocked_reason"] == "operator_actor_mismatch"
    assert calls == 2
    assert waits == [1.0]


def test_initial_authority_preflight_rejects_exact_expiry_window_boundary(
    monkeypatch,
    _patch_current_authority,
) -> None:
    """Authority must remain valid beyond the full task window, not merely to its endpoint."""

    from apps.data_center.application import tasks
    from apps.data_center.application.data02_task_authority import (
        preflight_data02_task_authority,
    )

    observed_at = datetime.now(UTC)
    minimum_window = timedelta(minutes=30)
    boundary = SimpleNamespace(
        **{
            **vars(_patch_current_authority),
            "authority_valid_until": observed_at + minimum_window,
        }
    )
    monkeypatch.setattr(
        tasks.audit_integration,
        "preflight_data_reliability_audit_runtime",
        lambda **_: boundary,
    )

    authority, failure = preflight_data02_task_authority(
        as_of=observed_at,
        minimum_window=minimum_window,
        sleeper=lambda _: pytest.fail("expiry boundary was retried"),
    )

    assert authority is None
    assert failure is not None
    assert failure["blocked_reason"] == "authority_window_too_short"


def test_initial_authority_preflight_rejects_unbounded_attempt_override(
    _patch_current_authority,
) -> None:
    """Callers cannot expand the governed initial authority retry window."""

    from apps.data_center.application.data02_task_authority import (
        preflight_data02_task_authority,
    )

    with pytest.raises(ValueError, match="max_attempts must be between 1 and 6"):
        preflight_data02_task_authority(
            as_of=datetime.now(UTC),
            minimum_window=timedelta(minutes=30),
            max_attempts=7,
        )


@pytest.mark.parametrize("retry_delay_seconds", [float("nan"), float("inf")])
def test_initial_authority_preflight_rejects_nonfinite_retry_delay(
    _patch_current_authority,
    retry_delay_seconds: float,
) -> None:
    """A non-finite delay cannot escape the bounded retry policy."""

    from apps.data_center.application.data02_task_authority import (
        preflight_data02_task_authority,
    )

    with pytest.raises(ValueError, match="retry_delay_seconds must be a non-negative number"):
        preflight_data02_task_authority(
            as_of=datetime.now(UTC),
            minimum_window=timedelta(minutes=30),
            retry_delay_seconds=retry_delay_seconds,
        )


def test_authority_revalidation_outlasts_back_to_back_writer_transactions(
    monkeypatch,
    _patch_current_authority,
) -> None:
    """Bounded backoff crosses repeated short writer locks without weakening identity checks."""

    from apps.audit.application.system_audit_composition import SystemAuditCompositionUnavailable
    from apps.data_center.application import tasks
    from apps.data_center.application.data02_task_authority import (
        revalidate_data02_task_authority,
    )

    calls = 0

    def contended_then_current(**_):
        nonlocal calls
        calls += 1
        if calls <= 4:
            raise SystemAuditCompositionUnavailable(
                "back-to-back writer lock",
                reason_code="authority_unavailable",
            )
        return _patch_current_authority

    waits: list[float] = []
    observed_at = datetime.now(UTC)
    monkeypatch.setattr(
        tasks.audit_integration,
        "preflight_data_reliability_audit_runtime",
        contended_then_current,
    )

    result = revalidate_data02_task_authority(
        _patch_current_authority,
        as_of=observed_at,
        max_attempts=6,
        retry_delay_seconds=1.0,
        sleeper=waits.append,
        clock=lambda: observed_at + timedelta(seconds=sum(waits)),
    )

    assert result.current is True
    assert result.reason_code == "authority_current"
    assert result.attempts == 5
    assert waits == [1.0, 2.0, 3.0, 4.0]


def test_authority_revalidation_rejects_unbounded_attempt_override(
    _patch_current_authority,
) -> None:
    """Callers cannot expand the governed authority retry window."""

    from apps.data_center.application.data02_task_authority import (
        revalidate_data02_task_authority,
    )

    with pytest.raises(ValueError, match="max_attempts must be between 1 and 6"):
        revalidate_data02_task_authority(
            _patch_current_authority,
            as_of=datetime.now(UTC),
            max_attempts=7,
        )


def test_authority_revalidation_exhaustion_stays_blocked_and_zero_write(
    monkeypatch,
    _patch_current_authority,
) -> None:
    """Six transient read failures exhaust the budget without fabricating progress."""

    from apps.audit.application.system_audit_composition import SystemAuditCompositionUnavailable
    from apps.data_center.application import tasks
    from apps.data_center.application.data02_task_authority import (
        data02_authority_failure,
        revalidate_data02_task_authority,
    )

    calls = 0

    def unavailable(**_):
        nonlocal calls
        calls += 1
        raise SystemAuditCompositionUnavailable(
            "authority tables remain contended",
            reason_code="authority_unavailable",
        )

    waits: list[float] = []
    observed_at = datetime.now(UTC)
    monkeypatch.setattr(
        tasks.audit_integration,
        "preflight_data_reliability_audit_runtime",
        unavailable,
    )

    result = revalidate_data02_task_authority(
        _patch_current_authority,
        as_of=observed_at,
        sleeper=waits.append,
        clock=lambda: observed_at + timedelta(seconds=sum(waits)),
    )
    failure = data02_authority_failure(result.reason_code)

    assert result.current is False
    assert result.reason_code == "system_audit_authority_unavailable"
    assert result.attempts == 6
    assert calls == 6
    assert waits == [1.0, 2.0, 3.0, 4.0, 5.0]
    assert failure["outcome"] == "blocked"
    assert failure["requested"] == 0
    assert failure["succeeded"] == 0
    assert failure["failed"] == 0
    assert failure["stored"] == 0


def test_authority_revalidation_does_not_retry_identity_drift(
    monkeypatch,
    _patch_current_authority,
) -> None:
    """A real actor change remains fail-closed without transient retries."""

    from types import SimpleNamespace

    from apps.data_center.application import tasks
    from apps.data_center.application.data02_task_authority import (
        revalidate_data02_task_authority,
    )

    changed = SimpleNamespace(
        **{
            **vars(_patch_current_authority),
            "actor_id": "service:other-refresh",
        }
    )
    calls = 0

    def changed_context(**_):
        nonlocal calls
        calls += 1
        return changed

    monkeypatch.setattr(
        tasks.audit_integration,
        "preflight_data_reliability_audit_runtime",
        changed_context,
    )

    result = revalidate_data02_task_authority(
        _patch_current_authority,
        as_of=datetime.now(UTC),
        max_attempts=3,
        sleeper=lambda _: pytest.fail("identity drift retried"),
    )

    assert result.current is False
    assert result.reason_code == "operator_actor_mismatch"
    assert result.attempts == 1
    assert calls == 1


def test_authority_revalidation_rejects_starting_grant_at_exact_window_boundary(
    monkeypatch,
    _patch_current_authority,
) -> None:
    """The starting grant must outlive, rather than equal, the finalization window."""

    from apps.data_center.application import tasks
    from apps.data_center.application.data02_task_authority import (
        revalidate_data02_task_authority,
    )

    observed_at = datetime.now(UTC)
    minimum_window = timedelta(minutes=5)
    boundary = SimpleNamespace(
        **{
            **vars(_patch_current_authority),
            "authority_valid_until": observed_at + minimum_window,
        }
    )
    monkeypatch.setattr(
        tasks.audit_integration,
        "preflight_data_reliability_audit_runtime",
        lambda **_: boundary,
    )

    result = revalidate_data02_task_authority(
        boundary,
        as_of=observed_at,
        minimum_window=minimum_window,
        sleeper=lambda _: pytest.fail("expiry boundary was retried"),
    )

    assert result.current is False
    assert result.reason_code == "authority_window_too_short"
    assert result.attempts == 1


def test_provider_identity_gap_is_a_partial_business_result() -> None:
    def reject_valuation(_codes, _day):
        from apps.data_center.application.batch_identity import ProviderAssetIdentityError

        raise ProviderAssetIdentityError("valuation provider asset identities mismatch")

    ports = MarketPublicationRefreshPorts(
        list_codes=lambda: ["000001.SZ", "000016.SZ"],
        sync_quotes=lambda codes: len(codes),
        sync_valuations=reject_valuation,
        publish=lambda _: pytest.fail("incomplete valuation scope reached publication"),
    )

    result = refresh_market_publications(
        ports=ports,
        as_of_date=date(2026, 9, 23),
        batch_size=2,
    )

    assert result["outcome"] == "partial"
    assert result["success"] is False
    assert result["stored"] == 2
    assert result["published_members"] == 0
    assert result["errors"] == [
        "PROVIDER_ASSET_IDENTITY_MISMATCH",
        "market_publication_skipped_incomplete_refresh",
    ]


def test_publication_evidence_failure_is_not_success():
    result, published = run(publish_error=True)
    assert result["outcome"] == "partial"
    assert result["failed"] == 1
    assert result["error_code"] == "MARKET_PUBLICATION_VALIDATION_FAILED"
    assert result["blocked_reason"] == "MARKET_PUBLICATION_VALIDATION_FAILED"
    assert result["errors"] == ["MARKET_PUBLICATION_VALIDATION_FAILED"]
    assert published == []


def test_publication_failure_preserves_phase_and_actual_write_counts():
    result, _ = run(publish_error=True)
    assert result["phase"] == "publication"
    assert result["stored_count_unit"] == "fact_row"
    assert result["target_trade_date"] == "2026-09-18"
    assert result["phase_results"] == [
        {"phase": "quote", "requested": 2, "succeeded": 2, "failed": 0, "stored": 3},
        {"phase": "valuation", "requested": 2, "succeeded": 2, "failed": 0, "stored": 3},
        {"phase": "publication", "requested": 1, "succeeded": 0, "failed": 1, "stored": 0},
    ]


def test_failed_quote_phase_is_not_hidden_by_skipped_publication():
    result, _ = run(quote_count=0)
    assert result["phase"] == "quote"
    assert result["phase_results"][0] == {
        "phase": "quote",
        "requested": 2,
        "succeeded": 0,
        "failed": 2,
        "stored": 0,
    }
    assert result["phase_results"][-1]["succeeded"] == 0


def test_empty_scope_is_not_success():
    result, published = run(empty=True)
    assert result["outcome"] == "failed"
    assert result["stored"] == 0
    assert published == []


@pytest.mark.parametrize("count", [True, -1, 0, 1.5, "3", None])
def test_invalid_publication_count_never_reports_success(count):
    ports = MarketPublicationRefreshPorts(
        list_codes=lambda: ["000001.SZ"],
        sync_quotes=lambda codes: len(codes),
        sync_valuations=lambda codes, day: len(codes),
        publish=lambda codes: count,
    )
    result = refresh_market_publications(ports=ports, as_of_date=date(2026, 9, 24))
    assert result["outcome"] == "partial"
    assert result["publication_updated"] is False
    assert result["published_members"] == 0
    assert result["failed"] == 1
    assert result["error_code"] == "MARKET_PUBLICATION_COUNT_INVALID"


@pytest.mark.parametrize("batch_size", [True, 0, 201, "10"])
def test_market_refresh_rejects_invalid_input_before_io(batch_size):
    ports = MarketPublicationRefreshPorts(
        list_codes=lambda: pytest.fail("unexpected IO"),
        sync_quotes=lambda _: 0,
        sync_valuations=lambda *_: 0,
        publish=lambda _: 0,
    )
    with pytest.raises(ValueError):
        refresh_market_publications(
            ports=ports, as_of_date=date(2026, 9, 18), batch_size=batch_size
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"batch_size": True},
        {"batch_size": 0},
        {"source": "bad"},
        {"quote_source": "bad"},
        {"valuation_source": "bad"},
    ],
)
def test_task_invalid_input_returns_failure_without_provider_access(monkeypatch, kwargs):
    from apps.data_center.application import tasks

    monkeypatch.setattr(
        tasks, "get_active_provider_id_by_source", lambda _: pytest.fail("provider IO")
    )
    result = tasks.refresh_full_market_publications_task.run(**kwargs)
    assert result["outcome"] == "failed"
    assert result["stored"] == 0


def test_task_attempt_identity_failure_precedes_authority_progress_and_provider_io(monkeypatch):
    """An absent monitor attempt blocks before preflight, progress, or provider access."""

    from apps.data_center.application import tasks
    from core.integration.task_monitor_runtime import CurrentTaskAttemptIdentityUnavailable

    def unexpected(*_args, **_kwargs):
        pytest.fail("task attempt failure must precede every other collaborator")

    monkeypatch.setattr(
        tasks,
        "get_current_task_attempt_identity",
        lambda: (_ for _ in ()).throw(CurrentTaskAttemptIdentityUnavailable()),
    )
    monkeypatch.setattr(tasks, "_preflight_data02_task_authority", unexpected)
    monkeypatch.setattr(tasks, "get_active_provider_id_by_source", unexpected)
    monkeypatch.setattr(tasks, "record_current_task_progress", unexpected)
    monkeypatch.setattr(tasks, "sync_active_a_share_universe", unexpected)

    result = tasks.refresh_full_market_publications_task.run()

    assert result["outcome"] == "blocked"
    assert result["phase"] == "task_attempt_identity"
    assert result["requested"] == result["succeeded"] == result["failed"] == result["stored"] == 0
    assert result["error_code"] == "CURRENT_TASK_ATTEMPT_IDENTITY_UNAVAILABLE"
    assert result["publication_updated"] is False
    assert result["must_not_use_for_decision"] is True


def test_task_calendar_unavailable_is_blocked(monkeypatch):
    from types import SimpleNamespace

    from apps.data_center.application import tasks

    monkeypatch.setattr(tasks, "get_active_provider_id_by_source", lambda _: 3)
    monkeypatch.setattr(tasks, "latest_closed_cn_market_session", lambda _: None)
    monkeypatch.setattr(tasks, "make_backfill_sync_quote_use_case", lambda: SimpleNamespace())
    monkeypatch.setattr(
        tasks, "make_backfill_sync_current_valuation_batch_use_case", lambda: SimpleNamespace()
    )
    monkeypatch.setattr(
        tasks, "make_core_current_publication_rebuild_use_case", lambda **_: SimpleNamespace()
    )
    result = tasks.refresh_full_market_publications_task.run()
    assert result["outcome"] == "blocked"
    assert result["stored"] == 0


@pytest.mark.parametrize(
    ("activation_failure", "expected_code"),
    [
        ("validation", "CURRENT_PUBLICATION_GROUP_ACTIVATION_FAILED"),
        ("composition", "CURRENT_PUBLICATION_GROUP_ACTIVATION_FAILED"),
        ("preview_database", "CURRENT_PUBLICATION_PREVIEW_FAILED"),
        ("pointer_database", "CURRENT_PUBLICATION_CURRENT_POINTER_UNAVAILABLE"),
        ("price_stage", "CURRENT_PUBLICATION_STAGING_FAILED"),
        ("price_stage_database", "CURRENT_PUBLICATION_STAGING_FAILED"),
        ("audit_writer", "CURRENT_PUBLICATION_AUDIT_UNAVAILABLE"),
        ("audit_writer_database", "CURRENT_PUBLICATION_AUDIT_UNAVAILABLE"),
        ("authority_capture_database", "CURRENT_PUBLICATION_AUTHORITY_CAPTURE_FAILED"),
        ("audit_outbox", "CURRENT_PUBLICATION_AUDIT_WRITE_FAILED"),
        ("group_activation_database", "CURRENT_PUBLICATION_GROUP_ACTIVATION_FAILED"),
    ],
)
def test_task_maps_known_publication_failures_to_partial_business_outcome(
    monkeypatch,
    activation_failure: str,
    expected_code: str,
) -> None:
    """Known stage/group errors do not escape as Celery failures after fact writes."""

    from django.db import DatabaseError

    from apps.audit.application.system_audit_composition import SystemAuditCompositionUnavailable
    from apps.data_center.application import market_publication_refresh, public, tasks
    from core.exceptions import DataValidationError
    from core.integration import data_center_audit as audit_integration

    provider_ids = {"tushare": 3, "akshare": 7}
    active_codes = ["000001.SZ", "600000.SH"]
    target_date = date(2026, 9, 18)
    observed = datetime(2026, 9, 18, 7, tzinfo=UTC)

    monkeypatch.setattr(tasks, "get_active_provider_id_by_source", provider_ids.get)
    monkeypatch.setattr(tasks, "latest_closed_cn_market_session", lambda _: target_date)
    monkeypatch.setattr(tasks, "list_active_stock_codes_for_backfill", lambda: active_codes)
    monkeypatch.setattr(
        tasks,
        "make_backfill_sync_quote_use_case",
        lambda: _prefetched_quote_sync(
            lambda *_args, **_kwargs: SimpleNamespace(
                stored_count=len(active_codes),
                stored_asset_codes=tuple(active_codes),
            )
        ),
    )
    monkeypatch.setattr(
        tasks,
        "make_backfill_sync_current_valuation_batch_use_case",
        lambda: _audited_valuation_sync(
            lambda **_kwargs: SimpleNamespace(
                stored_count=len(active_codes),
                succeeded_asset_codes=tuple(active_codes),
                returned_asset_codes=tuple(active_codes),
            )
        ),
    )
    datasets = [
        SimpleNamespace(
            dataset_key=key,
            ready=True,
            requested_asset_count=len(active_codes),
            covered_asset_count=len(active_codes),
            member_count=len(active_codes),
            missing_asset_codes=(),
            unexpected_asset_codes=(),
            oldest_observed_at=observed,
            newest_observed_at=observed,
        )
        for key in (
            "equity.quote.snapshot",
            "equity.price.bar",
            "equity.valuation.fact",
        )
    ]

    def fail_activation(**_):
        if activation_failure == "validation":
            raise DataValidationError("activation denied", code="PUBLICATION_ACTIVATION_INVALID")
        raise SystemAuditCompositionUnavailable(
            "activation runtime unavailable",
            reason_code="activation_runtime_unavailable",
        )

    monkeypatch.setattr(
        tasks,
        "make_core_current_publication_rebuild_use_case",
        lambda **_: SimpleNamespace(
            preview=lambda **_: SimpleNamespace(datasets=datasets),
            execute=fail_activation,
        ),
    )
    publication_bundles = []
    original_bundle_factory = tasks.build_production_current_market_publication_bundle

    def capture_publication_bundle(**kwargs):
        bundle = original_bundle_factory(**kwargs)
        if activation_failure in {"price_stage", "price_stage_database"}:

            def fail_price_stage(_command):
                bundle.bundle_events.append("stage:equity.price.bar")
                if activation_failure == "price_stage_database":
                    raise DatabaseError("candidate staging repository unavailable")
                raise DataValidationError("price candidate staging failed")

            bundle.price_staging.execute = fail_price_stage
        elif activation_failure == "preview_database":

            def fail_preview(**_kwargs):
                raise DatabaseError("publication preview database unavailable")

            bundle.previewer.preview = fail_preview
        elif activation_failure == "pointer_database":

            def fail_pointer(*_args):
                bundle.bundle_events.append("current_pointer")
                raise DatabaseError("current pointer database unavailable")

            bundle.current_pointer_reader = fail_pointer
        elif activation_failure in {"audit_writer", "audit_writer_database"}:

            def fail_audit_writer():
                bundle.bundle_events.append("audit_writer")
                if activation_failure == "audit_writer_database":
                    raise DatabaseError("publication writer database unavailable")
                raise SystemAuditCompositionUnavailable(
                    "publication audit writer unavailable",
                    reason_code="publication_writer_unavailable",
                )

            bundle.audit_writer_factory = fail_audit_writer
        elif activation_failure == "authority_capture_database":

            def fail_authority_capture(**_kwargs):
                bundle.bundle_events.append("authority_capture")
                raise DatabaseError("Account authority capture database unavailable")

            bundle.authority_capture = fail_authority_capture
        elif activation_failure == "audit_outbox":

            def fail_audit_outbox(*_args, **_kwargs):
                bundle.bundle_events.append("activation")
                raise audit_integration.SystemAuditEventOutboxUnavailable(
                    "publication event outbox unavailable"
                )

            bundle.activate_group.execute = fail_audit_outbox
        elif activation_failure == "group_activation_database":

            def fail_group_activation(*_args, **_kwargs):
                bundle.bundle_events.append("activation")
                raise DatabaseError("publication activation database unavailable")

            bundle.activate_group.execute = fail_group_activation
        publication_bundles.append(bundle)
        return bundle

    monkeypatch.setattr(
        tasks,
        "build_production_current_market_publication_bundle",
        capture_publication_bundle,
    )
    monkeypatch.setattr(public, "get_model_market_data_port", lambda: object())
    monkeypatch.setattr(
        market_publication_refresh,
        "refresh_market_price_inputs",
        lambda *_args: _market_price_result_with_member_binding(),
    )

    result = tasks.refresh_full_market_publications_task.run(batch_size=2)

    assert result["outcome"] == "partial"
    assert result["phase"] == "publication"
    assert result["error_code"] == expected_code
    assert result["blocked_reason"] == expected_code
    assert result["publication_updated"] is False
    assert result["requested"] == len(active_codes)
    assert result["succeeded"] == len(active_codes)
    assert result["failed"] == 0
    assert result["stored"] == len(active_codes) * 2
    assert result["operation_requested"] == 3
    assert result["operation_succeeded"] == 2
    assert result["operation_failed"] == 1
    assert result["must_not_use_for_decision"] is True
    assert len(publication_bundles) == 1
    bundle_events = publication_bundles[0].bundle_events
    if activation_failure == "preview_database":
        assert "current_pointer" not in bundle_events
        assert "stage:equity.quote.snapshot" not in bundle_events
        assert "activation" not in bundle_events
    elif activation_failure == "pointer_database":
        assert "current_pointer" in bundle_events
        assert "stage:equity.quote.snapshot" not in bundle_events
        assert "authority_capture" not in bundle_events
        assert "activation" not in bundle_events
    elif activation_failure in {"price_stage", "price_stage_database"}:
        assert "authority_capture" not in bundle_events
        assert "activation" not in bundle_events
        assert "stage:equity.quote.snapshot" in bundle_events
        assert "stage:equity.price.bar" in bundle_events
    elif activation_failure in {"audit_writer", "audit_writer_database"}:
        assert "audit_writer" in bundle_events
        assert "authority_capture" not in bundle_events
        assert "activation" not in bundle_events
    elif activation_failure == "authority_capture_database":
        assert bundle_events.index("audit_writer") < bundle_events.index("authority_capture")
        assert "activation" not in bundle_events
    elif activation_failure in {"audit_outbox", "group_activation_database"}:
        assert bundle_events.index("audit_writer") < bundle_events.index("authority_capture")
        assert bundle_events.index("authority_capture") < bundle_events.index("activation")


def test_task_blocks_without_current_authority_before_provider_access(monkeypatch):
    """Scheduled market writes require the canonical current Audit authority."""

    from apps.audit.application.system_audit_composition import SystemAuditCompositionUnavailable
    from apps.data_center.application import data02_task_authority, tasks

    monkeypatch.setattr(data02_task_authority, "sleep", lambda _: None)

    def unavailable(**_):
        raise SystemAuditCompositionUnavailable(
            "unavailable",
            reason_code="authority_unavailable",
        )

    monkeypatch.setattr(
        tasks.audit_integration,
        "preflight_data_reliability_audit_runtime",
        unavailable,
    )
    provider = monkeypatch.setattr(
        tasks,
        "get_active_provider_id_by_source",
        lambda _: pytest.fail("provider IO"),
    )

    result = tasks.refresh_full_market_publications_task.run()

    assert provider is None
    assert result["outcome"] == "blocked"
    assert result["blocked_reason"] == "system_audit_authority_unavailable"
    assert result["stored"] == 0


def test_task_blocks_authority_window_shorter_than_task_budget(
    monkeypatch,
    _patch_current_authority,
):
    """A scheduled refresh cannot outlive the authority used to start it."""

    from apps.data_center.application import tasks

    assert tasks.refresh_full_market_publications_task.time_limit == 5700
    assert tasks.refresh_full_market_publications_task.soft_time_limit == 5400
    _patch_current_authority.authority_valid_until = datetime.now(UTC) + timedelta(seconds=6299)
    monkeypatch.setattr(
        tasks,
        "get_active_provider_id_by_source",
        lambda _: pytest.fail("provider IO"),
    )

    result = tasks.refresh_full_market_publications_task.run()

    assert result["outcome"] == "blocked"
    assert result["blocked_reason"] == "authority_window_too_short"
    assert result["stored"] == 0


def test_full_market_task_mutex_fails_fast_before_refresh(monkeypatch) -> None:
    """Overlapping manual and scheduled invocations stop before refresh side effects."""

    from apps.data_center.application import tasks

    refresh_started = Event()
    release_refresh = Event()
    refresh_calls: list[object] = []
    refresh_calls_lock = Lock()

    def hold_first_refresh(**_kwargs):
        with refresh_calls_lock:
            refresh_calls.append(object())
            call_number = len(refresh_calls)
        if call_number == 1:
            refresh_started.set()
            if not release_refresh.wait(timeout=5):
                raise TimeoutError("first refresh test barrier was not released")
        return {
            "outcome": "success",
            "success": True,
            "requested": 1,
            "succeeded": 1,
            "failed": 0,
            "stored": 2,
        }

    monkeypatch.setattr(tasks, "run_full_market_publication_refresh", hold_first_refresh)
    with ThreadPoolExecutor(max_workers=1) as executor:
        first_run = executor.submit(tasks.refresh_full_market_publications_task.run)
        assert refresh_started.wait(timeout=5)
        try:
            second_result = tasks.refresh_full_market_publications_task.run()
        finally:
            release_refresh.set()
        first_result = first_run.result(timeout=5)

    assert first_result["outcome"] == "success"
    assert second_result["outcome"] == "noop"
    assert second_result["requested"] == 0
    assert second_result["succeeded"] == 0
    assert second_result["failed"] == 0
    assert second_result["stored"] == 0
    assert second_result["error_code"] == "FULL_MARKET_REFRESH_ALREADY_RUNNING"
    assert second_result["noop_reason"] == "full_market_refresh_already_running"
    assert len(refresh_calls) == 1
    assert second_result["published_members"] == 0
    assert second_result["must_not_use_for_decision"] is True


def test_full_market_task_blocks_before_refresh_when_lease_cache_is_unavailable(
    monkeypatch,
) -> None:
    """An unavailable cache cannot silently disable full-market exclusion."""

    from redis.exceptions import RedisError

    from apps.data_center.application import tasks

    class UnavailableCache:
        def add(self, *_args, **_kwargs):
            raise RedisError("cache unavailable")

    monkeypatch.setattr(tasks, "cache", UnavailableCache())
    monkeypatch.setattr(
        tasks,
        "run_full_market_publication_refresh",
        lambda **_: pytest.fail("refresh started without an acquired lease"),
    )

    result = tasks.refresh_full_market_publications_task.run()

    assert result["outcome"] == "blocked"
    assert result["requested"] == 0
    assert result["succeeded"] == 0
    assert result["failed"] == 0
    assert result["stored"] == 0
    assert result["error_code"] == "FULL_MARKET_REFRESH_LEASE_UNAVAILABLE"
    assert result["blocked_reason"] == "full_market_refresh_lease_unavailable"
    assert result["publication_updated"] is False
    assert result["published_members"] == 0
    assert result["must_not_use_for_decision"] is True


def test_full_market_task_releases_lease_after_soft_time_limit(monkeypatch) -> None:
    """A soft time limit still releases this invocation's lease in finally."""

    from apps.data_center.application import full_market_refresh_lease, tasks

    monkeypatch.setattr(
        tasks,
        "run_full_market_publication_refresh",
        lambda **_: (_ for _ in ()).throw(SoftTimeLimitExceeded()),
    )

    with pytest.raises(SoftTimeLimitExceeded):
        tasks.refresh_full_market_publications_task.run()

    assert tasks.cache.get(full_market_refresh_lease.FULL_MARKET_REFRESH_LOCK_KEY) is None

    monkeypatch.setattr(
        tasks,
        "run_full_market_publication_refresh",
        lambda **_: {
            "outcome": "success",
            "success": True,
            "requested": 1,
            "succeeded": 1,
            "failed": 0,
            "stored": 2,
        },
    )
    retry_result = tasks.refresh_full_market_publications_task.run()

    assert retry_result["outcome"] == "success"
    assert tasks.cache.get(full_market_refresh_lease.FULL_MARKET_REFRESH_LOCK_KEY) is None


def test_full_market_task_release_does_not_delete_a_replacement_owner(monkeypatch) -> None:
    """Lease cleanup never deletes a value that no longer belongs to this run."""

    from apps.data_center.application import full_market_refresh_lease, tasks

    replacement_owner = "replacement-full-market-refresh-owner"

    def replace_owner(**_kwargs):
        tasks.cache.set(
            full_market_refresh_lease.FULL_MARKET_REFRESH_LOCK_KEY,
            replacement_owner,
            timeout=60,
        )
        return {
            "outcome": "success",
            "success": True,
            "requested": 1,
            "succeeded": 1,
            "failed": 0,
            "stored": 2,
        }

    monkeypatch.setattr(tasks, "run_full_market_publication_refresh", replace_owner)

    result = tasks.refresh_full_market_publications_task.run()

    assert result["outcome"] == "success"
    assert tasks.cache.get(full_market_refresh_lease.FULL_MARKET_REFRESH_LOCK_KEY) == (
        replacement_owner
    )


def test_full_market_refresh_lease_ttl_is_bounded_by_task_and_authority_budgets() -> None:
    """Lease expiry outlives the hard limit and stays inside the authority window."""

    from apps.data_center.application import full_market_refresh_lease, tasks

    lease = full_market_refresh_lease
    task = tasks.refresh_full_market_publications_task
    assert task.soft_time_limit == lease.FULL_MARKET_REFRESH_SOFT_TIME_LIMIT_SECONDS == 5400
    assert task.time_limit == lease.FULL_MARKET_REFRESH_HARD_TIME_LIMIT_SECONDS == 5700
    assert lease.FULL_MARKET_REFRESH_LOCK_LEASE_TTL_SECONDS == (
        task.time_limit + lease.FULL_MARKET_REFRESH_FINALIZATION_MARGIN_SECONDS
    )
    assert task.time_limit < lease.FULL_MARKET_REFRESH_LOCK_LEASE_TTL_SECONDS
    assert lease.FULL_MARKET_REFRESH_LOCK_LEASE_TTL_SECONDS < (
        lease.FULL_MARKET_REFRESH_AUTHORITY_WINDOW_SECONDS
    )
    assert lease.FULL_MARKET_REFRESH_AUTHORITY_WINDOW_SECONDS == 6300
    assert tasks._FULL_MARKET_AUTHORITY_WINDOW.total_seconds() == (
        lease.FULL_MARKET_REFRESH_AUTHORITY_WINDOW_SECONDS
    )


def test_full_market_refresh_lease_expires_after_a_worker_crash(monkeypatch) -> None:
    """A crashed owner is replaced after the finite lease TTL expires."""

    from apps.data_center.application import full_market_refresh_lease, tasks

    monkeypatch.setattr(full_market_refresh_lease, "FULL_MARKET_REFRESH_LOCK_LEASE_TTL_SECONDS", 1)
    assert full_market_refresh_lease.claim_full_market_refresh_lease(tasks.cache, "crashed-owner")
    sleep(1.1)
    assert full_market_refresh_lease.claim_full_market_refresh_lease(tasks.cache, "next-owner")

    assert full_market_refresh_lease.release_full_market_refresh_lease(tasks.cache, "next-owner")


def test_task_stops_before_provider_when_authority_identity_changes(monkeypatch):
    """A scheduled batch must not continue under a different authority identity."""

    from types import SimpleNamespace

    from apps.data_center.application import tasks

    initial = SimpleNamespace(
        authority_source_id="config-center",
        actor_id="service:market-refresh",
        user_id=1,
        tenant_id="tenant:production",
        owner_id="owner:production",
        is_authenticated=True,
        is_staff=True,
        role="system_owner",
        authority_content_hash="b" * 64,
        authority_valid_until=datetime.now(UTC) + timedelta(hours=2),
    )
    changed = SimpleNamespace(
        authority_source_id=initial.authority_source_id,
        actor_id="service:other-refresh",
        user_id=initial.user_id,
        tenant_id=initial.tenant_id,
        owner_id=initial.owner_id,
        is_authenticated=initial.is_authenticated,
        is_staff=initial.is_staff,
        role=initial.role,
        authority_content_hash="c" * 64,
        authority_valid_until=initial.authority_valid_until,
    )
    contexts = iter((initial, changed))
    monkeypatch.setattr(
        tasks.audit_integration,
        "preflight_data_reliability_audit_runtime",
        lambda **_: next(contexts),
    )
    monkeypatch.setattr(tasks, "get_active_provider_id_by_source", lambda _: 3)
    monkeypatch.setattr(tasks, "latest_closed_cn_market_session", lambda _: date(2026, 9, 18))
    monkeypatch.setattr(
        tasks,
        "list_active_stock_codes_for_backfill",
        lambda: ["000001.SZ"],
    )
    quote = SimpleNamespace(
        execute=lambda *_args, **_kwargs: pytest.fail("quote provider called after authority drift")
    )
    monkeypatch.setattr(tasks, "make_backfill_sync_quote_use_case", lambda: quote)
    monkeypatch.setattr(
        tasks,
        "make_backfill_sync_current_valuation_batch_use_case",
        lambda: SimpleNamespace(execute=lambda **_: pytest.fail("valuation provider called")),
    )
    monkeypatch.setattr(
        tasks,
        "make_core_current_publication_rebuild_use_case",
        lambda **_: SimpleNamespace(preview=lambda **_: pytest.fail("publication preview called")),
    )

    result = tasks.refresh_full_market_publications_task.run(batch_size=1)

    assert result["outcome"] == "blocked"
    assert result["blocked_reason"] == "operator_actor_mismatch"
    assert result["stored"] == 0


@pytest.mark.parametrize(
    ("failure", "expected_code", "expected_reason", "provider_details"),
    [
        pytest.param(
            ValueError("secret upstream response"),
            "MARKET_UNIVERSE_REFRESH_FAILED",
            "market_universe_refresh_failed",
            None,
            id="unknown-provider-error-is-redacted",
        ),
        pytest.param(
            DataFetchError(
                "secret upstream response",
                code="A_SHARE_UNIVERSE_FAILOVER_INCONSISTENT",
                details={"source": "tushare.stock_basic[provider_id=7]", "tolerance": 0.01},
            ),
            "A_SHARE_UNIVERSE_FAILOVER_INCONSISTENT",
            "a_share_universe_failover_inconsistent",
            {"source": "tushare.stock_basic[provider_id=7]", "tolerance": 0.01},
            id="classified-provider-error-keeps-code-and-provenance",
        ),
    ],
)
def test_task_exposes_stable_universe_refresh_error(
    monkeypatch,
    failure: Exception,
    expected_code: str,
    expected_reason: str,
    provider_details: dict[str, object] | None,
) -> None:
    """Provider exception text stays out of the user-facing task result."""

    from types import SimpleNamespace

    from apps.data_center.application import tasks

    monkeypatch.setattr(tasks, "get_active_provider_id_by_source", lambda _: 3)
    monkeypatch.setattr(tasks, "latest_closed_cn_market_session", lambda _: date(2026, 9, 18))
    monkeypatch.setattr(tasks, "make_backfill_sync_quote_use_case", SimpleNamespace)
    monkeypatch.setattr(
        tasks,
        "make_backfill_sync_current_valuation_batch_use_case",
        SimpleNamespace,
    )
    monkeypatch.setattr(
        tasks,
        "make_core_current_publication_rebuild_use_case",
        lambda **_: SimpleNamespace(),
    )
    monkeypatch.setattr(
        tasks,
        "sync_active_a_share_universe",
        lambda: (_ for _ in ()).throw(failure),
    )

    result = tasks.refresh_full_market_publications_task.run()

    assert result["outcome"] == "blocked"
    assert result["blocked_reason"] == expected_reason
    assert result["error_code"] == expected_code
    assert result["errors"] == [expected_code]
    if provider_details is not None:
        assert result["market_universe_error"] == provider_details
    else:
        assert "market_universe_error" not in result
    assert "secret" not in str(result)


def test_task_blocks_partial_valuation_seed_without_verified_scope_exclusions(monkeypatch):
    """A provider omission cannot silently reduce the active publication denominator."""

    from types import SimpleNamespace

    from apps.data_center.application import tasks

    active_codes = ["000001.SZ", "000002.SZ", "000003.SZ"]
    policy = SimpleNamespace(
        dataset=SimpleNamespace(value="equity.valuation.fact"),
        allow_partial=True,
        uses_versioned_evidence=True,
        minimum_coverage_ratio=0.99,
        identity="p2:valuation-current-v1:" + "a" * 64,
    )
    monkeypatch.setattr(
        tasks,
        "get_publication_policy_repository",
        lambda: SimpleNamespace(get_active=lambda _dataset: policy),
    )
    monkeypatch.setattr(tasks, "get_active_provider_id_by_source", lambda _: 3)
    monkeypatch.setattr(tasks, "latest_closed_cn_market_session", lambda _: date(2026, 9, 18))
    monkeypatch.setattr(
        tasks,
        "sync_active_a_share_universe",
        lambda: _universe_report(active_codes),
    )
    monkeypatch.setattr(
        tasks,
        "list_active_stock_codes_for_backfill",
        lambda: list(active_codes),
    )
    monkeypatch.setattr(
        tasks,
        "make_backfill_sync_quote_use_case",
        lambda: SimpleNamespace(
            execute=lambda *_args, **_kwargs: pytest.fail(
                "quote provider called after incomplete valuation scope"
            )
        ),
    )
    monkeypatch.setattr(
        tasks,
        "make_backfill_sync_current_valuation_batch_use_case",
        lambda: _audited_valuation_sync(
            lambda **_kwargs: SimpleNamespace(
                stored_count=1,
                status="partial",
                succeeded_asset_codes=("000001.SZ",),
                returned_asset_codes=("000001.SZ",),
            )
        ),
    )
    monkeypatch.setattr(
        tasks,
        "make_core_current_publication_rebuild_use_case",
        lambda **_: SimpleNamespace(
            preview=lambda **_: pytest.fail("incomplete scope reached publication preview"),
            execute=lambda **_: pytest.fail("incomplete scope reached publication"),
        ),
    )

    result = tasks.refresh_full_market_publications_task.run(batch_size=2)

    assert result["outcome"] == "blocked"
    assert result["success"] is False
    assert result["publication_updated"] is False
    assert result["published_members"] == 0
    assert result["requested"] == 3
    assert result["succeeded"] == 1
    assert result["failed"] == 2
    assert result["stored"] == 1
    assert result["count_unit"] == "valuation_asset"
    assert result["operation_requested"] == 1
    assert result["operation_succeeded"] == 0
    assert result["operation_failed"] == 1
    assert result["requested_asset_count"] == 3
    assert result["succeeded_asset_count"] == 1
    assert result["failed_asset_count"] == 2
    assert result["missing_asset_codes"] == ["000002.SZ", "000003.SZ"]
    assert result["excluded_non_trading_codes"] == []
    assert result["error_code"] == "CURRENT_VALUATION_SCOPE_INCOMPLETE"
    assert result["blocked_reason"] == "current_valuation_scope_incomplete"


def test_task_publishes_policy_allowed_partial_valuation_and_reports_asset_counts(monkeypatch):
    """A bounded valuation gap remains visible without blocking qualified assets."""

    from types import SimpleNamespace

    from apps.data_center.application import market_publication_refresh, public, tasks

    progress_snapshots = []
    monkeypatch.setattr(
        tasks,
        "record_current_task_progress",
        lambda progress: progress_snapshots.append(progress) or True,
    )

    active_codes = [f"{index:06d}.SZ" for index in range(100)]
    succeeded_codes = tuple(active_codes[:-1])
    missing_code = active_codes[-1]
    observed = datetime(2026, 9, 18, 7, tzinfo=UTC)
    policy = SimpleNamespace(
        dataset=SimpleNamespace(value="equity.valuation.fact"),
        allow_partial=True,
        uses_versioned_evidence=True,
        minimum_coverage_ratio=0.99,
        identity="p2:valuation-current-v1:" + "a" * 64,
    )
    monkeypatch.setattr(tasks, "get_active_provider_id_by_source", lambda _: 3)
    monkeypatch.setattr(tasks, "latest_closed_cn_market_session", lambda _: date(2026, 9, 18))
    monkeypatch.setattr(
        tasks, "sync_active_a_share_universe", lambda: _universe_report(active_codes)
    )
    monkeypatch.setattr(tasks, "list_active_stock_codes_for_backfill", lambda: list(active_codes))
    monkeypatch.setattr(
        tasks,
        "get_publication_policy_repository",
        lambda: SimpleNamespace(get_active=lambda _dataset: policy),
    )
    monkeypatch.setattr(
        tasks,
        "make_backfill_sync_quote_use_case",
        lambda: _prefetched_quote_sync(
            lambda request: SimpleNamespace(
                stored_count=len(request.asset_codes),
                stored_asset_codes=tuple(request.asset_codes),
            )
        ),
    )
    monkeypatch.setattr(
        tasks,
        "make_backfill_sync_current_valuation_batch_use_case",
        lambda: _audited_valuation_sync(
            lambda **_: SimpleNamespace(
                stored_count=len(succeeded_codes),
                status="partial",
                succeeded_asset_codes=succeeded_codes,
                returned_asset_codes=succeeded_codes,
            )
        ),
    )
    quote_preview = SimpleNamespace(
        dataset_key="equity.quote.snapshot",
        ready=True,
        oldest_observed_at=observed,
        newest_observed_at=observed,
    )
    price_preview = SimpleNamespace(
        dataset_key="equity.price.bar",
        ready=True,
        requested_asset_count=len(active_codes),
        covered_asset_count=len(active_codes),
        member_count=len(active_codes),
        missing_asset_codes=(),
        unexpected_asset_codes=(),
        oldest_observed_at=observed,
        newest_observed_at=observed,
    )
    valuation_preview = SimpleNamespace(
        dataset_key="equity.valuation.fact",
        ready=False,
        covered_asset_count=len(succeeded_codes),
        missing_asset_codes=(missing_code,),
        unexpected_asset_codes=(),
        oldest_observed_at=observed,
        newest_observed_at=observed,
    )
    publication_id = "bf8c00f5-59df-42c0-a3cb-44d2e306d668"
    preview_calls: list[dict[str, object]] = []
    publication_calls: list[dict[str, object]] = []

    def preview_publication(**kwargs: object) -> SimpleNamespace:
        preview_calls.append(dict(kwargs))
        return SimpleNamespace(datasets=[quote_preview, price_preview, valuation_preview])

    def execute_publication(**kwargs: object) -> SimpleNamespace:
        publication_calls.append(dict(kwargs))
        return SimpleNamespace(
            published_count=299,
            to_dict=lambda: {
                "published_count": 299,
                "publication_ids": [publication_id],
                "datasets": [
                    {
                        "dataset_key": "equity.valuation.fact",
                        "scope_blocks": [
                            {
                                "asset_code": missing_code,
                                "reason_code": "valuation_source_data_unavailable",
                                "target_trade_date": "2026-09-18",
                                "source": "akshare",
                                "publication_run_id": kwargs["run_id"],
                                "policy_version": policy.identity,
                                "publication_id": publication_id,
                            }
                        ],
                    }
                ],
                "run_id": kwargs["run_id"],
            },
        )

    monkeypatch.setattr(
        tasks,
        "make_core_current_publication_rebuild_use_case",
        lambda **_: SimpleNamespace(
            preview=preview_publication,
            execute=execute_publication,
        ),
    )
    monkeypatch.setattr(public, "get_model_market_data_port", lambda: object())
    monkeypatch.setattr(
        market_publication_refresh,
        "refresh_market_price_inputs",
        lambda *_: _market_price_result_with_member_binding(),
    )

    result = tasks.refresh_full_market_publications_task.run(batch_size=100)

    assert result["outcome"] == "partial"
    assert result["success"] is True
    assert result["publication_updated"] is True
    assert result["requested"] == 100
    assert result["succeeded"] == 99
    assert result["failed"] == 1
    assert result["stored"] == 199
    assert result["missing_asset_codes"] == [missing_code]
    assert result["scope_blocks"] == [
        {
            "asset_code": missing_code,
            "reason_code": "valuation_source_data_unavailable",
            "target_trade_date": "2026-09-18",
            "source": "akshare",
            "publication_run_id": result["publication_run_id"],
            "policy_version": policy.identity,
            "publication_id": result["scope_blocks"][0]["publication_id"],
        }
    ]
    assert result["scope_blocks"][0]["publication_id"] in result["publication_ids"]
    assert result["excluded_non_trading_codes"] == []
    assert result["publication_run_id"] == result["run_id"]
    required_observation_dates = {
        "equity.quote.snapshot": date(2026, 9, 18),
        "equity.price.bar": date(2026, 9, 18),
        "equity.valuation.fact": date(2026, 9, 18),
    }
    assert preview_calls[0]["required_observation_dates"] == required_observation_dates
    assert publication_calls[0]["required_observation_dates"] == required_observation_dates
    assert progress_snapshots[0].phase == "universe"
    assert progress_snapshots[0].requested == 1
    assert progress_snapshots[0].succeeded == 0
    assert progress_snapshots[0].stored is None
    assert [phase.phase for phase in progress_snapshots[-1].phase_results] == [
        "universe",
        "scope",
        "valuation",
        "quote_prefetch",
        "quote",
        "publication",
    ]
    phase_results = {phase.phase: phase for phase in progress_snapshots[-1].phase_results}
    assert phase_results["universe"].requested == 1
    assert phase_results["universe"].succeeded == 1
    assert phase_results["universe"].stored == len(active_codes)
    assert phase_results["universe"].stored_count_unit == "universe_asset"
    assert phase_results["scope"].requested == 1
    assert phase_results["scope"].succeeded == 1
    assert phase_results["scope"].stored == len(active_codes)
    assert phase_results["scope"].stored_count_unit == "universe_asset"
    assert phase_results["valuation"].requested == len(active_codes)
    assert phase_results["valuation"].succeeded == len(succeeded_codes)
    assert phase_results["valuation"].failed == 1
    assert phase_results["valuation"].stored == len(succeeded_codes)
    assert phase_results["valuation"].count_unit == "valuation_asset"
    assert phase_results["valuation"].stored_count_unit == "fact_row"
    assert phase_results["quote_prefetch"].requested == 1
    assert phase_results["quote_prefetch"].succeeded == 1
    assert phase_results["quote_prefetch"].stored == 0
    assert phase_results["quote_prefetch"].count_unit == "provider_request"
    assert phase_results["quote"].requested == 1
    assert phase_results["quote"].succeeded == 1
    assert phase_results["quote"].stored == len(active_codes)
    assert phase_results["quote"].stored_count_unit == "fact_row"
    assert phase_results["publication"].count_unit == "sync_operation"
    assert phase_results["publication"].stored_count_unit == "publication_member"
    quote_in_progress = next(
        progress
        for progress in progress_snapshots
        if progress.phase == "quote" and progress.succeeded == 0
    )
    assert quote_in_progress.requested == 1
    assert quote_in_progress.stored == 0
    assert progress_snapshots[-1].phase == "publication"
    assert progress_snapshots[-1].succeeded == 1
    assert progress_snapshots[-1].stored == 299
    assert progress_snapshots[-1].stored_count_unit == "publication_member"


def test_task_reports_quote_prefetch_failure_before_any_quote_write(monkeypatch):
    """A failed full-session read keeps seed evidence and never enters batch writes."""

    from apps.data_center.application import tasks

    active_codes = ["000001.SZ", "600000.SH"]
    progress_snapshots = []
    monkeypatch.setattr(
        tasks,
        "record_current_task_progress",
        lambda progress: progress_snapshots.append(progress) or True,
    )
    monkeypatch.setattr(tasks, "get_active_provider_id_by_source", lambda _: 3)
    monkeypatch.setattr(tasks, "latest_closed_cn_market_session", lambda _: date(2026, 9, 18))
    monkeypatch.setattr(
        tasks, "sync_active_a_share_universe", lambda: _universe_report(active_codes)
    )
    monkeypatch.setattr(tasks, "list_active_stock_codes_for_backfill", lambda: active_codes)

    def fail_prefetch(**_: object) -> object:
        raise DataFetchError("provider rejected", code="TUSHARE_PROVIDER_REJECTED")

    quote = SimpleNamespace(
        prepare_session=fail_prefetch,
        execute_prefetched_session_batch=lambda *_: pytest.fail("quote batch write executed"),
    )
    valuation = _audited_valuation_sync(
        lambda **_: SimpleNamespace(
            stored_count=2,
            status="success",
            succeeded_asset_codes=tuple(active_codes),
            returned_asset_codes=tuple(active_codes),
        )
    )
    monkeypatch.setattr(tasks, "make_backfill_sync_quote_use_case", lambda: quote)
    monkeypatch.setattr(
        tasks, "make_backfill_sync_current_valuation_batch_use_case", lambda: valuation
    )
    monkeypatch.setattr(
        tasks,
        "make_core_current_publication_rebuild_use_case",
        lambda **_: SimpleNamespace(
            preview=lambda **__: pytest.fail("publication preview executed"),
            execute=lambda **__: pytest.fail("publication write executed"),
        ),
    )

    result = tasks.refresh_full_market_publications_task.run(batch_size=2)

    assert result["outcome"] == "partial"
    assert result["phase"] == "quote"
    assert result["requested"] == 2
    assert result["succeeded"] == 0
    assert result["failed"] == 2
    assert result["stored"] == 2
    assert result["count_unit"] == "quote_asset"
    assert result["error_code"] == "TUSHARE_PROVIDER_REJECTED"
    assert result["publication_updated"] is False
    assert result["published_members"] == 0
    assert progress_snapshots[-1].phase == "quote_prefetch"
    assert progress_snapshots[-1].failed == 1
    assert progress_snapshots[-1].stored == 0


def test_task_verifies_dynamic_quote_gap_and_publishes_full_scope_with_exclusion(monkeypatch):
    """A proven suspension narrows quote writes while publication keeps the frozen denominator."""

    from apps.data_center.application import market_publication_refresh, tasks

    target = date(2026, 9, 18)
    active_codes = ["000001.SZ", "600000.SH"]
    excluded = active_codes[1]
    monkeypatch.setattr(tasks, "get_active_provider_id_by_source", lambda _: 3)
    monkeypatch.setattr(tasks, "latest_closed_cn_market_session", lambda _: target)
    monkeypatch.setattr(
        tasks, "sync_active_a_share_universe", lambda: _universe_report(active_codes)
    )
    monkeypatch.setattr(tasks, "list_active_stock_codes_for_backfill", lambda: list(active_codes))

    quote_calls: list[tuple[str, ...]] = []
    verify_calls: list[tuple[str, ...]] = []

    def prepare_session(**kwargs: object) -> SimpleNamespace:
        verifier = kwargs["missing_asset_verifier"]
        assert callable(verifier)
        verified = verifier((excluded,), target)
        verify_calls.append(tuple(verified))
        return SimpleNamespace(
            universe_codes=tuple(active_codes),
            available_codes=(active_codes[0],),
            eligible_codes=(active_codes[0],),
            excluded_codes=(excluded,),
        )

    quote = SimpleNamespace(
        prepare_session=prepare_session,
        execute_prefetched_session_batch=lambda request, _session: (
            quote_calls.append(tuple(request.asset_codes))
            or _with_raw_audit_reference(
                SimpleNamespace(
                    stored_count=len(request.asset_codes),
                    stored_asset_codes=tuple(request.asset_codes),
                ),
                "quote-dynamic-test-audit",
            )
        ),
    )
    valuation = _audited_valuation_sync(
        lambda **_: SimpleNamespace(
            stored_count=len(active_codes),
            succeeded_asset_codes=tuple(active_codes),
            returned_asset_codes=tuple(active_codes),
            status="success",
        )
    )
    monkeypatch.setattr(tasks, "make_backfill_sync_quote_use_case", lambda: quote)
    monkeypatch.setattr(
        tasks, "make_backfill_sync_current_valuation_batch_use_case", lambda: valuation
    )

    observed = datetime(2026, 9, 18, 7, tzinfo=UTC)
    datasets = [
        SimpleNamespace(
            dataset_key="equity.quote.snapshot",
            ready=False,
            covered_asset_count=1,
            missing_asset_codes=(excluded,),
            unexpected_asset_codes=(),
            oldest_observed_at=observed,
            newest_observed_at=observed,
        ),
        SimpleNamespace(
            dataset_key="equity.valuation.fact",
            ready=True,
            covered_asset_count=len(active_codes),
            missing_asset_codes=(),
            unexpected_asset_codes=(),
            oldest_observed_at=observed,
            newest_observed_at=observed,
        ),
        SimpleNamespace(
            dataset_key="equity.price.bar",
            ready=False,
            requested_asset_count=len(active_codes),
            covered_asset_count=1,
            member_count=1,
            missing_asset_codes=(active_codes[0],),
            unexpected_asset_codes=(),
            oldest_observed_at=observed,
            newest_observed_at=observed,
        ),
    ]
    publication_calls: list[dict[str, object]] = []

    def execute_publication(**kwargs: object) -> SimpleNamespace:
        publication_calls.append(dict(kwargs))
        run_id = str(kwargs["run_id"])
        block = {
            "asset_code": excluded,
            "reason_code": "quote_full_day_suspension",
            "target_trade_date": target.isoformat(),
            "source": "tushare",
            "publication_run_id": run_id,
            "policy_version": "p2:quote-current-v1:policy-digest",
            "publication_id": "quote-publication-20260918",
            "evidence_source": "tushare.suspend_d",
        }
        return SimpleNamespace(
            published_count=1,
            to_dict=lambda: {
                "published_count": 1,
                "run_id": run_id,
                "datasets": [
                    {
                        "dataset_key": "equity.quote.snapshot",
                        "scope_blocks": [block],
                    }
                ],
            },
        )

    preview_calls: list[dict[str, object]] = []

    def preview_publication(**kwargs: object) -> SimpleNamespace:
        preview_calls.append(dict(kwargs))
        return SimpleNamespace(datasets=datasets)

    publication = SimpleNamespace(
        preview=preview_publication,
        execute=execute_publication,
    )
    monkeypatch.setattr(
        tasks, "make_core_current_publication_rebuild_use_case", lambda **_: publication
    )
    monkeypatch.setattr(tasks.public_services, "get_model_market_data_port", lambda: object())
    monkeypatch.setattr(
        market_publication_refresh,
        "refresh_market_price_inputs",
        lambda _port, codes, _target: (
            MarketPricePreparationResult(
                suspended_codes=(excluded,),
                raw_audit_references=(),
                suspension_evidence=(
                    MarketPriceSuspensionEvidence(
                        asset_code=excluded,
                        target_trade_date=target,
                        evidence_source="akshare",
                    ),
                ),
            )
            if tuple(codes) == (excluded,)
            else MarketPricePreparationResult(
                suspended_codes=(active_codes[0],),
                raw_audit_references=(
                    _market_price_result_with_member_binding().raw_audit_references[0],
                ),
                suspension_evidence=(
                    MarketPriceSuspensionEvidence(
                        asset_code=active_codes[0],
                        target_trade_date=target,
                        evidence_source="akshare",
                    ),
                ),
                raw_audit_bindings=(
                    _market_price_result_with_member_binding().raw_audit_bindings[0],
                ),
                member_owning_raw_audit_bindings=(
                    _market_price_result_with_member_binding().member_owning_raw_audit_bindings[0],
                ),
            )
        ),
    )

    result = tasks.refresh_full_market_publications_task.run(batch_size=2)

    assert verify_calls == [(excluded,)]
    assert quote_calls == [(active_codes[0],)]
    assert result["excluded_non_trading_codes"] == [excluded]
    assert result["missing_asset_codes"] == [excluded]
    assert result["requested"] == 2
    assert result["succeeded"] == 1
    assert result["failed"] == 1
    assert result["quote_eligible_asset_count"] == 1
    assert result["quote_selected_asset_count"] == 1
    assert result["suspension_evidence_source"] == "tushare.suspend_d"
    assert result["quote_scope_blocks"][0]["asset_code"] == excluded
    assert result["scope_blocks"] == result["quote_scope_blocks"]
    assert "全天停牌" in result["scope_notice"]
    assert result.get("must_not_use_for_decision") is not True
    assert publication_calls[0]["asset_codes"] == active_codes
    exclusions = publication_calls[0]["scope_exclusions_by_dataset"]["equity.quote.snapshot"]
    assert exclusions[0].asset_code == excluded
    assert exclusions[0].reason_code == "quote_full_day_suspension"
    price_exclusions = publication_calls[0]["scope_exclusions_by_dataset"]["equity.price.bar"]
    assert price_exclusions[0].asset_code == active_codes[0]
    assert price_exclusions[0].reason_code == "price_full_day_suspension"
    assert price_exclusions[0].target_trade_date == target
    assert price_exclusions[0].evidence_source == "akshare"
    assert excluded not in {item.asset_code for item in price_exclusions}
    assert preview_calls[0]["asset_codes"] == active_codes
    assert (
        preview_calls[0]["scope_exclusions_by_dataset"]
        == publication_calls[0]["scope_exclusions_by_dataset"]
    )
    required_observation_dates = {
        "equity.quote.snapshot": target,
        "equity.price.bar": target,
        "equity.valuation.fact": target,
    }
    assert preview_calls[0]["required_observation_dates"] == required_observation_dates
    assert publication_calls[0]["required_observation_dates"] == required_observation_dates


def test_task_blocks_when_refreshed_universe_count_differs_from_frozen_codes(monkeypatch):
    """The refreshed active count is the denominator and cannot be silently reduced."""

    from types import SimpleNamespace

    from apps.data_center.application import tasks

    monkeypatch.setattr(tasks, "get_active_provider_id_by_source", lambda _: 3)
    monkeypatch.setattr(tasks, "latest_closed_cn_market_session", lambda _: date(2026, 9, 18))
    monkeypatch.setattr(
        tasks,
        "sync_active_a_share_universe",
        lambda: _universe_report(["000001.SZ", "000002.SZ"], active_count=3),
    )
    monkeypatch.setattr(
        tasks,
        "list_active_stock_codes_for_backfill",
        lambda: ["000001.SZ", "000002.SZ"],
    )
    monkeypatch.setattr(tasks, "make_backfill_sync_quote_use_case", SimpleNamespace)
    monkeypatch.setattr(
        tasks,
        "make_backfill_sync_current_valuation_batch_use_case",
        lambda: SimpleNamespace(execute=lambda **_: pytest.fail("valuation provider called")),
    )
    monkeypatch.setattr(
        tasks,
        "make_core_current_publication_rebuild_use_case",
        lambda **_: SimpleNamespace(preview=lambda **_: pytest.fail("publication preview called")),
    )

    result = tasks.refresh_full_market_publications_task.run()

    assert result["outcome"] == "blocked"
    assert result["error_code"] == "MARKET_UNIVERSE_SCOPE_INVALID"
    assert result["blocked_reason"] == "market_universe_scope_invalid"
    assert result["publication_updated"] is False
    assert result["published_members"] == 0
    assert result["requested_asset_count"] == 2
    assert result["market_universe"]["active_count"] == 3


def test_task_blocks_same_count_universe_identity_substitution(monkeypatch):
    """Equal counts cannot hide a different provider-observed security identity."""

    from types import SimpleNamespace

    from apps.data_center.application import tasks

    monkeypatch.setattr(tasks, "get_active_provider_id_by_source", lambda _: 3)
    monkeypatch.setattr(tasks, "latest_closed_cn_market_session", lambda _: date(2026, 9, 18))
    monkeypatch.setattr(
        tasks,
        "sync_active_a_share_universe",
        lambda: _universe_report(["000001.SZ", "000003.SZ"]),
    )
    monkeypatch.setattr(
        tasks,
        "list_active_stock_codes_for_backfill",
        lambda: ["000001.SZ", "000002.SZ"],
    )
    monkeypatch.setattr(tasks, "make_backfill_sync_quote_use_case", SimpleNamespace)
    monkeypatch.setattr(
        tasks,
        "make_backfill_sync_current_valuation_batch_use_case",
        lambda: SimpleNamespace(execute=lambda **_: pytest.fail("valuation provider called")),
    )
    monkeypatch.setattr(
        tasks,
        "make_core_current_publication_rebuild_use_case",
        lambda **_: SimpleNamespace(preview=lambda **_: pytest.fail("publication preview called")),
    )

    result = tasks.refresh_full_market_publications_task.run()

    assert result["outcome"] == "blocked"
    assert result["error_code"] == "MARKET_UNIVERSE_SCOPE_INVALID"
    assert result["frozen_universe_sha256"] != result["reported_universe_sha256"]
    assert result["publication_updated"] is False


def test_task_uses_effective_universe_when_provider_omission_is_bounded(monkeypatch) -> None:
    """A retained provider omission stays in the denominator and reaches valuation checks."""

    from types import SimpleNamespace

    from apps.data_center.application import tasks

    target = date(2026, 9, 30)
    active_codes = tuple(f"{index:06d}.SZ" for index in range(1, 201))
    retained_code = active_codes[-1]
    observed_codes = active_codes[:-1]
    valuation_calls: list[tuple[str, ...]] = []
    universe_report = _universe_report(list(active_codes))
    universe_report.update(
        {
            "observed_count": len(observed_codes),
            "observed_codes_sha256": hashlib.sha256(
                json.dumps(
                    sorted(observed_codes),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
            "retained_missing_count": 1,
            "retained_missing_codes": [retained_code],
            "retained_missing_ratio": 1 / len(active_codes),
            "retained_missing_tolerance": 0.01,
            "retained_missing_reason_code": "provider_membership_not_observed",
        }
    )
    monkeypatch.setattr(tasks, "get_active_provider_id_by_source", lambda _: 3)
    monkeypatch.setattr(tasks, "latest_closed_cn_market_session", lambda _: target)
    monkeypatch.setattr(tasks, "sync_active_a_share_universe", lambda: universe_report)
    monkeypatch.setattr(
        tasks,
        "build_target_date_a_share_universe_scope",
        lambda day: _unknown_listing_date_scope(day, list(active_codes)),
    )
    monkeypatch.setattr(tasks, "make_backfill_sync_quote_use_case", SimpleNamespace)
    monkeypatch.setattr(
        tasks,
        "make_backfill_sync_current_valuation_batch_use_case",
        lambda: _audited_valuation_sync(
            lambda **kwargs: (
                valuation_calls.append(tuple(kwargs["asset_codes"]))
                or SimpleNamespace(
                    stored_count=len(observed_codes),
                    status="partial",
                    succeeded_asset_codes=observed_codes,
                    returned_asset_codes=observed_codes,
                )
            )
        ),
    )
    monkeypatch.setattr(
        tasks,
        "get_publication_policy_repository",
        lambda: SimpleNamespace(get_active=lambda _dataset: None),
    )
    monkeypatch.setattr(
        tasks,
        "make_core_current_publication_rebuild_use_case",
        lambda **_: SimpleNamespace(),
    )

    result = tasks.refresh_full_market_publications_task.run(batch_size=100)

    assert valuation_calls == [active_codes]
    assert result["error_code"] != "MARKET_UNIVERSE_SCOPE_INVALID"
    assert result["requested_asset_count"] == len(active_codes)
    assert result["missing_asset_codes"] == [retained_code]
    assert result["market_universe"]["retained_missing_codes"] == [retained_code]
    assert result["publication_updated"] is False


def test_equivalent_authority_successor_does_not_interrupt_active_refresh(
    monkeypatch,
    _patch_current_authority,
):
    """An append-only renewal with the same identity may rotate the authority hash."""

    from types import SimpleNamespace

    from apps.data_center.application import tasks

    successor = SimpleNamespace(
        **{
            **vars(_patch_current_authority),
            "authority_content_hash": "c" * 64,
            "authority_valid_until": datetime.now(UTC) + timedelta(hours=3),
        }
    )
    monkeypatch.setattr(
        tasks.audit_integration,
        "preflight_data_reliability_audit_runtime",
        lambda **_: successor,
    )

    assert tasks._same_data02_task_authority_is_current(
        _patch_current_authority,
        as_of=datetime.now(UTC),
    )


def test_audit_configuration_blocks_before_market_fetch(monkeypatch):
    from apps.audit.application.system_audit_composition import SystemAuditCompositionUnavailable
    from apps.data_center.application import tasks

    monkeypatch.setattr(tasks, "get_active_provider_id_by_source", lambda _: 3)

    def unavailable():
        raise SystemAuditCompositionUnavailable("unavailable", reason_code="audit_runtime_disabled")

    monkeypatch.setattr(tasks, "make_backfill_sync_quote_use_case", unavailable)
    monkeypatch.setattr(
        tasks,
        "make_backfill_sync_current_valuation_batch_use_case",
        lambda: pytest.fail("unexpected valuation fetch"),
    )
    result = tasks.refresh_full_market_publications_task.run()
    assert result["outcome"] == "blocked"
    assert result["blocked_reason"] == "system_audit_audit_runtime_disabled"
    assert result["stored"] == 0


def test_task_does_not_publish_stale_quotes_even_when_all_rows_were_stored(monkeypatch):
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from apps.data_center.application import market_publication_refresh, public, tasks

    monkeypatch.setattr(tasks, "get_active_provider_id_by_source", lambda _: 3)
    monkeypatch.setattr(tasks, "latest_closed_cn_market_session", lambda _: date(2026, 9, 18))
    monkeypatch.setattr(tasks, "list_active_stock_codes_for_backfill", lambda: ["000001.SZ"])

    def execute_sync(*_: object, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            stored_count=1,
            stored_asset_codes=("000001.SZ",),
            succeeded_asset_codes=("000001.SZ",),
            returned_asset_codes=("000001.SZ",),
        )

    quote_sync = _prefetched_quote_sync(execute_sync)
    valuation_sync = _audited_valuation_sync(execute_sync)
    monkeypatch.setattr(tasks, "make_backfill_sync_quote_use_case", lambda: quote_sync)
    monkeypatch.setattr(
        tasks, "make_backfill_sync_current_valuation_batch_use_case", lambda: valuation_sync
    )
    current_observed = datetime(2026, 9, 18, 7, tzinfo=UTC)
    preview = SimpleNamespace(
        ready=False,
        datasets=[
            SimpleNamespace(
                dataset_key="equity.quote.snapshot",
                ready=True,
                oldest_observed_at=datetime(2026, 9, 17, 7, tzinfo=UTC),
                newest_observed_at=datetime(2026, 9, 17, 7, tzinfo=UTC),
            ),
            SimpleNamespace(
                dataset_key="equity.price.bar",
                ready=True,
                requested_asset_count=1,
                covered_asset_count=1,
                member_count=1,
                missing_asset_codes=(),
                unexpected_asset_codes=(),
                oldest_observed_at=current_observed,
                newest_observed_at=current_observed,
            ),
            SimpleNamespace(
                dataset_key="equity.valuation.fact",
                ready=True,
                oldest_observed_at=current_observed,
                newest_observed_at=current_observed,
            ),
        ],
    )
    composition_calls = []

    def build_publications(**kwargs):
        composition_calls.append(kwargs)
        return SimpleNamespace(
            preview=lambda **_: preview, execute=lambda **_: pytest.fail("published stale scope")
        )

    monkeypatch.setattr(tasks, "make_core_current_publication_rebuild_use_case", build_publications)
    monkeypatch.setattr(public, "get_model_market_data_port", lambda: object())
    monkeypatch.setattr(
        market_publication_refresh,
        "refresh_market_price_inputs",
        lambda *_: MarketPricePreparationResult(suspended_codes=(), raw_audit_references=()),
    )
    result = tasks.refresh_full_market_publications_task.run()
    assert result["outcome"] == "partial"
    assert result["published_members"] == 0
    assert composition_calls[0]["created_by"] == (
        "celery.full_market_refresh:service:market-refresh"
    )


@pytest.mark.parametrize(
    ("quote_codes", "valuation_succeeded_codes", "expected_outcome"),
    [
        (("000001.SZ", "000001.SZ"), ("000001.SZ", "000002.SZ"), "partial"),
        (("000001.SZ", "000002.SZ"), ("000001.SZ", "000001.SZ"), "blocked"),
    ],
)
def test_task_rejects_duplicate_provider_asset_identities_before_publication(
    monkeypatch,
    quote_codes,
    valuation_succeeded_codes,
    expected_outcome,
):
    """A count-equal duplicate batch cannot reach full-market publication."""

    from types import SimpleNamespace

    from apps.data_center.application import tasks

    monkeypatch.setattr(tasks, "get_active_provider_id_by_source", lambda _: 3)
    monkeypatch.setattr(tasks, "latest_closed_cn_market_session", lambda _: date(2026, 9, 18))
    monkeypatch.setattr(
        tasks,
        "list_active_stock_codes_for_backfill",
        lambda: ["000001.SZ", "000002.SZ"],
    )
    monkeypatch.setattr(
        tasks,
        "sync_active_a_share_universe",
        lambda: _universe_report(["000001.SZ", "000002.SZ"]),
    )
    quote = _prefetched_quote_sync(
        lambda *_args, **_kwargs: SimpleNamespace(
            stored_count=2,
            stored_asset_codes=quote_codes,
        )
    )
    valuation = _audited_valuation_sync(
        lambda *_args, **_kwargs: SimpleNamespace(
            stored_count=2,
            succeeded_asset_codes=valuation_succeeded_codes,
            returned_asset_codes=("000001.SZ", "000002.SZ"),
        )
    )
    monkeypatch.setattr(tasks, "make_backfill_sync_quote_use_case", lambda: quote)
    monkeypatch.setattr(
        tasks,
        "make_backfill_sync_current_valuation_batch_use_case",
        lambda: valuation,
    )
    publication = SimpleNamespace(
        preview=lambda **_: pytest.fail("duplicate quote batch reached preview"),
        execute=lambda **_: pytest.fail("duplicate quote batch reached publication"),
    )
    monkeypatch.setattr(
        tasks,
        "make_core_current_publication_rebuild_use_case",
        lambda **_: publication,
    )

    result = tasks.refresh_full_market_publications_task.run(batch_size=2)

    assert result["outcome"] == expected_outcome
    assert result.get("published_members", 0) == 0


def test_market_dataset_selection_retains_default_financial_rebuild():
    from apps.data_center.composition import make_core_current_publication_rebuild_use_case

    default = make_core_current_publication_rebuild_use_case()
    assert len(default._rebuilders) == 4
    selected = make_core_current_publication_rebuild_use_case(
        dataset_keys=("equity.quote.snapshot", "equity.valuation.fact")
    )
    assert {item.dataset.dataset_key for item in selected._rebuilders} == {
        "equity.quote.snapshot",
        "equity.valuation.fact",
    }
    for keys in [(), ("bad",), ("equity.price.bar", "equity.price.bar")]:
        with pytest.raises(ValueError):
            make_core_current_publication_rebuild_use_case(dataset_keys=keys)


@pytest.mark.parametrize("reason", ["MODEL_MARKET_STALE", "MODEL_MARKET_SOURCE_CONFLICT"])
def test_price_stage_never_publishes_stale_or_conflicting_existing_facts(reason):
    from types import SimpleNamespace

    def fail(*args):
        raise DataFetchError("invalid", code=reason)

    with pytest.raises(DataFetchError) as caught:
        refresh_market_price_inputs(
            SimpleNamespace(stock_history=fail), ["000001.SZ"], date(2026, 9, 18)
        )
    assert caught.value.code == reason


def test_price_stage_prefetches_only_target_session_at_full_market_scale():
    """Full-market validation must reuse one target-session prefetch, not Qlib history."""
    from types import SimpleNamespace

    target = date(2026, 9, 18)
    codes = [f"{value:06d}.SZ" for value in range(1, 5570)]

    class PreparedPort(_PriceAuditEvidence):
        def __init__(self):
            super().__init__()
            self.prepare_calls = []
            self.provider_batch_requests = 0
            self.per_asset_provider_requests = []
            self.prepared_rows = {}

        def prepare_stock_history(self, asset_codes, start_date, end_date):
            self.prepare_calls.append((asset_codes, start_date, end_date))
            self.provider_batch_requests += 1
            self.prepared_codes = set(asset_codes)
            self.prepared_rows = {
                code: (SimpleNamespace(trade_date=target),) for code in asset_codes
            }

        def stock_history(self, asset_code, start_date, end_date):
            assert (start_date, end_date) == (target, target)
            assert asset_code in self.prepared_codes
            if asset_code not in self.prepared_rows:
                self.per_asset_provider_requests.append(asset_code)
                return ()
            return self.prepared_rows[asset_code]

    port = PreparedPort()

    assert refresh_market_price_inputs(port, codes, target).suspended_codes == ()
    assert port.prepare_calls == [(tuple(codes), target, target)]
    assert port.provider_batch_requests == 1
    assert port.per_asset_provider_requests == []


def test_price_stage_expands_only_missing_assets_for_native_suspension_evidence():
    """Only missing target-session members may use the bounded history fallback."""
    from types import SimpleNamespace

    target = date(2026, 9, 18)
    missing_code = "000016.SZ"
    calls = []

    class Port(_PriceAuditEvidence):
        def __init__(self):
            super().__init__()

        def prepare_stock_history(self, asset_codes, start_date, end_date):
            calls.append(("prepare", asset_codes, start_date, end_date))

        def stock_history(self, asset_code, start_date, end_date):
            calls.append(("read", asset_code, start_date, end_date))
            if start_date == target:
                if asset_code == missing_code:
                    raise DataFetchError("missing target session", code="MODEL_MARKET_UNAVAILABLE")
                return (SimpleNamespace(trade_date=target),)
            assert start_date == target - timedelta(days=120)
            assert asset_code == missing_code
            raise DataFetchError(
                "verified suspension",
                code="MODEL_MARKET_SUSPENDED",
                details={
                    "asset_code": missing_code,
                    "suspended_through": target.isoformat(),
                    "source": "akshare",
                },
            )

    result = refresh_market_price_inputs(Port(), ["000001.SZ", missing_code, "000002.SZ"], target)
    assert result.suspended_codes == (missing_code,)
    assert result.suspension_evidence == (
        MarketPriceSuspensionEvidence(
            asset_code=missing_code,
            target_trade_date=target,
            evidence_source="akshare",
        ),
    )
    assert calls[0] == ("prepare", ("000001.SZ", missing_code, "000002.SZ"), target, target)
    assert [call for call in calls if call[0] == "prepare"] == [
        ("prepare", ("000001.SZ", missing_code, "000002.SZ"), target, target),
        (
            "prepare",
            (missing_code,),
            target - timedelta(days=120),
            target,
        ),
    ]
    assert [call[1] for call in calls if call[0] == "read" and call[2] != target] == [missing_code]


def test_price_stage_rejects_unverified_suspension_after_missing_target_read():
    """A historical gap without exact target-day suspension evidence still blocks."""
    from types import SimpleNamespace

    target = date(2026, 9, 18)

    class Port:
        def stock_history(self, asset_code, start_date, end_date):
            if start_date == target:
                raise DataFetchError("missing target session", code="MODEL_MARKET_UNAVAILABLE")
            return (SimpleNamespace(trade_date=target - timedelta(days=1)),)

    with pytest.raises(DataFetchError) as caught:
        refresh_market_price_inputs(Port(), ["000016.SZ"], target)
    assert caught.value.code == "MODEL_MARKET_STALE"


def test_price_stage_does_not_expand_provider_rejection_into_history_requests():
    """Provider rejection is a terminal route error, not evidence of a missing price."""
    target = date(2026, 9, 18)
    calls = []

    class Port:
        def stock_history(self, asset_code, start_date, end_date):
            calls.append((asset_code, start_date, end_date))
            raise DataFetchError("rejected", code="TUSHARE_PROVIDER_REJECTED")

    with pytest.raises(DataFetchError) as caught:
        refresh_market_price_inputs(Port(), ["000001.SZ"], target)
    assert caught.value.code == "TUSHARE_PROVIDER_REJECTED"
    assert calls == [("000001.SZ", target, target)]


@pytest.mark.parametrize("evidence_date", ["2026-09-18", "2026-09-17"])
def test_price_stage_requires_target_bound_suspension_evidence(evidence_date):
    from types import SimpleNamespace

    def read(code, start, end):
        if code == "000001.SZ":
            return [SimpleNamespace(trade_date=end)]
        raise DataFetchError(
            "suspended",
            code="MODEL_MARKET_SUSPENDED",
            details={
                "asset_code": code,
                "suspended_through": evidence_date,
                "source": "tushare",
            },
        )

    class Port(_PriceAuditEvidence):
        def __init__(self):
            super().__init__()

        def stock_history(self, code, start, end):
            return read(code, start, end)

    port = Port()
    if evidence_date == "2026-09-18":
        result = refresh_market_price_inputs(port, ["000001.SZ", "000016.SZ"], date(2026, 9, 18))
        assert result.suspended_codes == ("000016.SZ",)
        assert result.suspension_evidence[0].evidence_source == "tushare"
    else:
        with pytest.raises(DataFetchError):
            refresh_market_price_inputs(port, ["000016.SZ"], date(2026, 9, 18))


@pytest.mark.parametrize("missing_reference_stage", [None, "quote", "valuation", "stale_price"])
def test_task_repairs_missing_price_scope_before_final_publication(
    monkeypatch, missing_reference_stage
):
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from apps.data_center.application import market_publication_refresh, public, tasks
    from apps.data_center.domain.entities import RawAuditReference

    price_reference = RawAuditReference(
        raw_audit_id="price-raw-1",
        version="raw-audit-v1",
        content_hash="a" * 64,
        run_id="price-run-1",
        ingested_run_id="price-ingested-1",
    )

    request_only_price_reference = RawAuditReference(
        raw_audit_id="price-raw-0",
        version="raw-audit-v1",
        content_hash="b" * 64,
        run_id="price-request-run",
        ingested_run_id="price-request-ingested",
    )

    events = []
    provider_ids = {"tushare": 3, "akshare": 7}
    monkeypatch.setattr(tasks, "get_active_provider_id_by_source", lambda name: provider_ids[name])
    monkeypatch.setattr(tasks, "latest_closed_cn_market_session", lambda _: date(2026, 9, 18))
    monkeypatch.setattr(tasks, "list_active_stock_codes_for_backfill", lambda: ["000001.SZ"])
    quote_provider_ids = []
    valuation_provider_ids = []

    def sync_quote(request):
        quote_provider_ids.append(request.provider_id)
        return SimpleNamespace(
            stored_count=1,
            stored_asset_codes=("000001.SZ",),
        )

    def sync_valuation(**kwargs):
        valuation_provider_ids.append(kwargs["provider_id"])
        return SimpleNamespace(
            stored_count=1,
            succeeded_asset_codes=("000001.SZ",),
            returned_asset_codes=("000001.SZ",),
        )

    quote_sync = _prefetched_quote_sync(
        sync_quote, include_audit_reference=missing_reference_stage != "quote"
    )
    monkeypatch.setattr(tasks, "make_backfill_sync_quote_use_case", lambda: quote_sync)
    monkeypatch.setattr(
        tasks,
        "make_backfill_sync_current_valuation_batch_use_case",
        lambda: _audited_valuation_sync(
            sync_valuation,
            include_audit_reference=missing_reference_stage != "valuation",
        ),
    )
    observed = datetime(2026, 9, 18, 7, tzinfo=UTC)
    price_observed = (
        datetime(2026, 9, 17, 7, tzinfo=UTC)
        if missing_reference_stage == "stale_price"
        else observed
    )
    datasets = [
        SimpleNamespace(
            dataset_key=key,
            ready=True,
            requested_asset_count=1,
            covered_asset_count=1,
            member_count=1,
            missing_asset_codes=(),
            unexpected_asset_codes=(),
            oldest_observed_at=observed,
            newest_observed_at=observed,
        )
        for key in ("equity.quote.snapshot", "equity.valuation.fact")
    ]
    datasets.append(
        SimpleNamespace(
            dataset_key="equity.price.bar",
            ready=True,
            requested_asset_count=1,
            covered_asset_count=1,
            member_count=1,
            missing_asset_codes=(),
            unexpected_asset_codes=(),
            oldest_observed_at=price_observed,
            newest_observed_at=price_observed,
        )
    )
    publication_id = "bf8c00f5-59df-42c0-a3cb-44d2e306d668"
    monkeypatch.setattr(
        tasks,
        "make_core_current_publication_rebuild_use_case",
        lambda **_: SimpleNamespace(
            preview=lambda **_: (
                events.append("preview") or SimpleNamespace(ready=False, datasets=datasets)
            ),
            execute=lambda **kwargs: (
                events.append("publish")
                or SimpleNamespace(
                    published_count=3,
                    to_dict=lambda: {
                        "published_count": 3,
                        "publication_ids": [publication_id],
                        "datasets": [
                            {
                                "dataset_key": "equity.quote.snapshot",
                                "publication_id": publication_id,
                                "publication_hash": "a" * 64,
                            }
                        ],
                        "run_id": kwargs["run_id"],
                    },
                )
            ),
        ),
    )
    publication_bundles = []
    original_bundle_factory = tasks.build_production_current_market_publication_bundle

    def capture_publication_bundle(**kwargs):
        bundle = original_bundle_factory(**kwargs)
        publication_bundles.append(bundle)
        return bundle

    monkeypatch.setattr(
        tasks,
        "build_production_current_market_publication_bundle",
        capture_publication_bundle,
    )
    monkeypatch.setattr(public, "get_model_market_data_port", lambda: object())
    monkeypatch.setattr(
        market_publication_refresh,
        "refresh_market_price_inputs",
        lambda *_: (
            events.append("refresh_prices")
            or MarketPricePreparationResult(
                suspended_codes=(),
                raw_audit_references=(request_only_price_reference, price_reference),
                raw_audit_bindings=(
                    ModelHistoryRawAuditBinding(request_only_price_reference, "akshare"),
                    ModelHistoryRawAuditBinding(price_reference, "tushare"),
                ),
                member_owning_raw_audit_bindings=(
                    ModelHistoryRawAuditBinding(price_reference, "tushare"),
                ),
            )
        ),
    )
    result = tasks.refresh_full_market_publications_task.run()
    if missing_reference_stage is not None:
        if missing_reference_stage == "stale_price":
            assert events == ["refresh_prices", "preview"]
            assert result["publication_updated"] is False
            assert result["published_members"] == 0
            return
        assert events == []
        assert result["outcome"] == "partial"
        assert result["publication_updated"] is False
        assert result["published_members"] == 0
        assert result["error_code"] == "CURRENT_RAW_AUDIT_REFERENCE_MISSING"
        assert result["requested"] == 1
        assert result["succeeded"] == 1
        assert result["failed"] == 0
        assert result["count_unit"] == "valuation_asset"
        assert result["requested_asset_count"] == 1
        assert result["succeeded_asset_count"] == 1
        assert result["failed_asset_count"] == 0
        assert result["missing_asset_codes"] == []
        if missing_reference_stage == "quote":
            assert result["blocked_reason"] == result["error_code"]
            assert result["phase"] == "quote"
            assert result["stored"] == 2
            assert result["operation_requested"] == 3
            assert result["operation_succeeded"] == 0
            assert result["operation_failed"] == 3
            quote_phase = next(item for item in result["phase_results"] if item["phase"] == "quote")
            assert quote_phase["succeeded"] == 0
            assert quote_phase["failed"] == 1
            assert quote_phase["stored"] == 1
            assert len(quote_sync.prepare_calls) == 1
            assert quote_provider_ids == [3]
            assert valuation_provider_ids == [7]
        else:
            assert result["blocked_reason"] == "current_raw_audit_reference_unavailable"
            assert result["phase"] == "valuation"
            assert result["stored"] == 1
            assert result["operation_requested"] == 1
            assert result["operation_succeeded"] == 0
            assert result["operation_failed"] == 1
            assert quote_sync.prepare_calls == []
            assert quote_provider_ids == []
            assert valuation_provider_ids == [7]
        references = result["raw_audit_references_by_dataset"]
        assert references["equity.quote.snapshot"] == []
        if missing_reference_stage == "valuation":
            assert references["equity.valuation.fact"] == []
        else:
            assert references["equity.valuation.fact"][0]["raw_audit_id"] == (
                "valuation-test-audit"
            )
        return

    assert events == ["refresh_prices", "preview", "publish"]
    assert result["outcome"] == "success"
    assert result["price_scope_verified"] == 1
    assert len(result["publication_ids"]) == 3
    assert len(set(result["publication_ids"])) == 3
    assert result["raw_audit_references"] == [
        {
            "raw_audit_id": "price-raw-0",
            "version": "raw-audit-v1",
            "content_hash": "b" * 64,
            "run_id": "price-request-run",
            "ingested_run_id": "price-request-ingested",
        },
        {
            "raw_audit_id": "price-raw-1",
            "version": "raw-audit-v1",
            "content_hash": "a" * 64,
            "run_id": "price-run-1",
            "ingested_run_id": "price-ingested-1",
        },
    ]
    assert (
        result["raw_audit_references_by_dataset"]["equity.quote.snapshot"][0]["raw_audit_id"]
        == "quote-test-audit"
    )
    assert (
        result["raw_audit_references_by_dataset"]["equity.valuation.fact"][0]["raw_audit_id"]
        == "valuation-test-audit"
    )
    assert (
        result["raw_audit_references_by_dataset"]["equity.price.bar"]
        == result["raw_audit_references"]
    )
    assert result["publication_run_id"] == result["run_id"]
    assert result["quote_source"] == "tushare"
    assert result["valuation_source"] == "akshare"
    assert len(quote_sync.prepare_calls) == 1
    prepare_call = quote_sync.prepare_calls[0]
    assert callable(prepare_call["missing_asset_verifier"])
    assert {
        key: value for key, value in prepare_call.items() if key != "missing_asset_verifier"
    } == {
        "provider_id": 3,
        "asset_codes": ("000001.SZ",),
        "target_trade_date": date(2026, 9, 18),
    }
    assert quote_provider_ids == [3]
    assert valuation_provider_ids == [7]
    assert len(publication_bundles) == 1
    publication_bundle = publication_bundles[0]
    stage_commands = publication_bundle.staged_commands
    assert tuple(stage_commands) == (
        "equity.quote.snapshot",
        "equity.price.bar",
        "equity.valuation.fact",
    )
    assert {command.run_id for command in stage_commands.values()} == {result["publication_run_id"]}
    assert {command.task_attempt_id for command in stage_commands.values()} == {
        "test-full-market-attempt"
    }
    price_stage_bindings = stage_commands["equity.price.bar"].raw_audit_bindings
    assert tuple(item.reference.raw_audit_id for item in price_stage_bindings) == ("price-raw-1",)
    assert tuple(item.expected_source_type for item in price_stage_bindings) == ("tushare",)
    assert len(publication_bundle.activation_requests) == 1
    assert len(publication_bundle.activation_requests[0].candidates) == 3
    assert publication_bundle.bundle_events.count("activation") == 1
    assert publication_bundle.bundle_events.count("current_pointer") == 3
    capture_index = publication_bundle.bundle_events.index("authority_capture")
    assert publication_bundle.bundle_events[capture_index + 1 :] == ["activation"]
    assert len(result["datasets"]) == 3
    assert {item["dataset_key"] for item in result["datasets"]} == {
        "equity.quote.snapshot",
        "equity.price.bar",
        "equity.valuation.fact",
    }
    assert all(item["publication_hash"] for item in result["datasets"])


def test_task_reports_business_outcome_when_publication_hits_soft_time_limit(monkeypatch):
    """A worker timeout must preserve the completed write counts and failed phase."""

    from types import SimpleNamespace

    from apps.data_center.application import market_publication_refresh, public, tasks

    provider_ids = {"tushare": 3, "akshare": 7}
    monkeypatch.setattr(tasks, "get_active_provider_id_by_source", lambda name: provider_ids[name])
    monkeypatch.setattr(tasks, "latest_closed_cn_market_session", lambda _: date(2026, 9, 18))
    monkeypatch.setattr(
        tasks,
        "list_active_stock_codes_for_backfill",
        lambda: ["000001.SZ", "600000.SH"],
    )
    monkeypatch.setattr(
        tasks,
        "sync_active_a_share_universe",
        lambda: _universe_report(["000001.SZ", "600000.SH"]),
    )
    monkeypatch.setattr(
        tasks,
        "make_backfill_sync_quote_use_case",
        lambda: _prefetched_quote_sync(
            lambda *_args, **_kwargs: SimpleNamespace(
                stored_count=2,
                stored_asset_codes=("000001.SZ", "600000.SH"),
            )
        ),
    )
    monkeypatch.setattr(
        tasks,
        "make_backfill_sync_current_valuation_batch_use_case",
        lambda: _audited_valuation_sync(
            lambda *_args, **_kwargs: SimpleNamespace(
                stored_count=2,
                succeeded_asset_codes=("000001.SZ", "600000.SH"),
                returned_asset_codes=("000001.SZ", "600000.SH"),
            )
        ),
    )
    monkeypatch.setattr(
        tasks,
        "make_core_current_publication_rebuild_use_case",
        lambda **_: SimpleNamespace(
            preview=lambda **_: (_ for _ in ()).throw(SoftTimeLimitExceeded()),
            execute=lambda **_: pytest.fail("timed-out preview reached publication"),
        ),
    )
    monkeypatch.setattr(public, "get_model_market_data_port", lambda: object())
    monkeypatch.setattr(
        market_publication_refresh,
        "refresh_market_price_inputs",
        lambda *_: MarketPricePreparationResult(suspended_codes=(), raw_audit_references=()),
    )

    result = tasks.refresh_full_market_publications_task.run(batch_size=2)

    assert result["outcome"] == "failed"
    assert result["requested"] == 3
    assert result["succeeded"] == 2
    assert result["failed"] == 1
    assert result["stored"] == 4
    assert result["phase"] == "publication"
    assert result["error_code"] == "MARKET_REFRESH_SOFT_TIME_LIMIT_EXCEEDED"
    assert result["publication_updated"] is False
    assert result["must_not_use_for_decision"] is True


def test_task_uses_verified_target_date_scope_and_keeps_unknown_provider_gap_requested(
    monkeypatch,
) -> None:
    """Only verified later listing dates leave requested scope; unknown gaps still block."""

    from types import SimpleNamespace

    from apps.data_center.application import tasks

    target = date(2026, 9, 28)
    candidates = ("000001.SZ", "000002.SZ", "301716.SZ", "920202.BJ")
    requested = ("000001.SZ", "000002.SZ")
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(tasks, "get_active_provider_id_by_source", lambda _: 3)
    monkeypatch.setattr(tasks, "latest_closed_cn_market_session", lambda _: target)
    monkeypatch.setattr(
        tasks,
        "sync_active_a_share_universe",
        lambda: _universe_report(list(candidates)),
    )
    monkeypatch.setattr(
        tasks,
        "list_active_stock_codes_for_backfill",
        lambda: list(candidates),
    )
    monkeypatch.setattr(
        tasks,
        "build_target_date_a_share_universe_scope",
        lambda day: TargetDateAssetUniverseScope(
            target_date=day,
            candidate_codes=candidates,
            requested_codes=requested,
            excluded_not_yet_listed=(
                NotYetListedAsset(
                    asset_code="301716.SZ",
                    list_date=date(2026, 9, 29),
                    evidence_source="tushare.new_share[provider_id=7].issue_date",
                ),
                NotYetListedAsset(
                    asset_code="920202.BJ",
                    list_date=date(2026, 9, 29),
                    evidence_source="tushare.stock_basic[provider_id=7].list_date",
                ),
            ),
            unknown_listing_date_codes=("000002.SZ",),
        ),
    )
    monkeypatch.setattr(
        tasks,
        "make_backfill_sync_quote_use_case",
        SimpleNamespace,
    )
    monkeypatch.setattr(
        tasks,
        "make_backfill_sync_current_valuation_batch_use_case",
        lambda: _audited_valuation_sync(
            lambda **kwargs: (
                calls.append(tuple(kwargs["asset_codes"]))
                or SimpleNamespace(
                    stored_count=1,
                    status="partial",
                    succeeded_asset_codes=("000001.SZ",),
                    returned_asset_codes=("000001.SZ",),
                )
            )
        ),
    )
    monkeypatch.setattr(
        tasks,
        "get_publication_policy_repository",
        lambda: SimpleNamespace(get_active=lambda _dataset: None),
    )
    monkeypatch.setattr(
        tasks,
        "make_core_current_publication_rebuild_use_case",
        lambda **_: SimpleNamespace(),
    )

    result = tasks.refresh_full_market_publications_task.run(batch_size=2)

    assert calls == [requested]
    assert result["outcome"] == "blocked"
    assert result["requested_asset_count"] == 2
    assert result["missing_asset_codes"] == ["000002.SZ"]
    assert result["market_universe"]["active_count"] == len(candidates)
    scope_evidence = result["market_universe"]["target_date_scope"]
    assert scope_evidence["candidate_asset_count"] == len(candidates)
    assert scope_evidence["requested_asset_count"] == len(requested)
    assert scope_evidence["unknown_listing_date_codes_sample"] == ["000002.SZ"]
    assert scope_evidence["excluded_not_yet_listed_count"] == 2
    assert [item["asset_code"] for item in scope_evidence["excluded_not_yet_listed_evidence"]] == [
        "301716.SZ",
        "920202.BJ",
    ]
