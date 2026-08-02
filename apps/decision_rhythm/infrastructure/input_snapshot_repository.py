"""Repository for immutable decision input snapshots."""

from apps.data_center.application.pit_provider import get_pit_manifest_evidence
from apps.decision_rhythm.domain.input_snapshot import DecisionInputSnapshot

from .input_snapshot_models import DecisionInputSnapshotModel


class DecisionInputSnapshotRepository:
    """Persist and load canonical decision packages."""

    def save(self, snapshot: DecisionInputSnapshot) -> DecisionInputSnapshot:
        """Persist a verified snapshot idempotently by state hash."""

        snapshot.verify()
        from django.conf import settings

        if bool(getattr(settings, "DECISION_SNAPSHOT_REQUIRED", False)):
            from apps.events.infrastructure.event_store import StoredEventModel

            event_ids = {
                str(component["event_id"]) for component in snapshot.components.values()
            }
            stored_ids = set(
                StoredEventModel._default_manager.filter(event_id__in=event_ids).values_list(
                    "event_id", flat=True
                )
            )
            missing = sorted(event_ids - stored_ids)
            if missing:
                raise ValueError(
                    f"decision snapshot references missing events: {', '.join(missing)}"
                )
            manifest = get_pit_manifest_evidence(snapshot.pit_manifest_id)
            if manifest is None or not manifest["verified"]:
                raise ValueError("decision snapshot requires a verified PIT manifest")
        existing = DecisionInputSnapshotModel._default_manager.filter(
            state_hash=snapshot.state_hash
        ).first()
        if existing:
            return self._to_domain(existing)
        DecisionInputSnapshotModel._default_manager.create(
            snapshot_id=snapshot.snapshot_id,
            schema_version=snapshot.schema_version,
            as_of_time=snapshot.as_of_time,
            state_hash=snapshot.state_hash,
            pit_manifest_id=snapshot.pit_manifest_id,
            components=snapshot.components,
            portfolio_snapshot_id=snapshot.portfolio_snapshot_id,
            config_version=snapshot.config_version,
            strategy_version=snapshot.strategy_version,
            prompt_version=snapshot.prompt_version,
            freshness=snapshot.freshness,
            quality=snapshot.quality,
            must_not_use=snapshot.must_not_use,
            missing_components=list(snapshot.missing_components),
            creation_reason=snapshot.creation_reason,
            correlation_id=snapshot.correlation_id,
            caller=snapshot.caller,
        )
        return snapshot

    def get(self, snapshot_id: str) -> DecisionInputSnapshot | None:
        """Return one snapshot."""

        row = DecisionInputSnapshotModel._default_manager.filter(snapshot_id=snapshot_id).first()
        return self._to_domain(row) if row else None

    @staticmethod
    def _to_domain(row: DecisionInputSnapshotModel) -> DecisionInputSnapshot:
        return DecisionInputSnapshot(
            snapshot_id=row.snapshot_id,
            schema_version=row.schema_version,
            as_of_time=row.as_of_time,
            state_hash=row.state_hash,
            pit_manifest_id=row.pit_manifest_id,
            components=dict(row.components or {}),
            portfolio_snapshot_id=row.portfolio_snapshot_id,
            config_version=row.config_version,
            strategy_version=row.strategy_version,
            prompt_version=row.prompt_version,
            freshness=dict(row.freshness or {}),
            quality=dict(row.quality or {}),
            must_not_use=row.must_not_use,
            missing_components=tuple(row.missing_components or []),
            creation_reason=row.creation_reason,
            correlation_id=row.correlation_id,
            caller=row.caller,
        )
