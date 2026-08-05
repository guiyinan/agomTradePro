"""Django persistence for governed stress scenarios and immutable run evidence."""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import cast
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.risk_center.application.scenario_dtos import (
    ActivateScenarioSetCommandDTO,
    CreateScenarioRevisionCommandDTO,
)
from apps.risk_center.domain.scenarios import (
    ProbabilitySource,
    ScenarioActivation,
    ScenarioDefinition,
    ScenarioDefinitionStatus,
    ScenarioRevision,
    ScenarioRevisionStatus,
    ScenarioRunEvidence,
    ScenarioSet,
    ScenarioSetMember,
    ScenarioSetRevision,
    ScenarioSourceType,
    ScenarioType,
    scenario_parameters_from_mapping,
    scenario_parameters_to_dict,
)
from apps.risk_center.infrastructure.models import (
    ScenarioActivationModel,
    ScenarioRunEvidenceModel,
    ScenarioSetMemberModel,
    ScenarioSetModel,
    ScenarioSetRevisionModel,
    StressScenarioDefinitionModel,
    StressScenarioRevisionModel,
)


def _json_default(value: object) -> str:
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def _json_safe(value: object) -> object:
    return json.loads(json.dumps(value, ensure_ascii=False, default=_json_default))


def _definition_to_domain(model: StressScenarioDefinitionModel) -> ScenarioDefinition:
    return ScenarioDefinition(
        scenario_key=model.scenario_key,
        name=model.name,
        category=model.category,
        owner=model.owner,
        status=ScenarioDefinitionStatus(model.status),
        description=model.description,
        legacy_aliases=tuple(str(item) for item in (model.legacy_aliases or [])),
        created_at=model.created_at,
    )


def _revision_to_domain(model: StressScenarioRevisionModel) -> ScenarioRevision:
    scenario_type = ScenarioType(model.scenario_type)
    parameters = scenario_parameters_from_mapping(
        scenario_type,
        cast(dict[str, object], model.parameters or {}),
    )
    source_evidence = tuple(
        cast(dict[str, object], item)
        for item in (model.source_evidence or [])
        if isinstance(item, dict)
    )
    return ScenarioRevision(
        revision_id=str(model.revision_id),
        scenario_key=model.definition.scenario_key,
        version=model.version,
        based_on_version=model.based_on_version,
        status=ScenarioRevisionStatus(model.status),
        scenario_type=scenario_type,
        parameters=parameters,
        assumptions=tuple(str(item) for item in (model.assumptions or [])),
        source_type=ScenarioSourceType(model.source_type),
        source_evidence=source_evidence,
        content_hash=model.content_hash,
        created_by=model.created_by,
        change_reason=model.change_reason,
        effective_at=model.effective_at,
        created_at=model.created_at,
    )


def _set_to_domain(model: ScenarioSetModel) -> ScenarioSet:
    return ScenarioSet(
        set_key=model.set_key,
        name=model.name,
        purpose=model.purpose,
        owner=model.owner,
        applicable_asset_scope=tuple(str(item) for item in (model.applicable_asset_scope or [])),
        status=ScenarioDefinitionStatus(model.status),
    )


def _set_revision_to_domain(model: ScenarioSetRevisionModel) -> ScenarioSetRevision:
    members = tuple(
        ScenarioSetMember(
            scenario_revision_id=str(item.scenario_revision_id),
            probability=Decimal(str(item.probability)),
            probability_source=ProbabilitySource(item.probability_source),
            sort_order=item.sort_order,
        )
        for item in model.members.all()
    )
    return ScenarioSetRevision(
        revision_id=str(model.revision_id),
        set_key=model.scenario_set.set_key,
        version=model.version,
        status=ScenarioRevisionStatus(model.status),
        members=members,
        driver_axes=tuple(str(item) for item in (model.driver_axes or [])),
        created_by=model.created_by,
        change_reason=model.change_reason,
        created_at=model.created_at,
        effective_from=model.effective_from,
        effective_to=model.effective_to,
        content_hash=model.content_hash,
    )


class DjangoScenarioRepository:
    """Single transactional implementation of scenario application ports."""

    def list_definitions(self, *, include_retired: bool = False) -> tuple[ScenarioDefinition, ...]:
        """List definitions without supplying a static fallback."""

        queryset = StressScenarioDefinitionModel._default_manager.all()
        if not include_retired:
            queryset = queryset.filter(status=ScenarioDefinitionStatus.ACTIVE.value)
        return tuple(_definition_to_domain(item) for item in queryset)

    def list_current_revisions(
        self,
        *,
        scenario_type: ScenarioType | None = None,
        include_inactive: bool = False,
    ) -> tuple[ScenarioRevision, ...]:
        """Return the highest eligible version of each requested definition."""

        queryset = StressScenarioRevisionModel._default_manager.select_related(
            "definition"
        ).order_by("definition__category", "definition__scenario_key", "-version")
        if include_inactive:
            queryset = queryset.all()
        else:
            queryset = queryset.filter(
                definition__status=ScenarioDefinitionStatus.ACTIVE.value,
                status__in=(
                    ScenarioRevisionStatus.APPROVED.value,
                    ScenarioRevisionStatus.ACTIVE.value,
                ),
            )
        if scenario_type is not None:
            queryset = queryset.filter(scenario_type=scenario_type.value)
        current: list[ScenarioRevision] = []
        seen: set[int] = set()
        for model in queryset:
            if model.definition_id in seen:
                continue
            seen.add(model.definition_id)
            current.append(_revision_to_domain(model))
        return tuple(current)

    def _definition_for_identifier(self, identifier: str) -> StressScenarioDefinitionModel | None:
        definition = StressScenarioDefinitionModel._default_manager.filter(
            scenario_key=identifier
        ).first()
        if definition is not None:
            return definition
        for candidate in StressScenarioDefinitionModel._default_manager.all():
            if identifier in {str(item) for item in (candidate.legacy_aliases or [])}:
                return candidate
        return None

    def get_revision(
        self,
        identifier: str,
        *,
        version: int | None = None,
    ) -> ScenarioRevision | None:
        """Resolve exact revision ids before scenario keys and legacy aliases."""

        try:
            model = (
                StressScenarioRevisionModel._default_manager.select_related("definition")
                .filter(revision_id=identifier)
                .first()
            )
        except (ValidationError, ValueError):
            model = None
        if model is not None:
            if version is not None and model.version != version:
                return None
            return _revision_to_domain(model)
        definition = self._definition_for_identifier(identifier)
        if definition is None:
            return None
        queryset = StressScenarioRevisionModel._default_manager.select_related("definition").filter(
            definition=definition
        )
        if version is not None:
            queryset = queryset.filter(version=version)
        else:
            queryset = queryset.filter(
                status__in=(
                    ScenarioRevisionStatus.APPROVED.value,
                    ScenarioRevisionStatus.ACTIVE.value,
                )
            ).order_by("-version")
        model = queryset.first()
        return _revision_to_domain(model) if model is not None else None

    def list_revisions(self, identifier: str) -> tuple[ScenarioRevision, ...]:
        """List immutable history for a canonical key or legacy alias."""

        definition = self._definition_for_identifier(identifier)
        if definition is None:
            return ()
        queryset = (
            StressScenarioRevisionModel._default_manager.select_related("definition")
            .filter(definition=definition)
            .order_by("-version")
        )
        return tuple(_revision_to_domain(model) for model in queryset)

    def get_active_set_revision(
        self,
        *,
        environment: str,
        purpose: str,
    ) -> ScenarioSetRevision | None:
        """Read the database-constrained active pointer for one scope."""

        activation = (
            ScenarioActivationModel._default_manager.select_related(
                "scenario_set_revision__scenario_set"
            )
            .prefetch_related("scenario_set_revision__members")
            .filter(environment=environment, purpose=purpose, is_active=True)
            .first()
        )
        if activation is None:
            return None
        return _set_revision_to_domain(activation.scenario_set_revision)

    @transaction.atomic
    def save_definition(self, definition: ScenarioDefinition) -> ScenarioDefinition:
        """Create a stable definition; existing keys are never silently overwritten."""

        model, created = StressScenarioDefinitionModel._default_manager.get_or_create(
            scenario_key=definition.scenario_key,
            defaults={
                "name": definition.name,
                "category": definition.category,
                "owner": definition.owner,
                "status": definition.status.value,
                "description": definition.description,
                "legacy_aliases": list(definition.legacy_aliases),
                "created_at": definition.created_at,
            },
        )
        if not created and _definition_to_domain(model) != definition:
            raise ValueError("scenario definition key already exists with different content")
        return _definition_to_domain(model)

    @transaction.atomic
    def save_revision(self, revision: ScenarioRevision) -> ScenarioRevision:
        """Append an exact caller-supplied version, primarily for trusted migrations/tests."""

        definition = (
            StressScenarioDefinitionModel._default_manager.select_for_update()
            .filter(scenario_key=revision.scenario_key)
            .first()
        )
        if definition is None:
            raise ValueError("scenario definition does not exist")
        try:
            model = StressScenarioRevisionModel._default_manager.create(
                revision_id=revision.revision_id,
                definition=definition,
                version=revision.version,
                based_on_version=revision.based_on_version,
                status=revision.status.value,
                scenario_type=revision.scenario_type.value,
                parameters=scenario_parameters_to_dict(revision.parameters),
                assumptions=list(revision.assumptions),
                source_evidence=_json_safe(revision.source_evidence),
                source_type=revision.source_type.value,
                content_hash=revision.content_hash,
                created_by=revision.created_by,
                change_reason=revision.change_reason,
                effective_at=revision.effective_at,
                created_at=revision.created_at,
            )
        except IntegrityError as exc:
            raise ValueError("scenario revision version or id already exists") from exc
        return _revision_to_domain(model)

    @transaction.atomic
    def append_next_revision(
        self,
        command: CreateScenarioRevisionCommandDTO,
    ) -> ScenarioRevision:
        """Lock the definition and allocate the next revision id/version server-side."""

        definition = (
            StressScenarioDefinitionModel._default_manager.select_for_update()
            .filter(scenario_key=command.scenario_key, status="active")
            .first()
        )
        if definition is None:
            raise ValueError("scenario definition does not exist or is retired")
        latest = (
            StressScenarioRevisionModel._default_manager.filter(definition=definition)
            .order_by("-version")
            .first()
        )
        latest_version = latest.version if latest is not None else None
        if command.based_on_version != latest_version:
            raise ValueError(
                f"scenario revision version conflict: expected {latest_version}, "
                f"received {command.based_on_version}"
            )
        revision = ScenarioRevision(
            revision_id=str(uuid4()),
            scenario_key=command.scenario_key,
            version=(latest_version or 0) + 1,
            based_on_version=latest_version,
            status=command.status,
            scenario_type=command.scenario_type,
            parameters=command.parameters,
            assumptions=command.assumptions,
            source_type=command.source_type,
            source_evidence=command.source_evidence,
            created_by=command.created_by,
            change_reason=command.change_reason,
            created_at=timezone.now(),
        )
        return self.save_revision(revision)

    @transaction.atomic
    def save_scenario_set(self, scenario_set: ScenarioSet) -> ScenarioSet:
        """Create a stable scenario-set identity."""

        model, created = ScenarioSetModel._default_manager.get_or_create(
            set_key=scenario_set.set_key,
            defaults={
                "name": scenario_set.name,
                "purpose": scenario_set.purpose,
                "owner": scenario_set.owner,
                "applicable_asset_scope": list(scenario_set.applicable_asset_scope),
                "status": scenario_set.status.value,
            },
        )
        if not created and _set_to_domain(model) != scenario_set:
            raise ValueError("scenario set key already exists with different content")
        return _set_to_domain(model)

    @transaction.atomic
    def save_set_revision(self, revision: ScenarioSetRevision) -> ScenarioSetRevision:
        """Append an immutable set revision and its validated probability members."""

        scenario_set = (
            ScenarioSetModel._default_manager.select_for_update()
            .filter(set_key=revision.set_key)
            .first()
        )
        if scenario_set is None:
            raise ValueError("scenario set does not exist")
        model = ScenarioSetRevisionModel._default_manager.create(
            revision_id=revision.revision_id,
            scenario_set=scenario_set,
            version=revision.version,
            status=revision.status.value,
            driver_axes=list(revision.driver_axes),
            content_hash=revision.content_hash,
            created_by=revision.created_by,
            change_reason=revision.change_reason,
            effective_from=revision.effective_from,
            effective_to=revision.effective_to,
            created_at=revision.created_at,
        )
        for member in revision.members:
            scenario_revision = StressScenarioRevisionModel._default_manager.filter(
                revision_id=member.scenario_revision_id,
                status__in=("approved", "active"),
            ).first()
            if scenario_revision is None:
                raise ValueError("active scenario sets may reference only approved revisions")
            ScenarioSetMemberModel._default_manager.create(
                scenario_set_revision=model,
                scenario_revision=scenario_revision,
                probability=member.probability,
                probability_source=member.probability_source.value,
                sort_order=member.sort_order,
            )
        return _set_revision_to_domain(model)

    @transaction.atomic
    def activate(self, activation: ScenarioActivation) -> ScenarioActivation:
        """Activate a caller-built domain pointer using its previous id as an expectation."""

        return self.activate_set_revision(
            ActivateScenarioSetCommandDTO(
                environment=activation.environment,
                purpose=activation.purpose,
                scenario_set_revision_id=activation.scenario_set_revision_id,
                activated_by=activation.activated_by,
                reason=activation.reason,
                expected_active_activation_id=activation.previous_activation_id,
                correlation_id=activation.correlation_id,
            )
        )

    @transaction.atomic
    def activate_set_revision(
        self,
        command: ActivateScenarioSetCommandDTO,
    ) -> ScenarioActivation:
        """Atomically switch an approved set revision with optimistic locking."""

        target = (
            ScenarioSetRevisionModel._default_manager.select_for_update()
            .select_related("scenario_set")
            .filter(revision_id=command.scenario_set_revision_id)
            .first()
        )
        if target is None or target.status not in {"approved", "active"}:
            raise ValueError("only approved scenario set revisions may be activated")
        if target.scenario_set.purpose != command.purpose:
            raise ValueError("scenario set purpose mismatch")
        list(
            ScenarioSetModel._default_manager.select_for_update()
            .filter(purpose=command.purpose)
            .values_list("pk", flat=True)
        )
        current = (
            ScenarioActivationModel._default_manager.select_for_update()
            .filter(
                environment=command.environment,
                purpose=command.purpose,
                is_active=True,
            )
            .first()
        )
        current_id = str(current.activation_id) if current is not None else None
        if current_id != command.expected_active_activation_id:
            raise ValueError(
                f"scenario activation conflict: expected {current_id}, "
                f"received {command.expected_active_activation_id}"
            )
        activated_at = timezone.now()
        if current is not None:
            current.is_active = False
            current.deactivated_at = activated_at
            current.save(update_fields=["is_active", "deactivated_at"])
        try:
            model = ScenarioActivationModel._default_manager.create(
                environment=command.environment,
                purpose=command.purpose,
                scenario_set_revision=target,
                previous_activation=current,
                activated_by=command.activated_by,
                reason=command.reason,
                correlation_id=command.correlation_id,
                activated_at=activated_at,
                is_active=True,
            )
        except IntegrityError as exc:
            raise ValueError("scenario activation conflict") from exc
        return ScenarioActivation(
            activation_id=str(model.activation_id),
            environment=model.environment,
            purpose=model.purpose,
            scenario_set_revision_id=str(model.scenario_set_revision_id),
            previous_activation_id=(
                str(model.previous_activation_id) if model.previous_activation_id else None
            ),
            activated_by=model.activated_by,
            reason=model.reason,
            correlation_id=model.correlation_id,
            activated_at=model.activated_at,
        )

    @transaction.atomic
    def save_run_evidence(self, evidence: ScenarioRunEvidence) -> ScenarioRunEvidence:
        """Append exact run evidence and reject conflicting run ids."""

        scenario_revision = StressScenarioRevisionModel._default_manager.filter(
            revision_id=evidence.scenario_revision_id
        ).first()
        if scenario_revision is None:
            raise ValueError("scenario revision for run evidence does not exist")
        scenario_set_revision = None
        if evidence.scenario_set_revision_id is not None:
            scenario_set_revision = ScenarioSetRevisionModel._default_manager.filter(
                revision_id=evidence.scenario_set_revision_id
            ).first()
            if scenario_set_revision is None:
                raise ValueError("scenario set revision for run evidence does not exist")
        existing = ScenarioRunEvidenceModel._default_manager.filter(run_id=evidence.run_id).first()
        if existing is not None:
            if existing.result_hash != evidence.result_hash:
                raise ValueError("scenario run id already exists with different evidence")
            return evidence
        ScenarioRunEvidenceModel._default_manager.create(
            run_id=evidence.run_id,
            scenario_revision=scenario_revision,
            scenario_set_revision=scenario_set_revision,
            portfolio_snapshot_id=evidence.portfolio_snapshot_id,
            portfolio_snapshot_hash=evidence.portfolio_snapshot_hash,
            as_of_time=evidence.as_of_time,
            data_evidence_ids=list(evidence.data_evidence_ids),
            result_hash=evidence.result_hash,
            allocation_policy_version=evidence.allocation_policy_version,
            code_version=evidence.code_version,
            must_not_use_for_decision=evidence.must_not_use_for_decision,
            blocked_reason=evidence.blocked_reason,
            created_at=evidence.created_at,
        )
        return evidence


__all__ = ["DjangoScenarioRepository"]
