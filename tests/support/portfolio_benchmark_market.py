"""Local test-market facts staged and switched by the real three-dataset activation use case."""

import hashlib
import json
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.db import connection, transaction

from apps.audit.infrastructure.publication_activation_audit_writer import (
    DjangoPublicationActivationAuditWriter,
)
from apps.audit.infrastructure.system_audit_event_outbox_coordinator import (
    DjangoSystemAuditEventOutboxCoordinator,
)
from apps.data_center.application.publication_activation import (
    ActivateCanonicalPublicationGroupUseCase,
    PublicationActivationGroupCandidate,
    PublicationActivationGroupRequest,
)
from apps.data_center.application.publication_utils import (
    current_publication_id_for_hash,
    member_reference,
    publication_hash,
    publication_member_from_reference,
)
from apps.data_center.domain.control_plane import (
    CanonicalPublication,
    CoverageSnapshot,
    PublicationState,
)
from apps.data_center.domain.entities import RawAudit
from apps.data_center.domain.market_time import cn_market_session_close_utc
from apps.data_center.domain.raw_audit_manifest import (
    CandidateRawAuditManifest,
    CandidateRawAuditReference,
    canonical_capability_for_publication_dataset,
)
from apps.data_center.infrastructure.candidate_raw_audit_manifest_repository import (
    DjangoCandidateRawAuditManifestRepository,
)
from apps.data_center.infrastructure.models import (
    PriceBarModel,
    QuoteSnapshotModel,
    ValuationFactModel,
)
from apps.data_center.infrastructure.provider_state_repositories import RawAuditRepository
from apps.data_center.infrastructure.publication_activation_repository import (
    DjangoPublicationActivationRepository,
)
from apps.data_center.infrastructure.publication_fact_evidence import (
    publication_fact_reference_for_dataset,
)
from apps.data_center.infrastructure.publication_policy_repository import (
    PublicationPolicyRepository,
)
from apps.data_center.infrastructure.publication_rollback_models import (
    CanonicalPublicationPointerModel,
)
from tests.component.data_center.test_publication_activation import _FenceResult
from tests.support.native_postgres_database import assert_native_postgres_test_database
from tests.support.tui_research.market_consumer_state import ensure_market_catalog


def activate_benchmark_market_day(*, asset, day, close, at):
    """Activate three real candidates and audit events with an isolated fixture authority lease."""
    if connection.vendor == "postgresql":
        assert_native_postgres_test_database()
    elif connection.vendor != "sqlite" or not (
        "memory" in str(connection.settings_dict["NAME"])
        or "test" in Path(str(connection.settings_dict["NAME"])).name
    ):
        raise AssertionError("disposable benchmark-market test database required")
    ensure_market_catalog(governance_root=Path(settings.BASE_DIR) / "governance")
    observed = cn_market_session_close_utc(day)
    source = "synthetic-consumer-market"
    repository = DjangoPublicationActivationRepository()
    scopes = []
    run = str(uuid4())
    for dataset, model, key, values in (
        (
            "equity.price.bar",
            PriceBarModel,
            {"bar_date": day, "freq": "1d", "adjustment": "none"},
            {
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "volume": 100,
                "amount": 1000,
            },
        ),
        (
            "equity.quote.snapshot",
            QuoteSnapshotModel,
            {"snapshot_at": observed},
            {"current_price": close},
        ),
        (
            "equity.valuation.fact",
            ValuationFactModel,
            {"val_date": day},
            {
                "pe_ttm": 8,
                "pb": 1,
                "observed_at": observed,
                "available_at": observed,
                "extra": {"raw_payload_scope": "record_response_body"},
            },
        ),
    ):
        policy = PublicationPolicyRepository().get_active(dataset)
        assert policy
        revision = model.objects.filter(asset_code=asset, source=source, **key).count() + 1
        record = f"{source}:{asset}:{day}:{dataset}:{revision}"
        payload = json.dumps(dict(values, **key), sort_keys=True, default=str).encode()
        raw_hash = hashlib.sha256(payload).hexdigest()
        ingestion = uuid4()
        raw = RawAuditRepository().log(
            RawAudit(
                provider_name=source,
                capability=canonical_capability_for_publication_dataset(dataset),
                request_params={"asset": asset},
                status="ok",
                row_count=1,
                fetched_at=at,
                run_id=str(uuid4()),
                ingested_run_id=str(ingestion),
                response_payload_hash=raw_hash,
                schema_fingerprint=hashlib.sha256(dataset.encode()).hexdigest(),
                parser_version="benchmark-market-fixture",
                extra={"source_type": source, "source_record_id": record},
            )
        )
        fact = model.objects.create(
            asset_code=asset,
            source=source,
            ingested_run_id=ingestion,
            revision_number=revision,
            source_record_id=record,
            raw_payload_hash=raw_hash,
            quality_status="accepted",
            fetched_at=at,
            **values,
            **key,
        )
        fact.refresh_from_db()
        reference = publication_fact_reference_for_dataset(fact, dataset_key=dataset)
        digest = publication_hash([reference], policy_identity=policy.identity)
        identity = current_publication_id_for_hash(dataset, "current", digest)
        member = publication_member_from_reference(
            reference, member_id=str(uuid4()), publication_id=identity, dataset_key=dataset
        )
        assert (
            publication_hash([member_reference(member)], policy_identity=policy.identity) == digest
        )
        candidate = CanonicalPublication(
            publication_id=identity,
            dataset_key=dataset,
            publication_key="current",
            policy_version=policy.identity,
            state=PublicationState.CANDIDATE,
            selected_source=source,
            publication_hash=digest,
            coverage=CoverageSnapshot(
                coverage_id=str(uuid4()),
                publication_id=identity,
                requested_count=1,
                eligible_count=1,
                selected_count=1,
                missing_count=0,
                conflict_count=0,
                generated_at=at,
            ),
            member_count=1,
            as_of=observed,
            created_by="benchmark-market-fixture",
            run_id=run,
        )
        repository.stage_candidate_with_members(candidate, (member,))
        ref = CandidateRawAuditReference(
            raw.raw_audit_id,
            "1",
            raw.content_hash,
            raw.provider_name,
            raw.capability,
            raw.run_id,
            raw.ingested_run_id,
        )
        manifest = CandidateRawAuditManifest.create(
            publication_id=identity,
            publication_hash=digest,
            run_id=run,
            dataset_key=dataset,
            publication_key="current",
            task_attempt_id="benchmark-market-" + run,
            raw_audits=(ref,),
        )
        DjangoCandidateRawAuditManifestRepository().stage(manifest)
        pointer = CanonicalPublicationPointerModel.objects.get(
            dataset_key=dataset, publication_key="current"
        )
        scopes.append(
            PublicationActivationGroupCandidate(
                dataset,
                "current",
                identity,
                digest,
                str(pointer.publication_id) if pointer.publication_id else None,
                pointer.publication_hash or None,
            )
        )

    class TestFence:
        @contextmanager
        def fence_complete(self, proof):
            assert proof == run
            with transaction.atomic():
                yield _FenceResult(checked_at=at, valid_until=at + timedelta(hours=1))

    activated = ActivateCanonicalPublicationGroupUseCase(repository).execute(
        PublicationActivationGroupRequest("portfolio-benchmark-" + run, tuple(scopes)),
        audit_writer=DjangoPublicationActivationAuditWriter(
            DjangoSystemAuditEventOutboxCoordinator()
        ),
        authority_fence=TestFence(),
        authority_proof=run,
    )
    return next(result for result in activated if result.dataset_key == "equity.price.bar")
