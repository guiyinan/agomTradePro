"""Django repository for append-only calibration definitions and receipts."""

from __future__ import annotations

from datetime import datetime

from django.db import IntegrityError, transaction

from apps.signal.domain.forecast_calibration_sample import (
    ForecastCalibrationExpectedMember,
    ForecastCalibrationSampleDefinition,
    ForecastCalibrationSampleMemberReceipt,
    ForecastCalibrationSampleReceipt,
)
from apps.signal.infrastructure.forecast_calibration_sample_codec import (
    decode_forecast_calibration_sample_definition,
    decode_forecast_calibration_sample_receipt,
    encode_forecast_calibration_sample_definition,
    encode_forecast_calibration_sample_receipt,
)
from apps.signal.infrastructure.forecast_calibration_sample_models import (
    ForecastCalibrationExpectedMemberModel,
    ForecastCalibrationSampleDefinitionModel,
    ForecastCalibrationSampleMemberReceiptModel,
    ForecastCalibrationSampleReceiptModel,
)
from apps.signal.infrastructure.forecast_realization_models import (
    _claim_forecast_realization_insert,
)


class ForecastCalibrationSampleCorruption(ValueError):
    """Raised when owner rows fork, overlap, or disagree with sealed payloads."""


def _aware(value: datetime, field_name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ForecastCalibrationSampleCorruption(f"{field_name} must be timezone-aware")


def _model_values(definition: ForecastCalibrationSampleDefinition) -> dict[str, object]:
    source = definition.source
    return {
        "definition_version": definition.definition_version,
        "sample_id": source.sample_id,
        "sample_version": source.sample_version,
        "scope_content_hash": source.scope_content_hash,
        "scenario_set_revision_id": source.scenario_set_revision_id,
        "scenario_revision_ids": [str(value) for value in source.scenario_revision_ids],
        "forecast_horizon_microseconds": int(source.forecast_horizon.total_seconds() * 1_000_000),
        "censoring_rule_version": source.censoring_rule_version,
        "sample_window_start": source.sample_window_start,
        "sample_window_end": source.sample_window_end,
        "available_at": source.available_at,
        "valid_until": source.valid_until,
        "evidence_ref": source.evidence_ref,
        "source_content_hash": source.content_hash,
        "registered_at": definition.registered_at,
        "canonical_payload": encode_forecast_calibration_sample_definition(definition),
        "content_hash": definition.content_hash,
        "research_only": True,
        "must_not_use_for_decision": True,
        "must_not_execute": True,
    }


def _model_snapshot(model: ForecastCalibrationSampleDefinitionModel) -> dict[str, object]:
    return {
        "definition_version": model.definition_version,
        "sample_id": model.sample_id,
        "sample_version": model.sample_version,
        "scope_content_hash": model.scope_content_hash,
        "scenario_set_revision_id": model.scenario_set_revision_id,
        "scenario_revision_ids": model.scenario_revision_ids,
        "forecast_horizon_microseconds": model.forecast_horizon_microseconds,
        "censoring_rule_version": model.censoring_rule_version,
        "sample_window_start": model.sample_window_start,
        "sample_window_end": model.sample_window_end,
        "available_at": model.available_at,
        "valid_until": model.valid_until,
        "evidence_ref": model.evidence_ref,
        "source_content_hash": model.source_content_hash,
        "registered_at": model.registered_at,
        "canonical_payload": model.canonical_payload,
        "content_hash": model.content_hash,
        "research_only": model.research_only,
        "must_not_use_for_decision": model.must_not_use_for_decision,
        "must_not_execute": model.must_not_execute,
    }


def _member_scalar_values(
    member: ForecastCalibrationExpectedMember,
) -> dict[str, object]:
    binding = member.binding
    return {
        "source_version": member.source_version,
        "entry_id": member.entry_id,
        "observation_version": member.observation_version,
        "forecast_group_id": member.forecast_group_id,
        "scenario_revision_id": binding.scenario_revision_id,
        "scenario_set_revision_id": binding.scenario_set_revision_id,
        "subjective_probability": binding.subjective_probability,
        "subjective_probability_source_version": binding.subjective_probability_source_version,
        "model_probability": binding.model_probability,
        "model_probability_source_version": binding.model_probability_source_version or "",
        "model_promotion_decision_id": binding.model_promotion_decision_id or "",
        "pit_manifest_id": member.pit_manifest_id,
        "pit_manifest_version": member.pit_manifest_version,
        "pit_manifest_hash": member.pit_manifest_hash,
        "censoring_rule_version": member.censoring_rule_version,
        "published_at": member.published_at,
        "horizon_end": member.horizon_end,
        "entry_recorded_at": member.entry_recorded_at,
        "outcome_evidence_valid_until": member.outcome_evidence_valid_until,
        "evidence_ref": member.evidence_ref,
        "content_hash": member.content_hash,
    }


def _member_values(
    definition_model: ForecastCalibrationSampleDefinitionModel,
    member: ForecastCalibrationExpectedMember,
) -> dict[str, object]:
    return {"definition": definition_model, **_member_scalar_values(member)}


def _member_snapshot(model: ForecastCalibrationExpectedMemberModel) -> dict[str, object]:
    return {
        "definition_id": model.definition_id,
        "source_version": model.source_version,
        "entry_id": model.entry_id,
        "observation_version": model.observation_version,
        "forecast_group_id": model.forecast_group_id,
        "scenario_revision_id": model.scenario_revision_id,
        "scenario_set_revision_id": model.scenario_set_revision_id,
        "subjective_probability": model.subjective_probability,
        "subjective_probability_source_version": model.subjective_probability_source_version,
        "model_probability": model.model_probability,
        "model_probability_source_version": model.model_probability_source_version,
        "model_promotion_decision_id": model.model_promotion_decision_id,
        "pit_manifest_id": model.pit_manifest_id,
        "pit_manifest_version": model.pit_manifest_version,
        "pit_manifest_hash": model.pit_manifest_hash,
        "censoring_rule_version": model.censoring_rule_version,
        "published_at": model.published_at,
        "horizon_end": model.horizon_end,
        "entry_recorded_at": model.entry_recorded_at,
        "outcome_evidence_valid_until": model.outcome_evidence_valid_until,
        "evidence_ref": model.evidence_ref,
        "content_hash": model.content_hash,
    }


def _expected_member_snapshot(
    definition_id: int,
    member: ForecastCalibrationExpectedMember,
) -> dict[str, object]:
    return {"definition_id": definition_id, **_member_scalar_values(member)}


def _receipt_scalar_values(
    receipt: ForecastCalibrationSampleReceipt,
) -> dict[str, object]:
    return {
        "receipt_version": receipt.receipt_version,
        "receipt_id": receipt.receipt_id,
        "pit_as_of": receipt.pit_as_of,
        "recorded_at": receipt.recorded_at,
        "canonical_payload": encode_forecast_calibration_sample_receipt(receipt),
        "content_hash": receipt.content_hash,
        "research_only": True,
        "must_not_use_for_decision": True,
        "must_not_execute": True,
    }


def _receipt_values(
    definition_model: ForecastCalibrationSampleDefinitionModel,
    receipt: ForecastCalibrationSampleReceipt,
) -> dict[str, object]:
    return {"definition": definition_model, **_receipt_scalar_values(receipt)}


def _receipt_snapshot(model: ForecastCalibrationSampleReceiptModel) -> dict[str, object]:
    return {
        "definition_id": model.definition_id,
        "receipt_version": model.receipt_version,
        "receipt_id": model.receipt_id,
        "pit_as_of": model.pit_as_of,
        "recorded_at": model.recorded_at,
        "canonical_payload": model.canonical_payload,
        "content_hash": model.content_hash,
        "research_only": model.research_only,
        "must_not_use_for_decision": model.must_not_use_for_decision,
        "must_not_execute": model.must_not_execute,
    }


def _expected_receipt_snapshot(
    definition_id: int,
    receipt: ForecastCalibrationSampleReceipt,
) -> dict[str, object]:
    return {"definition_id": definition_id, **_receipt_scalar_values(receipt)}


def _invalidation_payload(
    member: ForecastCalibrationSampleMemberReceipt,
) -> dict[str, object] | None:
    evidence = member.invalidation
    if evidence is None:
        return None
    return {
        "evidence_version": evidence.evidence_version,
        "invalidated_at": evidence.invalidated_at.isoformat(timespec="microseconds"),
        "invalidation_rule_version": evidence.invalidation_rule_version,
        "evidence_refs": list(evidence.evidence_refs),
        "content_hash": evidence.content_hash,
    }


def _receipt_member_scalar_values(
    member: ForecastCalibrationSampleMemberReceipt,
) -> dict[str, object]:
    invalidation = member.invalidation
    owner = member.owner
    binding = member.expected.binding
    return {
        "receipt_version": member.receipt_version,
        "entry_id": member.entry_id,
        "expected_member_hash": member.expected.content_hash,
        "owner_record_version": owner.source_version,
        "owner_record_hash": owner.content_hash,
        "scenario_revision_id": binding.scenario_revision_id,
        "scenario_set_revision_id": binding.scenario_set_revision_id,
        "pit_manifest_id": member.expected.pit_manifest_id,
        "published_at": member.expected.published_at,
        "horizon_end": member.expected.horizon_end,
        "entry_recorded_at": member.expected.entry_recorded_at,
        "resolution": member.resolution.value,
        "scenario_realized": member.scenario_realized,
        "outcome_recorded_at": member.outcome_recorded_at,
        "outcome_source_type": owner.outcome_source_type or "",
        "outcome_source_hash": owner.outcome_source_hash or "",
        "invalidation_payload": _invalidation_payload(member),
        "invalidated_at": None if invalidation is None else invalidation.invalidated_at,
        "invalidation_rule_version": (
            "" if invalidation is None else invalidation.invalidation_rule_version
        ),
        "invalidation_content_hash": "" if invalidation is None else invalidation.content_hash,
        "recorded_at": member.recorded_at,
        "content_hash": member.content_hash,
    }


def _receipt_member_values(
    receipt_model: ForecastCalibrationSampleReceiptModel,
    expected_model: ForecastCalibrationExpectedMemberModel,
    member: ForecastCalibrationSampleMemberReceipt,
) -> dict[str, object]:
    return {
        "receipt": receipt_model,
        "expected_member": expected_model,
        **_receipt_member_scalar_values(member),
    }


def _receipt_member_snapshot(
    model: ForecastCalibrationSampleMemberReceiptModel,
) -> dict[str, object]:
    return {
        "receipt_id": model.receipt_id,
        "expected_member_id": model.expected_member_id,
        "receipt_version": model.receipt_version,
        "entry_id": model.entry_id,
        "expected_member_hash": model.expected_member_hash,
        "owner_record_version": model.owner_record_version,
        "owner_record_hash": model.owner_record_hash,
        "scenario_revision_id": model.scenario_revision_id,
        "scenario_set_revision_id": model.scenario_set_revision_id,
        "pit_manifest_id": model.pit_manifest_id,
        "published_at": model.published_at,
        "horizon_end": model.horizon_end,
        "entry_recorded_at": model.entry_recorded_at,
        "resolution": model.resolution,
        "scenario_realized": model.scenario_realized,
        "outcome_recorded_at": model.outcome_recorded_at,
        "outcome_source_type": model.outcome_source_type,
        "outcome_source_hash": model.outcome_source_hash,
        "invalidation_payload": model.invalidation_payload,
        "invalidated_at": model.invalidated_at,
        "invalidation_rule_version": model.invalidation_rule_version,
        "invalidation_content_hash": model.invalidation_content_hash,
        "recorded_at": model.recorded_at,
        "content_hash": model.content_hash,
    }


def _expected_receipt_member_snapshot(
    receipt_id: int,
    expected_member_id: int,
    member: ForecastCalibrationSampleMemberReceipt,
) -> dict[str, object]:
    return {
        "receipt_id": receipt_id,
        "expected_member_id": expected_member_id,
        **_receipt_member_scalar_values(member),
    }


class DjangoForecastCalibrationSampleRepository:
    """Append and query exact calibration owner graphs on one Django alias."""

    def __init__(self, *, using: str = "default") -> None:
        if not isinstance(using, str) or not using.strip():
            raise ValueError("using is required")
        self._using = using.strip()
        self.unit_of_work_key = f"django:{self._using}"

    def append_definition(
        self,
        definition: ForecastCalibrationSampleDefinition,
        *,
        token: object,
    ) -> ForecastCalibrationSampleDefinition:
        """Append an exact definition and all expected members idempotently."""

        if type(definition) is not ForecastCalibrationSampleDefinition:
            raise ForecastCalibrationSampleCorruption("definition type is not canonical")
        canonical = definition.validated_copy()
        existing = (
            ForecastCalibrationSampleDefinitionModel._default_manager.using(self._using)
            .filter(content_hash=canonical.content_hash)
            .first()
        )
        if existing is not None:
            return self._definition_from_model(existing)
        values = _model_values(canonical)
        model = ForecastCalibrationSampleDefinitionModel(**values)
        try:
            with transaction.atomic(using=self._using):
                model.full_clean()
                with _claim_forecast_realization_insert(
                    token=token,
                    model_type=ForecastCalibrationSampleDefinitionModel,
                    expected_values=values,
                ):
                    model.save(force_insert=True, using=self._using)
                for member in canonical.source.members:
                    member_values = _member_values(model, member)
                    member_model = ForecastCalibrationExpectedMemberModel(**member_values)
                    member_model.full_clean()
                    with _claim_forecast_realization_insert(
                        token=token,
                        model_type=ForecastCalibrationExpectedMemberModel,
                        expected_values=member_values,
                    ):
                        member_model.save(force_insert=True, using=self._using)
        except IntegrityError:
            existing = (
                ForecastCalibrationSampleDefinitionModel._default_manager.using(self._using)
                .filter(content_hash=canonical.content_hash)
                .first()
            )
            if existing is None:
                raise
            return self._definition_from_model(existing)
        return self._definition_from_model(model)

    def append_receipt(
        self,
        receipt: ForecastCalibrationSampleReceipt,
        *,
        token: object,
    ) -> ForecastCalibrationSampleReceipt:
        """Append an exhaustive receipt and explicit state row for every member."""

        if type(receipt) is not ForecastCalibrationSampleReceipt:
            raise ForecastCalibrationSampleCorruption("receipt type is not canonical")
        canonical = receipt.validated_copy()
        definition_model = self._definition_model_for_hash(canonical.definition.content_hash)
        existing = (
            ForecastCalibrationSampleReceiptModel._default_manager.using(self._using)
            .filter(content_hash=canonical.content_hash)
            .first()
        )
        if existing is not None:
            return self._receipt_from_model(existing)
        expected_models = {
            model.entry_id: model
            for model in ForecastCalibrationExpectedMemberModel._default_manager.using(self._using)
            .filter(definition=definition_model)
            .order_by("entry_id", "pk")
        }
        if set(expected_models) != {member.entry_id for member in canonical.members}:
            raise ForecastCalibrationSampleCorruption("persisted expected membership is incomplete")
        values = _receipt_values(definition_model, canonical)
        model = ForecastCalibrationSampleReceiptModel(**values)
        try:
            with transaction.atomic(using=self._using):
                model.full_clean()
                with _claim_forecast_realization_insert(
                    token=token,
                    model_type=ForecastCalibrationSampleReceiptModel,
                    expected_values=values,
                ):
                    model.save(force_insert=True, using=self._using)
                for member in canonical.members:
                    member_values = _receipt_member_values(
                        model,
                        expected_models[member.entry_id],
                        member,
                    )
                    member_model = ForecastCalibrationSampleMemberReceiptModel(**member_values)
                    member_model.full_clean()
                    with _claim_forecast_realization_insert(
                        token=token,
                        model_type=ForecastCalibrationSampleMemberReceiptModel,
                        expected_values=member_values,
                    ):
                        member_model.save(force_insert=True, using=self._using)
        except IntegrityError:
            existing = (
                ForecastCalibrationSampleReceiptModel._default_manager.using(self._using)
                .filter(content_hash=canonical.content_hash)
                .first()
            )
            if existing is None:
                raise
            return self._receipt_from_model(existing)
        return self._receipt_from_model(model)

    def get_definition(
        self,
        *,
        sample_id: str,
        sample_version: str,
        as_of: datetime,
    ) -> ForecastCalibrationSampleDefinition | None:
        """Return one exact active identity or fail closed on an active fork."""

        _aware(as_of, "as_of")
        models_found = list(
            ForecastCalibrationSampleDefinitionModel._default_manager.using(self._using)
            .filter(
                sample_id=sample_id,
                sample_version=sample_version,
                available_at__lte=as_of,
                registered_at__lte=as_of,
                valid_until__gt=as_of,
            )
            .order_by("content_hash", "pk")
        )
        if not models_found:
            return None
        definitions = tuple(self._definition_from_model(model) for model in models_found)
        if len({definition.content_hash for definition in definitions}) != 1:
            raise ForecastCalibrationSampleCorruption("active calibration definition fork")
        return definitions[0]

    def get_for_scope(
        self,
        *,
        scope_content_hash: str,
        sample_window_start: datetime,
        sample_window_end: datetime,
        as_of: datetime,
    ) -> ForecastCalibrationSampleReceipt | None:
        """Resolve one exact non-overlapping scope/window receipt at PIT."""

        for value, label in (
            (sample_window_start, "sample_window_start"),
            (sample_window_end, "sample_window_end"),
            (as_of, "as_of"),
        ):
            _aware(value, label)
        definition_models = list(
            ForecastCalibrationSampleDefinitionModel._default_manager.using(self._using)
            .filter(
                scope_content_hash=scope_content_hash,
                sample_window_start__lt=sample_window_end,
                sample_window_end__gt=sample_window_start,
                available_at__lte=as_of,
                registered_at__lte=as_of,
                valid_until__gt=as_of,
            )
            .order_by("content_hash", "pk")
        )
        if not definition_models:
            return None
        definitions = tuple(self._definition_from_model(model) for model in definition_models)
        if any(
            definition.source.sample_window_start != sample_window_start
            or definition.source.sample_window_end != sample_window_end
            for definition in definitions
        ):
            raise ForecastCalibrationSampleCorruption("overlapping calibration sample windows")
        if len({definition.content_hash for definition in definitions}) != 1:
            raise ForecastCalibrationSampleCorruption("calibration scope/window fork")
        definition_model = definition_models[0]
        receipt_models = list(
            ForecastCalibrationSampleReceiptModel._default_manager.using(self._using)
            .filter(
                definition=definition_model,
                pit_as_of__lte=as_of,
                recorded_at__lte=as_of,
            )
            .order_by("-pit_as_of", "-recorded_at", "content_hash", "pk")
        )
        if not receipt_models:
            return None
        highest = (receipt_models[0].pit_as_of, receipt_models[0].recorded_at)
        winners = [
            model for model in receipt_models if (model.pit_as_of, model.recorded_at) == highest
        ]
        receipts = tuple(self._receipt_from_model(model) for model in winners)
        if len({receipt.content_hash for receipt in receipts}) != 1:
            raise ForecastCalibrationSampleCorruption("calibration receipt winner fork")
        return receipts[0]

    def _definition_model_for_hash(
        self,
        content_hash: str,
    ) -> ForecastCalibrationSampleDefinitionModel:
        models_found = list(
            ForecastCalibrationSampleDefinitionModel._default_manager.using(self._using)
            .filter(content_hash=content_hash)
            .order_by("pk")[:2]
        )
        if len(models_found) != 1:
            raise ForecastCalibrationSampleCorruption("definition row is missing or forked")
        self._definition_from_model(models_found[0])
        return models_found[0]

    def _definition_from_model(
        self,
        model: ForecastCalibrationSampleDefinitionModel,
    ) -> ForecastCalibrationSampleDefinition:
        try:
            definition = decode_forecast_calibration_sample_definition(model.canonical_payload)
        except ValueError as exc:
            raise ForecastCalibrationSampleCorruption("definition payload is corrupt") from exc
        if _model_snapshot(model) != _model_values(definition):
            raise ForecastCalibrationSampleCorruption(
                "definition row mirrors disagree with payload"
            )
        if model.pk is None:
            raise ForecastCalibrationSampleCorruption("definition row has no primary key")
        member_models = list(
            ForecastCalibrationExpectedMemberModel._default_manager.using(self._using)
            .filter(definition_id=model.pk)
            .order_by("entry_id", "pk")
        )
        if len(member_models) != len(definition.source.members):
            raise ForecastCalibrationSampleCorruption("expected membership row count mismatch")
        expected = {
            member.entry_id: _expected_member_snapshot(model.pk, member)
            for member in definition.source.members
        }
        if any(
            member_model.entry_id not in expected
            or _member_snapshot(member_model) != expected[member_model.entry_id]
            for member_model in member_models
        ):
            raise ForecastCalibrationSampleCorruption(
                "expected membership mirrors disagree with payload"
            )
        return definition

    def _receipt_from_model(
        self,
        model: ForecastCalibrationSampleReceiptModel,
    ) -> ForecastCalibrationSampleReceipt:
        try:
            receipt = decode_forecast_calibration_sample_receipt(model.canonical_payload)
        except ValueError as exc:
            raise ForecastCalibrationSampleCorruption("receipt payload is corrupt") from exc
        if model.definition_id is None or model.pk is None:
            raise ForecastCalibrationSampleCorruption("receipt relation is incomplete")
        if _receipt_snapshot(model) != _expected_receipt_snapshot(model.definition_id, receipt):
            raise ForecastCalibrationSampleCorruption("receipt row mirrors disagree with payload")
        definition_model = self._definition_model_for_hash(receipt.definition.content_hash)
        if definition_model.pk != model.definition_id:
            raise ForecastCalibrationSampleCorruption("receipt points to a substituted definition")
        expected_models = {
            item.entry_id: item
            for item in ForecastCalibrationExpectedMemberModel._default_manager.using(self._using)
            .filter(definition_id=model.definition_id)
            .order_by("entry_id", "pk")
        }
        member_models = list(
            ForecastCalibrationSampleMemberReceiptModel._default_manager.using(self._using)
            .filter(receipt_id=model.pk)
            .order_by("entry_id", "pk")
        )
        if len(member_models) != len(receipt.members):
            raise ForecastCalibrationSampleCorruption("receipt membership row count mismatch")
        expected = {
            member.entry_id: _expected_receipt_member_snapshot(
                model.pk,
                expected_models[member.entry_id].pk,
                member,
            )
            for member in receipt.members
        }
        if any(
            member_model.entry_id not in expected
            or _receipt_member_snapshot(member_model) != expected[member_model.entry_id]
            for member_model in member_models
        ):
            raise ForecastCalibrationSampleCorruption(
                "receipt member mirrors disagree with payload"
            )
        return receipt


class DjangoForecastCalibrationSampleQueryRepository:
    """Read-only façade that never retains an append-capable registry object."""

    __slots__ = ("_using",)

    def __init__(self, *, using: str = "default") -> None:
        if not isinstance(using, str) or not using.strip():
            raise ValueError("using is required")
        self._using = using.strip()

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared Django transaction identity."""

        return f"django:{self._using}"

    def get_for_scope(
        self,
        *,
        scope_content_hash: str,
        sample_window_start: datetime,
        sample_window_end: datetime,
        as_of: datetime,
    ) -> ForecastCalibrationSampleReceipt | None:
        """Perform one exact read without retaining a mutation capability."""

        return DjangoForecastCalibrationSampleRepository(using=self._using).get_for_scope(
            scope_content_hash=scope_content_hash,
            sample_window_start=sample_window_start,
            sample_window_end=sample_window_end,
            as_of=as_of,
        )


__all__ = [
    "DjangoForecastCalibrationSampleQueryRepository",
    "DjangoForecastCalibrationSampleRepository",
    "ForecastCalibrationSampleCorruption",
]
