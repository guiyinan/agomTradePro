"""Real ORM composition for an execution quote candidate and exact pointer read."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.db import connection

import apps.data_center.application.execution_quote_activation as execution_quote_activation
import apps.data_center.execution_quote_publication_composition as execution_quote_composition
import apps.data_center.infrastructure.publication_group_activation_repository as group_activation_repository
from apps.audit.application.system_audit_query import SystemAuditReaderContext
from apps.audit.infrastructure.publication_activation_audit_writer import (
    DjangoPublicationActivationAuditVerifier,
    DjangoPublicationActivationAuditWriter,
)
from apps.audit.infrastructure.system_audit_event_outbox_coordinator import (
    DjangoSystemAuditEventOutboxCoordinator,
)
from apps.audit.infrastructure.system_audit_models import SystemAuditEventModel
from apps.audit.infrastructure.system_audit_outbox_models import SystemAuditOutboxModel
from apps.data_center.application.current_publication_staging import (
    CurrentPublicationStageRawAuditBinding,
)
from apps.data_center.application.execution_quote_activation import (
    ExecutionQuotePublicationActivationBundle,
    ExecutionQuotePublicationActivationError,
    stage_and_activate_execution_quote_candidate,
)
from apps.data_center.application.public import get_execution_quote
from apps.data_center.domain.contracts import DatasetKey, PublicationPolicy
from apps.data_center.domain.entities import RawAudit
from apps.data_center.execution_quote_publication_composition import (
    build_production_execution_quote_publication_bundle,
)
from apps.data_center.infrastructure.catalog_models import DatasetContractModel
from apps.data_center.infrastructure.fact_and_operational_models import RawAuditModel
from apps.data_center.infrastructure.models import QuoteSnapshotModel
from apps.data_center.infrastructure.provider_state_repositories import RawAuditRepository
from apps.data_center.infrastructure.publication_models import (
    CanonicalPublicationModel,
    CanonicalPublicationPointerModel,
)
from apps.data_center.infrastructure.publication_policy_repository import (
    PublicationPolicyRepository,
)

pytestmark = pytest.mark.django_db(
    transaction=True, available_apps=["apps.data_center", "apps.audit"]
)


@dataclass(frozen=True)
class _FenceFingerprint:
    complete_graph_hash: str = "f" * 64


@dataclass(frozen=True)
class _FenceResult:
    database_alias: str
    tenant_id: str
    owner_id: str
    generation: int
    fingerprint: _FenceFingerprint
    checked_at: datetime
    valid_until: datetime
    scope: str = "account_authority_complete_graph"


class _TestAuthorityFence:
    """Provide a complete test graph while owning the real activation transaction."""

    def __init__(
        self,
        *,
        checked_at: datetime | None = None,
        tenant_id: str = "fixture-tenant",
        owner_id: str = "fixture-owner",
    ) -> None:
        self._checked_at = checked_at
        self._tenant_id = tenant_id
        self._owner_id = owner_id

    @contextmanager
    def fence_complete(self, proof: object):
        """Yield one short-lived test lease for the real activation repository."""

        from django.db import transaction

        assert proof == "fixture-authority-proof"
        with transaction.atomic():
            checked_at = self._checked_at or datetime.now(UTC)
            yield _FenceResult(
                database_alias="default",
                tenant_id=self._tenant_id,
                owner_id=self._owner_id,
                generation=1,
                fingerprint=_FenceFingerprint(),
                checked_at=checked_at,
                valid_until=checked_at + timedelta(minutes=5),
            )


@dataclass(frozen=True)
class _TestAuthorityCapture:
    database_alias: str
    authority_fence: _TestAuthorityFence
    authority_proof: object


def _reader_context() -> SystemAuditReaderContext:
    """Build a capability-bearing test preflight context for the activation seam."""

    now = datetime.now(UTC)
    return SystemAuditReaderContext._from_authority(
        authority_source_id="fixture:authority",
        authority_source_version="1",
        actor_id="fixture:operator",
        user_id=7,
        tenant_id="fixture-tenant",
        owner_id="fixture-owner",
        authority_content_hash="a" * 64,
        is_authenticated=True,
        is_staff=True,
        role="admin",
        authority_state="active",
        authority_recorded_at=now - timedelta(minutes=1),
        authority_valid_until=now + timedelta(hours=1),
    )


def _seed_execution_quote(
    *,
    execution_ttl: int = 120,
    age_seconds: int = 20,
    run_id: str | None = None,
    asset_code: str = "600000.SH",
    create_catalog: bool = True,
) -> tuple[QuoteSnapshotModel, RawAudit, str, str]:
    """Persist synthetic quote, catalog, policy, and matching successful RawAudit."""

    now = datetime.now(UTC)
    observed_at = now - timedelta(seconds=age_seconds)
    fetched_at = observed_at + timedelta(seconds=2)
    run_id = run_id or str(uuid4())
    ingested_run_id = str(uuid4())
    dataset = DatasetKey("equity.quote.snapshot", "2.0", "1.0")
    policy = PublicationPolicy(
        dataset=dataset,
        minimum_coverage_ratio=1.0,
        allow_partial=False,
        conflict_action="block",
        required_evidence=(
            "source",
            "observed_at",
            "fetched_at",
            "source_record_id",
            "raw_payload_hash",
            "raw_payload_scope",
            "fact_content_hash",
        ),
        retention_days=3650,
        policy_version="2",
    )
    if create_catalog:
        PublicationPolicyRepository().save(policy)
        DatasetContractModel.objects.create(
            dataset_key=dataset.value,
            contract_version=dataset.contract_version,
            schema_version=dataset.schema_version,
            owner="data-platform",
            frequency="intraday",
            decision_critical=True,
            fields=[{"name": "snapshot_at", "value_type": "datetime"}],
            freshness_seconds=3600,
            execution_freshness_seconds=execution_ttl,
            active=True,
        )
    source = "activation-quote-test"
    source_record_id = f"fixture-quote:{uuid4().hex}"
    row = QuoteSnapshotModel.objects.create(
        asset_code=asset_code,
        snapshot_at=observed_at,
        fetched_at=fetched_at,
        current_price=Decimal("10.1234"),
        bid=Decimal("10.1200"),
        ask=Decimal("10.1300"),
        prev_close=Decimal("9.9000"),
        source=source,
        source_record_id=source_record_id,
        raw_payload_hash="b" * 64,
        quality_status="accepted",
        revision_number=1,
        contract_version=dataset.contract_version,
        schema_version=dataset.schema_version,
        ingested_run_id=ingested_run_id,
        extra={"raw_payload_scope": "batch_response_body"},
    )
    raw = RawAuditRepository().log(
        RawAudit(
            provider_name=source,
            capability="realtime_quote",
            request_params={"asset_code": asset_code},
            status="ok",
            row_count=1,
            fetched_at=fetched_at,
            extra={"source_type": "activation-quote-test"},
            response_payload_hash="c" * 64,
            schema_fingerprint="d" * 64,
            parser_version="execution-activation-fixture-v1",
            run_id=run_id,
            ingested_run_id=ingested_run_id,
        )
    )
    return row, raw, run_id, asset_code


def _bundle(
    *,
    audit_writer_factory=None,
    authority_checked_at: datetime | None = None,
    authority_tenant_id: str = "fixture-tenant",
    authority_owner_id: str = "fixture-owner",
) -> ExecutionQuotePublicationActivationBundle:
    """Use production candidate/repository composition with fixture authority and audit."""

    bundle = build_production_execution_quote_publication_bundle()
    writer_factory = audit_writer_factory or (
        lambda: DjangoPublicationActivationAuditWriter(DjangoSystemAuditEventOutboxCoordinator())
    )

    def verifier_factory(expected_epoch):
        """Bind a test-only verifier to the component database and expected epoch."""

        return execution_quote_composition._CompletedExecutionQuoteAuditAdapter(
            expected_epoch=expected_epoch,
            verifier=DjangoPublicationActivationAuditVerifier(
                DjangoSystemAuditEventOutboxCoordinator()
            ),
        )

    return replace(
        bundle,
        audit_writer_factory=writer_factory,
        audit_verifier_factory=verifier_factory,
        authority_capture=lambda **_kwargs: _TestAuthorityCapture(
            database_alias="default",
            authority_fence=_TestAuthorityFence(
                checked_at=authority_checked_at,
                tenant_id=authority_tenant_id,
                owner_id=authority_owner_id,
            ),
            authority_proof="fixture-authority-proof",
        ),
    )


def _stage_arguments(raw: RawAudit, run_id: str, asset_code: str) -> dict[str, object]:
    """Return one exact test-stage request bound to the persisted RawAudit row."""

    return {
        "asset_codes": (asset_code,),
        "published_at": datetime.now(UTC),
        "run_id": run_id,
        "task_attempt_id": "execution-activation-test:1",
        "raw_audit_bindings": (
            CurrentPublicationStageRawAuditBinding(
                reference=raw.exact_reference(),
                expected_source_type="activation-quote-test",
            ),
        ),
        "preflight_context": _reader_context(),
    }


def _resume_completed(run_id: str, asset_codes: tuple[str, ...]):
    """Call the public completed-only resume use case for this workflow fixture."""

    resume = execution_quote_activation.resume_completed_execution_quote_activation
    return resume(
        bundle=_bundle(),
        run_id=run_id,
        task_attempt_id="execution-activation-test:1",
        asset_codes=asset_codes,
        preflight_context=_reader_context(),
    )


def test_execution_quote_candidate_stages_activates_and_reads_exact_fact() -> None:
    """Run the real stage, manifest, fenced activation, pointer, and quote-read path."""

    row, raw, run_id, asset_code = _seed_execution_quote()

    publication = stage_and_activate_execution_quote_candidate(
        bundle=_bundle(),
        **_stage_arguments(raw, run_id, asset_code),
    )

    pointer = CanonicalPublicationPointerModel.objects.get(
        dataset_key="equity.quote.snapshot",
        publication_key="execution",
    )
    result = get_execution_quote(asset_code, as_of=datetime.now(UTC))

    assert publication.state.value == "published"
    assert str(pointer.publication_id) == publication.publication_id
    assert pointer.publication_hash == publication.publication_hash
    assert result.fact_pk == str(row.pk)
    assert result.publication_id == publication.publication_id
    assert result.last == Decimal("10.1234")
    assert (
        SystemAuditEventModel.objects.filter(publication_id=publication.publication_id).count() == 1
    )
    assert SystemAuditOutboxModel.objects.count() == 1
    assert RawAuditModel.objects.filter(pk=raw.raw_audit_id).exists()


def test_execution_activation_rechecks_fact_version_after_staging() -> None:
    """A fact version changed after candidate staging cannot move the execution pointer."""

    row, raw, run_id, asset_code = _seed_execution_quote()

    def mutate_then_build_writer() -> DjangoPublicationActivationAuditWriter:
        QuoteSnapshotModel.objects.filter(pk=row.pk).update(contract_version="3.0")
        return DjangoPublicationActivationAuditWriter(DjangoSystemAuditEventOutboxCoordinator())

    with pytest.raises(ExecutionQuotePublicationActivationError):
        stage_and_activate_execution_quote_candidate(
            bundle=_bundle(audit_writer_factory=mutate_then_build_writer),
            **_stage_arguments(raw, run_id, asset_code),
        )

    candidate = CanonicalPublicationModel.objects.get(
        dataset_key="equity.quote.snapshot",
        publication_key="execution",
    )
    pointer = CanonicalPublicationPointerModel.objects.get(
        dataset_key="equity.quote.snapshot",
        publication_key="execution",
    )
    assert candidate.state == "candidate"
    assert pointer.publication_id is None
    assert SystemAuditEventModel.objects.count() == 0
    assert SystemAuditOutboxModel.objects.count() == 0


def test_execution_staging_uses_execution_ttl_even_when_research_window_is_fresh() -> None:
    """Candidate construction rejects source evidence beyond its explicit execution TTL."""

    _row, raw, run_id, asset_code = _seed_execution_quote(execution_ttl=60, age_seconds=120)

    with pytest.raises(ExecutionQuotePublicationActivationError):
        stage_and_activate_execution_quote_candidate(
            bundle=_bundle(),
            **_stage_arguments(raw, run_id, asset_code),
        )

    assert not CanonicalPublicationModel.objects.filter(
        dataset_key="equity.quote.snapshot",
        publication_key="execution",
    ).exists()
    assert not CanonicalPublicationPointerModel.objects.filter(
        dataset_key="equity.quote.snapshot",
        publication_key="execution",
        publication_id__isnull=False,
    ).exists()


def test_execution_activation_rechecks_ttl_at_equality_before_pointer_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A wait to the exact TTL deadline blocks before pointer or audit writes."""

    row, raw, run_id, asset_code = _seed_execution_quote(execution_ttl=600, age_seconds=100)
    checked_at = datetime.now(UTC)
    deadline = row.snapshot_at + timedelta(seconds=600)
    clock_values = iter((checked_at, deadline))

    def install_clock() -> DjangoPublicationActivationAuditWriter:
        monkeypatch.setattr(
            group_activation_repository,
            "timezone",
            SimpleNamespace(now=lambda: next(clock_values)),
        )
        return DjangoPublicationActivationAuditWriter(DjangoSystemAuditEventOutboxCoordinator())

    with pytest.raises(ExecutionQuotePublicationActivationError):
        stage_and_activate_execution_quote_candidate(
            bundle=_bundle(
                audit_writer_factory=install_clock,
                authority_checked_at=checked_at,
            ),
            **_stage_arguments(raw, run_id, asset_code),
        )

    candidate = CanonicalPublicationModel.objects.get(
        dataset_key="equity.quote.snapshot",
        publication_key="execution",
    )
    pointer = CanonicalPublicationPointerModel.objects.get(
        dataset_key="equity.quote.snapshot",
        publication_key="execution",
    )
    assert candidate.state == "candidate"
    assert pointer.publication_id is None
    assert SystemAuditEventModel.objects.count() == 0
    assert SystemAuditOutboxModel.objects.count() == 0


def test_execution_activation_rolls_back_if_audit_io_crosses_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A post-audit clock check rolls back pointer, publication, audit, and outbox."""

    row, raw, run_id, asset_code = _seed_execution_quote(execution_ttl=600, age_seconds=100)
    checked_at = datetime.now(UTC)
    deadline = row.snapshot_at + timedelta(seconds=600)
    clock_values = iter((checked_at, deadline - timedelta(seconds=1), deadline))

    def install_clock() -> DjangoPublicationActivationAuditWriter:
        monkeypatch.setattr(
            group_activation_repository,
            "timezone",
            SimpleNamespace(now=lambda: next(clock_values)),
        )
        return DjangoPublicationActivationAuditWriter(DjangoSystemAuditEventOutboxCoordinator())

    with pytest.raises(ExecutionQuotePublicationActivationError):
        stage_and_activate_execution_quote_candidate(
            bundle=_bundle(
                audit_writer_factory=install_clock,
                authority_checked_at=checked_at,
            ),
            **_stage_arguments(raw, run_id, asset_code),
        )

    candidate = CanonicalPublicationModel.objects.get(
        dataset_key="equity.quote.snapshot",
        publication_key="execution",
    )
    pointer = CanonicalPublicationPointerModel.objects.get(
        dataset_key="equity.quote.snapshot",
        publication_key="execution",
    )
    assert candidate.state == "candidate"
    assert pointer.publication_id is None
    assert SystemAuditEventModel.objects.count() == 0
    assert SystemAuditOutboxModel.objects.count() == 0


def test_resume_returns_only_the_exact_completed_activation_without_writes() -> None:
    """Resume verifies a completed activation and does not append another event or outbox."""

    _row, raw, run_id, asset_code = _seed_execution_quote()
    activated = stage_and_activate_execution_quote_candidate(
        bundle=_bundle(),
        **_stage_arguments(raw, run_id, asset_code),
    )
    pointer_before = CanonicalPublicationPointerModel.objects.get(
        dataset_key="equity.quote.snapshot",
        publication_key="execution",
    )
    event_count_before = SystemAuditEventModel.objects.count()
    outbox_count_before = SystemAuditOutboxModel.objects.count()

    resumed = _resume_completed(run_id, (asset_code,))

    pointer_after = CanonicalPublicationPointerModel.objects.get(pk=pointer_before.pk)
    assert resumed == activated
    assert pointer_after.publication_id == pointer_before.publication_id
    assert pointer_after.publication_hash == pointer_before.publication_hash
    assert pointer_after.activation_id == pointer_before.activation_id
    assert pointer_after.updated_at == pointer_before.updated_at
    assert SystemAuditEventModel.objects.count() == event_count_before == 1
    assert SystemAuditOutboxModel.objects.count() == outbox_count_before == 1


def test_resume_blocks_a_staged_candidate_without_a_durable_activation_cas() -> None:
    """A CANDIDATE has no persisted original pointer CAS and cannot be resumed."""

    _row, raw, run_id, asset_code = _seed_execution_quote()
    bundle = _bundle()
    bundle.quote_staging.execute(
        execution_quote_activation.CurrentPublicationStageCommand(
            asset_codes=(asset_code,),
            published_at=datetime.now(UTC),
            run_id=run_id,
            task_attempt_id="execution-activation-test:1",
            raw_audit_bindings=(
                CurrentPublicationStageRawAuditBinding(
                    reference=raw.exact_reference(),
                    expected_source_type="activation-quote-test",
                ),
            ),
        )
    )

    with pytest.raises(execution_quote_activation.ExecutionQuoteResumeError):
        _resume_completed(run_id, (asset_code,))

    candidate = CanonicalPublicationModel.objects.get(
        dataset_key="equity.quote.snapshot",
        publication_key="execution",
    )
    pointer = CanonicalPublicationPointerModel.objects.get(
        dataset_key="equity.quote.snapshot",
        publication_key="execution",
    )
    assert candidate.state == "candidate"
    assert pointer.publication_id is None
    assert SystemAuditEventModel.objects.count() == 0
    assert SystemAuditOutboxModel.objects.count() == 0


def test_resume_blocks_when_the_completed_pointer_epoch_has_changed() -> None:
    """A same-publication pointer with a changed epoch is not the recorded completion."""

    _row, raw, run_id, asset_code = _seed_execution_quote()
    stage_and_activate_execution_quote_candidate(
        bundle=_bundle(),
        **_stage_arguments(raw, run_id, asset_code),
    )
    pointer = CanonicalPublicationPointerModel.objects.get(
        dataset_key="equity.quote.snapshot",
        publication_key="execution",
    )
    original_event_count = SystemAuditEventModel.objects.count()
    original_outbox_count = SystemAuditOutboxModel.objects.count()
    CanonicalPublicationPointerModel.objects.filter(pk=pointer.pk).update(
        updated_at=pointer.updated_at + timedelta(seconds=1)
    )

    with pytest.raises(execution_quote_activation.ExecutionQuoteResumeError):
        _resume_completed(run_id, (asset_code,))

    assert SystemAuditEventModel.objects.count() == original_event_count == 1
    assert SystemAuditOutboxModel.objects.count() == original_outbox_count == 1


def test_resume_reports_missing_outbox_as_corruption_without_repairing_it() -> None:
    """A missing persisted outbox is corruption, never an invitation to enqueue it."""

    _row, raw, run_id, asset_code = _seed_execution_quote()
    publication = stage_and_activate_execution_quote_candidate(
        bundle=_bundle(),
        **_stage_arguments(raw, run_id, asset_code),
    )
    with connection.cursor() as cursor:
        cursor.execute(
            "DELETE FROM audit_system_outbox WHERE event_id IN ("
            "SELECT event_id FROM audit_system_event WHERE publication_id = %s)",
            [publication.publication_id],
        )
    event_count = SystemAuditEventModel.objects.count()

    with pytest.raises(execution_quote_activation.ExecutionQuoteResumeCorruption):
        _resume_completed(run_id, (asset_code,))

    assert SystemAuditEventModel.objects.count() == event_count == 1
    assert SystemAuditOutboxModel.objects.count() == 0


def test_resume_reports_tampered_audit_event_as_corruption_without_repairing_it() -> None:
    """A scalar/header mismatch in the persisted Audit row is typed corruption."""

    _row, raw, run_id, asset_code = _seed_execution_quote()
    publication = stage_and_activate_execution_quote_candidate(
        bundle=_bundle(),
        **_stage_arguments(raw, run_id, asset_code),
    )
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE audit_system_event SET detail = %s WHERE publication_id = %s",
            ['{"altered":true}', publication.publication_id],
        )
    event_count = SystemAuditEventModel.objects.count()
    outbox_count = SystemAuditOutboxModel.objects.count()

    with pytest.raises(execution_quote_activation.ExecutionQuoteResumeCorruption):
        _resume_completed(run_id, (asset_code,))

    assert SystemAuditEventModel.objects.count() == event_count == 1
    assert SystemAuditOutboxModel.objects.count() == outbox_count == 1


def test_resume_blocks_when_current_authority_scope_differs_from_completion() -> None:
    """The completed event cannot be replayed using a changed current Account scope."""

    _row, raw, run_id, asset_code = _seed_execution_quote()
    stage_and_activate_execution_quote_candidate(
        bundle=_bundle(),
        **_stage_arguments(raw, run_id, asset_code),
    )
    event_count = SystemAuditEventModel.objects.count()
    outbox_count = SystemAuditOutboxModel.objects.count()
    bundle = replace(
        _bundle(),
        authority_capture=lambda **_kwargs: _TestAuthorityCapture(
            database_alias="default",
            authority_fence=_TestAuthorityFence(
                tenant_id="changed-tenant",
                owner_id="fixture-owner",
            ),
            authority_proof="fixture-authority-proof",
        ),
    )

    with pytest.raises(
        (
            execution_quote_activation.ExecutionQuoteResumeError,
            execution_quote_activation.ExecutionQuoteResumeCorruption,
        )
    ):
        execution_quote_activation.resume_completed_execution_quote_activation(
            bundle=bundle,
            run_id=run_id,
            task_attempt_id="execution-activation-test:1",
            asset_codes=(asset_code,),
            preflight_context=_reader_context(),
        )

    assert SystemAuditEventModel.objects.count() == event_count == 1
    assert SystemAuditOutboxModel.objects.count() == outbox_count == 1


def test_resume_rechecks_execution_ttl_at_the_exact_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A completed quote expires under the current execution TTL and cannot resume."""

    row, raw, run_id, asset_code = _seed_execution_quote(execution_ttl=120, age_seconds=20)
    stage_and_activate_execution_quote_candidate(
        bundle=_bundle(),
        **_stage_arguments(raw, run_id, asset_code),
    )
    deadline = row.snapshot_at + timedelta(seconds=120)
    monkeypatch.setattr(
        group_activation_repository,
        "timezone",
        SimpleNamespace(now=lambda: deadline),
    )
    event_count = SystemAuditEventModel.objects.count()
    outbox_count = SystemAuditOutboxModel.objects.count()

    with pytest.raises(execution_quote_activation.ExecutionQuoteResumeError):
        _resume_completed(run_id, (asset_code,))

    assert SystemAuditEventModel.objects.count() == event_count == 1
    assert SystemAuditOutboxModel.objects.count() == outbox_count == 1


def test_resume_blocks_ambiguous_manifest_run_and_task_binding() -> None:
    """Two complete manifests for one run/task pair are ambiguous even if one is active."""

    _row, raw, run_id, asset_code = _seed_execution_quote()
    stage_and_activate_execution_quote_candidate(
        bundle=_bundle(),
        **_stage_arguments(raw, run_id, asset_code),
    )
    _other_row, other_raw, other_run_id, other_asset = _seed_execution_quote(
        run_id=run_id,
        asset_code="000001.SZ",
        create_catalog=False,
    )
    assert other_run_id == run_id
    _bundle().quote_staging.execute(
        execution_quote_activation.CurrentPublicationStageCommand(
            asset_codes=(other_asset,),
            published_at=datetime.now(UTC),
            run_id=run_id,
            task_attempt_id="execution-activation-test:1",
            raw_audit_bindings=(
                CurrentPublicationStageRawAuditBinding(
                    reference=other_raw.exact_reference(),
                    expected_source_type="activation-quote-test",
                ),
            ),
        )
    )

    with pytest.raises(execution_quote_activation.ExecutionQuoteResumeError):
        _resume_completed(run_id, (asset_code,))

    assert SystemAuditEventModel.objects.count() == 1
    assert SystemAuditOutboxModel.objects.count() == 1
