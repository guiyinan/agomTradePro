"""Read exact complete modeled tax history without creating an assessment or financial operation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path
from typing import Literal

from django.db import DEFAULT_DB_ALIAS
from django.utils import timezone

from apps.data_center.application.statutory_source_bundle import ConfiguredStatutorySourceBundleRead
from apps.data_center.instrument_reference_snapshot_composition import (
    read_instrument_reference_snapshot,
)
from apps.data_center.statutory_source_capture_composition import (
    ConfiguredStatutorySourceCaptureService,
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
    ConfiguredSimulatedDividendTaxPolicy,
    read_current_simulated_dividend_tax_policy,
)
from apps.simulated_trading.corporate_action_tax_qualification_composition import (
    _record_entitlement,
)
from apps.simulated_trading.corporate_action_tax_settlement_history_composition import (
    build_read_simulated_tax_settlement_history_use_case,
)
from apps.simulated_trading.corporate_action_tax_statutory_qualification import (
    SimulatedDividendTaxStatutoryEvidence,
    qualify_simulated_dividend_tax_statutory_evidence,
)
from apps.simulated_trading.domain.corporate_action_tax_assessment import (
    QualifiedCorporateActionTaxFacts,
)
from apps.simulated_trading.domain.simulated_dividend_tax_policy_scope import (
    SimulatedDividendTaxExchange,
    SimulatedDividendTaxInstrumentKind,
    SimulatedDividendTaxPersona,
)
from apps.simulated_trading.domain.simulated_tax_settlement_history import (
    SimulatedTaxSettlementHistoryBuild,
)
from apps.simulated_trading.execution_current_reference_composition import (
    build_current_reference_classification_reader,
)
from apps.simulated_trading.official_disclosure_action_composition import (
    VerifiedSzseActionSourceQualifier,
)
from core.exceptions import BusinessLogicError


def _blocked() -> BusinessLogicError:
    return BusinessLogicError(
        "不能完整核对本账户这一分红事件的模拟税务历史。",
        code="SIMULATED_TAX_EXPOSURE_HISTORY_UNVERIFIED",
    )


@dataclass(frozen=True, slots=True)
class CurrentSimulatedTaxExposureHistory:
    """Complete explicit-date history plus original current-model/source witnesses.

    Zero-net rows remain genuine history rows. This value is not an assessment,
    accepted liability, real-holder qualification or financial permission.
    """

    configured: ConfiguredSimulatedDividendTaxPolicy
    retained: ConfiguredStatutorySourceBundleRead
    statutory: SimulatedDividendTaxStatutoryEvidence
    history: SimulatedTaxSettlementHistoryBuild
    instrument_sha256: str
    source_epoch_sha256: str
    known_at: datetime
    checked_at: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        """Reject malformed source clocks and preserve the original finite lease."""
        self.configured.__post_init__()
        self.retained.__post_init__()
        self.history.__post_init__()
        clocks = (self.known_at, self.checked_at, self.valid_until)
        if (
            any(
                type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None
                for value in clocks
            )
            or not self.known_at <= self.checked_at < self.valid_until
            or any(
                len(value) != 64 or any(character not in "0123456789abcdef" for character in value)
                for value in (self.instrument_sha256, self.source_epoch_sha256)
            )
        ):
            raise _blocked()

    @property
    def simulation_only(self) -> Literal[True]:
        """Retain the explicit local simulation scope."""
        return True

    @property
    def must_not_use_for_real_tax_decision(self) -> Literal[True]:
        """Keep actual taxpayer and real-tax decisions outside this model."""
        return True


def _same_policy(
    first: ConfiguredSimulatedDividendTaxPolicy, second: ConfiguredSimulatedDividendTaxPolicy
) -> bool:
    return replace(first, as_of=second.as_of) == second


def _policy_epoch(configured: ConfiguredSimulatedDividendTaxPolicy) -> dict[str, object]:
    configured.__post_init__()
    return {
        "definition_key": configured.definition_key,
        "environment": configured.environment,
        "profile_id": configured.profile_id,
        "profile_key": configured.profile_key,
        "profile_version": configured.profile_version,
        "profile_sha256": configured.profile_content_hash,
        "snapshot_id": configured.snapshot_id,
        "snapshot_sha256": configured.snapshot_hash,
        "created_at": configured.created_at.isoformat(),
        "known_at": configured.known_at.isoformat(),
        "activated_at": configured.activated_at.isoformat(),
        "snapshot_generated_at": configured.snapshot_generated_at.isoformat(),
        "effective_at": configured.effective_at.isoformat(),
        "candidate_sha256": configured.candidate.semantic_sha256,
        "valid_from": configured.candidate.valid_from.isoformat(),
        "valid_until": configured.candidate.valid_until.isoformat(),
    }


def read_current_simulated_tax_exposure_history(
    *,
    action: QualifiedCorporateActionTaxFacts,
    canonical_account_id: str,
    complete_through: date,
    environment: str,
    calendar_dataset_key: str,
    statutory_provider_id: int,
    statutory_body_store_root: Path,
    action_body_store_root: Path,
    deployment_region: str,
    using: str = DEFAULT_DB_ALIAS,
) -> CurrentSimulatedTaxExposureHistory:
    """Join actual retained inputs for a closed prefix, including exact net-zero dates.

    No HTTP refresh, assessment bridge, ledger append or implicit settlement-date
    selection occurs. The caller supplies a date from the actual formal calendar.
    """
    if (
        using != DEFAULT_DB_ALIAS
        or type(action) is not QualifiedCorporateActionTaxFacts
        or type(complete_through) is not date
    ):
        raise _blocked()
    action.__post_init__()
    started = timezone.now()
    classification = build_current_reference_classification_reader(
        runtime_environment=environment
    ).resolve_simulated_instrument_classification(
        security_id=action.security_id, asset_code=action.asset_code, as_of=started
    )
    if classification is None:
        raise _blocked()
    native = classification.identity_evidence.source_evidence
    snapshot = read_instrument_reference_snapshot(snapshot_id=native.snapshot_id)
    if snapshot is None:
        raise _blocked()
    exchange = SimulatedDividendTaxExchange(native.rule_market)
    # Keep typed keyword calls: policy declarations are explicit scenario labels,
    # never inferred evidence of an actual person's tax status.
    configured = read_current_simulated_dividend_tax_policy(
        environment=environment,
        as_of=started,
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
        as_of=started,
    )
    sources = ConfiguredStatutorySourceCaptureService(
        provider_id=statutory_provider_id,
        body_store_root=statutory_body_store_root,
        deployment_region=deployment_region,
        using=using,
    )
    retained = sources.read_retained_bundle(
        bundle_id=configured.candidate.statutory_bundle_id,
        version=configured.candidate.statutory_bundle_version,
    )
    source_cutoff = timezone.now()
    if source_cutoff < started:
        raise _blocked()
    statutory = qualify_simulated_dividend_tax_statutory_evidence(
        configured=configured, retained=retained, as_of=source_cutoff
    )
    action_source = VerifiedSzseActionSourceQualifier(
        body_store_root=action_body_store_root, using=using
    )
    if not action_source.verify_tax_action(action, as_of=source_cutoff):
        raise _blocked()
    proof = build_corporate_action_ownership_history_repository(
        runtime_environment=environment, using=using
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
        runtime_environment=environment, calendar_dataset_key=calendar_dataset_key, using=using
    ).execute(
        SimulatedTaxSettlementHistoryQuery(
            environment=environment,
            account_kind="simulated",
            physical_account_id=action.account_id,
            canonical_account_id=canonical_account_id,
            owner_user_id=action.owner_user_id,
            security_id=action.security_id,
            asset_code=action.asset_code,
            record_date=action.record_date,
            complete_through=complete_through,
            record_date_entitlement=entitlement,
        )
    )
    history.__post_init__()
    observed = history.observation
    if (
        observed.date_rule.profile_id != configured.profile_id
        or observed.date_rule.profile_content_hash != configured.profile_content_hash
        or observed.date_rule.snapshot_id != configured.snapshot_id
        or observed.date_rule.snapshot_hash != configured.snapshot_hash
    ):
        raise _blocked()
    before_final = timezone.now()
    current = read_current_simulated_dividend_tax_policy(
        environment=environment,
        as_of=before_final,
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
    final_retained = sources.read_retained_bundle(
        bundle_id=configured.candidate.statutory_bundle_id,
        version=configured.candidate.statutory_bundle_version,
    )
    final_classification = build_current_reference_classification_reader(
        runtime_environment=environment
    ).resolve_simulated_instrument_classification(
        security_id=action.security_id, asset_code=action.asset_code, as_of=timezone.now()
    )
    if final_classification is None:
        raise _blocked()
    final_instrument = qualify_simulated_dividend_tax_instrument(
        scope=current.candidate,
        classification=final_classification,
        snapshot=snapshot,
        record_date=action.record_date,
        as_of=timezone.now(),
    )
    if (
        not _same_policy(configured, current)
        or final_retained.configuration_sha256 != retained.configuration_sha256
        or final_retained.bundle != retained.bundle
        or final_retained.catalog != retained.catalog
        or final_retained.bodies != retained.bodies
        or final_instrument.semantic_sha256 != instrument.semantic_sha256
        or not action_source.verify_tax_action(action, as_of=timezone.now())
    ):
        raise _blocked()
    checked = timezone.now()
    deadline = min(
        instrument.valid_until,
        statutory.valid_until,
        observed.convention_valid_until,
        observed.calendar_reference_valid_until,
    )
    if (
        checked < before_final
        or before_final < source_cutoff
        or not observed.read_at <= checked < deadline
    ):
        raise _blocked()
    classification.validate_at(as_of=checked)
    epoch = {
        "schema": "simulated-tax-exposure-source-epoch.v1",
        "full_policy": _policy_epoch(configured),
        "action_source_sha256": action.source_revision_sha256,
        "body_sha256": action.source_payload_sha256,
        "candidate_sha256": configured.candidate.semantic_sha256,
        "profile_id": configured.profile_id,
        "profile_sha256": configured.profile_content_hash,
        "snapshot_id": configured.snapshot_id,
        "snapshot_sha256": configured.snapshot_hash,
        "instrument_sha256": instrument.semantic_sha256,
        "source_configuration_sha256": retained.configuration_sha256,
        "capture_manifest_sha256": retained.bundle.capture_manifest_sha256,
        "date_rule_sha256": observed.date_rule.convention_sha256,
        "calendar_snapshot_id": observed.calendar_snapshot_id,
        "calendar_digest": observed.calendar_record_digest,
        "calendar_publication_id": observed.calendar_publication_id,
        "calendar_publication_hash": observed.calendar_publication_hash,
        "calendar_publication_recorded_at": observed.calendar_publication_recorded_at.isoformat(),
    }
    epoch_sha = hashlib.sha256(
        json.dumps(epoch, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    known = max(
        configured.snapshot_generated_at,
        observed.date_rule.snapshot_generated_at,
        observed.calendar_publication_recorded_at,
        native.snapshot_recorded_at,
        native.mapping_recorded_at,
        classification.identity_evidence.reference_response_completed_at,
        *(capture.captured_at for capture in retained.bundle.captures),
    )
    return CurrentSimulatedTaxExposureHistory(
        configured,
        retained,
        statutory,
        history,
        instrument.semantic_sha256,
        epoch_sha,
        known,
        checked,
        deadline,
    )
