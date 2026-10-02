"""Candidate/member/current-pointer activation contracts on the real ORM."""

from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from django.db import connection, transaction

from apps.audit.domain.system_audit_event import AuditOutcome, AuditScopeRef
from apps.audit.infrastructure.publication_activation_audit_writer import (
    DjangoPublicationActivationAuditWriter,
)
from apps.audit.infrastructure.system_audit_event_outbox_coordinator import (
    DjangoSystemAuditEventOutboxCoordinator,
)
from apps.audit.infrastructure.system_audit_models import SystemAuditEventModel
from apps.audit.infrastructure.system_audit_outbox_models import SystemAuditOutboxModel
from apps.data_center.application.publication_activation import (
    ActivateCanonicalPublicationGroupUseCase,
    ActivateCanonicalPublicationUseCase,
    PublicationActivationError,
    PublicationActivationGroupCandidate,
    PublicationActivationGroupRequest,
    PublicationActivationRequest,
)
from apps.data_center.application.publication_utils import (
    member_reference,
    publication_hash,
    publication_member_from_reference,
)
from apps.data_center.domain.contracts import DatasetKey, PublicationPolicy
from apps.data_center.domain.control_plane import (
    CanonicalPublication,
    CoverageSnapshot,
    PublicationState,
)
from apps.data_center.domain.entities import RawAudit, ValuationFact
from apps.data_center.domain.raw_audit_manifest import (
    CandidateRawAuditManifest,
    CandidateRawAuditReference,
    canonical_capability_for_publication_dataset,
)
from apps.data_center.infrastructure.candidate_raw_audit_manifest_models import (
    CandidateRawAuditManifestMemberModel,
    CandidateRawAuditManifestModel,
)
from apps.data_center.infrastructure.candidate_raw_audit_manifest_repository import (
    DjangoCandidateRawAuditManifestRepository,
)
from apps.data_center.infrastructure.control_plane_repositories import (
    CanonicalPublicationRepository,
)
from apps.data_center.infrastructure.models import (
    CanonicalPublicationModel,
    CanonicalPublicationPointerModel,
    NewsFactModel,
    PriceBarModel,
    PublicationMemberModel,
    QuoteSnapshotModel,
    RawAuditModel,
    ValuationFactModel,
)
from apps.data_center.infrastructure.provider_state_repositories import RawAuditRepository
from apps.data_center.infrastructure.publication_activation_repository import (
    DjangoPublicationActivationRepository,
)
from apps.data_center.infrastructure.publication_fact_evidence import (
    publication_fact_reference_for_dataset,
)
from apps.data_center.infrastructure.publication_group_activation_state import (
    PublicationGroupActivationStateWriter,
)
from apps.data_center.infrastructure.publication_policy_repository import (
    PublicationPolicyRepository,
)
from apps.data_center.infrastructure.valuation_fact_repository import ValuationFactRepository
from core.integration.data_center_audit import (
    DataPublicationAuditObservation,
    SystemAuditEventOutboxCommit,
)
from tests.component.data_center.test_current_publication_evidence_gate import _published_snapshot

pytestmark = pytest.mark.django_db(transaction=True)


class _AuditWriter(DjangoPublicationActivationAuditWriter):
    """Required event/outbox seam used without production composition."""

    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[tuple[str, str]] = []
        self.fail = fail
        self.coordinator = DjangoSystemAuditEventOutboxCoordinator()
        super().__init__(self.coordinator)

    def append_required(self, *, request, publication, members, observation):
        assert connection.in_atomic_block
        if self.fail:
            raise RuntimeError("required audit/outbox failure")
        assert len(members) == publication.member_count
        assert observation.recorded_at <= datetime.now(UTC)
        commit = super().append_required(
            request=request,
            publication=publication,
            members=members,
            observation=observation,
        )
        assert isinstance(commit, SystemAuditEventOutboxCommit)
        self.calls.append((request.activation_id, publication.publication_id))
        return commit


class _AuthorityFence:
    """Feature-off fence seam that owns the real outer transaction in tests."""

    @contextmanager
    def fence_complete(self, proof):
        assert proof == "proof"
        with transaction.atomic():
            checked_at = datetime.now(UTC)
            yield _FenceResult(
                checked_at=checked_at,
                valid_until=checked_at + timedelta(hours=1),
            )


@dataclass(frozen=True)
class _FenceFingerprint:
    complete_graph_hash: str = "f" * 64


@dataclass(frozen=True)
class _FenceResult:
    database_alias: str = "default"
    tenant_id: str = "tenant-1"
    owner_id: str = "owner-1"
    generation: int = 1
    fingerprint: _FenceFingerprint = _FenceFingerprint()
    checked_at: datetime = datetime.now(UTC)
    valid_until: datetime = datetime.now(UTC) + timedelta(hours=1)
    scope: str = "account_authority_complete_graph"


def _successor_candidate(
    publication_id: str,
    *,
    source_fact: ValuationFact,
    policy_version: str,
    run_id: str,
) -> tuple[CanonicalPublication, object]:
    reference = ValuationFactRepository().list_publication_candidates([source_fact])[0]
    member = publication_member_from_reference(
        reference,
        member_id=str(uuid4()),
        publication_id=publication_id,
        dataset_key="equity.valuation.fact",
    )
    generated_at = datetime.now(UTC)
    candidate = CanonicalPublication(
        publication_id=publication_id,
        dataset_key="equity.valuation.fact",
        publication_key="current",
        policy_version=policy_version,
        state=PublicationState.CANDIDATE,
        selected_source=source_fact.source,
        publication_hash=publication_hash(
            [member_reference(member)],
            policy_identity=policy_version if policy_version.startswith("p2:") else None,
        ),
        coverage=CoverageSnapshot(
            coverage_id=str(uuid4()),
            publication_id=publication_id,
            requested_count=1,
            eligible_count=1,
            selected_count=1,
            missing_count=0,
            conflict_count=0,
            generated_at=generated_at,
        ),
        member_count=1,
        as_of=reference.observed_at,
        created_by="test.activation",
        run_id=run_id,
    )
    return candidate, member


def _stage_successor(
    old_publication,
    *,
    stage: bool = True,
) -> tuple[CanonicalPublication, object, object, RawAudit]:
    current_member = CanonicalPublicationRepository().list_members(old_publication.publication_id)[
        0
    ]
    old_model = ValuationFactModel.objects.get(pk=current_member.fact_pk)
    successor = ValuationFact(
        asset_code=old_model.asset_code,
        val_date=old_model.val_date,
        pe_ttm=99.0,
        pb=9.0,
        dv_ratio=0.99,
        source=old_model.source,
        observed_at=old_model.observed_at,
        available_at=old_model.available_at,
        fetched_at=old_model.fetched_at + timedelta(seconds=1),
        extra=old_model.extra or {},
        source_record_id="activation-successor-" + uuid4().hex,
        raw_payload_hash="c" * 64,
    )
    assert ValuationFactRepository().bulk_upsert([successor]) == 1
    raw = RawAuditRepository().log(
        RawAudit(
            provider_name=old_model.source,
            capability="valuation",
            request_params={"asset_code": old_model.asset_code},
            status="ok",
            row_count=1,
            fetched_at=successor.fetched_at,
            run_id=str(uuid4()),
            ingested_run_id=str(uuid4()),
            response_payload_hash="d" * 64,
            schema_fingerprint="e" * 64,
            parser_version="test",
        )
    )
    candidate, member = _successor_candidate(
        str(uuid4()),
        source_fact=successor,
        policy_version=old_publication.policy_version,
        run_id=raw.run_id,
    )
    if stage:
        DjangoPublicationActivationRepository().stage_candidate_with_members(candidate, (member,))
    return candidate, member, old_model, raw


def _published_news_snapshot():
    """Create a supported non-market-bundle current publication for single-UOW tests."""

    now = datetime.now(UTC)
    observed_at = now - timedelta(minutes=2)
    source = "activation-news-test"
    policy = PublicationPolicy(
        dataset=DatasetKey("market.news", "1.0", "1.0"),
        minimum_coverage_ratio=1.0,
        allow_partial=False,
        conflict_action="block",
        required_evidence=("source", "observed_at", "payload_hash"),
        retention_days=3650,
    )
    PublicationPolicyRepository().save(policy)
    ingested_run_id = uuid4()
    fact = NewsFactModel.objects.create(
        asset_code="000001.SZ",
        title="activation test news",
        summary="",
        url="",
        published_at=observed_at,
        source=source,
        external_id="activation-news-" + uuid4().hex,
        source_record_id="activation-news-record-" + uuid4().hex,
        raw_payload_hash="a" * 64,
        quality_status="accepted",
        revision_number=1,
        ingested_run_id=ingested_run_id,
        available_at=observed_at,
    )
    reference = publication_fact_reference_for_dataset(fact, dataset_key="market.news")
    publication_id = str(uuid4())
    member = publication_member_from_reference(
        reference,
        member_id=str(uuid4()),
        publication_id=publication_id,
        dataset_key="market.news",
    )
    run_id = str(uuid4())
    publication = CanonicalPublication(
        publication_id=publication_id,
        dataset_key="market.news",
        publication_key="current",
        policy_version=policy.identity,
        state=PublicationState.PUBLISHED,
        selected_source=source,
        publication_hash=publication_hash([member_reference(member)]),
        coverage=CoverageSnapshot(
            coverage_id=str(uuid4()),
            publication_id=publication_id,
            requested_count=1,
            eligible_count=1,
            selected_count=1,
            missing_count=0,
            conflict_count=0,
            generated_at=now,
        ),
        member_count=1,
        as_of=observed_at,
        published_at=now,
        created_by="test.activation.news",
        run_id=run_id,
    )
    published = CanonicalPublicationRepository().publish_with_members(publication, (member,))
    CanonicalPublicationPointerModel.objects.create(
        dataset_key=published.dataset_key,
        publication_key=published.publication_key,
        publication_id=published.publication_id,
        publication_hash=published.publication_hash,
        activation_id="fixture:" + published.publication_id,
    )
    return policy, published, member


def _stage_news_successor(
    old_publication: CanonicalPublication,
    *,
    stage: bool = True,
) -> tuple[CanonicalPublication, object, NewsFactModel, RawAudit]:
    """Create a successor current news candidate with exact persisted lineage."""

    current_member = CanonicalPublicationRepository().list_members(old_publication.publication_id)[
        0
    ]
    old_model = NewsFactModel.objects.get(pk=current_member.fact_pk)
    observed_at = old_model.published_at + timedelta(seconds=1)
    ingested_run_id = uuid4()
    source_record_id = "activation-news-successor-" + uuid4().hex
    fact = NewsFactModel.objects.create(
        asset_code=old_model.asset_code,
        title="activation test news successor",
        summary="",
        url="",
        published_at=observed_at,
        source=old_model.source,
        external_id="activation-news-" + uuid4().hex,
        source_record_id=source_record_id,
        raw_payload_hash="c" * 64,
        quality_status="accepted",
        revision_number=1,
        ingested_run_id=ingested_run_id,
        available_at=observed_at,
    )
    reference = publication_fact_reference_for_dataset(fact, dataset_key="market.news")
    publication_id = str(uuid4())
    member = publication_member_from_reference(
        reference,
        member_id=str(uuid4()),
        publication_id=publication_id,
        dataset_key="market.news",
    )
    run_id = str(uuid4())
    fetched_at = datetime.now(UTC)
    raw = RawAuditRepository().log(
        RawAudit(
            provider_name=old_model.source,
            capability="news",
            request_params={"source_record_id": source_record_id},
            status="ok",
            row_count=1,
            fetched_at=fetched_at,
            run_id=run_id,
            ingested_run_id=str(ingested_run_id),
            response_payload_hash="d" * 64,
            schema_fingerprint="e" * 64,
            parser_version="activation-news-test",
        )
    )
    as_of = reference.observed_at
    publication = CanonicalPublication(
        publication_id=publication_id,
        dataset_key="market.news",
        publication_key="current",
        policy_version=old_publication.policy_version,
        state=PublicationState.CANDIDATE,
        selected_source=old_model.source,
        publication_hash=publication_hash([member_reference(member)]),
        coverage=CoverageSnapshot(
            coverage_id=str(uuid4()),
            publication_id=publication_id,
            requested_count=1,
            eligible_count=1,
            selected_count=1,
            missing_count=0,
            conflict_count=0,
            generated_at=fetched_at,
        ),
        member_count=1,
        as_of=as_of,
        created_by="test.activation.news",
        run_id=run_id,
    )
    if stage:
        DjangoPublicationActivationRepository().stage_candidate_with_members(
            publication,
            (member,),
        )
    return publication, member, old_model, raw


def _activation_request(
    candidate,
    raw: RawAudit,
    *,
    activation_id: str = "activation-1",
):
    pointer = CanonicalPublicationPointerModel.objects.get(
        dataset_key=candidate.dataset_key,
        publication_key=candidate.publication_key,
    )
    return PublicationActivationRequest(
        dataset_key=candidate.dataset_key,
        publication_key=candidate.publication_key,
        candidate_publication_id=candidate.publication_id,
        candidate_publication_hash=candidate.publication_hash,
        activation_id=activation_id,
        audit_observation=_audit_observation(candidate, raw),
        expected_current_publication_id=str(pointer.publication_id),
        expected_current_publication_hash=pointer.publication_hash,
    )


def _audit_observation(
    candidate: CanonicalPublication,
    raw: RawAudit,
) -> DataPublicationAuditObservation:
    raw_reference = raw.exact_reference()
    return DataPublicationAuditObservation(
        dataset_key=candidate.dataset_key,
        publication_key=candidate.publication_key,
        publication_id=candidate.publication_id,
        publication_version=candidate.policy_version,
        publication_hash=candidate.publication_hash,
        provider_key=candidate.selected_source,
        run_id=raw.run_id,
        ingested_run_id=raw.ingested_run_id,
        member_count=candidate.member_count,
        coverage_requested_count=candidate.coverage.requested_count,
        coverage_eligible_count=candidate.coverage.eligible_count,
        coverage_selected_count=candidate.coverage.selected_count,
        outcome=AuditOutcome.PUBLISHED,
        raw_audit_id=raw_reference.raw_audit_id,
        raw_audit_version=raw_reference.version,
        raw_audit_content_hash=raw_reference.content_hash,
        occurred_at=candidate.as_of,
        recorded_at=raw.fetched_at,
        scope=AuditScopeRef(tenant_id="tenant-1", owner_id="owner-1"),
    )


def _activate(request: PublicationActivationRequest, writer: _AuditWriter):
    return DjangoPublicationActivationRepository().activate_candidate(
        request,
        audit_writer=writer,
        authority_fence=_AuthorityFence(),
        authority_proof="proof",
    )


class _GroupAuditWriter(_AuditWriter):
    """Observe manifest-bound group appends and inject one selected write failure."""

    def __init__(
        self,
        *,
        fail_on_call: int | None = None,
        fail_after_call: int | None = None,
    ) -> None:
        super().__init__()
        self.fail_on_call = fail_on_call
        self.fail_after_call = fail_after_call
        self.manifest_calls: list[str] = []

    def append_manifest_required(
        self,
        *,
        request,
        publication,
        members,
        manifest,
        observation,
    ):
        assert connection.in_atomic_block
        call_no = len(self.manifest_calls) + 1
        if self.fail_on_call == call_no:
            raise RuntimeError(f"required manifest audit failure at {call_no}")
        commit = super().append_manifest_required(
            request=request,
            publication=publication,
            members=members,
            manifest=manifest,
            observation=observation,
        )
        self.manifest_calls.append(publication.publication_id)
        if self.fail_after_call == call_no:
            raise RuntimeError(f"required manifest outbox failure after {call_no}")
        return commit

    def append_manifest_group_required(self, *, request, writes):
        return tuple(
            self.append_manifest_required(
                request=request,
                publication=write.publication,
                members=write.members,
                manifest=write.manifest,
                observation=write.observation,
            )
            for write in writes
        )


def _build_group_candidate(
    dataset_key: str,
    *,
    without_fact_lineage: bool = False,
    extra_unused_source: bool = False,
    fact_source_type: str = "group-test",
    raw_source_type: str | None = None,
    omit_raw_source_type: bool = False,
    duplicate_source_pair: bool = False,
    fail_raw_audit_after_stage: bool = False,
    require_missing_available_at: bool = False,
    raw_audit_capability: str | None = None,
) -> CanonicalPublication:
    """Persist one small candidate and its exact candidate-level RawAudit manifest."""

    required_evidence = (
        "source",
        "observed_at",
        "fetched_at",
        "source_record_id",
        "fact_content_hash",
    )
    if require_missing_available_at:
        required_evidence = (*required_evidence, "available_at")
    policy = PublicationPolicy(
        dataset=DatasetKey(dataset_key, "1.0", "1.0"),
        minimum_coverage_ratio=1.0,
        allow_partial=False,
        conflict_action="block",
        required_evidence=required_evidence,
        retention_days=3650,
        policy_version="group-activation-v1",
    )
    PublicationPolicyRepository().save(policy)
    observed_at = datetime.now(UTC) - timedelta(minutes=2)
    fetched_at = observed_at + timedelta(seconds=1)
    ingested_run_id = uuid4()
    run_id = uuid4()
    asset_code = f"GROUP{uuid4().hex[:8].upper()}.SZ"
    source_record_id = "group-source-" + uuid4().hex
    payload_hash = "a" * 64

    if dataset_key == "equity.quote.snapshot":
        fact_row = QuoteSnapshotModel.objects.create(
            asset_code=asset_code,
            snapshot_at=observed_at,
            fetched_at=fetched_at,
            current_price=Decimal("10.2500"),
            source=fact_source_type,
            source_record_id=source_record_id,
            raw_payload_hash=payload_hash,
            quality_status="accepted",
            revision_number=1,
            ingested_run_id=None if without_fact_lineage else ingested_run_id,
        )
    elif dataset_key == "equity.price.bar":
        fact_row = PriceBarModel.objects.create(
            asset_code=asset_code,
            bar_date=observed_at.date(),
            freq="1d",
            adjustment="none",
            open=Decimal("10.0000"),
            high=Decimal("11.0000"),
            low=Decimal("9.5000"),
            close=Decimal("10.2500"),
            source=fact_source_type,
            fetched_at=fetched_at,
            source_record_id=source_record_id,
            raw_payload_hash=payload_hash,
            quality_status="accepted",
            revision_number=1,
            ingested_run_id=None if without_fact_lineage else ingested_run_id,
        )
    elif dataset_key == "equity.valuation.fact":
        fact_row = ValuationFactModel.objects.create(
            asset_code=asset_code,
            val_date=observed_at.date(),
            pe_ttm=Decimal("12.5000"),
            pb=Decimal("1.5000"),
            source=fact_source_type,
            observed_at=observed_at,
            available_at=fetched_at,
            fetched_at=fetched_at,
            source_record_id=source_record_id,
            raw_payload_hash=payload_hash,
            quality_status="accepted",
            revision_number=1,
            ingested_run_id=None if without_fact_lineage else ingested_run_id,
        )
    else:
        raise AssertionError("unsupported group candidate dataset")

    fact_reference = publication_fact_reference_for_dataset(
        fact_row,
        dataset_key=dataset_key,
    )
    publication_id = str(uuid4())
    member = publication_member_from_reference(
        fact_reference,
        member_id=str(uuid4()),
        publication_id=publication_id,
        dataset_key=dataset_key,
    )
    publication = CanonicalPublication(
        publication_id=publication_id,
        dataset_key=dataset_key,
        publication_key="current",
        policy_version=policy.identity,
        state=PublicationState.CANDIDATE,
        selected_source=fact_source_type,
        publication_hash=publication_hash(
            [member_reference(member)],
            policy_identity=policy.identity,
        ),
        coverage=CoverageSnapshot(
            coverage_id=str(uuid4()),
            publication_id=publication_id,
            requested_count=1,
            eligible_count=1,
            selected_count=1,
            missing_count=0,
            conflict_count=0,
            generated_at=fetched_at,
        ),
        member_count=1,
        as_of=fetched_at,
        created_by="test.activation.group",
        run_id=str(run_id),
    )
    repository = DjangoPublicationActivationRepository()
    repository.stage_candidate_with_members(publication, (member,))

    capability = raw_audit_capability or canonical_capability_for_publication_dataset(dataset_key)
    assert capability is not None
    raw_extra = (
        {}
        if omit_raw_source_type
        else {
            "source_type": raw_source_type or fact_source_type,
        }
    )
    raw_audit = RawAuditRepository().log(
        RawAudit(
            provider_name="group-provider-adapter",
            capability=capability,
            request_params={"dataset_key": dataset_key},
            status="ok",
            row_count=1,
            fetched_at=fetched_at,
            run_id=str(run_id),
            ingested_run_id=str(ingested_run_id),
            response_payload_hash="b" * 64,
            schema_fingerprint="c" * 64,
            parser_version="group-activation-test",
            extra=raw_extra,
        )
    )
    raw_references = [
        CandidateRawAuditReference(
            raw_audit_id=raw_audit.raw_audit_id,
            version="1",
            content_hash=raw_audit.content_hash,
            provider_name=raw_audit.provider_name,
            capability=raw_audit.capability,
            run_id=raw_audit.run_id,
            ingested_run_id=raw_audit.ingested_run_id,
        )
    ]
    if extra_unused_source:
        unused_audit = RawAuditRepository().log(
            RawAudit(
                provider_name="group-provider-adapter",
                capability=capability,
                request_params={"dataset_key": dataset_key, "unused": True},
                status="ok",
                row_count=1,
                fetched_at=fetched_at,
                run_id=str(uuid4()),
                ingested_run_id=str(uuid4()),
                response_payload_hash="d" * 64,
                schema_fingerprint="e" * 64,
                parser_version="group-activation-test",
                extra={"source_type": fact_source_type},
            )
        )
        raw_references.append(
            CandidateRawAuditReference(
                raw_audit_id=unused_audit.raw_audit_id,
                version="1",
                content_hash=unused_audit.content_hash,
                provider_name=unused_audit.provider_name,
                capability=unused_audit.capability,
                run_id=unused_audit.run_id,
                ingested_run_id=unused_audit.ingested_run_id,
            )
        )
    if duplicate_source_pair:
        duplicate_audit = RawAuditRepository().log(
            RawAudit(
                provider_name="group-provider-adapter",
                capability=capability,
                request_params={"dataset_key": dataset_key, "duplicate": True},
                status="ok",
                row_count=1,
                fetched_at=fetched_at,
                run_id=str(run_id),
                ingested_run_id=str(ingested_run_id),
                response_payload_hash="f" * 64,
                schema_fingerprint="1" * 64,
                parser_version="group-activation-test",
                extra={"source_type": fact_source_type},
            )
        )
        raw_references.append(
            CandidateRawAuditReference(
                raw_audit_id=duplicate_audit.raw_audit_id,
                version="1",
                content_hash=duplicate_audit.content_hash,
                provider_name=duplicate_audit.provider_name,
                capability=duplicate_audit.capability,
                run_id=duplicate_audit.run_id,
                ingested_run_id=duplicate_audit.ingested_run_id,
            )
        )
    manifest = CandidateRawAuditManifest.create(
        publication_id=publication.publication_id,
        publication_hash=publication.publication_hash,
        run_id=publication.run_id,
        dataset_key=publication.dataset_key,
        publication_key=publication.publication_key,
        task_attempt_id="group-attempt-" + uuid4().hex,
        raw_audits=tuple(raw_references),
    )
    DjangoCandidateRawAuditManifestRepository().stage(manifest)
    if fail_raw_audit_after_stage:
        RawAuditModel.objects.filter(pk=int(raw_audit.raw_audit_id)).update(status="error")
    return publication


def _build_group_request(
    *,
    without_fact_lineage_dataset: str | None = None,
    extra_unused_source_dataset: str | None = None,
    fact_source_type: str = "group-test",
    raw_source_type: str | None = None,
    omit_raw_source_type_dataset: str | None = None,
    duplicate_source_pair_dataset: str | None = None,
    failed_raw_audit_dataset: str | None = None,
    missing_required_evidence_dataset: str | None = None,
    raw_audit_capability_overrides: dict[str, str] | None = None,
) -> tuple[PublicationActivationGroupRequest, dict[str, CanonicalPublication]]:
    """Stage the fixed quote/price/valuation group and capture its empty-head CAS."""

    datasets = (
        "equity.price.bar",
        "equity.quote.snapshot",
        "equity.valuation.fact",
    )
    publications = {
        dataset_key: _build_group_candidate(
            dataset_key,
            without_fact_lineage=dataset_key == without_fact_lineage_dataset,
            extra_unused_source=dataset_key == extra_unused_source_dataset,
            fact_source_type=fact_source_type,
            raw_source_type=raw_source_type,
            omit_raw_source_type=dataset_key == omit_raw_source_type_dataset,
            duplicate_source_pair=dataset_key == duplicate_source_pair_dataset,
            fail_raw_audit_after_stage=dataset_key == failed_raw_audit_dataset,
            require_missing_available_at=dataset_key == missing_required_evidence_dataset,
            raw_audit_capability=(raw_audit_capability_overrides or {}).get(dataset_key),
        )
        for dataset_key in datasets
    }
    assert all(
        CanonicalPublicationPointerModel.objects.get(
            dataset_key=dataset_key,
            publication_key="current",
        ).publication_id
        is None
        for dataset_key in datasets
    )
    candidates = tuple(
        PublicationActivationGroupCandidate(
            dataset_key=dataset_key,
            publication_key=publication.publication_key,
            candidate_publication_id=publication.publication_id,
            candidate_publication_hash=publication.publication_hash,
        )
        for dataset_key, publication in publications.items()
    )
    return (
        PublicationActivationGroupRequest(
            activation_id="activation-group-" + uuid4().hex,
            candidates=candidates,
        ),
        publications,
    )


def _activate_group(
    request: PublicationActivationGroupRequest,
    writer: _GroupAuditWriter,
) -> tuple[CanonicalPublication, ...]:
    """Run one group request through the feature-off complete fence seam."""

    return ActivateCanonicalPublicationGroupUseCase(
        DjangoPublicationActivationRepository()
    ).execute(
        request,
        audit_writer=writer,
        authority_fence=_AuthorityFence(),
        authority_proof="proof",
    )


def _assert_group_candidates_unpublished(
    request: PublicationActivationGroupRequest,
) -> None:
    """Assert a failed group left each candidate and pre-created pointer untouched."""

    for item in request.candidates:
        candidate = CanonicalPublicationModel.objects.get(
            publication_id=item.candidate_publication_id
        )
        pointer = CanonicalPublicationPointerModel.objects.get(
            dataset_key=item.dataset_key,
            publication_key=item.publication_key,
        )
        assert candidate.state == PublicationState.CANDIDATE.value
        assert pointer.publication_id is None
        assert pointer.publication_hash == ""
        assert pointer.activation_id == ""


def test_group_activation_switches_three_candidates_and_replays_manifest_events() -> None:
    request, publications = _build_group_request()
    writer = _GroupAuditWriter()

    activated = _activate_group(request, writer)

    assert {publication.publication_id for publication in activated} == {
        publication.publication_id for publication in publications.values()
    }
    assert all(publication.state is PublicationState.PUBLISHED for publication in activated)
    assert len(writer.manifest_calls) == 3
    assert (
        CanonicalPublicationModel.objects.filter(
            publication_id__in=[
                publication.publication_id for publication in publications.values()
            ],
            state=PublicationState.PUBLISHED.value,
        ).count()
        == 3
    )
    for item in request.candidates:
        pointer = CanonicalPublicationPointerModel.objects.get(
            dataset_key=item.dataset_key,
            publication_key=item.publication_key,
        )
        assert str(pointer.publication_id) == item.candidate_publication_id
        assert pointer.publication_hash == item.candidate_publication_hash
        assert pointer.activation_id == request.activation_id
    assert SystemAuditEventModel.objects.count() == 3
    assert SystemAuditOutboxModel.objects.count() == 3
    events = tuple(SystemAuditEventModel.objects.order_by("dataset_key"))
    assert tuple(row.dataset_key for row in events) == tuple(
        item.dataset_key for item in request.candidates
    )
    for event, item in zip(events, request.candidates, strict=True):
        manifest_reference = next(
            reference
            for reference in event.evidence_refs
            if reference["artifact_type"] == "candidate_raw_audit_manifest"
        )
        raw_references = tuple(
            reference
            for reference in event.evidence_refs
            if reference["artifact_type"] == "raw_audit"
        )
        assert event.publication_id == item.candidate_publication_id
        assert len(raw_references) == 1
        assert manifest_reference["artifact_id"]
        assert event.detail["raw_audit_manifest"]["raw_audit_count"] == 1
    persisted_raw_ids = {
        int(reference["artifact_id"])
        for event in events
        for reference in event.evidence_refs
        if reference["artifact_type"] == "raw_audit"
    }
    raw_rows = RawAuditModel.objects.filter(pk__in=persisted_raw_ids)
    assert raw_rows.count() == 3
    assert all(row.provider_name != row.extra["source_type"] for row in raw_rows)

    _activate_group(request, writer)
    assert SystemAuditEventModel.objects.count() == 3
    assert SystemAuditOutboxModel.objects.count() == 3


def test_group_activation_request_identifies_fixed_current_market_contract() -> None:
    candidates = tuple(
        PublicationActivationGroupCandidate(
            dataset_key=dataset_key,
            publication_key="preview" if dataset_key == "equity.price.bar" else "current",
            candidate_publication_id=str(uuid4()),
            candidate_publication_hash="a" * 64,
        )
        for dataset_key in (
            "equity.price.bar",
            "equity.quote.snapshot",
            "equity.valuation.fact",
        )
    )

    with pytest.raises(PublicationActivationError, match="market group activation contract"):
        PublicationActivationGroupRequest(
            activation_id="activation-fixed-market-contract",
            candidates=candidates,
        )


@pytest.mark.parametrize(
    "dataset_key",
    ["equity.quote.snapshot", "equity.price.bar", "equity.valuation.fact"],
)
def test_market_dataset_single_activation_fails_closed_at_application_and_repository(
    dataset_key: str,
) -> None:
    candidate = _build_group_candidate(dataset_key)
    raw_row = RawAuditModel.objects.get(run_id=candidate.run_id)
    raw = RawAuditRepository._from_model(raw_row)
    request = PublicationActivationRequest(
        dataset_key=candidate.dataset_key,
        publication_key=candidate.publication_key,
        candidate_publication_id=candidate.publication_id,
        candidate_publication_hash=candidate.publication_hash,
        activation_id="activation-market-single-entry",
        audit_observation=_audit_observation(candidate, raw),
    )

    class RecordingRepository:
        called = False

        def activate_candidate(self, *_args, **_kwargs):
            self.called = True
            raise AssertionError("single activation repository should not be called")

    repository = RecordingRepository()
    use_case = ActivateCanonicalPublicationUseCase(repository)
    with pytest.raises(PublicationActivationError, match="requires atomic group activation"):
        use_case.execute(
            request,
            audit_writer=_AuditWriter(),
            authority_fence=_AuthorityFence(),
            authority_proof="proof",
        )
    assert repository.called is False

    with pytest.raises(PublicationActivationError, match="requires atomic group activation"):
        DjangoPublicationActivationRepository().activate_candidate(
            request,
            audit_writer=_AuditWriter(),
            authority_fence=_AuthorityFence(),
            authority_proof="proof",
        )

    persisted = CanonicalPublicationModel.objects.get(publication_id=candidate.publication_id)
    pointer = CanonicalPublicationPointerModel.objects.get(
        dataset_key=dataset_key,
        publication_key="current",
    )
    assert persisted.state == PublicationState.CANDIDATE.value
    assert pointer.publication_id is None
    assert SystemAuditEventModel.objects.count() == 0
    assert SystemAuditOutboxModel.objects.count() == 0


def test_group_activation_enforces_versioned_required_fact_evidence() -> None:
    request, _publications = _build_group_request(
        missing_required_evidence_dataset="equity.quote.snapshot",
    )

    with pytest.raises(PublicationActivationError, match="policy or freshness evidence"):
        _activate_group(request, _GroupAuditWriter())

    _assert_group_candidates_unpublished(request)
    assert SystemAuditEventModel.objects.count() == 0
    assert SystemAuditOutboxModel.objects.count() == 0


@pytest.mark.parametrize("fail_on_call", [1, 2, 3])
def test_group_activation_rolls_back_all_switches_if_any_required_audit_fails(
    fail_on_call: int,
) -> None:
    request, _publications = _build_group_request()
    writer = _GroupAuditWriter(fail_on_call=fail_on_call)

    with pytest.raises(RuntimeError, match=f"required manifest audit failure at {fail_on_call}"):
        _activate_group(request, writer)

    _assert_group_candidates_unpublished(request)
    assert SystemAuditEventModel.objects.count() == 0
    assert SystemAuditOutboxModel.objects.count() == 0
    assert len(writer.manifest_calls) == fail_on_call - 1


def test_group_activation_rolls_back_if_last_outbox_fails_after_append() -> None:
    request, _publications = _build_group_request()
    writer = _GroupAuditWriter(fail_after_call=3)

    with pytest.raises(RuntimeError, match="required manifest outbox failure after 3"):
        _activate_group(request, writer)

    _assert_group_candidates_unpublished(request)
    assert SystemAuditEventModel.objects.count() == 0
    assert SystemAuditOutboxModel.objects.count() == 0
    assert len(writer.manifest_calls) == 3


def test_group_activation_rolls_back_all_switches_if_batched_pointer_write_fails(
    monkeypatch,
) -> None:
    request, _publications = _build_group_request()
    original_compare_and_swap = PublicationGroupActivationStateWriter._compare_and_swap_pointers

    def fail_batched_pointer_save(transitions, **kwargs):
        original_compare_and_swap(transitions, **kwargs)
        raise RuntimeError("batched group pointer write failed")

    monkeypatch.setattr(
        PublicationGroupActivationStateWriter,
        "_compare_and_swap_pointers",
        staticmethod(fail_batched_pointer_save),
    )
    with pytest.raises(RuntimeError, match="batched group pointer write failed"):
        _activate_group(request, _GroupAuditWriter())

    _assert_group_candidates_unpublished(request)
    assert SystemAuditEventModel.objects.count() == 0
    assert SystemAuditOutboxModel.objects.count() == 0


def test_group_activation_rejects_bad_empty_pointer_cas_before_any_write() -> None:
    request, _publications = _build_group_request()
    changed = tuple(
        (
            replace(
                item,
                expected_current_publication_id=str(uuid4()),
                expected_current_publication_hash="f" * 64,
            )
            if item.dataset_key == "equity.price.bar"
            else item
        )
        for item in request.candidates
    )
    request = replace(request, candidates=changed)

    with pytest.raises(PublicationActivationError, match="empty current pointer"):
        _activate_group(request, _GroupAuditWriter())

    _assert_group_candidates_unpublished(request)
    assert SystemAuditEventModel.objects.count() == 0


@pytest.mark.parametrize(
    ("stale_field", "stale_value"),
    [("publication_hash", "f" * 64), ("activation_id", "stale-activation")],
)
def test_group_activation_rejects_residual_empty_pointer_identity_before_any_write(
    stale_field: str,
    stale_value: str,
) -> None:
    request, _publications = _build_group_request()
    item = request.candidates[0]
    CanonicalPublicationPointerModel.objects.filter(
        dataset_key=item.dataset_key,
        publication_key=item.publication_key,
    ).update(**{stale_field: stale_value})

    with pytest.raises(PublicationActivationError, match="empty current pointer"):
        _activate_group(request, _GroupAuditWriter())

    for candidate in request.candidates:
        persisted = CanonicalPublicationModel.objects.get(
            publication_id=candidate.candidate_publication_id
        )
        assert persisted.state == PublicationState.CANDIDATE.value
    assert SystemAuditEventModel.objects.count() == 0
    assert SystemAuditOutboxModel.objects.count() == 0
    pointer = CanonicalPublicationPointerModel.objects.get(
        dataset_key=item.dataset_key,
        publication_key=item.publication_key,
    )
    assert pointer.publication_id is None
    assert getattr(pointer, stale_field) == stale_value


@pytest.mark.parametrize(
    "dataset_key",
    ["equity.quote.snapshot", "equity.price.bar", "equity.valuation.fact"],
)
def test_group_activation_rejects_dataset_mismatched_raw_audit_capability_before_writes(
    dataset_key: str,
) -> None:
    request, _publications = _build_group_request(
        raw_audit_capability_overrides={dataset_key: "wrong_capability"},
    )

    with pytest.raises(PublicationActivationError, match="capability does not match its dataset"):
        _activate_group(request, _GroupAuditWriter())

    _assert_group_candidates_unpublished(request)
    assert SystemAuditEventModel.objects.count() == 0
    assert SystemAuditOutboxModel.objects.count() == 0


def test_group_activation_rejects_partially_current_idempotent_set() -> None:
    request, _publications = _build_group_request()
    item = request.candidates[0]
    candidate = CanonicalPublicationModel.objects.get(publication_id=item.candidate_publication_id)
    activated_at = datetime.now(UTC)
    candidate.state = PublicationState.PUBLISHED.value
    candidate.published_at = activated_at
    candidate.save(update_fields=("state", "published_at", "updated_at"))
    CanonicalPublicationPointerModel.objects.filter(
        dataset_key=item.dataset_key,
        publication_key=item.publication_key,
    ).update(
        publication_id=candidate.publication_id,
        publication_hash=candidate.publication_hash,
        activation_id=request.activation_id,
    )

    with pytest.raises(PublicationActivationError, match="partially current"):
        _activate_group(request, _GroupAuditWriter())

    assert SystemAuditEventModel.objects.count() == 0
    assert SystemAuditOutboxModel.objects.count() == 0


@pytest.mark.parametrize(
    (
        "without_fact_lineage_dataset",
        "extra_unused_source_dataset",
        "omit_raw_source_type_dataset",
        "raw_source_type",
        "duplicate_source_pair_dataset",
        "failed_raw_audit_dataset",
        "message",
    ),
    [
        ("equity.quote.snapshot", None, None, None, None, None, "no ingestion lineage"),
        (None, "equity.price.bar", None, None, None, None, "exactly match member fact lineage"),
        (None, None, "equity.valuation.fact", None, None, None, "source_type is missing"),
        (None, None, None, "different-source", None, None, "exactly match member fact lineage"),
        (
            None,
            None,
            None,
            None,
            "equity.quote.snapshot",
            None,
            "ambiguous duplicate source lineage",
        ),
        (
            None,
            None,
            None,
            None,
            None,
            "equity.price.bar",
            "successful and non-empty",
        ),
    ],
)
def test_group_activation_requires_bidirectional_manifest_fact_lineage(
    without_fact_lineage_dataset: str | None,
    extra_unused_source_dataset: str | None,
    omit_raw_source_type_dataset: str | None,
    raw_source_type: str | None,
    duplicate_source_pair_dataset: str | None,
    failed_raw_audit_dataset: str | None,
    message: str,
) -> None:
    request, _publications = _build_group_request(
        without_fact_lineage_dataset=without_fact_lineage_dataset,
        extra_unused_source_dataset=extra_unused_source_dataset,
        fact_source_type="canonical-source",
        raw_source_type=raw_source_type,
        omit_raw_source_type_dataset=omit_raw_source_type_dataset,
        duplicate_source_pair_dataset=duplicate_source_pair_dataset,
        failed_raw_audit_dataset=failed_raw_audit_dataset,
    )

    with pytest.raises(PublicationActivationError, match=message):
        _activate_group(request, _GroupAuditWriter())

    _assert_group_candidates_unpublished(request)
    assert SystemAuditEventModel.objects.count() == 0
    assert SystemAuditOutboxModel.objects.count() == 0


@pytest.mark.parametrize(
    ("drift_target", "message"),
    [
        ("manifest_header", "manifest seal is invalid"),
        ("manifest_child", "manifest seal is invalid"),
        ("raw_audit", "RawAudit row differs from its manifest"),
    ],
)
def test_group_activation_rechecks_manifest_header_children_and_raw_audits(
    drift_target: str,
    message: str,
) -> None:
    """Inject out-of-band database drift; raw SQL is not a supported write path."""

    request, _publications = _build_group_request()
    candidate = request.candidates[0]
    manifest_header = CandidateRawAuditManifestModel.objects.get(
        publication_id=candidate.candidate_publication_id
    )
    if drift_target == "manifest_header":
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE data_center_candidate_raw_audit_manifest "
                "SET manifest_hash=%s WHERE manifest_id=%s",
                ["e" * 64, manifest_header.manifest_id.hex],
            )
            assert cursor.rowcount == 1
        manifest_header.refresh_from_db()
        assert manifest_header.manifest_hash == "e" * 64
    elif drift_target == "manifest_child":
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE data_center_candidate_raw_audit_manifest_member "
                "SET provider_name=%s WHERE manifest_id=%s",
                ["drifted-provider", manifest_header.manifest_id.hex],
            )
            assert cursor.rowcount == 1
        assert CandidateRawAuditManifestMemberModel.objects.filter(
            manifest_id=manifest_header.manifest_id,
            provider_name="drifted-provider",
        ).exists()
    else:
        reference = CandidateRawAuditManifestMemberModel.objects.get(
            manifest_id=manifest_header.manifest_id
        )
        RawAuditModel.objects.filter(pk=reference.raw_audit_id).update(
            extra={"source_type": "drifted-source"},
        )

    with pytest.raises(PublicationActivationError, match=message):
        _activate_group(request, _GroupAuditWriter())

    _assert_group_candidates_unpublished(request)
    assert SystemAuditEventModel.objects.count() == 0
    assert SystemAuditOutboxModel.objects.count() == 0


def test_activation_switches_pointer_and_retry_is_idempotent() -> None:
    _policy, old_publication, _member = _published_news_snapshot()
    candidate, member, _old_model, raw = _stage_news_successor(old_publication)
    request = _activation_request(candidate, raw)
    writer = _AuditWriter()

    activated = _activate(request, writer)
    assert activated.publication_id == candidate.publication_id
    assert (
        CanonicalPublicationRepository().get_current(candidate.dataset_key, "current") == activated
    )
    assert writer.calls == [(request.activation_id, candidate.publication_id)]
    assert (
        CanonicalPublicationModel.objects.get(publication_id=old_publication.publication_id).state
        == PublicationState.SUPERSEDED.value
    )
    pointer = CanonicalPublicationPointerModel.objects.get(
        dataset_key=candidate.dataset_key,
        publication_key="current",
    )
    assert str(pointer.publication_id) == candidate.publication_id
    assert pointer.publication_hash == candidate.publication_hash
    assert pointer.activation_id == request.activation_id
    assert CanonicalPublicationRepository().list_members(candidate.publication_id) == [member]

    retried = _activate(request, writer)
    assert retried.publication_id == candidate.publication_id
    assert len(writer.calls) == 2


def test_activation_rolls_back_pointer_and_publication_when_required_audit_fails() -> None:
    _policy, old_publication, _member = _published_news_snapshot()
    candidate, _member, _old_model, raw = _stage_news_successor(old_publication)
    request = _activation_request(candidate, raw)

    with pytest.raises(RuntimeError, match="required audit/outbox failure"):
        _activate(request, _AuditWriter(fail=True))

    current = CanonicalPublicationRepository().get_current(old_publication.dataset_key, "current")
    assert current is not None
    assert current.publication_id == old_publication.publication_id
    assert (
        CanonicalPublicationModel.objects.get(publication_id=candidate.publication_id).state
        == PublicationState.CANDIDATE.value
    )
    pointer = CanonicalPublicationPointerModel.objects.get(
        dataset_key=old_publication.dataset_key,
        publication_key="current",
    )
    assert str(pointer.publication_id) == old_publication.publication_id


def test_candidate_stage_rolls_back_publication_members_and_pointer_on_bulk_failure(
    monkeypatch,
) -> None:
    _policy, old_publication, _member = _published_snapshot()
    candidate, member, _old_model, _raw = _stage_successor(old_publication, stage=False)
    pointer = CanonicalPublicationPointerModel.objects.get(
        dataset_key=old_publication.dataset_key,
        publication_key="current",
    )

    def _fail_bulk_create(*_args, **_kwargs):
        raise RuntimeError("member staging failure")

    monkeypatch.setattr(
        PublicationMemberModel._default_manager,
        "bulk_create",
        _fail_bulk_create,
    )
    with pytest.raises(RuntimeError, match="member staging failure"):
        DjangoPublicationActivationRepository().stage_candidate_with_members(
            candidate,
            (member,),
        )

    assert not CanonicalPublicationModel.objects.filter(
        publication_id=candidate.publication_id
    ).exists()
    assert not PublicationMemberModel.objects.filter(
        publication_id=candidate.publication_id
    ).exists()
    pointer.refresh_from_db()
    assert str(pointer.publication_id) == old_publication.publication_id


def test_legacy_publish_does_not_advance_activation_owned_pointer() -> None:
    _policy, old_publication, _member = _published_snapshot()
    candidate, member, _old_model, _raw = _stage_successor(old_publication, stage=False)
    pointer = CanonicalPublicationPointerModel.objects.get(
        dataset_key=old_publication.dataset_key,
        publication_key="current",
    )
    original_activation_id = pointer.activation_id
    legacy_publication = replace(
        candidate,
        state=PublicationState.PUBLISHED,
        published_at=datetime.now(UTC),
    )

    published = CanonicalPublicationRepository().publish_with_members(
        legacy_publication,
        (member,),
    )

    assert published.publication_id == candidate.publication_id
    pointer.refresh_from_db()
    assert str(pointer.publication_id) == old_publication.publication_id
    assert pointer.activation_id == original_activation_id
    assert (
        CanonicalPublicationRepository().get_current(
            candidate.dataset_key,
            candidate.publication_key,
        )
        is None
    )


def test_activation_rolls_back_when_audit_event_append_fails(monkeypatch) -> None:
    _policy, old_publication, _member = _published_news_snapshot()
    candidate, _member, _old_model, raw = _stage_news_successor(old_publication)
    request = _activation_request(candidate, raw)
    writer = _AuditWriter()

    def _fail_event_append(*_args, **_kwargs):
        raise RuntimeError("event append failure")

    monkeypatch.setattr(
        type(writer.coordinator._event_repository),
        "append_targeted",
        _fail_event_append,
    )
    with pytest.raises(RuntimeError, match="event append failure"):
        _activate(request, writer)
    assert SystemAuditEventModel.objects.count() == 0
    assert SystemAuditOutboxModel.objects.count() == 0
    assert (
        CanonicalPublicationModel.objects.get(publication_id=candidate.publication_id).state
        == PublicationState.CANDIDATE.value
    )


def test_activation_rolls_back_when_audit_outbox_enqueue_fails(monkeypatch) -> None:
    _policy, old_publication, _member = _published_news_snapshot()
    candidate, _member, _old_model, raw = _stage_news_successor(old_publication)
    request = _activation_request(candidate, raw)
    writer = _AuditWriter()

    def _fail_outbox_enqueue(*_args, **_kwargs):
        raise RuntimeError("outbox enqueue failure")

    monkeypatch.setattr(
        type(writer.coordinator._outbox_repository),
        "enqueue_targeted",
        _fail_outbox_enqueue,
    )
    with pytest.raises(RuntimeError, match="outbox enqueue failure"):
        _activate(request, writer)
    assert SystemAuditEventModel.objects.count() == 0
    assert SystemAuditOutboxModel.objects.count() == 0
    assert (
        CanonicalPublicationModel.objects.get(publication_id=candidate.publication_id).state
        == PublicationState.CANDIDATE.value
    )


def test_activation_rolls_back_when_pointer_write_fails(monkeypatch) -> None:
    _policy, old_publication, _member = _published_news_snapshot()
    candidate, _member, _old_model, raw = _stage_news_successor(old_publication)
    request = _activation_request(candidate, raw)

    def _fail_pointer_compare_and_swap(*_args, **_kwargs):
        raise RuntimeError("pointer write failure")

    monkeypatch.setattr(
        DjangoPublicationActivationRepository,
        "_compare_and_swap_pointer",
        staticmethod(_fail_pointer_compare_and_swap),
    )
    with pytest.raises(RuntimeError, match="pointer write failure"):
        _activate(request, _AuditWriter())
    assert (
        CanonicalPublicationRepository()
        .get_current(old_publication.dataset_key, "current")
        .publication_id
        == old_publication.publication_id
    )
    assert (
        CanonicalPublicationModel.objects.get(publication_id=candidate.publication_id).state
        == PublicationState.CANDIDATE.value
    )


@pytest.mark.parametrize(
    ("stale_field", "stale_value"),
    [("publication_hash", "f" * 64), ("activation_id", "stale-activation")],
)
def test_single_activation_rejects_residual_empty_pointer_identity_before_any_write(
    stale_field: str,
    stale_value: str,
) -> None:
    _policy, old_publication, _member = _published_news_snapshot()
    candidate, _member, _old_model, raw = _stage_news_successor(old_publication)
    request = _activation_request(candidate, raw)
    pointer = CanonicalPublicationPointerModel.objects.get(
        dataset_key=candidate.dataset_key,
        publication_key=candidate.publication_key,
    )
    empty_identity: dict[str, object] = {
        "publication_id": None,
        "publication_hash": "",
        "activation_id": "",
    }
    empty_identity[stale_field] = stale_value
    CanonicalPublicationPointerModel.objects.filter(pk=pointer.pk).update(**empty_identity)

    with pytest.raises(
        PublicationActivationError,
        match="empty current pointer contains stale activation identity",
    ):
        _activate(request, _AuditWriter())

    persisted = CanonicalPublicationModel.objects.get(publication_id=candidate.publication_id)
    assert persisted.state == PublicationState.CANDIDATE.value
    assert SystemAuditEventModel.objects.count() == 0
    assert SystemAuditOutboxModel.objects.count() == 0
    pointer.refresh_from_db()
    assert pointer.publication_id is None
    assert getattr(pointer, stale_field) == stale_value


def test_activation_fails_closed_on_fact_drift_without_pointer_write() -> None:
    _policy, old_publication, _member = _published_news_snapshot()
    candidate, member, old_model, raw = _stage_news_successor(old_publication)
    NewsFactModel.objects.filter(pk=member.fact_pk).update(title="rewritten after staging")
    request = _activation_request(candidate, raw)

    with pytest.raises(PublicationActivationError, match="fact content hash drifted"):
        _activate(request, _AuditWriter())

    assert (
        CanonicalPublicationRepository()
        .get_current(old_publication.dataset_key, "current")
        .publication_id
        == old_publication.publication_id
    )
    assert (
        CanonicalPublicationModel.objects.get(publication_id=candidate.publication_id).state
        == PublicationState.CANDIDATE.value
    )
    assert old_model.title == "activation test news"


def test_activation_fails_closed_on_candidate_hash_drift_without_pointer_write() -> None:
    _policy, old_publication, _member = _published_news_snapshot()
    candidate, _member, _old_model, raw = _stage_news_successor(old_publication)
    CanonicalPublicationModel.objects.filter(publication_id=candidate.publication_id).update(
        publication_hash="f" * 64
    )
    request = _activation_request(candidate, raw)

    with pytest.raises(PublicationActivationError, match="candidate publication identity drifted"):
        _activate(request, _AuditWriter())

    assert (
        CanonicalPublicationRepository()
        .get_current(old_publication.dataset_key, "current")
        .publication_id
        == old_publication.publication_id
    )
    assert (
        CanonicalPublicationModel.objects.get(publication_id=candidate.publication_id).state
        == PublicationState.CANDIDATE.value
    )


def test_activation_fails_closed_when_candidate_run_identity_is_missing() -> None:
    _policy, old_publication, _member = _published_news_snapshot()
    candidate, _member, _old_model, raw = _stage_news_successor(old_publication)
    CanonicalPublicationModel.objects.filter(publication_id=candidate.publication_id).update(
        run_id=None
    )
    request = _activation_request(candidate, raw)

    with pytest.raises(PublicationActivationError, match="timing or run evidence differs"):
        _activate(request, _AuditWriter())

    assert (
        CanonicalPublicationRepository()
        .get_current(old_publication.dataset_key, "current")
        .publication_id
        == old_publication.publication_id
    )


def test_activation_fails_closed_on_member_manifest_drift_without_pointer_write() -> None:
    _policy, old_publication, _member = _published_news_snapshot()
    candidate, member, _old_model, raw = _stage_news_successor(old_publication)
    PublicationMemberModel.objects.filter(member_id=member.member_id).update(
        natural_key="drifted-natural-key"
    )
    request = _activation_request(candidate, raw)

    with pytest.raises(PublicationActivationError, match="member manifest drifted"):
        _activate(request, _AuditWriter())

    assert (
        CanonicalPublicationRepository()
        .get_current(old_publication.dataset_key, "current")
        .publication_id
        == old_publication.publication_id
    )


def test_sealed_candidate_rejects_concurrent_member_append() -> None:
    _policy, old_publication, _member = _published_snapshot()
    candidate, member, _old_model, _raw = _stage_successor(old_publication)

    with pytest.raises(ValueError, match="member set is sealed"):
        CanonicalPublicationRepository().add_member(member)


def test_activation_fails_closed_when_scope_pointer_is_missing() -> None:
    _policy, old_publication, _member = _published_news_snapshot()
    candidate, _member, _old_model, raw = _stage_news_successor(old_publication)
    CanonicalPublicationPointerModel.objects.filter(
        dataset_key=old_publication.dataset_key,
        publication_key="current",
    ).delete()
    request = PublicationActivationRequest(
        dataset_key=candidate.dataset_key,
        publication_key="current",
        candidate_publication_id=candidate.publication_id,
        candidate_publication_hash=candidate.publication_hash,
        activation_id="activation-no-pointer",
        audit_observation=_audit_observation(candidate, raw),
    )

    with pytest.raises(PublicationActivationError, match="pointer is missing"):
        _activate(request, _AuditWriter())
    assert (
        CanonicalPublicationRepository().get_current(old_publication.dataset_key, "current") is None
    )
