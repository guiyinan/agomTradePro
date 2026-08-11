"""Exact PIT repository for Signal realization-source definitions."""

from __future__ import annotations

from datetime import datetime

from django.db import transaction

from apps.signal.application.forecast_realization_source_definition import (
    ForecastRealizationSourceDefinitionRepository,
)
from apps.signal.domain.forecast_realization_owner import (
    ForecastRealizationManifestSource,
    ForecastRealizationMemberSource,
)
from apps.signal.domain.forecast_realization_source_definition import (
    ForecastRealizationSourceDefinition,
)
from apps.signal.infrastructure.forecast_realization_models import (
    ForecastRealizationSourceDefinitionMemberModel,
    ForecastRealizationSourceDefinitionModel,
)
from apps.signal.infrastructure.forecast_realization_source_definition_codec import (
    ForecastRealizationSourceDefinitionCodecError,
    decode_forecast_realization_source_definition,
    encode_forecast_realization_source_definition,
)


class ForecastRealizationSourceDefinitionCorruption(ValueError):
    """Persisted definition payload, header, or membership differs from its seal."""


def _require_selector(value: str, field_name: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 300
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a bounded token")


def _require_aware(value: datetime) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")


class DjangoForecastRealizationSourceDefinitionRepository(
    ForecastRealizationSourceDefinitionRepository
):
    """Read-only, hash-bound PIT registry repository."""

    __slots__ = ("_using",)

    def __init__(self, *, using: str = "default") -> None:
        self._using = using

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared Django transaction identity."""

        return f"django:{self._using}"

    def get_exact(
        self,
        *,
        owner_record_id: str,
        owner_record_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> ForecastRealizationSourceDefinition | None:
        """Return one exact live definition or preserve absence as ``None``."""

        _require_selector(owner_record_id, "owner_record_id")
        _require_selector(owner_record_version, "owner_record_version")
        _require_selector(expected_content_hash, "expected_content_hash")
        _require_aware(as_of)
        with transaction.atomic(using=self._using):
            model = (
                ForecastRealizationSourceDefinitionModel._default_manager.using(self._using)
                .select_for_update()
                .prefetch_related("source_members")
                .filter(
                    owner_record_id=owner_record_id,
                    owner_record_version=owner_record_version,
                    content_hash=expected_content_hash,
                    available_at__lte=as_of,
                    registered_at__lte=as_of,
                    valid_until__gt=as_of,
                )
                .first()
            )
            if model is None:
                return None
            return _definition_from_model(model)


class DjangoForecastRealizationManifestSourceRegistryProvider:
    """Read the exact 0012 registry source for the private 0011 owner writer."""

    __slots__ = ("_using",)

    def __init__(self, *, using: str = "default") -> None:
        self._using = using

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared Django transaction identity."""

        return f"django:{self._using}"

    def get_exact(
        self,
        *,
        owner_record_id: str,
        owner_record_version: str,
        as_of: datetime,
    ) -> ForecastRealizationManifestSource | None:
        """Return the registered source only while its exact definition is live."""

        _require_selector(owner_record_id, "owner_record_id")
        _require_selector(owner_record_version, "owner_record_version")
        _require_aware(as_of)
        with transaction.atomic(using=self._using):
            model = (
                ForecastRealizationSourceDefinitionModel._default_manager.using(self._using)
                .select_for_update()
                .prefetch_related("source_members")
                .filter(
                    owner_record_id=owner_record_id,
                    owner_record_version=owner_record_version,
                    available_at__lte=as_of,
                    registered_at__lte=as_of,
                    valid_until__gt=as_of,
                )
                .first()
            )
            if model is None:
                return None
            return _definition_from_model(model).source


def _definition_from_model(
    model: ForecastRealizationSourceDefinitionModel,
) -> ForecastRealizationSourceDefinition:
    """Decode the strict payload and verify every relational mirror."""

    members = tuple(model.source_members.all().order_by("entry_id"))
    if not members:
        raise ForecastRealizationSourceDefinitionCorruption(
            "realization source definition has no members"
        )
    try:
        definition = decode_forecast_realization_source_definition(model.canonical_payload)
    except ForecastRealizationSourceDefinitionCodecError as error:
        raise ForecastRealizationSourceDefinitionCorruption(
            "realization source definition payload is invalid"
        ) from error
    if _definition_model_values(definition) != _definition_model_snapshot(model):
        raise ForecastRealizationSourceDefinitionCorruption(
            "realization source definition header differs from its payload"
        )
    if len(definition.source.members) != len(members):
        raise ForecastRealizationSourceDefinitionCorruption(
            "realization source definition membership is incomplete"
        )
    for source_member, model_member in zip(definition.source.members, members, strict=True):
        if _definition_member_model_values(
            source_member,
            definition_id=model.pk,
        ) != _definition_member_model_snapshot(model_member):
            raise ForecastRealizationSourceDefinitionCorruption(
                "realization source definition member differs from its payload"
            )
    return definition


def _definition_model_values(
    definition: ForecastRealizationSourceDefinition,
) -> dict[str, object]:
    source = definition.source
    return {
        "definition_version": definition.definition_version,
        "owner": definition.owner,
        "owner_record_id": source.owner_record_id,
        "owner_record_version": source.owner_record_version,
        "result_id": source.result_id,
        "result_version": source.result_version,
        "result_hash": source.result_hash,
        "calendar_id": source.calendar_id,
        "calendar_version": source.calendar_version,
        "period_id": source.period_id,
        "period_version": source.period_version,
        "period_hash": source.period_hash,
        "period_start": source.period_start,
        "period_end": source.period_end,
        "available_at": source.available_at,
        "valid_until": source.valid_until,
        "evidence_ref": source.evidence_ref,
        "source_content_hash": source.content_hash,
        "registered_at": definition.registered_at,
        "canonical_payload": encode_forecast_realization_source_definition(definition),
        "content_hash": definition.content_hash,
        "research_only": definition.research_only,
        "must_not_use_for_decision": definition.must_not_use_for_decision,
        "must_not_execute": definition.must_not_execute,
    }


def _definition_model_snapshot(
    model: ForecastRealizationSourceDefinitionModel,
) -> dict[str, object]:
    return {
        name: getattr(model, name)
        for name in (
            "definition_version",
            "owner",
            "owner_record_id",
            "owner_record_version",
            "result_id",
            "result_version",
            "result_hash",
            "calendar_id",
            "calendar_version",
            "period_id",
            "period_version",
            "period_hash",
            "period_start",
            "period_end",
            "available_at",
            "valid_until",
            "evidence_ref",
            "source_content_hash",
            "registered_at",
            "canonical_payload",
            "content_hash",
            "research_only",
            "must_not_use_for_decision",
            "must_not_execute",
        )
    }


def _definition_member_model_values(
    member: ForecastRealizationMemberSource,
    *,
    definition_id: int,
) -> dict[str, object]:
    return {
        "definition_id": definition_id,
        "entry_id": member.entry_id,
        "observation_id": member.observation_id,
        "observation_version": member.observation_version,
        "expected_observation_hash": member.expected_observation_hash,
        "forecast_group_id": member.forecast_group_id,
        "pit_manifest_version": member.pit_manifest_version,
        "pit_manifest_hash": member.pit_manifest_hash,
        "censoring_rule_version": member.censoring_rule_version,
        "outcome_evidence_valid_until": member.outcome_evidence_valid_until,
        "available_at": member.available_at,
        "evidence_ref": member.evidence_ref,
        "content_hash": member.content_hash,
    }


def _definition_member_model_snapshot(
    model: ForecastRealizationSourceDefinitionMemberModel,
) -> dict[str, object]:
    return {
        name: getattr(model, name)
        for name in (
            "definition_id",
            "entry_id",
            "observation_id",
            "observation_version",
            "expected_observation_hash",
            "forecast_group_id",
            "pit_manifest_version",
            "pit_manifest_hash",
            "censoring_rule_version",
            "outcome_evidence_valid_until",
            "available_at",
            "evidence_ref",
            "content_hash",
        )
    }


__all__ = [
    "DjangoForecastRealizationManifestSourceRegistryProvider",
    "DjangoForecastRealizationSourceDefinitionRepository",
    "ForecastRealizationSourceDefinitionCorruption",
]
