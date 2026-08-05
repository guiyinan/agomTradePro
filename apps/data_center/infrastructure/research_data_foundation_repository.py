"""Django persistence for governed R1/R2 research-data foundations."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.data_center.domain.pit import KnowledgeScope, PITFactVersion, PITQuality
from apps.data_center.domain.research_data_foundation import (
    ASSET_GROUP_MEMBERSHIP_DATASET,
    INVESTOR_FLOW_OBSERVATION_DATASET,
    OPERATING_OBSERVATION_DATASET,
    AssetGroupRevision,
    InvestorFlowDefinition,
    InvestorFlowObservation,
    ObservationValueKind,
    OperatingMetricDefinition,
    OperatingObservation,
    PITAssetGroupMembership,
    validate_asset_group_membership,
    validate_investor_flow_observation,
    validate_operating_observation,
)

from .models import AssetMasterModel
from .pit_models import PITFactVersionModel
from .pit_repository import DjangoPITDataView
from .research_data_foundation_models import (
    AssetGroupRevisionModel,
    InvestorFlowDefinitionModel,
    OperatingMetricDefinitionModel,
)


def _content_hash(payload: dict[str, object]) -> str:
    """Return a stable digest for one canonical PIT payload."""

    encoded = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _utc_iso(value: datetime | None) -> str | None:
    """Serialize one aware clock to a stable UTC representation."""

    return value.astimezone(UTC).isoformat() if value is not None else None


def _business_key(*parts: str) -> str:
    """Build a human-auditable key that fits canonical PIT storage."""

    key = "|".join(parts)
    if len(key) > 255:
        raise ValueError("PIT business key exceeds 255 characters")
    return key


class ResearchDataFoundationRepository:
    """Persist versioned governance definitions and append-only PIT values."""

    def __init__(self, clock: Callable[[], datetime] = timezone.now) -> None:
        self._clock = clock

    @transaction.atomic
    def save_operating_metric_definition(
        self,
        definition: OperatingMetricDefinition,
    ) -> OperatingMetricDefinition:
        """Insert an operating definition or return an identical existing version."""

        existing = (
            OperatingMetricDefinitionModel._default_manager.select_for_update()
            .filter(
                metric_code=definition.metric_code,
                definition_version=definition.definition_version,
            )
            .first()
        )
        if existing is not None:
            if existing.to_domain() != definition:
                raise ValueError("operating metric definition version already has other content")
            return existing.to_domain()
        model = OperatingMetricDefinitionModel._default_manager.create(
            metric_code=definition.metric_code,
            definition_version=definition.definition_version,
            name=definition.name,
            canonical_unit=definition.canonical_unit,
            frequency=definition.frequency,
            source=definition.source,
            effective_at=definition.effective_at,
            effective_to=definition.effective_to,
            description=definition.description,
            is_active=definition.is_active,
        )
        return model.to_domain()

    def get_operating_metric_definition(
        self,
        metric_code: str,
        definition_version: int,
    ) -> OperatingMetricDefinition | None:
        """Return one exact governed operating definition version."""

        model = OperatingMetricDefinitionModel._default_manager.filter(
            metric_code=metric_code,
            definition_version=definition_version,
        ).first()
        return model.to_domain() if model is not None else None

    @transaction.atomic
    def save_investor_flow_definition(
        self,
        definition: InvestorFlowDefinition,
    ) -> InvestorFlowDefinition:
        """Insert a flow definition or return an identical existing version."""

        existing = (
            InvestorFlowDefinitionModel._default_manager.select_for_update()
            .filter(
                flow_code=definition.flow_code,
                definition_version=definition.definition_version,
            )
            .first()
        )
        if existing is not None:
            if existing.to_domain() != definition:
                raise ValueError("investor-flow definition version already has other content")
            return existing.to_domain()
        model = InvestorFlowDefinitionModel._default_manager.create(
            flow_code=definition.flow_code,
            definition_version=definition.definition_version,
            actor_code=definition.actor_code,
            actor_name=definition.actor_name,
            measure_kind=definition.measure_kind.value,
            canonical_unit=definition.canonical_unit,
            frequency=definition.frequency,
            source=definition.source,
            effective_at=definition.effective_at,
            effective_to=definition.effective_to,
            is_proxy=definition.is_proxy,
            proxy_target_actor_code=definition.proxy_target_actor_code,
            proxy_methodology_ref=definition.proxy_methodology_ref,
            description=definition.description,
            is_active=definition.is_active,
        )
        return model.to_domain()

    def get_investor_flow_definition(
        self,
        flow_code: str,
        definition_version: int,
    ) -> InvestorFlowDefinition | None:
        """Return one exact governed investor-flow definition version."""

        model = InvestorFlowDefinitionModel._default_manager.filter(
            flow_code=flow_code,
            definition_version=definition_version,
        ).first()
        return model.to_domain() if model is not None else None

    @transaction.atomic
    def save_asset_group_revision(
        self,
        definition: AssetGroupRevision,
    ) -> AssetGroupRevision:
        """Insert an asset-group revision or return an identical existing row."""

        existing = (
            AssetGroupRevisionModel._default_manager.select_for_update()
            .filter(group_code=definition.group_code, revision=definition.revision)
            .first()
        )
        if existing is not None:
            if existing.to_domain() != definition:
                raise ValueError("asset-group revision already has other content")
            return existing.to_domain()
        model = AssetGroupRevisionModel._default_manager.create(
            group_code=definition.group_code,
            revision=definition.revision,
            name=definition.name,
            source=definition.source,
            effective_at=definition.effective_at,
            effective_to=definition.effective_to,
            description=definition.description,
            is_active=definition.is_active,
        )
        return model.to_domain()

    def get_asset_group_revision(
        self,
        group_code: str,
        revision: int,
    ) -> AssetGroupRevision | None:
        """Return one exact governed asset-group revision."""

        model = AssetGroupRevisionModel._default_manager.filter(
            group_code=group_code,
            revision=revision,
        ).first()
        return model.to_domain() if model is not None else None

    def append_operating_observation(
        self,
        observation: OperatingObservation,
    ) -> PITFactVersion:
        """Validate and append an operating value to the canonical PIT store."""

        definition = self.get_operating_metric_definition(
            observation.metric_code,
            observation.definition_version,
        )
        if definition is None:
            raise ValueError("operating metric definition was not found")
        validate_operating_observation(definition, observation)
        payload: dict[str, object] = {
            "metric_code": observation.metric_code,
            "definition_version": observation.definition_version,
            "subject_type": observation.subject_type,
            "subject_code": observation.subject_code,
            "effective_at": _utc_iso(observation.effective_at),
            "effective_to": _utc_iso(observation.effective_to),
            "available_at": _utc_iso(observation.available_at),
            "revision_number": observation.revision_number,
            "value": str(observation.value),
            "unit": observation.unit,
            "frequency": observation.frequency,
            "source": observation.source,
            "value_kind": observation.value_kind.value,
            "source_record_id": observation.source_record_id,
            "assumption_set_id": observation.assumption_set_id,
            "model_version": observation.model_version,
        }
        key = _business_key(
            observation.metric_code,
            f"v{observation.definition_version}",
            observation.subject_type,
            observation.subject_code,
            _utc_iso(observation.effective_at) or "",
            observation.value_kind.value,
        )
        quality = (
            PITQuality.VERIFIED
            if observation.value_kind is ObservationValueKind.OBSERVED_FACT
            else PITQuality.ESTIMATED
        )
        return self._append_pit_version(
            dataset=OPERATING_OBSERVATION_DATASET,
            business_key=key,
            effective_at=observation.effective_at,
            effective_to=observation.effective_to,
            available_at=observation.available_at,
            revision_number=observation.revision_number,
            source_record_id=observation.lineage_ref,
            quality=quality,
            payload=payload,
        )

    def append_investor_flow_observation(
        self,
        observation: InvestorFlowObservation,
    ) -> PITFactVersion:
        """Validate and append a typed investor-flow value to PIT storage."""

        definition = self.get_investor_flow_definition(
            observation.flow_code,
            observation.definition_version,
        )
        if definition is None:
            raise ValueError("investor-flow definition was not found")
        validate_investor_flow_observation(definition, observation)
        payload: dict[str, object] = {
            "flow_code": observation.flow_code,
            "definition_version": observation.definition_version,
            "actor_code": definition.actor_code,
            "actor_name": definition.actor_name,
            "scope_type": observation.scope_type,
            "scope_code": observation.scope_code,
            "effective_at": _utc_iso(observation.effective_at),
            "effective_to": _utc_iso(observation.effective_to),
            "available_at": _utc_iso(observation.available_at),
            "revision_number": observation.revision_number,
            "value": str(observation.value),
            "measure_kind": observation.measure_kind.value,
            "unit": observation.unit,
            "frequency": observation.frequency,
            "source": observation.source,
            "source_record_id": observation.source_record_id,
            "is_proxy": observation.is_proxy,
            "proxy_target_actor_code": observation.proxy_target_actor_code,
            "proxy_methodology_ref": observation.proxy_methodology_ref,
        }
        key = _business_key(
            observation.flow_code,
            f"v{observation.definition_version}",
            observation.scope_type,
            observation.scope_code,
            _utc_iso(observation.effective_at) or "",
        )
        return self._append_pit_version(
            dataset=INVESTOR_FLOW_OBSERVATION_DATASET,
            business_key=key,
            effective_at=observation.effective_at,
            effective_to=observation.effective_to,
            available_at=observation.available_at,
            revision_number=observation.revision_number,
            source_record_id=observation.source_record_id,
            quality=PITQuality.VERIFIED,
            payload=payload,
        )

    def append_asset_group_membership(
        self,
        membership: PITAssetGroupMembership,
    ) -> PITFactVersion:
        """Validate and append one canonical asset-group membership version."""

        definition = self.get_asset_group_revision(
            membership.group_code,
            membership.group_revision,
        )
        if definition is None:
            raise ValueError("asset-group revision was not found")
        validate_asset_group_membership(definition, membership)
        if not AssetMasterModel._default_manager.filter(code=membership.asset_code).exists():
            raise ValueError("asset-group member is not in the canonical asset master")
        payload: dict[str, object] = {
            "group_code": membership.group_code,
            "group_revision": membership.group_revision,
            "asset_code": membership.asset_code,
            "effective_at": _utc_iso(membership.effective_at),
            "effective_to": _utc_iso(membership.effective_to),
            "available_at": _utc_iso(membership.available_at),
            "revision_number": membership.revision_number,
            "source": membership.source,
            "source_record_id": membership.source_record_id,
        }
        key = _business_key(
            membership.group_code,
            f"r{membership.group_revision}",
            membership.asset_code,
        )
        return self._append_pit_version(
            dataset=ASSET_GROUP_MEMBERSHIP_DATASET,
            business_key=key,
            effective_at=membership.effective_at,
            effective_to=membership.effective_to,
            available_at=membership.available_at,
            revision_number=membership.revision_number,
            source_record_id=membership.source_record_id,
            quality=PITQuality.VERIFIED,
            payload=payload,
        )

    def query_versions(
        self,
        *,
        dataset: str,
        as_of_time: datetime,
        knowledge_scope: KnowledgeScope,
        filters: dict[str, Any],
    ) -> list[PITFactVersion]:
        """Query canonical PIT versions through explicit knowledge-time semantics."""

        return DjangoPITDataView().query(
            dataset,
            as_of_time,
            knowledge_scope,
            filters,
        )

    def get_operating_fact_versions(
        self,
        version_ids: tuple[int, ...],
        *,
        as_of_time: datetime,
        knowledge_scope: KnowledgeScope,
    ) -> list[PITFactVersion]:
        """Return exact versions only when they are the latest knowable facts."""

        business_keys = list(
            PITFactVersionModel._default_manager.filter(
                pk__in=version_ids,
                dataset=OPERATING_OBSERVATION_DATASET,
            ).values_list("business_key", flat=True)
        )
        if len(business_keys) != len(version_ids):
            return []
        selected = DjangoPITDataView().query(
            OPERATING_OBSERVATION_DATASET,
            as_of_time,
            knowledge_scope,
            {"business_key__in": business_keys},
        )
        by_id = {fact.version_id: fact for fact in selected}
        return [by_id[version_id] for version_id in version_ids if version_id in by_id]

    @transaction.atomic
    def _append_pit_version(
        self,
        *,
        dataset: str,
        business_key: str,
        effective_at: datetime,
        effective_to: datetime | None,
        available_at: datetime,
        revision_number: int,
        source_record_id: str,
        quality: PITQuality,
        payload: dict[str, object],
    ) -> PITFactVersion:
        """Append idempotently while rejecting content conflicts per revision."""

        ingested_at = self._clock()
        if ingested_at.tzinfo is None or ingested_at.utcoffset() is None:
            raise ValueError("repository clock must be timezone-aware")
        if available_at > ingested_at:
            raise ValueError("available_at cannot be later than ingested_at")
        digest = _content_hash(payload)
        existing = (
            PITFactVersionModel._default_manager.select_for_update()
            .filter(
                dataset=dataset,
                business_key=business_key,
                revision_number=revision_number,
            )
            .first()
        )
        if existing is not None:
            if existing.content_hash != digest:
                raise ValueError("PIT revision already has conflicting content")
            return DjangoPITDataView._to_domain(existing)
        model = PITFactVersionModel._default_manager.create(
            dataset=dataset,
            business_key=business_key,
            effective_at=effective_at,
            effective_to=effective_to,
            available_at=available_at,
            ingested_at=ingested_at,
            revision_number=revision_number,
            source_record_id=source_record_id,
            content_hash=digest,
            pit_quality=quality.value,
            payload=payload,
        )
        return DjangoPITDataView._to_domain(model)


__all__ = ["ResearchDataFoundationRepository"]
