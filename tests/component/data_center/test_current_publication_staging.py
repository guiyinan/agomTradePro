"""Component contracts for fence-external current-publication candidate staging."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from django.db import connection

from apps.data_center.application.current_publication_rebuild import (
    CurrentPublicationDataset,
    CurrentPublicationRebuildUseCase,
    CurrentPublicationScopeExclusion,
)
from apps.data_center.application.current_publication_staging import (
    CurrentPublicationStageCommand,
    CurrentPublicationStageRawAuditBinding,
    CurrentPublicationStagingError,
    CurrentPublicationStagingUseCase,
)
from apps.data_center.application.current_valuation_sync import SyncCurrentValuationBatchUseCase
from apps.data_center.domain.contracts import DatasetKey, PublicationPolicy
from apps.data_center.domain.control_plane import PublicationState
from apps.data_center.domain.entities import ProviderConfig, RawAudit
from apps.data_center.domain.market_time import cn_market_session_close_utc
from apps.data_center.domain.raw_audit_manifest import CandidateRawAuditManifestError
from apps.data_center.infrastructure._provider_adapter_akshare import AkshareUnifiedProviderAdapter
from apps.data_center.infrastructure.audited_sync_runtime import (
    DjangoDataCenterSyncUnitOfWork,
    DjangoSyncExecutionIdentityIssuer,
)
from apps.data_center.infrastructure.candidate_raw_audit_manifest_models import (
    CandidateRawAuditManifestMemberModel,
    CandidateRawAuditManifestModel,
)
from apps.data_center.infrastructure.candidate_raw_audit_metadata_resolver import (
    DjangoCandidateRawAuditMetadataResolver,
)
from apps.data_center.infrastructure.control_plane_repositories import (
    CanonicalPublicationRepository,
    SyncExecutionIdentityRepository,
)
from apps.data_center.infrastructure.current_publication_staging_repository import (
    DjangoCurrentPublicationStagingRepository,
)
from apps.data_center.infrastructure.gateways.tencent_gateway import TencentGateway
from apps.data_center.infrastructure.market_gateway_entities import ValuationSnapshot
from apps.data_center.infrastructure.models import (
    CanonicalPublicationModel,
    CanonicalPublicationPointerModel,
    PriceBarModel,
    PublicationMemberModel,
    QuoteSnapshotModel,
    RawAuditModel,
)
from apps.data_center.infrastructure.price_bar_repository import PriceBarRepository
from apps.data_center.infrastructure.provider_state_repositories import RawAuditRepository
from apps.data_center.infrastructure.publication_policy_repository import (
    PublicationPolicyRepository,
)
from apps.data_center.infrastructure.valuation_fact_repository import ValuationFactRepository
from apps.data_center.publication_candidate_activation_composition import (
    build_production_current_market_publication_bundle,
)

pytestmark = pytest.mark.django_db(transaction=True)

DATASET = CurrentPublicationDataset(
    dataset_key="equity.price.bar",
    fact_table="data_center_price_bar",
    created_by="ops.current_publication_rebuild",
)
PUBLISHED_AT = datetime(2026, 10, 2, 1, 0, tzinfo=UTC)
SOURCE_TYPE = "tushare"


class _PolicyRepository:
    def get_active(self, dataset_key: str) -> PublicationPolicy:
        return PublicationPolicy(
            dataset=DatasetKey(dataset_key, "1.0", "1.0"),
            minimum_coverage_ratio=1.0,
            allow_partial=False,
            conflict_action="block",
            required_evidence=("source", "observed_at", "payload_hash"),
            retention_days=3650,
        )


def _stage_case(
    *,
    source_type: str | None = SOURCE_TYPE,
    capability: str = "historical_price",
    fact_ingested_run_id: str | None = None,
) -> tuple[
    CurrentPublicationStagingUseCase,
    DjangoCurrentPublicationStagingRepository,
    CurrentPublicationStageCommand,
    str,
]:
    """Create one real price fact, its RawAudit row, and an isolated stage use case."""

    ingested_run_id = fact_ingested_run_id or str(uuid4())
    fact = PriceBarModel._default_manager.create(
        asset_code="000001.SZ",
        bar_date=date(2026, 9, 30),
        freq="1d",
        adjustment="none",
        open=10.0,
        high=11.0,
        low=9.5,
        close=10.5,
        source=SOURCE_TYPE,
        source_record_id="price-row-1",
        raw_payload_hash="a" * 64,
        quality_status="accepted",
        revision_number=1,
        ingested_run_id=ingested_run_id,
    )
    assert fact.pk is not None
    PriceBarModel._default_manager.filter(pk=fact.pk).update(
        fetched_at=datetime(2026, 10, 1, 7, 59, tzinfo=UTC),
    )
    extra: dict[str, object] = {}
    if source_type is not None:
        extra["source_type"] = source_type
    raw = RawAuditRepository().log(
        RawAudit(
            provider_name="tushare-provider",
            capability=capability,
            request_params={"asset_code": "000001.SZ"},
            status="ok",
            row_count=1,
            fetched_at=datetime(2026, 10, 1, 8, 0, tzinfo=UTC),
            extra=extra,
            run_id=str(uuid4()),
            ingested_run_id=ingested_run_id,
        )
    )
    raw_reference = raw.exact_reference()
    command = CurrentPublicationStageCommand(
        asset_codes=("000001.SZ",),
        published_at=PUBLISHED_AT,
        run_id=str(uuid4()),
        task_attempt_id="current-market-attempt-1",
        raw_audit_bindings=(
            CurrentPublicationStageRawAuditBinding(
                reference=raw_reference,
                expected_source_type=SOURCE_TYPE,
            ),
        ),
    )
    rebuilder = CurrentPublicationRebuildUseCase(
        dataset=DATASET,
        candidate_repository=PriceBarRepository(),
        publication_repository=CanonicalPublicationRepository(),
        policy_repository=_PolicyRepository(),
    )
    stage_repository = DjangoCurrentPublicationStagingRepository()
    use_case = CurrentPublicationStagingUseCase(
        rebuilder=rebuilder,
        raw_audit_resolver=DjangoCandidateRawAuditMetadataResolver(),
        repository=stage_repository,
    )
    return use_case, stage_repository, command, ingested_run_id


def _assert_no_partial_stage() -> None:
    assert CanonicalPublicationModel._default_manager.count() == 0
    assert PublicationMemberModel._default_manager.count() == 0
    assert CandidateRawAuditManifestModel._default_manager.count() == 0
    assert CandidateRawAuditManifestMemberModel._default_manager.count() == 0
    assert CanonicalPublicationPointerModel._default_manager.count() == 0


def test_valuation_sync_reference_stages_actual_source_and_rejects_route_binding_postgresql(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bind a real AKShare valuation adapter's Tencent facts through exact audit staging."""

    asset_code = "000001.SZ"
    target_date = date(2026, 9, 30)
    observed_at = cn_market_session_close_utc(target_date)
    fetched_at = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
    config = ProviderConfig(
        id=71,
        name="AKShare Public",
        source_type="akshare",
        is_active=True,
        priority=1,
        api_key="",
        api_secret="",
        http_url="",
        api_endpoint="",
        extra_config={},
        description="",
    )
    monkeypatch.setattr(
        TencentGateway,
        "get_valuation_snapshots",
        lambda _gateway, codes: [
            ValuationSnapshot(
                stock_code=asset_code,
                observed_at=observed_at,
                pe_ttm=12.5,
                pb=1.5,
                source="tencent",
                available_at=fetched_at,
                fetched_at=fetched_at,
                raw_payload_hash="a" * 64,
                source_record_id="tencent:valuation:000001.SZ",
                raw_payload_scope="batch_response_body",
            )
            for code in codes
            if code == asset_code
        ],
    )
    adapter = AkshareUnifiedProviderAdapter(config)

    class ProviderConfigRepository:
        unit_of_work_key = "django:default"

        def get_by_id(self, provider_id: int) -> ProviderConfig:
            assert provider_id == config.id
            return config

        def save(self, value: ProviderConfig) -> ProviderConfig:
            return value

    class ProviderRegistry:
        def get_by_id(self, provider_id: int) -> AkshareUnifiedProviderAdapter:
            assert provider_id == config.id
            return adapter

        def record_success(self, *_args: object) -> None:
            return None

        def record_failure(self, *_args: object) -> None:
            return None

        def get_all_statuses(self) -> list[object]:
            return []

    class FetchAuditWriter:
        database_alias = "default"

        def write(self, _observation: object) -> object:
            assert connection.in_atomic_block
            return object()

    class Clock:
        def now(self) -> datetime:
            return fetched_at

    provider_repository = ProviderConfigRepository()
    fact_repository = ValuationFactRepository()
    raw_audit_repository = RawAuditRepository()
    identity_repository = SyncExecutionIdentityRepository()
    fetch_audit_writer = FetchAuditWriter()
    sync = SyncCurrentValuationBatchUseCase(
        provider_repo=provider_repository,
        provider_registry=ProviderRegistry(),
        fact_repo=fact_repository,
        raw_audit_repo=raw_audit_repository,
        sync_identity_issuer=DjangoSyncExecutionIdentityIssuer(identity_repository),
        sync_unit_of_work=DjangoDataCenterSyncUnitOfWork(
            (
                provider_repository,
                fact_repository,
                raw_audit_repository,
                identity_repository,
            ),
            fetch_audit_writer,
        ),
        data_fetch_audit_writer=fetch_audit_writer,
        clock=Clock(),
    )

    result = sync.execute(
        provider_id=config.id or 0,
        asset_codes=[asset_code],
        as_of_date=target_date,
        require_exact_asset_codes=True,
    )

    fact = fact_repository.get_latest(asset_code)
    assert fact is not None
    assert fact.source == "tencent"
    assert result.fact_source_type == "tencent"
    raw_audit = RawAuditModel._default_manager.get(pk=result.raw_audit_reference.raw_audit_id)
    assert raw_audit.extra == {
        "source_type": "tencent",
        "provider_source_type": "akshare",
    }
    assert raw_audit.content_hash == result.raw_audit_reference.content_hash

    valuation_dataset = CurrentPublicationDataset(
        dataset_key="equity.valuation.fact",
        fact_table="data_center_valuation_fact",
        created_by="ops.current_publication_rebuild",
    )
    rebuilder = CurrentPublicationRebuildUseCase(
        dataset=valuation_dataset,
        candidate_repository=fact_repository,
        publication_repository=CanonicalPublicationRepository(),
        policy_repository=_PolicyRepository(),
    )
    staging = CurrentPublicationStagingUseCase(
        rebuilder=rebuilder,
        raw_audit_resolver=DjangoCandidateRawAuditMetadataResolver(),
        repository=DjangoCurrentPublicationStagingRepository(),
    )
    binding = CurrentPublicationStageRawAuditBinding(
        reference=result.raw_audit_reference,
        expected_source_type=result.fact_source_type or "",
    )
    command = CurrentPublicationStageCommand(
        asset_codes=(asset_code,),
        published_at=PUBLISHED_AT,
        run_id=str(uuid4()),
        task_attempt_id="valuation-source-stage-actual",
        raw_audit_bindings=(binding,),
        required_observation_date=target_date,
    )

    staged = staging.execute(command)

    assert staged.publication.state is PublicationState.CANDIDATE
    assert staged.manifest.raw_audits[0].raw_audit_id == result.raw_audit_reference.raw_audit_id
    pointer = CanonicalPublicationPointerModel._default_manager.get(
        dataset_key=valuation_dataset.dataset_key,
        publication_key="current",
    )
    assert pointer.publication_id is None

    forged_route_command = replace(
        command,
        task_attempt_id="valuation-source-stage-forged-route",
        raw_audit_bindings=(replace(binding, expected_source_type="akshare"),),
    )
    with pytest.raises(CurrentPublicationStagingError, match="source_type does not match"):
        staging.execute(forged_route_command)

    pointer.refresh_from_db()
    assert pointer.publication_id is None


def test_stage_builds_sealed_candidate_and_manifest_with_empty_lockable_pointer() -> None:
    use_case, _repository, command, _ingested_run_id = _stage_case()

    assert CanonicalPublicationPointerModel._default_manager.count() == 0

    staged = use_case.execute(command)
    persisted = CanonicalPublicationModel._default_manager.get(
        publication_id=staged.publication.publication_id
    )

    assert staged.publication.state is PublicationState.CANDIDATE
    assert staged.publication.member_count == 1
    assert staged.publication.published_at is None
    assert staged.publication.coverage.requested_count == 1
    assert staged.publication.coverage.eligible_count == 1
    assert staged.publication.coverage.selected_count == 1
    assert staged.publication.coverage.missing_count == 0
    assert staged.manifest.task_attempt_id == command.task_attempt_id
    assert staged.manifest.raw_audit_count == 1
    assert persisted.members_sealed_at is not None
    assert persisted.member_manifest_hash
    pointer = CanonicalPublicationPointerModel._default_manager.select_for_update().get(
        dataset_key=DATASET.dataset_key,
        publication_key="current",
    )
    assert pointer.publication_id is None
    assert pointer.publication_hash == ""
    assert pointer.activation_id == ""


@pytest.mark.parametrize(
    ("dataset_key", "stage_attribute", "capability"),
    [
        ("equity.quote.snapshot", "quote_staging", "realtime_quote"),
        ("equity.price.bar", "price_staging", "historical_price"),
    ],
)
def test_production_bundle_stages_suspension_scope_with_selected_members(
    dataset_key: str,
    stage_attribute: str,
    capability: str,
) -> None:
    """Production quote and price staging validate suspensions with frozen members."""

    active_codes = ("000001.SZ", "000003.SZ")
    suspended_code = "000002.SZ"
    target_date = date(2026, 9, 30)
    target_close = cn_market_session_close_utc(target_date)
    published_at = target_close + timedelta(minutes=5)
    ingested_run_id = str(uuid4())
    policy = PublicationPolicy(
        dataset=DatasetKey(dataset_key, "1.0", "1.0"),
        minimum_coverage_ratio=1.0,
        allow_partial=False,
        conflict_action="block",
        required_evidence=(
            "source",
            "observed_at",
            "fetched_at",
            "payload_hash",
            "fact_content_hash",
        ),
        retention_days=3650,
        policy_version="candidate-stage-test-v1",
    )
    PublicationPolicyRepository().save(policy)

    if dataset_key == "equity.price.bar":
        for active_code in active_codes:
            fact = PriceBarModel._default_manager.create(
                asset_code=active_code,
                bar_date=target_date,
                freq="1d",
                adjustment="none",
                open=10.0,
                high=11.0,
                low=9.5,
                close=10.5,
                source=SOURCE_TYPE,
                source_record_id=f"price-row-suspension-stage-{active_code}",
                raw_payload_hash="a" * 64,
                quality_status="accepted",
                revision_number=1,
                ingested_run_id=ingested_run_id,
            )
            assert fact.pk is not None
            PriceBarModel._default_manager.filter(pk=fact.pk).update(fetched_at=published_at)
    else:
        for active_code in active_codes:
            QuoteSnapshotModel._default_manager.create(
                asset_code=active_code,
                snapshot_at=target_close,
                fetched_at=published_at,
                current_price=10.5,
                source=SOURCE_TYPE,
                source_record_id=f"quote-row-suspension-stage-{active_code}",
                raw_payload_hash="a" * 64,
                quality_status="accepted",
                revision_number=1,
                ingested_run_id=ingested_run_id,
            )

    raw = RawAuditRepository().log(
        RawAudit(
            provider_name="tushare-provider",
            capability=capability,
            request_params={"asset_codes": [*active_codes, suspended_code]},
            status="ok",
            row_count=len(active_codes),
            fetched_at=published_at,
            extra={"source_type": SOURCE_TYPE},
            run_id=str(uuid4()),
            ingested_run_id=ingested_run_id,
        )
    )
    command = CurrentPublicationStageCommand(
        asset_codes=(*active_codes, suspended_code),
        published_at=published_at,
        run_id=str(uuid4()),
        task_attempt_id="market-suspension-stage-1",
        raw_audit_bindings=(
            CurrentPublicationStageRawAuditBinding(
                reference=raw.exact_reference(),
                expected_source_type=SOURCE_TYPE,
            ),
        ),
        scope_exclusions=(
            CurrentPublicationScopeExclusion(
                asset_code=suspended_code,
                reason_code=(
                    "quote_full_day_suspension"
                    if dataset_key == "equity.quote.snapshot"
                    else "price_full_day_suspension"
                ),
                target_trade_date=target_date,
                evidence_source="tushare.suspend_d",
            ),
        ),
        required_observation_date=target_date,
    )
    bundle = build_production_current_market_publication_bundle()
    staging = getattr(bundle, stage_attribute)
    candidate = staging._rebuilder.prepare_candidate(
        asset_codes=command.asset_codes,
        published_at=command.published_at,
        run_id=command.run_id,
        scope_exclusions=command.scope_exclusions,
        required_observation_date=command.required_observation_date,
    )

    # A metadata-only save still fails closed when its selected member evidence is absent.
    with pytest.raises(ValueError, match="Market suspension scope requires selected members"):
        CanonicalPublicationRepository().save(candidate.publication)

    member_repository = CanonicalPublicationRepository()
    mismatched_members = (
        (candidate.members[0],),
        (
            replace(candidate.members[0], publication_id=str(uuid4())),
            candidate.members[1],
        ),
        (
            candidate.members[0],
            replace(
                candidate.members[1],
                member_id=str(uuid4()),
                natural_key=candidate.members[0].natural_key,
            ),
        ),
    )
    expected_errors = (
        "Publication member_count does not match supplied members",
        "Publication member publication_id mismatch",
        "Publication members must have unique natural_key values",
    )
    for members, message in zip(mismatched_members, expected_errors, strict=True):
        with pytest.raises(ValueError, match=message):
            member_repository.save_candidate_with_members(candidate.publication, members)

    invalid_coverage = replace(
        candidate.publication,
        coverage=replace(candidate.publication.coverage, selected_count=1),
    )
    with pytest.raises(
        ValueError, match="Publication member_count must match selected coverage count"
    ):
        member_repository.save_candidate_with_members(invalid_coverage, candidate.members)

    without_as_of = replace(candidate.publication, as_of=None)
    with pytest.raises(ValueError, match="Publication member snapshot requires an as_of boundary"):
        member_repository.save_candidate_with_members(without_as_of, candidate.members)

    incomplete_block = replace(candidate.publication.scope_blocks[0], evidence_source="")
    invalid_publication = replace(
        candidate.publication,
        scope_blocks=(incomplete_block,),
    )
    with pytest.raises(ValueError, match="Market suspension scope block evidence is incomplete"):
        member_repository.save_candidate_with_members(
            invalid_publication,
            candidate.members,
        )
    assert not CanonicalPublicationModel._default_manager.filter(
        publication_id=candidate.publication.publication_id
    ).exists()

    staged = staging.execute(command)
    persisted_members = CanonicalPublicationRepository().list_members(
        staged.publication.publication_id
    )
    assert staged.publication.state is PublicationState.CANDIDATE
    assert staged.publication.coverage.requested_count == 3
    assert staged.publication.coverage.eligible_count == 2
    assert staged.publication.coverage.selected_count == 2
    assert staged.publication.coverage.missing_count == 1
    assert tuple(persisted_members) == candidate.members
    assert staged.publication.scope_blocks[0].asset_code == suspended_code
    assert staged.publication.scope_blocks[0].evidence_source == "tushare.suspend_d"


def test_exact_attempt_retry_is_idempotent_and_changed_manifest_fails_closed() -> None:
    use_case, _repository, command, ingested_run_id = _stage_case()
    staged = use_case.execute(command)
    retried = use_case.execute(command)

    assert retried.publication.publication_id == staged.publication.publication_id
    assert retried.manifest.manifest_id == staged.manifest.manifest_id
    assert CanonicalPublicationModel._default_manager.count() == 1
    assert PublicationMemberModel._default_manager.count() == 1
    assert CandidateRawAuditManifestModel._default_manager.count() == 1

    changed_attempt = replace(command, task_attempt_id="current-market-attempt-2")
    with pytest.raises(CurrentPublicationStagingError, match="task-attempt"):
        use_case.execute(changed_attempt)

    second_raw = RawAuditRepository().log(
        RawAudit(
            provider_name="tushare-provider",
            capability="historical_price",
            request_params={"asset_code": "000001.SZ", "retry": 2},
            status="ok",
            row_count=1,
            fetched_at=datetime(2026, 10, 1, 8, 1, tzinfo=UTC),
            extra={"source_type": SOURCE_TYPE},
            run_id=str(uuid4()),
            ingested_run_id=ingested_run_id,
        )
    )
    changed_manifest = replace(
        command,
        raw_audit_bindings=(
            CurrentPublicationStageRawAuditBinding(
                reference=second_raw.exact_reference(),
                expected_source_type=SOURCE_TYPE,
            ),
        ),
    )
    with pytest.raises(CurrentPublicationStagingError, match="different immutable"):
        use_case.execute(changed_manifest)
    assert CandidateRawAuditManifestModel._default_manager.count() == 1
    assert CandidateRawAuditManifestMemberModel._default_manager.count() == 1


@pytest.mark.parametrize(
    "task_attempt_id",
    ["attempt\n2", "attempt\r2", "x" * 161],
)
def test_stage_command_rejects_unbounded_or_multiline_task_attempt_ids(
    task_attempt_id: str,
) -> None:
    _use_case, _repository, command, _ingested_run_id = _stage_case()

    with pytest.raises(CurrentPublicationStagingError, match="task_attempt_id"):
        replace(command, task_attempt_id=task_attempt_id)


@pytest.mark.parametrize("run_id", ["", "not-a-uuid", "\n", str(uuid4()).upper()])
def test_stage_command_requires_canonical_uuid_run_id(run_id: str) -> None:
    _use_case, _repository, command, _ingested_run_id = _stage_case()

    with pytest.raises(CurrentPublicationStagingError, match="canonical run id"):
        replace(command, run_id=run_id)


@pytest.mark.parametrize(
    ("source_type", "capability", "expected_source_type", "message"),
    [
        (None, "historical_price", SOURCE_TYPE, "source_type metadata is missing"),
        ("akshare", "historical_price", SOURCE_TYPE, "source_type does not match"),
        (SOURCE_TYPE, "valuation", SOURCE_TYPE, "capability does not match"),
    ],
)
def test_raw_audit_source_metadata_and_dataset_capability_fail_closed(
    source_type: str | None,
    capability: str,
    expected_source_type: str,
    message: str,
) -> None:
    use_case, _repository, command, _ingested_run_id = _stage_case(
        source_type=source_type,
        capability=capability,
    )
    command = replace(
        command,
        raw_audit_bindings=(
            replace(
                command.raw_audit_bindings[0],
                expected_source_type=expected_source_type,
            ),
        ),
    )

    with pytest.raises(CurrentPublicationStagingError, match=message) as error:
        use_case.execute(command)
    assert error.value.code == "CURRENT_PUBLICATION_STAGING_INVALID"
    _assert_no_partial_stage()


def test_missing_raw_reference_and_hash_or_run_identity_drift_fail_closed() -> None:
    use_case, _repository, command, _ingested_run_id = _stage_case()
    binding = command.raw_audit_bindings[0]
    missing_reference = replace(binding.reference, raw_audit_id="999999999")
    with pytest.raises(CurrentPublicationStagingError, match="missing"):
        use_case.execute(
            replace(
                command,
                raw_audit_bindings=(replace(binding, reference=missing_reference),),
            )
        )

    raw_id = int(binding.reference.raw_audit_id)
    RawAuditModel._default_manager.filter(pk=raw_id).update(content_hash="0" * 64)
    with pytest.raises(CurrentPublicationStagingError, match="identity or content hash"):
        use_case.execute(command)
    _assert_no_partial_stage()


def test_foreign_ingestion_run_cannot_bind_candidate_facts() -> None:
    foreign_ingested_run_id = str(uuid4())
    use_case, _repository, _command, _ingested_run_id = _stage_case(
        fact_ingested_run_id=foreign_ingested_run_id,
    )
    command = _request_with_foreign_raw_ingestion(use_case, foreign_ingested_run_id)

    with pytest.raises(CurrentPublicationStagingError, match="foreign or missing ingestion run"):
        use_case.execute(command)
    _assert_no_partial_stage()


def _request_with_foreign_raw_ingestion(
    use_case: CurrentPublicationStagingUseCase,
    fact_ingested_run_id: str,
) -> CurrentPublicationStageCommand:
    """Create a valid audit reference whose ingestion identity does not own the fact."""

    del use_case
    raw = RawAuditRepository().log(
        RawAudit(
            provider_name="tushare-provider",
            capability="historical_price",
            request_params={"asset_code": "000001.SZ", "foreign": True},
            status="ok",
            row_count=1,
            fetched_at=datetime(2026, 10, 1, 8, 2, tzinfo=UTC),
            extra={"source_type": SOURCE_TYPE},
            run_id=str(uuid4()),
            ingested_run_id=str(uuid4()),
        )
    )
    return CurrentPublicationStageCommand(
        asset_codes=("000001.SZ",),
        published_at=PUBLISHED_AT,
        run_id=str(uuid4()),
        task_attempt_id="current-market-attempt-1",
        raw_audit_bindings=(
            CurrentPublicationStageRawAuditBinding(
                reference=raw.exact_reference(),
                expected_source_type=SOURCE_TYPE,
            ),
        ),
    )


@pytest.mark.parametrize("failure_stage", ["candidate", "members", "seal", "manifest"])
def test_any_candidate_bundle_write_failure_rolls_back_every_row(
    failure_stage: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_case, repository, command, _ingested_run_id = _stage_case()
    injected = CandidateRawAuditManifestError(f"injected {failure_stage} write failure")

    if failure_stage == "candidate":
        original = repository._publications.save_candidate_with_members

        def fail_after_candidate_write(publication, members):
            original(publication, members)
            raise injected

        monkeypatch.setattr(
            repository._publications,
            "save_candidate_with_members",
            fail_after_candidate_write,
        )
    elif failure_stage == "members":
        original = repository._persist_members

        def fail_after_member_write(members):
            original(members)
            raise injected

        monkeypatch.setattr(repository, "_persist_members", fail_after_member_write)
    elif failure_stage == "seal":
        original = repository._seal_candidate

        def fail_after_seal(candidate, members):
            original(candidate, members)
            raise injected

        monkeypatch.setattr(repository, "_seal_candidate", fail_after_seal)
    else:
        original = repository._manifests.stage

        def fail_after_manifest_write(manifest):
            original(manifest)
            raise injected

        monkeypatch.setattr(repository._manifests, "stage", fail_after_manifest_write)

    with pytest.raises(CurrentPublicationStagingError, match=f"injected {failure_stage}"):
        use_case.execute(command)
    _assert_no_partial_stage()


def test_legacy_published_same_id_is_never_adopted_as_candidate() -> None:
    use_case, repository, command, _ingested_run_id = _stage_case()
    candidate = repository._publications
    prepared = use_case._rebuilder.prepare_candidate(
        asset_codes=command.asset_codes,
        published_at=command.published_at,
        run_id=command.run_id,
        scope_exclusions=command.scope_exclusions,
        required_observation_date=command.required_observation_date,
    )
    candidate.save(prepared.publication)
    CanonicalPublicationModel._default_manager.filter(
        publication_id=prepared.publication.publication_id
    ).update(state=PublicationState.PUBLISHED.value)

    with pytest.raises(CurrentPublicationStagingError, match="cannot be adopted"):
        use_case.execute(command)

    persisted = CanonicalPublicationModel._default_manager.get(
        publication_id=prepared.publication.publication_id
    )
    assert persisted.state == PublicationState.PUBLISHED.value
    assert persisted.members_sealed_at is None
    assert CandidateRawAuditManifestModel._default_manager.count() == 0
    assert CanonicalPublicationPointerModel._default_manager.count() == 0


def test_rawaudit_source_metadata_hash_drift_is_detected_before_staging() -> None:
    use_case, _repository, command, _ingested_run_id = _stage_case()
    raw_id = int(command.raw_audit_bindings[0].reference.raw_audit_id)
    row = RawAuditModel._default_manager.get(pk=raw_id)
    extra = dict(row.extra)
    extra["source_type"] = "akshare"
    RawAuditModel._default_manager.filter(pk=raw_id).update(extra=extra)

    with pytest.raises(CurrentPublicationStagingError, match="identity or content hash"):
        use_case.execute(command)
    _assert_no_partial_stage()


def test_source_type_run_identity_is_explicit_and_not_inferred_from_provider_config() -> None:
    use_case, _repository, command, _ingested_run_id = _stage_case()
    binding = command.raw_audit_bindings[0]
    altered_run = replace(binding.reference, run_id=str(uuid4()))

    with pytest.raises(CurrentPublicationStagingError, match="identity or content hash"):
        use_case.execute(
            replace(
                command,
                raw_audit_bindings=(replace(binding, reference=altered_run),),
            )
        )
    _assert_no_partial_stage()
