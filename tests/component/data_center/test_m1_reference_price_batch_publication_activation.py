"""Native PostgreSQL contracts using synthetic provider captures and real persistence."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import cast

import pytest
from django.db import connection
from django.utils import timezone

from apps.audit.application.data_quality_audit import (
    AppendDataQualityAuditObservationUseCase,
    DataQualityAuditObservation,
    DataQualityStatusCount,
)
from apps.audit.infrastructure.system_audit_models import SystemAuditEventModel
from apps.audit.infrastructure.system_audit_outbox_models import SystemAuditOutboxModel
from apps.data_center.application.m1_reference_price_batch_publication import (
    M1ReferencePriceBatchPublicationCommand,
    M1ReferencePriceBatchPublicationError,
    M1ReferencePriceBatchPublicationUseCase,
)
from apps.data_center.application.m1_reference_price_publication import (
    M1PublicationPointerReader,
    M1ReferencePricePublicationCommand,
    M1ReferencePricePublicationUseCase,
)
from apps.data_center.application.price_response_capture import CapturedPriceBarResponse
from apps.data_center.application.public_published_queries import (
    get_published_price_bar_series,
)
from apps.data_center.application.publication_activation import (
    CurrentPublicationPointerSnapshot,
    PublicationActivationGroupAuditWriter,
)
from apps.data_center.application.publication_quality import RecordPublicationQualityUseCase
from apps.data_center.domain.control_plane import PublicationState
from apps.data_center.domain.publication_lanes import (
    M1_REBALANCE_REFERENCE_PUBLICATION_KEY,
)
from apps.data_center.infrastructure.candidate_raw_audit_manifest_repository import (
    DjangoCandidateRawAuditManifestRepository,
)
from apps.data_center.infrastructure.control_plane_repositories import (
    CanonicalPublicationRepository,
)
from apps.data_center.infrastructure.m1_reference_price_batch_publication_audit import (
    M1ReferencePriceBatchPublicationAuditWriter,
)
from apps.data_center.infrastructure.m1_reference_price_publication_audit import (
    M1ReferencePricePublicationAuditWriter,
)
from apps.data_center.infrastructure.publication_models import (
    CanonicalPublicationPointerModel,
)
from tests.component.data_center.test_m1_reference_price_publication_activation import (
    _build_m1_test_use_case,
)
from tests.support.native_postgres_database import assert_native_postgres_test_database

_DATASET_KEY = "equity.price.bar"
_ASSET_CODES = ("600036.SH", "601398.SH")
_TARGET_DATE = date(2026, 11, 3)
# Nov 4 00:00 UTC is 08:00 Shanghai, before the Nov 4 session opens, so Nov 3
# is still the latest completed market session for the public freshness gate.
_AS_OF = datetime(2026, 11, 4, 0, 0, tzinfo=UTC)


def _batch_use_case(
    single_use_case: M1ReferencePricePublicationUseCase,
    *,
    pointer_reader: M1PublicationPointerReader | None = None,
    quality_recorder: (
        RecordPublicationQualityUseCase | _PersistFirstRecoveryThenFailSecond | None
    ) = None,
) -> M1ReferencePriceBatchPublicationUseCase:
    """Reuse the M1 fixture's real sync, staging, activation and audit adapters."""

    def audit_writer_factory() -> PublicationActivationGroupAuditWriter:
        single_writer = single_use_case._audit_writer_factory()
        if not isinstance(single_writer, M1ReferencePricePublicationAuditWriter):
            raise AssertionError("the M1 fixture must supply its strict single-writer adapter")
        return cast(
            PublicationActivationGroupAuditWriter,
            M1ReferencePriceBatchPublicationAuditWriter(
                delegate=single_writer._delegate,
                quality_recorder=(
                    single_writer._quality_recorder
                    if quality_recorder is None
                    else cast(RecordPublicationQualityUseCase, quality_recorder)
                ),
            ),
        )

    return M1ReferencePriceBatchPublicationUseCase(
        price_sync=single_use_case._price_sync,
        provider_repository=single_use_case._providers,
        staging=single_use_case._staging,
        activate_group=single_use_case._activate_group,
        audit_writer_factory=audit_writer_factory,
        authority_preflight=single_use_case._authority_preflight,
        authority_capture=single_use_case._authority_capture,
        current_pointer_reader=pointer_reader or single_use_case._current_pointer_reader,
        clock=single_use_case._clock,
    )


def _read_public_member(*, asset_code: str, cutoff: datetime) -> dict[str, object]:
    """Read one exact member through the decision-facing public price query."""

    result = get_published_price_bar_series(
        asset_code,
        publication_key=M1_REBALANCE_REFERENCE_PUBLICATION_KEY,
        start=_TARGET_DATE,
        end=_TARGET_DATE,
        knowledge_cutoff=cutoff,
    )
    assert result["must_not_use_for_decision"] is False
    assert result["freshness_status"] == "fresh"
    rows = result["rows"]
    assert isinstance(rows, list) and len(rows) == 1
    row = rows[0]
    assert isinstance(row, dict)
    assert row["asset_code"] == asset_code
    assert row["timestamp"] == _TARGET_DATE.isoformat()
    return result


@pytest.mark.django_db(
    transaction=True,
    available_apps=["apps.data_center", "apps.audit"],
)
def test_two_exact_m1_members_activate_once_and_both_read_from_postgres(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Persist synthetic exact captures and expose both from one current pointer."""

    assert connection.vendor == "postgresql"
    assert_native_postgres_test_database()
    monkeypatch.setattr(timezone, "now", lambda: _AS_OF)
    single_use_case, source, provider_id, activation = _build_m1_test_use_case()
    batch = _batch_use_case(single_use_case)

    outcome = batch.execute(
        M1ReferencePriceBatchPublicationCommand(
            provider_id=provider_id,
            asset_codes=_ASSET_CODES,
            target_trade_date=_TARGET_DATE,
        )
    )

    assert source.calls == [(asset_code, _TARGET_DATE) for asset_code in _ASSET_CODES]
    assert len(activation.calls) == 1
    publication = outcome.publication
    assert publication.member_count == 2
    assert publication.selected_source == "tushare"
    assert (
        CanonicalPublicationRepository().get_current(
            _DATASET_KEY,
            M1_REBALANCE_REFERENCE_PUBLICATION_KEY,
        )
        == publication
    )
    manifest = DjangoCandidateRawAuditManifestRepository().validate(publication.publication_id)
    assert manifest.raw_audit_count == 2
    expected_lineage: dict[str, tuple[str, str, str]] = {}
    for result in outcome.sync_results:
        reference = result.raw_audit_reference
        assert reference is not None
        expected_lineage[reference.raw_audit_id] = (
            reference.content_hash,
            reference.run_id,
            reference.ingested_run_id,
        )
    actual_lineage = {
        reference.raw_audit_id: (
            reference.content_hash,
            reference.run_id,
            reference.ingested_run_id,
        )
        for reference in manifest.raw_audits
    }
    assert actual_lineage == expected_lineage
    events = SystemAuditEventModel._default_manager.filter(
        event_type="data.publication.published",
        publication_id=publication.publication_id,
    )
    assert events.count() == 1
    # Quality audit is a state-transition stream; the healthy accepted baseline
    # does not promise one persisted quality event for each source RawAudit.

    member_results = tuple(
        _read_public_member(asset_code=asset_code, cutoff=_AS_OF) for asset_code in _ASSET_CODES
    )
    assert all(item["publication_id"] == publication.publication_id for item in member_results)
    assert all(item["publication_hash"] == publication.publication_hash for item in member_results)


class _PersistFirstRecoveryThenFailSecond:
    """Use the real quality recorder once, verify its recovery event, then fail."""

    def __init__(self, delegate: RecordPublicationQualityUseCase) -> None:
        self._delegate = delegate
        self.calls: list[tuple[str, str, str, str]] = []
        self.publication_id: str | None = None
        self.raw_manifest_hash: str | None = None
        self.quality_event_id: str | None = None
        self.publication_event_id: str | None = None

    @property
    def database_alias(self) -> str:
        """Expose the real recorder's alias so the adapter keeps one UOW."""

        return self._delegate.database_alias

    def execute(
        self,
        *,
        publication_id: str,
        run_id: str,
        ingested_run_id: str,
        provider_key: str,
    ) -> DataQualityAuditObservation:
        """Persist and inspect the first recovery transition, then inject failure."""

        identity = (publication_id, run_id, ingested_run_id, provider_key)
        self.calls.append(identity)
        manifest = DjangoCandidateRawAuditManifestRepository().validate(publication_id)
        expected_pairs = tuple((item.run_id, item.ingested_run_id) for item in manifest.raw_audits)
        if len(expected_pairs) != 2:
            raise AssertionError("batch candidate must retain two exact RawAudit identities")

        if len(self.calls) == 1:
            if identity[1:3] != expected_pairs[0]:
                raise AssertionError("first quality call differs from the first RawAudit")
            observation = self._delegate.execute(
                publication_id=publication_id,
                run_id=run_id,
                ingested_run_id=ingested_run_id,
                provider_key=provider_key,
            )
            if observation.quality_state != "accepted":
                raise AssertionError("healthy batch must recover the prior degraded state")

            quality_event = SystemAuditEventModel._default_manager.get(
                event_type="data.quality.changed",
                publication_id=publication_id,
            )
            if (
                quality_event.correlations.get("run_id") != run_id
                or quality_event.correlations.get("ingested_run_id") != ingested_run_id
                or quality_event.detail.get("quality_state") != "accepted"
                or quality_event.detail.get("previous_quality_state") != "degraded"
                or quality_event.outcome != "recovered"
            ):
                raise AssertionError("first real quality recovery event lost its RawAudit lineage")
            SystemAuditOutboxModel._default_manager.get(event_id=quality_event.event_id)

            publication_event = SystemAuditEventModel._default_manager.get(
                event_type="data.publication.published",
                publication_id=publication_id,
            )
            raw_manifest = publication_event.detail.get("raw_audit_manifest")
            if not isinstance(raw_manifest, dict) or raw_manifest.get("raw_audit_count") != 2:
                raise AssertionError("activation manifest audit does not cover both RawAudits")
            event_references = publication_event.evidence_refs
            if not isinstance(event_references, list):
                raise AssertionError("activation manifest audit evidence is not a list")
            event_raw_ids = {
                reference.get("artifact_id")
                for reference in event_references
                if isinstance(reference, dict) and reference.get("artifact_type") == "raw_audit"
            }
            expected_raw_ids = {item.raw_audit_id for item in manifest.raw_audits}
            if event_raw_ids != expected_raw_ids:
                raise AssertionError("activation manifest audit omitted a batch RawAudit")
            SystemAuditOutboxModel._default_manager.get(event_id=publication_event.event_id)

            self.publication_id = publication_id
            self.raw_manifest_hash = manifest.manifest_hash
            self.quality_event_id = quality_event.event_id
            self.publication_event_id = publication_event.event_id
            return observation

        if len(self.calls) == 2:
            expected_publication_id = self.publication_id
            if (
                expected_publication_id is None
                or identity[0] != expected_publication_id
                or identity[1:3] != expected_pairs[1]
            ):
                raise AssertionError("second quality call differs from the second RawAudit")
            quality_event_id = self.quality_event_id
            publication_event_id = self.publication_event_id
            if quality_event_id is None or publication_event_id is None:
                raise AssertionError("first member quality and manifest audits were not persisted")
            SystemAuditEventModel._default_manager.get(event_id=quality_event_id)
            SystemAuditEventModel._default_manager.get(event_id=publication_event_id)
            SystemAuditOutboxModel._default_manager.get(event_id=quality_event_id)
            SystemAuditOutboxModel._default_manager.get(event_id=publication_event_id)
            raise ValueError("forced second member quality audit failure")

        raise AssertionError("batch writer requested more than two member quality audits")


@pytest.mark.django_db(
    transaction=True,
    available_apps=["apps.data_center", "apps.audit"],
)
def test_batch_quality_audit_failure_rolls_back_candidate_pointer_and_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Roll back batch recovery after a synthetic historical degraded audit state."""

    assert connection.vendor == "postgresql"
    assert_native_postgres_test_database()
    monkeypatch.setattr(timezone, "now", lambda: _AS_OF)
    single_use_case, _source, provider_id, _activation = _build_m1_test_use_case()
    baseline = single_use_case.execute(
        M1ReferencePricePublicationCommand(
            provider_id=provider_id,
            asset_code="000001.SZ",
            target_trade_date=_TARGET_DATE,
        )
    ).publication
    baseline_published_at = baseline.published_at
    if baseline_published_at is None:
        raise AssertionError("healthy baseline publication must have published_at")
    baseline_manifest = DjangoCandidateRawAuditManifestRepository().validate(
        baseline.publication_id
    )
    if baseline_manifest.raw_audit_count != 1:
        raise AssertionError("single baseline publication must retain one exact RawAudit")
    baseline_reference = baseline_manifest.raw_audits[0]

    single_writer = single_use_case._audit_writer_factory()
    if not isinstance(single_writer, M1ReferencePricePublicationAuditWriter):
        raise AssertionError("M1 fixture must supply its strict single-writer adapter")
    real_quality_recorder = single_writer._quality_recorder
    if not isinstance(real_quality_recorder, RecordPublicationQualityUseCase):
        raise AssertionError("M1 fixture must supply the real publication quality use case")
    quality_transition_writer = real_quality_recorder._quality_writer
    if not isinstance(
        quality_transition_writer,
        AppendDataQualityAuditObservationUseCase,
    ):
        raise AssertionError("M1 fixture must supply the public quality audit use case")
    if SystemAuditEventModel._default_manager.filter(
        event_type="data.quality.changed",
        publication_id=baseline.publication_id,
    ).exists():
        raise AssertionError("healthy initial quality state must not fabricate a transition")

    # This is an explicit synthetic audit-state premise for rollback coverage,
    # not a changed provider fact or a claim about market-data quality. It is
    # anchored to the healthy publication's real identity and exact RawAudit.
    degraded_recorded_at = baseline_published_at + timedelta(seconds=1)
    monkeypatch.setattr(timezone, "now", lambda: degraded_recorded_at)
    degraded_observation = DataQualityAuditObservation(
        dataset_key=baseline.dataset_key,
        publication_key=baseline.publication_key,
        publication_id=baseline.publication_id,
        publication_version=baseline.policy_version,
        publication_hash=baseline.publication_hash,
        provider_key=baseline.selected_source,
        run_id=baseline_reference.run_id,
        ingested_run_id=baseline_reference.ingested_run_id,
        quality_state="degraded",
        member_count=baseline.member_count,
        quality_status_counts=(
            DataQualityStatusCount(status="degraded", count=baseline.member_count),
        ),
        occurred_at=baseline_published_at,
        recorded_at=degraded_recorded_at,
    )
    degraded_commit = quality_transition_writer.execute(degraded_observation)
    if degraded_commit is None:
        raise AssertionError("synthetic degraded state must append through the public writer")
    baseline_quality_event = SystemAuditEventModel._default_manager.get(
        event_id=degraded_commit.event_id,
    )
    if (
        baseline_quality_event.event_type != "data.quality.changed"
        or baseline_quality_event.publication_id != baseline.publication_id
        or baseline_quality_event.correlations.get("run_id") != baseline_reference.run_id
        or baseline_quality_event.correlations.get("ingested_run_id")
        != baseline_reference.ingested_run_id
        or baseline_quality_event.detail.get("quality_state") != "degraded"
    ):
        raise AssertionError("synthetic degraded audit state lost its real publication lineage")
    baseline_outbox = SystemAuditOutboxModel._default_manager.get(
        event_id=baseline_quality_event.event_id
    )
    if (
        CanonicalPublicationRepository().get_current(
            _DATASET_KEY,
            M1_REBALANCE_REFERENCE_PUBLICATION_KEY,
        )
        != baseline
    ):
        raise AssertionError("quality audit premise must leave the healthy current pointer intact")

    batch_as_of = degraded_recorded_at + timedelta(seconds=1)
    monkeypatch.setattr(timezone, "now", lambda: batch_as_of)
    quality_recorder = _PersistFirstRecoveryThenFailSecond(real_quality_recorder)
    batch = _batch_use_case(single_use_case, quality_recorder=quality_recorder)

    with pytest.raises(M1ReferencePriceBatchPublicationError):
        batch.execute(
            M1ReferencePriceBatchPublicationCommand(
                provider_id=provider_id,
                asset_codes=_ASSET_CODES,
                target_trade_date=_TARGET_DATE,
            )
        )

    batch_publication_id = quality_recorder.publication_id
    raw_manifest_hash = quality_recorder.raw_manifest_hash
    quality_event_id = quality_recorder.quality_event_id
    publication_event_id = quality_recorder.publication_event_id
    if (
        batch_publication_id is None
        or raw_manifest_hash is None
        or quality_event_id is None
        or publication_event_id is None
    ):
        raise AssertionError("batch rollback checks did not capture the in-transaction audits")
    if len(quality_recorder.calls) != 2:
        raise AssertionError("batch must attempt one quality audit for each RawAudit")
    candidate_manifest = DjangoCandidateRawAuditManifestRepository().validate(batch_publication_id)
    assert candidate_manifest.manifest_hash == raw_manifest_hash
    expected_calls = tuple(
        (
            batch_publication_id,
            reference.run_id,
            reference.ingested_run_id,
            "tushare",
        )
        for reference in candidate_manifest.raw_audits
    )
    assert tuple(quality_recorder.calls) == expected_calls

    pointer = CanonicalPublicationPointerModel._default_manager.filter(
        dataset_key=_DATASET_KEY,
        publication_key=M1_REBALANCE_REFERENCE_PUBLICATION_KEY,
    ).first()
    assert pointer is not None and str(pointer.publication_id) == baseline.publication_id
    assert (
        CanonicalPublicationRepository().get_current(
            _DATASET_KEY,
            M1_REBALANCE_REFERENCE_PUBLICATION_KEY,
        )
        == baseline
    )
    assert not SystemAuditEventModel._default_manager.filter(
        event_id__in=(quality_event_id, publication_event_id)
    ).exists()
    assert not SystemAuditOutboxModel._default_manager.filter(
        event_id__in=(quality_event_id, publication_event_id)
    ).exists()
    assert (
        SystemAuditEventModel._default_manager.get(event_id=baseline_quality_event.event_id)
        == baseline_quality_event
    )
    assert (
        SystemAuditEventModel._default_manager.filter(stream_id=baseline_quality_event.stream_id)
        .order_by("-sequence_no")
        .first()
        == baseline_quality_event
    )
    assert SystemAuditOutboxModel._default_manager.get(event_id=baseline_outbox.event_id) == (
        baseline_outbox
    )
    assert (
        not SystemAuditEventModel._default_manager.filter(event_type="data.publication.published")
        .filter(publication_id=batch_publication_id)
        .exists()
    )
    # Candidate RawAudit manifests are sealed before activation. They remain as
    # an unpublished candidate after the activation transaction rolls back.
    candidate = CanonicalPublicationRepository().get_by_id(batch_publication_id)
    assert candidate is not None and candidate.state is PublicationState.CANDIDATE


@pytest.mark.django_db(
    transaction=True,
    available_apps=["apps.data_center", "apps.audit"],
)
def test_second_exact_raw_failure_never_stages_or_activates_a_partial_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject the candidate when its second exact provider capture cannot be stored."""

    assert connection.vendor == "postgresql"
    assert_native_postgres_test_database()
    monkeypatch.setattr(timezone, "now", lambda: _AS_OF)
    single_use_case, source, provider_id, _activation = _build_m1_test_use_case()
    batch = _batch_use_case(single_use_case)
    capture_exact = source.fetch_price_bar_with_capture

    def fail_second_capture(
        asset_code: str,
        target_trade_date: date,
    ) -> CapturedPriceBarResponse:
        if asset_code == _ASSET_CODES[1]:
            source.calls.append((asset_code, target_trade_date))
            raise RuntimeError("injected second RawAudit capture failure")
        return capture_exact(asset_code, target_trade_date)

    source.fetch_price_bar_with_capture = fail_second_capture
    with pytest.raises(RuntimeError, match="injected second RawAudit capture failure"):
        batch.execute(
            M1ReferencePriceBatchPublicationCommand(
                provider_id=provider_id,
                asset_codes=_ASSET_CODES,
                target_trade_date=_TARGET_DATE,
            )
        )

    assert source.calls == [(_ASSET_CODES[0], _TARGET_DATE), (_ASSET_CODES[1], _TARGET_DATE)]
    assert (
        CanonicalPublicationPointerModel._default_manager.filter(
            dataset_key=_DATASET_KEY,
            publication_key=M1_REBALANCE_REFERENCE_PUBLICATION_KEY,
            publication_id__isnull=False,
        ).count()
        == 0
    )
    assert not SystemAuditEventModel._default_manager.filter(
        event_type="data.publication.published"
    ).exists()


@pytest.mark.django_db(
    transaction=True,
    available_apps=["apps.data_center", "apps.audit"],
)
def test_batch_compare_and_swap_keeps_concurrent_single_publication_current(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject a stale batch CAS after another real M1 activation wins the pointer."""

    assert connection.vendor == "postgresql"
    assert_native_postgres_test_database()
    monkeypatch.setattr(timezone, "now", lambda: _AS_OF)
    single_use_case, source, provider_id, _activation = _build_m1_test_use_case()
    read_actual_pointer = single_use_case._current_pointer_reader
    expected_before_race: CurrentPublicationPointerSnapshot | None = None
    race_triggered = False

    def stale_snapshot_reader(
        dataset_key: str,
        publication_key: str,
    ) -> CurrentPublicationPointerSnapshot:
        nonlocal expected_before_race, race_triggered
        if expected_before_race is None:
            expected_before_race = read_actual_pointer(dataset_key, publication_key)
        if not race_triggered:
            race_triggered = True
            single_use_case.execute(
                # The established one-security path competes on the same actual M1 pointer.
                M1ReferencePricePublicationCommand(
                    provider_id=provider_id,
                    asset_code="000001.SZ",
                    target_trade_date=_TARGET_DATE,
                )
            )
            return expected_before_race
        return read_actual_pointer(dataset_key, publication_key)

    batch = _batch_use_case(single_use_case, pointer_reader=stale_snapshot_reader)
    with pytest.raises(M1ReferencePriceBatchPublicationError):
        batch.execute(
            M1ReferencePriceBatchPublicationCommand(
                provider_id=provider_id,
                asset_codes=_ASSET_CODES,
                target_trade_date=_TARGET_DATE,
            )
        )

    assert race_triggered
    assert source.calls == [
        (asset_code, _TARGET_DATE) for asset_code in (*_ASSET_CODES, "000001.SZ")
    ]
    current = CanonicalPublicationRepository().get_current(
        _DATASET_KEY,
        M1_REBALANCE_REFERENCE_PUBLICATION_KEY,
    )
    assert current is not None
    current_manifest = DjangoCandidateRawAuditManifestRepository().validate(current.publication_id)
    assert current.member_count == 1
    assert len(current_manifest.raw_audits) == 1
    assert (
        SystemAuditEventModel._default_manager.filter(
            event_type="data.publication.published"
        ).count()
        == 1
    )
    for asset_code in _ASSET_CODES:
        result = get_published_price_bar_series(
            asset_code,
            publication_key=M1_REBALANCE_REFERENCE_PUBLICATION_KEY,
            start=_TARGET_DATE,
            end=_TARGET_DATE,
            knowledge_cutoff=_AS_OF,
        )
        assert result["must_not_use_for_decision"] is True
