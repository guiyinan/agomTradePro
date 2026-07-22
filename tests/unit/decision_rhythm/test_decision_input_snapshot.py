from datetime import UTC, datetime, timedelta

import pytest

from apps.data_center.domain.pit import (
    KnowledgeScope,
    PITDatasetManifest,
    calculate_pit_manifest_hash,
)
from apps.decision_rhythm.application.input_snapshot_use_cases import (
    BuildDecisionInputSnapshotRequest,
    BuildDecisionInputSnapshotUseCase,
)
from apps.decision_rhythm.infrastructure.input_snapshot_repository import (
    DecisionInputSnapshotRepository,
)
from apps.events.infrastructure.event_store import StoredEventModel


def _payload_hash(payload: dict) -> str:
    import hashlib
    import json

    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


class InMemorySnapshotRepository:
    def __init__(self) -> None:
        self.snapshot = None

    def save(self, snapshot):  # type: ignore[no-untyped-def]
        self.snapshot = snapshot
        return snapshot

    def get(self, snapshot_id: str):  # type: ignore[no-untyped-def]
        return self.snapshot if self.snapshot and self.snapshot.snapshot_id == snapshot_id else None


def _request(as_of: datetime) -> BuildDecisionInputSnapshotRequest:
    components = {
        name: {
            "version": "v1",
            "event_id": f"evt-{name}",
            "as_of_time": (as_of - timedelta(minutes=1)).isoformat(),
        }
        for name in ("regime", "policy", "risk", "beta_gate", "decision_rhythm")
    }
    return BuildDecisionInputSnapshotRequest(
        as_of_time=as_of,
        pit_manifest_id="manifest-1",
        components=components,
        portfolio_snapshot_id="portfolio-1",
        config_version="config-1",
        strategy_version="strategy-1",
        prompt_version="prompt-1",
    )


def test_snapshot_build_is_deterministic_and_verifiable() -> None:
    request = _request(datetime(2025, 3, 1, tzinfo=UTC))
    first = BuildDecisionInputSnapshotUseCase(InMemorySnapshotRepository()).execute(request)
    second = BuildDecisionInputSnapshotUseCase(InMemorySnapshotRepository()).execute(request)

    assert first.snapshot_id == second.snapshot_id
    assert first.state_hash == second.state_hash
    first.verify()


def test_snapshot_rejects_component_from_the_future() -> None:
    as_of = datetime(2025, 3, 1, tzinfo=UTC)
    request = _request(as_of)
    request.components["risk"]["as_of_time"] = (as_of + timedelta(seconds=1)).isoformat()

    with pytest.raises(ValueError, match="not valid"):
        BuildDecisionInputSnapshotUseCase(InMemorySnapshotRepository()).execute(request)


def test_snapshot_rejects_missing_or_stale_required_state() -> None:
    as_of = datetime(2025, 3, 1, tzinfo=UTC)
    missing = _request(as_of)
    del missing.components["risk"]
    with pytest.raises(ValueError, match="missing decision components: risk"):
        BuildDecisionInputSnapshotUseCase(InMemorySnapshotRepository()).execute(missing)

    stale = _request(as_of)
    stale.freshness["risk"] = {"is_stale": True}
    with pytest.raises(ValueError, match="stale decision evidence"):
        BuildDecisionInputSnapshotUseCase(InMemorySnapshotRepository()).execute(stale)


@pytest.mark.django_db
def test_snapshot_cutover_requires_real_events_and_verified_manifest(settings) -> None:
    from apps.data_center.infrastructure.pit_models import (
        PITDatasetManifestModel,
        PITFactVersionModel,
    )

    as_of = datetime(2025, 3, 1, tzinfo=UTC)
    fact = PITFactVersionModel.objects.create(
        dataset="regime_state",
        business_key="global",
        effective_at=as_of - timedelta(days=1),
        available_at=as_of - timedelta(hours=1),
        ingested_at=as_of - timedelta(minutes=30),
        source_record_id="regime-v1",
        content_hash="a" * 64,
        pit_quality="verified",
        payload={"regime": "recovery"},
    )
    selected_versions = [
        {
            "id": fact.pk,
            "dataset": fact.dataset,
            "business_key": fact.business_key,
            "content_hash": fact.content_hash,
            "payload_hash": _payload_hash(fact.payload),
            "pit_quality": fact.pit_quality,
        }
    ]
    manifest = PITDatasetManifest(
        manifest_id="manifest-verified",
        as_of_time=as_of,
        knowledge_scope=KnowledgeScope.PUBLIC,
        calendar_version="sse-v1",
        query_spec={"regime_state": {}},
        selected_versions=tuple(selected_versions),
        coverage={"regime_state": 1.0},
        missing=(),
        estimated=(),
        unknown=(),
        manifest_hash="",
    )
    PITDatasetManifestModel.objects.create(
        manifest_id=manifest.manifest_id,
        as_of_time=manifest.as_of_time,
        knowledge_scope=manifest.knowledge_scope.value,
        calendar_version=manifest.calendar_version,
        query_spec=manifest.query_spec,
        selected_versions=selected_versions,
        coverage=manifest.coverage,
        manifest_hash=calculate_pit_manifest_hash(manifest),
    )
    request = _request(as_of)
    request = BuildDecisionInputSnapshotRequest(
        **{**request.__dict__, "pit_manifest_id": "manifest-verified"}
    )
    for name, component in request.components.items():
        StoredEventModel.objects.create(
            event_id=component["event_id"],
            event_type=f"{name}.changed",
            payload={},
            occurred_at=as_of - timedelta(minutes=1),
            aggregate_type=name,
            aggregate_id="global",
            aggregate_version=1,
            effective_at=as_of - timedelta(minutes=1),
        )
    settings.DECISION_SNAPSHOT_REQUIRED = True

    snapshot = BuildDecisionInputSnapshotUseCase(DecisionInputSnapshotRepository()).execute(request)

    assert snapshot.pit_manifest_id == "manifest-verified"
    missing_manifest = BuildDecisionInputSnapshotRequest(
        **{**request.__dict__, "pit_manifest_id": "does-not-exist"}
    )
    with pytest.raises(ValueError, match="verified PIT manifest"):
        BuildDecisionInputSnapshotUseCase(DecisionInputSnapshotRepository()).execute(
            missing_manifest
        )
