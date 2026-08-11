"""Exact PIT repository for Signal-owned R7 realization manifests."""

from __future__ import annotations

from datetime import datetime
from typing import NoReturn

from django.db import transaction

from apps.signal.application.forecast_realization_owner import (
    ForecastRealizationManifestRepository,
)
from apps.signal.domain.forecast_realization_owner import (
    ForecastOutcomeOwnerRecord,
    ForecastRealizationManifest,
    ForecastRealizationManifestSource,
    ForecastRealizationMemberSource,
    ForecastRealizationReceipt,
)
from apps.signal.domain.forecast_scenario_evidence import ScenarioForecastBinding
from apps.signal.infrastructure.forecast_models import ForecastOutcome
from apps.signal.infrastructure.forecast_realization_models import (
    ForecastRealizationManifestModel,
    ForecastRealizationReceiptModel,
)


class ForecastRealizationOwnerCorruption(ValueError):
    """Persisted receipt headers or their exact ForecastOutcome differ."""


class DjangoForecastOutcomeOwnerProvider:
    """Exact Application-compatible projection over immutable ForecastOutcome rows."""

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
        entry_id: str,
        as_of: datetime,
    ) -> ForecastOutcomeOwnerRecord | None:
        """Return one finalized scenario outcome at the exact PIT cutoff."""

        if not entry_id or any(character.isspace() for character in entry_id):
            raise ValueError("entry_id must be a bounded token")
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        with transaction.atomic(using=self._using):
            outcome = (
                ForecastOutcome._default_manager.using(self._using)
                .select_for_update()
                .select_related("entry")
                .filter(
                    entry_id=entry_id,
                    finalized_at__lte=as_of,
                    scenario_realized__isnull=False,
                )
                .first()
            )
            if outcome is None:
                return None
            entry = outcome.entry
            if (
                entry.scenario_revision_id is None
                or entry.subjective_probability is None
                or outcome.scenario_realized is None
            ):
                raise ForecastRealizationOwnerCorruption(
                    "forecast outcome scenario binding is incomplete"
                )
            try:
                binding = ScenarioForecastBinding.from_values(
                    scenario_revision_id=entry.scenario_revision_id,
                    scenario_set_revision_id=entry.scenario_set_revision_id,
                    subjective_probability=entry.subjective_probability,
                    subjective_probability_source_version=(
                        entry.subjective_probability_source_version
                    ),
                    model_probability=entry.model_probability,
                    model_probability_source_version=(
                        entry.model_probability_source_version or None
                    ),
                    model_promotion_decision_id=(entry.model_promotion_decision_id or None),
                )
                return ForecastOutcomeOwnerRecord.create(
                    entry_id=entry.entry_id,
                    binding=binding,
                    pit_manifest_id=entry.pit_manifest_id,
                    published_at=entry.published_at,
                    horizon_end=entry.horizon_end,
                    scenario_realized=outcome.scenario_realized,
                    outcome_recorded_at=outcome.finalized_at,
                )
            except (TypeError, ValueError) as error:
                raise ForecastRealizationOwnerCorruption(
                    "forecast outcome cannot be restored exactly"
                ) from error


class DjangoForecastRealizationManifestRepository(ForecastRealizationManifestRepository):
    """Read-only exact repository with dynamic ForecastOutcome replay."""

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
        result_id: str,
        result_version: str,
        expected_result_hash: str,
        period_id: str,
        period_version: str,
        expected_period_hash: str,
        as_of: datetime,
    ) -> ForecastRealizationManifest | None:
        """Return one exact active manifest or preserve absence as ``None``."""

        with transaction.atomic(using=self._using):
            model = (
                ForecastRealizationManifestModel._default_manager.using(self._using)
                .select_for_update()
                .prefetch_related("receipts__entry")
                .filter(
                    result_id=result_id,
                    result_version=result_version,
                    result_hash=expected_result_hash,
                    period_id=period_id,
                    period_version=period_version,
                    period_hash=expected_period_hash,
                    recorded_at__lte=as_of,
                    pit_as_of__lte=as_of,
                    valid_until__gt=as_of,
                )
                .first()
            )
            if model is None:
                return None
            return _manifest_from_model(
                model=model,
                outcome_provider=DjangoForecastOutcomeOwnerProvider(using=self._using),
                as_of=as_of,
            )


def _member_source_from_model(
    model: ForecastRealizationReceiptModel,
) -> ForecastRealizationMemberSource:
    try:
        source = ForecastRealizationMemberSource.create(
            entry_id=model.entry_id,
            observation_id=model.observation_id,
            observation_version=model.observation_version,
            expected_observation_hash=model.observation_hash,
            forecast_group_id=model.forecast_group_id,
            pit_manifest_version=model.pit_manifest_version,
            pit_manifest_hash=model.pit_manifest_hash,
            censoring_rule_version=model.censoring_rule_version,
            outcome_evidence_valid_until=model.outcome_evidence_valid_until,
            available_at=model.available_at,
            evidence_ref=model.evidence_ref,
        )
    except (TypeError, ValueError) as error:
        raise ForecastRealizationOwnerCorruption(
            "realization receipt metadata is invalid"
        ) from error
    if source.content_hash != model.member_source_hash:
        raise ForecastRealizationOwnerCorruption("realization receipt metadata hash mismatch")
    return source


def _source_from_model(
    model: ForecastRealizationManifestModel,
    member_sources: tuple[ForecastRealizationMemberSource, ...],
) -> ForecastRealizationManifestSource:
    try:
        source = ForecastRealizationManifestSource.create(
            owner_record_id=model.owner_record_id,
            owner_record_version=model.owner_record_version,
            result_id=model.result_id,
            result_version=model.result_version,
            result_hash=model.result_hash,
            calendar_id=model.calendar_id,
            calendar_version=model.calendar_version,
            period_id=model.period_id,
            period_version=model.period_version,
            period_hash=model.period_hash,
            period_start=model.period_start,
            period_end=model.period_end,
            available_at=model.available_at,
            valid_until=model.valid_until,
            evidence_ref=model.evidence_ref,
            members=member_sources,
        )
    except (TypeError, ValueError) as error:
        raise ForecastRealizationOwnerCorruption(
            "realization manifest source is invalid"
        ) from error
    if source.content_hash != model.source_manifest_hash:
        raise ForecastRealizationOwnerCorruption("realization manifest source hash mismatch")
    return source


def _manifest_from_model(
    *,
    model: ForecastRealizationManifestModel,
    outcome_provider: DjangoForecastOutcomeOwnerProvider,
    as_of: datetime,
) -> ForecastRealizationManifest:
    """Restore every header and dynamically reread every immutable outcome."""

    receipt_models = tuple(model.receipts.all().order_by("entry_id"))
    if not receipt_models:
        raise ForecastRealizationOwnerCorruption("realization manifest has no member receipts")
    member_sources = tuple(_member_source_from_model(item) for item in receipt_models)
    source = _source_from_model(model, member_sources)
    outcomes: list[ForecastOutcomeOwnerRecord] = []
    for receipt_model in receipt_models:
        outcome = outcome_provider.get_exact(entry_id=receipt_model.entry_id, as_of=as_of)
        if outcome is None:
            _raise_missing_outcome(receipt_model.entry_id)
        if outcome.content_hash != receipt_model.source_outcome_hash:
            raise ForecastRealizationOwnerCorruption(
                "realization receipt ForecastOutcome hash mismatch"
            )
        outcomes.append(outcome)
    try:
        manifest = ForecastRealizationManifest.from_sources(
            source=source,
            outcomes=tuple(outcomes),
            recorded_at=model.recorded_at,
        )
    except (TypeError, ValueError) as error:
        raise ForecastRealizationOwnerCorruption(
            "realization manifest cannot be replayed"
        ) from error
    if _manifest_model_values(manifest) != _manifest_model_snapshot(model):
        raise ForecastRealizationOwnerCorruption(
            "realization manifest header differs from its content seal"
        )
    for receipt, receipt_model, metadata in zip(
        manifest.members,
        receipt_models,
        member_sources,
        strict=True,
    ):
        expected = _receipt_model_values(
            receipt,
            manifest_id=model.pk,
            entry_id=receipt.entry_id,
            member_source_hash=metadata.content_hash,
        )
        if expected != _receipt_model_snapshot(receipt_model):
            raise ForecastRealizationOwnerCorruption(
                "realization receipt header differs from its content seal"
            )
    return manifest


def _raise_missing_outcome(entry_id: str) -> NoReturn:
    raise ForecastRealizationOwnerCorruption(
        f"realization receipt outcome is unavailable: {entry_id}"
    )


def _manifest_model_values(manifest: ForecastRealizationManifest) -> dict[str, object]:
    return {
        "manifest_version": manifest.manifest_version,
        "owner": manifest.owner,
        "owner_record_id": manifest.owner_record_id,
        "owner_record_version": manifest.owner_record_version,
        "result_id": manifest.result_id,
        "result_version": manifest.result_version,
        "result_hash": manifest.result_hash,
        "calendar_id": manifest.calendar_id,
        "calendar_version": manifest.calendar_version,
        "period_id": manifest.period_id,
        "period_version": manifest.period_version,
        "period_hash": manifest.period_hash,
        "period_start": manifest.period_start,
        "period_end": manifest.period_end,
        "pit_as_of": manifest.pit_as_of,
        "available_at": manifest.available_at,
        "recorded_at": manifest.recorded_at,
        "valid_until": manifest.valid_until,
        "evidence_ref": manifest.evidence_ref,
        "source_manifest_hash": manifest.source_manifest_hash,
        "payload_hash": manifest.payload_hash,
        "content_hash": manifest.content_hash,
        "research_only": manifest.research_only,
        "must_not_use_for_decision": manifest.must_not_use_for_decision,
        "must_not_execute": manifest.must_not_execute,
    }


def _manifest_model_snapshot(
    model: ForecastRealizationManifestModel,
) -> dict[str, object]:
    return {name: getattr(model, name) for name in _manifest_field_names()}


def _manifest_field_names() -> tuple[str, ...]:
    return (
        "manifest_version",
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
        "pit_as_of",
        "available_at",
        "recorded_at",
        "valid_until",
        "evidence_ref",
        "source_manifest_hash",
        "payload_hash",
        "content_hash",
        "research_only",
        "must_not_use_for_decision",
        "must_not_execute",
    )


def _receipt_model_values(
    receipt: ForecastRealizationReceipt,
    *,
    manifest_id: int,
    entry_id: str,
    member_source_hash: str,
) -> dict[str, object]:
    binding = receipt.binding
    return {
        "manifest_id": manifest_id,
        "entry_id": entry_id,
        "receipt_id": receipt.receipt_id,
        "receipt_version": receipt.receipt_version,
        "observation_id": receipt.observation_id,
        "observation_version": receipt.observation_version,
        "observation_hash": receipt.observation_hash,
        "forecast_group_id": receipt.forecast_group_id,
        "scenario_revision_id": binding.scenario_revision_id,
        "scenario_set_revision_id": binding.scenario_set_revision_id,
        "subjective_probability": binding.subjective_probability,
        "subjective_probability_source_version": (binding.subjective_probability_source_version),
        "model_probability": (
            None if binding.model_probability is None else binding.model_probability
        ),
        "model_probability_source_version": (binding.model_probability_source_version or ""),
        "model_promotion_decision_id": binding.model_promotion_decision_id or "",
        "pit_manifest_id": receipt.pit_manifest_id,
        "pit_manifest_version": receipt.pit_manifest_version,
        "pit_manifest_hash": receipt.pit_manifest_hash,
        "censoring_rule_version": receipt.censoring_rule_version,
        "published_at": receipt.published_at,
        "horizon_end": receipt.horizon_end,
        "scenario_realized": receipt.scenario_realized,
        "outcome_recorded_at": receipt.outcome_recorded_at,
        "outcome_evidence_valid_until": receipt.outcome_evidence_valid_until,
        "available_at": receipt.available_at,
        "recorded_at": receipt.recorded_at,
        "evidence_ref": receipt.evidence_ref,
        "member_source_hash": member_source_hash,
        "source_outcome_hash": receipt.source_outcome_hash,
        "content_hash": receipt.content_hash,
    }


def _receipt_model_snapshot(
    model: ForecastRealizationReceiptModel,
) -> dict[str, object]:
    return {
        name: getattr(model, name)
        for name in (
            "manifest_id",
            "entry_id",
            "receipt_id",
            "receipt_version",
            "observation_id",
            "observation_version",
            "observation_hash",
            "forecast_group_id",
            "scenario_revision_id",
            "scenario_set_revision_id",
            "subjective_probability",
            "subjective_probability_source_version",
            "model_probability",
            "model_probability_source_version",
            "model_promotion_decision_id",
            "pit_manifest_id",
            "pit_manifest_version",
            "pit_manifest_hash",
            "censoring_rule_version",
            "published_at",
            "horizon_end",
            "scenario_realized",
            "outcome_recorded_at",
            "outcome_evidence_valid_until",
            "available_at",
            "recorded_at",
            "evidence_ref",
            "member_source_hash",
            "source_outcome_hash",
            "content_hash",
        )
    }


__all__ = [
    "DjangoForecastOutcomeOwnerProvider",
    "DjangoForecastRealizationManifestRepository",
    "ForecastRealizationOwnerCorruption",
]
