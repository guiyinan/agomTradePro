"""Compose current simulation tax facts from exact retained sources and V4 history.

Configuration is opt-in and has no seeded legal policy or date convention.
This provider is confined to simulated accounts; it supplies no real custody
proof, taxpayer certification or financial write authority.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from django.db import DEFAULT_DB_ALIAS, connections
from django.utils import timezone

from apps.data_center.instrument_reference_snapshot_composition import (
    read_instrument_reference_snapshot,
)
from apps.data_center.statutory_source_capture_composition import (
    ConfiguredStatutorySourceCaptureService,
)
from apps.simulated_trading.application.corporate_action_tax_qualification import (
    CurrentTaxAssessmentQualification,
    CurrentTaxAssessmentQualificationPort,
)
from apps.simulated_trading.application.corporate_action_tax_settlement_history import (
    SimulatedTaxSettlementHistoryQuery,
)
from apps.simulated_trading.corporate_action_ownership_history_composition import (
    build_corporate_action_ownership_history_repository,
)
from apps.simulated_trading.corporate_action_tax_instrument_qualification import (
    qualify_simulated_dividend_tax_instrument,
)
from apps.simulated_trading.corporate_action_tax_policy_composition import (
    read_current_simulated_dividend_tax_policy,
)
from apps.simulated_trading.corporate_action_tax_settlement_history_composition import (
    build_read_simulated_tax_settlement_history_use_case,
)
from apps.simulated_trading.corporate_action_tax_statutory_qualification import (
    qualify_simulated_dividend_tax_statutory_evidence,
)
from apps.simulated_trading.domain.corporate_action_ownership_history import (
    RecordDateOwnershipProof,
)
from apps.simulated_trading.domain.corporate_action_tax_assessment import (
    CorporateActionTaxAssessment,
    QualifiedCorporateActionTaxFacts,
    _share_text,
)
from apps.simulated_trading.domain.corporate_action_tax_settlement_evidence import (
    RecordDateTaxEntitlementEvidence,
)
from apps.simulated_trading.domain.simulated_dividend_tax_policy_scope import (
    SimulatedDividendTaxExchange,
    SimulatedDividendTaxInstrumentKind,
    SimulatedDividendTaxPersona,
    SimulatedDividendTaxPolicyScope,
)
from apps.simulated_trading.execution_current_reference_composition import (
    build_current_reference_classification_reader,
)
from apps.simulated_trading.official_disclosure_action_composition import (
    VerifiedSzseActionSourceQualifier,
)
from core.exceptions import BusinessLogicError


def _blocked(message: str) -> BusinessLogicError:
    """Return an explicit unavailable-model result without Source fallback."""
    return BusinessLogicError(message, code="SIMULATED_CURRENT_TAX_QUALIFICATION_BLOCKED")


def _utc(value: datetime) -> datetime:
    """Reject invalid clocks before comparing current source windows."""
    if type(value) is not datetime or value.tzinfo is None:
        raise _blocked("current tax qualification requires an aware server clock")
    try:
        if value.utcoffset() is None:
            raise _blocked("current tax qualification requires an aware server clock")
        return value.astimezone(UTC)
    except (OverflowError, TypeError, ValueError) as error:
        raise _blocked("current tax qualification clock is not representable") from error


def _digest(payload: dict[str, object]) -> str:
    """Seal stable typed facts independently of observation timestamps."""
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _record_entitlement(
    *,
    scope: SimulatedDividendTaxPolicyScope,
    action: QualifiedCorporateActionTaxFacts,
    proof: RecordDateOwnershipProof,
) -> RecordDateTaxEntitlementEvidence:
    """Bind explicitly reviewed model coverage to independently replayed holdings.

    The candidate must explicitly declare the supported coverage rule. The
    current official announcement, instrument and statutory clauses have to be
    verified by the caller first. Observation IDs/clocks are excluded from total
    identity so a harmless re-read cannot create a different tax obligation.
    """
    scope.__post_init__()
    action.__post_init__()
    if (
        type(proof) is not RecordDateOwnershipProof
        or proof.account_id != scope.physical_account_id
        or proof.owner_user_id != scope.owner_user_id
        or proof.security_id != scope.security_id
        or proof.asset_code != scope.asset_code
        or proof.record_date != action.record_date
        or action.account_id != proof.account_id
        or action.owner_user_id != proof.owner_user_id
        or action.security_id != proof.security_id
        or action.asset_code != proof.asset_code
    ):
        raise _blocked("independent record-date proof differs from the explicit model scope")
    rule_sha = _digest(
        {
            "schema": "simulated-tax-entitlement-coverage.v1",
            "rule": scope.record_date_entitlement_rule.value,
            "review_ref": scope.applicability_ref,
            "account_id": scope.physical_account_id,
            "canonical_account_id": scope.canonical_account_id,
            "owner_user_id": scope.owner_user_id,
            "security_id": scope.security_id,
            "asset_code": scope.asset_code,
            "exchange": scope.exchange.value,
            "persona": scope.persona.value,
            "instrument_kind": scope.instrument_kind.value,
            "currency": scope.currency.value,
            "record_date_from": scope.record_date_from.isoformat(),
            "record_date_through": scope.record_date_through.isoformat(),
            "statutory_revision_set_sha256": scope.statutory_revision_set_sha256,
        }
    )
    total_sha = _digest(
        {
            "schema": "simulated-tax-entitlement-total.v1",
            "coverage_rule_sha256": rule_sha,
            "action_source_sha256": action.source_revision_sha256,
            "account_id": proof.account_id,
            "owner_user_id": proof.owner_user_id,
            "security_id": proof.security_id,
            "asset_code": proof.asset_code,
            "record_date": proof.record_date.isoformat(),
            "quantity": _share_text(proof.eligible_quantity),
        }
    )
    return RecordDateTaxEntitlementEvidence(
        kind=scope.record_date_entitlement_rule,
        rule_source_id=scope.applicability_ref,
        rule_source_sha256=rule_sha,
        qualified_total_quantity=proof.eligible_quantity,
        total_evidence_id=f"sim-tax-entitlement:{total_sha}",
        total_evidence_sha256=total_sha,
    )


@dataclass(frozen=True, slots=True)
class _CurrentBuild:
    """Actual reconstructed assessment and stable finite current qualification."""

    assessment: CorporateActionTaxAssessment
    qualification: CurrentTaxAssessmentQualification
    finished_at: datetime


class DjangoCurrentSimulatedTaxQualificationProvider(CurrentTaxAssessmentQualificationPort):
    """Reconstruct assessments through concrete public current-read adapters."""

    def __init__(
        self,
        *,
        runtime_environment: str,
        calendar_dataset_key: str,
        statutory_provider_id: int,
        statutory_body_store_root: Path,
        action_body_store_root: Path,
        deployment_region: str,
        using: str = DEFAULT_DB_ALIAS,
    ) -> None:
        """Bind explicit server-selected stores, provider, calendar and environment."""
        if (
            using != DEFAULT_DB_ALIAS
            or type(statutory_provider_id) is not int
            or statutory_provider_id <= 0
            or not isinstance(statutory_body_store_root, Path)
            or not isinstance(action_body_store_root, Path)
            or any(
                type(value) is not str or not value or value.strip() != value
                for value in (runtime_environment, calendar_dataset_key, deployment_region)
            )
        ):
            raise _blocked("an explicit same-alias simulated tax composition is required")
        self._environment = runtime_environment
        self._calendar_dataset_key = calendar_dataset_key
        self._using = using
        self._sources = ConfiguredStatutorySourceCaptureService(
            provider_id=statutory_provider_id,
            body_store_root=statutory_body_store_root,
            deployment_region=deployment_region,
            using=using,
        )
        self._action_source = VerifiedSzseActionSourceQualifier(
            body_store_root=action_body_store_root,
            using=using,
        )

    def prepare_current(
        self,
        *,
        action: QualifiedCorporateActionTaxFacts,
        canonical_account_id: str,
        target_settlement_date: date,
        assessment_revision_id: str,
        supersedes_assessment_revision_id: str | None,
    ) -> CorporateActionTaxAssessment:
        """Read a simulated assessment preview without granting write authority."""
        return self._build_current(
            action=action,
            canonical_account_id=canonical_account_id,
            target_settlement_date=target_settlement_date,
            assessment_revision_id=assessment_revision_id,
            supersedes_assessment_revision_id=supersedes_assessment_revision_id,
            as_of=_utc(timezone.now()),
        ).assessment

    def read_current(
        self,
        assessment: CorporateActionTaxAssessment,
        *,
        canonical_account_id: str,
        environment: str,
        using: str,
        as_of: datetime,
    ) -> CurrentTaxAssessmentQualification:
        """Re-read actual sources in the caller's same-alias PostgreSQL transaction."""
        current = _utc(as_of)
        if (
            using != self._using
            or environment != self._environment
            or connections[using].vendor != "postgresql"
            or not connections[using].in_atomic_block
            or type(assessment) is not CorporateActionTaxAssessment
        ):
            raise _blocked("current assessment write facts require the exact PostgreSQL UOW")
        assessment.verify_integrity()
        built = self._build_current(
            action=assessment.action,
            canonical_account_id=canonical_account_id,
            target_settlement_date=assessment.target_settlement_date,
            assessment_revision_id=assessment.assessment_revision_id,
            supersedes_assessment_revision_id=assessment.supersedes_assessment_revision_id,
            as_of=current,
        )
        if built.assessment.semantic_sha256 != assessment.semantic_sha256:
            raise _blocked("submitted assessment differs from current independently rebuilt facts")
        built.qualification.verify_for(
            assessment,
            canonical_account_id=canonical_account_id,
            environment=environment,
            as_of=_utc(timezone.now()),
        )
        final_clock = _utc(timezone.now())
        if final_clock < built.finished_at or final_clock >= built.qualification.valid_until:
            raise _blocked(
                "qualification expired or server clock moved backwards on final verification"
            )
        return built.qualification

    def _build_current(
        self,
        *,
        action: QualifiedCorporateActionTaxFacts,
        canonical_account_id: str,
        target_settlement_date: date,
        assessment_revision_id: str,
        supersedes_assessment_revision_id: str | None,
        as_of: datetime,
    ) -> _CurrentBuild:
        """Join exact current model, source bodies, listing facts and complete history."""
        if type(action) is not QualifiedCorporateActionTaxFacts:
            raise _blocked("exact corporate-action tax facts are required")
        action.__post_init__()
        classification = build_current_reference_classification_reader(
            runtime_environment=self._environment,
        ).resolve_simulated_instrument_classification(
            security_id=action.security_id,
            asset_code=action.asset_code,
            as_of=as_of,
        )
        if classification is None:
            raise _blocked("current explicit simulated instrument classification is unavailable")
        source = classification.identity_evidence.source_evidence
        snapshot = read_instrument_reference_snapshot(snapshot_id=source.snapshot_id)
        if snapshot is None:
            raise _blocked("the exact retained instrument snapshot is unavailable")
        try:
            exchange = SimulatedDividendTaxExchange(source.rule_market)
        except ValueError as error:
            raise _blocked(
                "the instrument market has no supported explicit simulation tax scope"
            ) from error
        configured = read_current_simulated_dividend_tax_policy(
            environment=self._environment,
            as_of=as_of,
            account_kind="simulated",
            physical_account_id=action.account_id,
            canonical_account_id=canonical_account_id,
            owner_user_id=action.owner_user_id,
            security_id=action.security_id,
            asset_code=action.asset_code,
            exchange=exchange,
            persona=SimulatedDividendTaxPersona.DOMESTIC_PUBLIC_MARKET_A_SHARE,
            instrument_kind=SimulatedDividendTaxInstrumentKind.LISTED_EQUITY,
            record_date=action.record_date,
        )
        instrument = qualify_simulated_dividend_tax_instrument(
            scope=configured.candidate,
            classification=classification,
            snapshot=snapshot,
            record_date=action.record_date,
            as_of=as_of,
        )
        retained = self._sources.read_retained_bundle(
            bundle_id=configured.candidate.statutory_bundle_id,
            version=configured.candidate.statutory_bundle_version,
        )
        source_cutoff = _utc(timezone.now())
        if source_cutoff < as_of:
            raise _blocked("server clock moved backwards during current tax qualification")
        statutory = qualify_simulated_dividend_tax_statutory_evidence(
            configured=configured,
            retained=retained,
            as_of=source_cutoff,
        )
        if not self._action_source.verify_tax_action(action, as_of=source_cutoff):
            raise _blocked(
                "the actual current disclosure body and complete correction lineage differ"
            )
        proof = build_corporate_action_ownership_history_repository(
            runtime_environment=self._environment,
            using=self._using,
        ).read_record_date_ownership_proof(
            account_id=action.account_id,
            owner_user_id=action.owner_user_id,
            security_id=action.security_id,
            asset_code=action.asset_code,
            record_date=action.record_date,
            evidence_cutoff_at=source_cutoff,
        )
        entitlement = _record_entitlement(scope=configured.candidate, action=action, proof=proof)
        history = build_read_simulated_tax_settlement_history_use_case(
            runtime_environment=self._environment,
            calendar_dataset_key=self._calendar_dataset_key,
            using=self._using,
        ).execute(
            SimulatedTaxSettlementHistoryQuery(
                environment=self._environment,
                account_kind="simulated",
                physical_account_id=action.account_id,
                canonical_account_id=canonical_account_id,
                owner_user_id=action.owner_user_id,
                security_id=action.security_id,
                asset_code=action.asset_code,
                record_date=action.record_date,
                complete_through=target_settlement_date,
                record_date_entitlement=entitlement,
            )
        )
        assessment = CorporateActionTaxAssessment(
            assessment_revision_id=assessment_revision_id,
            supersedes_assessment_revision_id=supersedes_assessment_revision_id,
            action=action,
            history=history.history,
            target_settlement_date=target_settlement_date,
            policy=configured.candidate.tax_policy,
            statutory_source_bundle=statutory.source_bundle,
            simulated_tax_date_observation=history.observation,
        )
        observation = history.observation
        deadline = min(
            instrument.valid_until,
            statutory.valid_until,
            observation.convention_valid_until,
            observation.calendar_reference_valid_until,
        )
        qualification_sha = _digest(
            {
                "schema": "current-simulated-tax-qualification.v1",
                "assessment_semantic_sha256": assessment.semantic_sha256,
                "candidate_sha256": configured.candidate.semantic_sha256,
                "instrument_sha256": instrument.semantic_sha256,
                "terms_sha256": statutory.terms.terms_sha256,
                "source_configuration_sha256": retained.configuration_sha256,
                "tax_profile_id": configured.profile_id,
                "tax_profile_sha256": configured.profile_content_hash,
                "tax_snapshot_id": configured.snapshot_id,
                "tax_snapshot_sha256": configured.snapshot_hash,
                "date_profile_id": observation.date_rule.profile_id,
                "date_profile_sha256": observation.date_rule.profile_content_hash,
                "date_snapshot_id": observation.date_rule.snapshot_id,
                "date_snapshot_sha256": observation.date_rule.snapshot_hash,
                "calendar_publication_hash": observation.calendar_publication_hash,
                "valid_until": deadline.isoformat(),
            }
        )
        result = CurrentTaxAssessmentQualification(
            assessment_semantic_sha256=assessment.semantic_sha256,
            account_id=assessment.account_id,
            owner_user_id=assessment.owner_user_id,
            canonical_account_id=canonical_account_id,
            environment=self._environment,
            qualification_id=f"sim-tax-q:{qualification_sha}",
            qualification_sha256=qualification_sha,
            runtime_profile_id=configured.profile_id,
            runtime_profile_content_sha256=configured.profile_content_hash,
            runtime_snapshot_id=configured.snapshot_id,
            runtime_snapshot_sha256=configured.snapshot_hash,
            valid_until=deadline,
        )
        finished = _utc(timezone.now())
        if finished < source_cutoff or finished < observation.read_at:
            raise _blocked("server clock moved backwards during history qualification")
        result.verify_for(
            assessment,
            canonical_account_id=canonical_account_id,
            environment=self._environment,
            as_of=finished,
        )
        final_clock = _utc(timezone.now())
        if final_clock < finished or final_clock >= deadline:
            raise _blocked(
                "qualification expired or server clock moved backwards on final reconstruction"
            )
        return _CurrentBuild(assessment, result, final_clock)


__all__ = ["DjangoCurrentSimulatedTaxQualificationProvider"]
