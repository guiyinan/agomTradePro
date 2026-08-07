"""Django repository for governed and immutable R2 market-structure research."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, cast

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import OuterRef, Q, Subquery

from apps.data_center.domain.market_structure import (
    ImmutableMarketStructureEvidence,
    InvestorActorDefinition,
    MarketStructureObservation,
    MarketStructurePeriodCalendar,
    MarketStructurePeriodCalendarRef,
    MarketStructureSeriesDefinition,
    MarketStructureSeriesRef,
    PITMembershipSnapshot,
    VersionedEvidenceReference,
    validate_series_against_flow_definition,
)
from apps.data_center.domain.pit import KnowledgeScope, PITQuality
from apps.data_center.domain.research_data_foundation import (
    ASSET_GROUP_MEMBERSHIP_DATASET,
    INVESTOR_FLOW_OBSERVATION_DATASET,
    InvestorFlowMeasureKind,
)

from .market_structure_models import (
    InvestorActorDefinitionModel,
    MarketStructurePeriodCalendarModel,
    MarketStructureResearchEvidenceModel,
    MarketStructureSeriesDefinitionModel,
)
from .pit_models import PITFactVersionModel
from .pit_repository import DjangoPITDataView
from .research_data_foundation_models import InvestorFlowDefinitionModel


def _require_aware(value: datetime, field_name: str) -> None:
    """Reject naive query clocks at the Infrastructure boundary."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _payload_str(payload: dict[str, Any], key: str) -> str:
    """Read one non-empty string from a dynamic PIT payload."""

    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"PIT payload {key} is invalid")
    return value


def _payload_int(payload: dict[str, Any], key: str) -> int:
    """Read one non-negative integer from a dynamic PIT payload."""

    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"PIT payload {key} is invalid")
    return value


def _payload_bool(payload: dict[str, Any], key: str) -> bool:
    """Read one strict boolean from a dynamic PIT payload."""

    value = payload.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"PIT payload {key} is invalid")
    return value


def _payload_decimal(payload: dict[str, Any], key: str) -> Decimal:
    """Read one finite Decimal from a dynamic PIT payload without float math."""

    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError(f"PIT payload {key} is invalid")
    try:
        decimal_value = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"PIT payload {key} is invalid") from exc
    if not decimal_value.is_finite():
        raise ValueError(f"PIT payload {key} is invalid")
    return decimal_value


_PERIOD_CALENDAR_CONFLICT = (
    "market-structure period calendar identity already has conflicting immutable content"
)


def _reload_period_calendar_after_unique_conflict(
    calendar: MarketStructurePeriodCalendar,
) -> MarketStructurePeriodCalendar:
    """Replay a concurrent unique winner only when identity, hash and payload agree."""

    candidates = list(
        MarketStructurePeriodCalendarModel._default_manager.filter(
            Q(
                calendar_code=calendar.calendar_code,
                calendar_version=calendar.calendar_version,
            )
            | Q(calendar_hash=calendar.calendar_hash)
        )
    )
    if not candidates:
        raise LookupError("concurrent period calendar winner was not found")
    if len(candidates) != 1:
        raise ValueError(_PERIOD_CALENDAR_CONFLICT)
    candidate = candidates[0]
    if (
        candidate.calendar_code != calendar.calendar_code
        or candidate.calendar_version != calendar.calendar_version
        or candidate.calendar_hash != calendar.calendar_hash
    ):
        raise ValueError(_PERIOD_CALENDAR_CONFLICT)
    try:
        stored = candidate.to_domain()
    except (ValidationError, ValueError) as exc:
        raise ValueError(_PERIOD_CALENDAR_CONFLICT) from exc
    if stored != calendar:
        raise ValueError(_PERIOD_CALENDAR_CONFLICT)
    return stored


class MarketStructureResearchRepository:
    """Store governed definitions and resolve exact PIT research evidence."""

    @transaction.atomic
    def save_actor_definition(
        self,
        definition: InvestorActorDefinition,
    ) -> InvestorActorDefinition:
        """Insert idempotently and reject mutation of an actor version."""

        existing = (
            InvestorActorDefinitionModel._default_manager.select_for_update()
            .filter(
                taxonomy_code=definition.taxonomy_code,
                taxonomy_version=definition.taxonomy_version,
                actor_code=definition.actor_code,
            )
            .first()
        )
        if existing is not None:
            stored = existing.to_domain()
            if stored != definition:
                raise ValueError("investor actor version already has conflicting content")
            return stored
        if definition.parent_actor_code and not (
            InvestorActorDefinitionModel._default_manager.filter(
                taxonomy_code=definition.taxonomy_code,
                taxonomy_version=definition.taxonomy_version,
                actor_code=definition.parent_actor_code,
                is_active=True,
            ).exists()
        ):
            raise ValueError("parent investor actor definition was not found")
        model = InvestorActorDefinitionModel(
            taxonomy_code=definition.taxonomy_code,
            taxonomy_version=definition.taxonomy_version,
            actor_code=definition.actor_code,
            actor_name=definition.actor_name,
            parent_actor_code=definition.parent_actor_code,
            source=definition.source,
            revision_policy_ref=definition.revision_policy_ref,
            effective_at=definition.effective_at,
            available_at=definition.available_at,
            effective_to=definition.effective_to,
            expires_at=definition.expires_at,
            description=definition.description,
            is_active=definition.is_active,
            definition_hash=definition.definition_hash,
        )
        try:
            model.full_clean()
            model.save(force_insert=True)
        except (IntegrityError, ValidationError) as exc:
            raise ValueError("invalid investor actor definition") from exc
        return model.to_domain()

    def get_actor_definition(
        self,
        *,
        taxonomy_code: str,
        taxonomy_version: int,
        actor_code: str,
        as_of_time: datetime,
    ) -> InvestorActorDefinition | None:
        """Return one exact immutable actor taxonomy entry."""

        _require_aware(as_of_time, "as_of_time")
        model = (
            InvestorActorDefinitionModel._default_manager.filter(
                taxonomy_code=taxonomy_code,
                taxonomy_version=taxonomy_version,
                actor_code=actor_code,
                is_active=True,
                effective_at__lte=as_of_time,
                available_at__lte=as_of_time,
            )
            .filter(
                Q(effective_to__isnull=True) | Q(effective_to__gt=as_of_time),
                Q(expires_at__isnull=True) | Q(expires_at__gt=as_of_time),
            )
            .first()
        )
        return model.to_domain() if model is not None else None

    @transaction.atomic
    def save_period_calendar(
        self,
        calendar: MarketStructurePeriodCalendar,
    ) -> MarketStructurePeriodCalendar:
        """Insert one exact schedule idempotently and reject version mutation."""

        existing = (
            MarketStructurePeriodCalendarModel._default_manager.select_for_update()
            .filter(
                calendar_code=calendar.calendar_code,
                calendar_version=calendar.calendar_version,
            )
            .first()
        )
        if existing is not None:
            stored = existing.to_domain()
            if stored != calendar:
                raise ValueError(_PERIOD_CALENDAR_CONFLICT)
            return stored
        model = MarketStructurePeriodCalendarModel(
            calendar_code=calendar.calendar_code,
            calendar_version=calendar.calendar_version,
            frequency=calendar.frequency,
            source=calendar.source,
            revision_policy_ref=calendar.revision_policy_ref,
            available_at=calendar.available_at,
            expires_at=calendar.expires_at,
            periods=[period.astimezone(UTC).isoformat() for period in calendar.periods],
            description=calendar.description,
            is_active=calendar.is_active,
            calendar_hash=calendar.calendar_hash,
        )
        try:
            model.full_clean()
        except ValidationError as exc:
            try:
                return _reload_period_calendar_after_unique_conflict(calendar)
            except LookupError:
                raise ValueError("invalid market-structure period calendar") from exc
            except ValueError as conflict:
                raise conflict from exc
        try:
            with transaction.atomic():
                model.save(force_insert=True)
        except ValidationError as exc:
            raise ValueError("invalid market-structure period calendar") from exc
        except IntegrityError as exc:
            try:
                return _reload_period_calendar_after_unique_conflict(calendar)
            except LookupError as missing:
                raise RuntimeError(
                    "concurrent market-structure period calendar could not be resolved"
                ) from missing
            except ValueError as conflict:
                raise conflict from exc
        return model.to_domain()

    def get_period_calendar(
        self,
        reference: MarketStructurePeriodCalendarRef,
        *,
        as_of_time: datetime,
    ) -> MarketStructurePeriodCalendar | None:
        """Return one exact active schedule knowable at the request clock."""

        _require_aware(as_of_time, "as_of_time")
        model = (
            MarketStructurePeriodCalendarModel._default_manager.filter(
                calendar_code=reference.calendar_code,
                calendar_version=reference.calendar_version,
                is_active=True,
                available_at__lte=as_of_time,
            )
            .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=as_of_time))
            .first()
        )
        return model.to_domain() if model is not None else None

    @transaction.atomic
    def save_series_definition(
        self,
        definition: MarketStructureSeriesDefinition,
    ) -> MarketStructureSeriesDefinition:
        """Verify canonical flow and actor semantics before immutable insertion."""

        existing = (
            MarketStructureSeriesDefinitionModel._default_manager.select_for_update()
            .filter(
                series_code=definition.series_code,
                series_version=definition.series_version,
            )
            .first()
        )
        if existing is not None:
            stored = existing.to_domain()
            if stored != definition:
                raise ValueError("market-structure series version has conflicting content")
            return stored
        actor = self.get_actor_definition(
            taxonomy_code=definition.taxonomy_code,
            taxonomy_version=definition.taxonomy_version,
            actor_code=definition.actor_code,
            as_of_time=definition.available_at,
        )
        if actor is None or not actor.is_active:
            raise ValueError("active investor actor definition was not found")
        if definition.effective_at < actor.effective_at or (
            actor.effective_to is not None and definition.effective_at >= actor.effective_to
        ):
            raise ValueError("market-structure series falls outside actor definition interval")
        flow_model = InvestorFlowDefinitionModel._default_manager.filter(
            flow_code=definition.flow_code,
            definition_version=definition.flow_definition_version,
        ).first()
        if flow_model is None:
            raise ValueError("canonical investor-flow definition was not found")
        validate_series_against_flow_definition(definition, flow_model.to_domain())
        model = MarketStructureSeriesDefinitionModel(
            series_code=definition.series_code,
            series_version=definition.series_version,
            flow_code=definition.flow_code,
            flow_definition_version=definition.flow_definition_version,
            taxonomy_code=definition.taxonomy_code,
            taxonomy_version=definition.taxonomy_version,
            actor_code=definition.actor_code,
            measure_concept=definition.measure_concept.value,
            measure_kind=definition.measure_kind.value,
            canonical_unit=definition.canonical_unit,
            frequency=definition.frequency,
            source=definition.source,
            revision_policy_ref=definition.revision_policy_ref,
            effective_at=definition.effective_at,
            available_at=definition.available_at,
            effective_to=definition.effective_to,
            expires_at=definition.expires_at,
            is_proxy=definition.is_proxy,
            proxy_target_actor_code=definition.proxy_target_actor_code,
            proxy_methodology_ref=definition.proxy_methodology_ref,
            description=definition.description,
            is_active=definition.is_active,
            definition_hash=definition.definition_hash,
        )
        try:
            model.full_clean()
            model.save(force_insert=True)
        except (IntegrityError, ValidationError) as exc:
            raise ValueError("invalid market-structure series definition") from exc
        return model.to_domain()

    def get_series_definition(
        self,
        reference: MarketStructureSeriesRef,
        *,
        as_of_time: datetime,
    ) -> MarketStructureSeriesDefinition | None:
        """Return one exact immutable research series definition."""

        _require_aware(as_of_time, "as_of_time")
        model = (
            MarketStructureSeriesDefinitionModel._default_manager.filter(
                series_code=reference.series_code,
                series_version=reference.series_version,
                is_active=True,
                effective_at__lte=as_of_time,
                available_at__lte=as_of_time,
            )
            .filter(
                Q(effective_to__isnull=True) | Q(effective_to__gt=as_of_time),
                Q(expires_at__isnull=True) | Q(expires_at__gt=as_of_time),
            )
            .first()
        )
        return model.to_domain() if model is not None else None

    def list_series_observations(
        self,
        definition: MarketStructureSeriesDefinition,
        *,
        as_of_time: datetime,
        knowledge_scope: KnowledgeScope,
    ) -> tuple[MarketStructureObservation, ...]:
        """Normalize verified canonical facts while preserving their hashes."""

        _require_aware(as_of_time, "as_of_time")
        facts = DjangoPITDataView().query(
            INVESTOR_FLOW_OBSERVATION_DATASET,
            as_of_time,
            knowledge_scope,
            {
                "flow_code": definition.flow_code,
                "definition_version": definition.flow_definition_version,
                "scope_type": "asset",
            },
        )
        observations: list[MarketStructureObservation] = []
        for fact in facts:
            if fact.pit_quality is not PITQuality.VERIFIED or fact.available_at is None:
                raise ValueError("market-structure fact is not verified public evidence")
            payload = fact.payload
            measure_kind = InvestorFlowMeasureKind(_payload_str(payload, "measure_kind"))
            actual = (
                _payload_str(payload, "actor_code"),
                measure_kind,
                _payload_str(payload, "unit"),
                _payload_str(payload, "frequency"),
                _payload_str(payload, "source"),
                _payload_bool(payload, "is_proxy"),
                str(payload.get("proxy_target_actor_code", "")),
                str(payload.get("proxy_methodology_ref", "")),
            )
            expected = (
                definition.actor_code,
                definition.measure_kind,
                definition.canonical_unit,
                definition.frequency,
                definition.source,
                definition.is_proxy,
                definition.proxy_target_actor_code,
                definition.proxy_methodology_ref,
            )
            if actual != expected:
                raise ValueError("market-structure fact relabels governed semantics")
            revision_number = _payload_int(payload, "revision_number")
            if revision_number != fact.revision_number:
                raise ValueError("market-structure fact revision semantics conflict")
            observations.append(
                MarketStructureObservation(
                    series_code=definition.series_code,
                    series_version=definition.series_version,
                    actor_code=definition.actor_code,
                    asset_code=_payload_str(payload, "scope_code"),
                    measure_concept=definition.measure_concept,
                    effective_at=fact.effective_at,
                    available_at=fact.available_at,
                    value=_payload_decimal(payload, "value"),
                    unit=definition.canonical_unit,
                    frequency=definition.frequency,
                    source=definition.source,
                    revision_number=revision_number,
                    is_proxy=definition.is_proxy,
                    proxy_target_actor_code=definition.proxy_target_actor_code,
                    proxy_methodology_ref=definition.proxy_methodology_ref,
                    evidence=VersionedEvidenceReference(
                        dataset=fact.dataset,
                        version_id=fact.version_id,
                        content_hash=fact.content_hash,
                    ),
                )
            )
        return tuple(
            sorted(
                observations,
                key=lambda item: (item.effective_at, item.asset_code),
            )
        )

    def resolve_asset_group_membership(
        self,
        *,
        group_code: str,
        group_revision: int,
        effective_at: datetime,
        knowledge_at: datetime,
        knowledge_scope: KnowledgeScope,
    ) -> PITMembershipSnapshot:
        """Resolve historical members without substituting the current component set."""

        _require_aware(effective_at, "effective_at")
        _require_aware(knowledge_at, "knowledge_at")
        if knowledge_at < effective_at:
            raise ValueError("membership knowledge_at cannot precede effective_at")
        scope = KnowledgeScope(knowledge_scope)
        clock_field = "available_at" if scope is KnowledgeScope.PUBLIC else "ingested_at"
        queryset = PITFactVersionModel._default_manager.filter(
            dataset=ASSET_GROUP_MEMBERSHIP_DATASET,
            effective_at__lte=effective_at,
            payload__group_code=group_code,
            payload__group_revision=group_revision,
        ).filter(Q(effective_to__isnull=True) | Q(effective_to__gt=effective_at))
        if scope is KnowledgeScope.PUBLIC:
            queryset = queryset.filter(available_at__isnull=False)
        queryset = queryset.filter(**{f"{clock_field}__lte": knowledge_at})
        latest_id = (
            queryset.filter(business_key=OuterRef("business_key"))
            .order_by(f"-{clock_field}", "-revision_number", "-id")
            .values("id")[:1]
        )
        rows = queryset.filter(id=Subquery(latest_id)).order_by("business_key")
        assets: list[str] = []
        references: list[VersionedEvidenceReference] = []
        for row in rows:
            fact = DjangoPITDataView._to_domain(row)
            if fact.pit_quality is not PITQuality.VERIFIED:
                raise ValueError("asset-group membership is not verified")
            asset_code = _payload_str(fact.payload, "asset_code")
            if asset_code in assets:
                raise ValueError("asset-group membership contains duplicate assets")
            assets.append(asset_code)
            references.append(
                VersionedEvidenceReference(
                    dataset=fact.dataset,
                    version_id=fact.version_id,
                    content_hash=fact.content_hash,
                )
            )
        return PITMembershipSnapshot(
            group_code=group_code,
            group_revision=group_revision,
            effective_at=effective_at,
            knowledge_at=knowledge_at,
            asset_codes=tuple(assets),
            evidence=tuple(references),
        )

    @transaction.atomic
    def add_evidence(
        self,
        evidence: ImmutableMarketStructureEvidence,
    ) -> ImmutableMarketStructureEvidence:
        """Append idempotently and reject conflicting evidence versions."""

        existing = (
            MarketStructureResearchEvidenceModel._default_manager.select_for_update()
            .filter(
                evidence_key=evidence.evidence_key,
                evidence_version=evidence.evidence_version,
            )
            .first()
        )
        if existing is not None:
            stored = existing.to_domain()
            if stored != evidence:
                raise ValueError("market-structure evidence version has conflicting content")
            return stored
        parsed = json.loads(evidence.payload_json)
        if not isinstance(parsed, dict):
            raise ValueError("market-structure evidence payload must be an object")
        payload = cast(dict[str, object], parsed)
        model = MarketStructureResearchEvidenceModel(
            evidence_key=evidence.evidence_key,
            evidence_version=evidence.evidence_version,
            as_of_time=evidence.as_of_time,
            group_code=evidence.group_code,
            group_revision=evidence.group_revision,
            method_version=evidence.method_version,
            policy_code=evidence.policy_code,
            policy_version=evidence.policy_version,
            status=evidence.status.value,
            input_hash=evidence.input_hash,
            output_hash=evidence.output_hash,
            evidence_hash=evidence.evidence_hash,
            payload=payload,
            source_evidence=[item.to_payload() for item in evidence.source_evidence],
            research_only=evidence.research_only,
            must_not_use_for_decision=evidence.must_not_use_for_decision,
            must_not_execute=evidence.must_not_execute,
        )
        try:
            model.full_clean()
            model.save(force_insert=True)
        except (IntegrityError, ValidationError) as exc:
            raise ValueError("invalid market-structure evidence") from exc
        return model.to_domain()

    def get_evidence(
        self,
        *,
        evidence_key: str,
        evidence_version: int,
    ) -> ImmutableMarketStructureEvidence | None:
        """Return one exact hash-verified evidence version."""

        model = MarketStructureResearchEvidenceModel._default_manager.filter(
            evidence_key=evidence_key,
            evidence_version=evidence_version,
        ).first()
        return model.to_domain() if model is not None else None

    def get_evidence_at(
        self,
        *,
        evidence_key: str,
        evidence_version: int,
        as_of_time: datetime,
    ) -> ImmutableMarketStructureEvidence | None:
        """Return one exact evidence version only after its server receipt."""

        _require_aware(as_of_time, "as_of_time")
        model = MarketStructureResearchEvidenceModel._default_manager.filter(
            evidence_key=evidence_key,
            evidence_version=evidence_version,
            created_at__lte=as_of_time,
        ).first()
        return model.to_domain() if model is not None else None


__all__ = ["MarketStructureResearchRepository"]
