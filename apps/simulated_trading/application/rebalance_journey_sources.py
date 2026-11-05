"""Map already qualified owner risk sources into immutable plan references."""

from __future__ import annotations

from datetime import tzinfo

from apps.portfolio.domain.transition_plan_revision_basis import TransitionPlanSourceBinding
from apps.risk_center.application.portfolio_risk_deadlines import (
    portfolio_risk_execution_deadline_for_evidence,
)
from apps.risk_center.application.portfolio_risk_report_clock_payload import (
    clock_evidence_proof_payload,
)
from apps.risk_center.application.portfolio_risk_serialization import portfolio_risk_content_hash
from apps.risk_center.domain.portfolio_risk_sources import (
    PortfolioRiskSourceEvidence,
    qualify_portfolio_risk_source,
)
from apps.simulated_trading.application.portfolio_risk_context import PreparedPortfolioRisk
from apps.simulated_trading.application.rebalance_journey_public import RebalanceJourneyUnavailable


def bind_prepared_plan_sources(
    prepared: PreparedPortfolioRisk, *, business_timezone: tzinfo
) -> tuple[TransitionPlanSourceBinding, ...]:
    """Preserve body/manifest identity and separate vendor clocks from admission.

    The policy carries manifest pins; report ``raw_payload_sha256`` contains the
    original body digest and must never be substituted for a manifest pin.
    Qualification and its deadline remain owned by the existing risk contract.
    """

    policy = prepared.policy
    if policy is None:
        raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_RISK_POLICY_MISSING")
    output: list[TransitionPlanSourceBinding] = []
    asset_identities = {(asset.asset_code, asset.security_id) for asset in prepared.assets.assets}
    references = tuple(
        reference
        for reference in policy.source_references
        if (reference.asset_code, reference.security_id) in asset_identities
    )
    for reference in references:
        matches = [
            evidence
            for evidence in prepared.assessment.all_source_evidence
            if evidence.source_record_id == reference.source_record_id
            and (
                evidence.policy_clock_proof is None
                or (
                    evidence.policy_clock_proof.asset_code == reference.asset_code
                    and evidence.policy_clock_proof.security_id == reference.security_id
                    and evidence.policy_clock_proof.source_kind == reference.kind
                )
            )
        ]
        unique_matches: list[PortfolioRiskSourceEvidence] = []
        for candidate in matches:
            if candidate not in unique_matches:
                unique_matches.append(candidate)
        if len(unique_matches) != 1:
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_SOURCE_BINDING_AMBIGUOUS")
        evidence = unique_matches[0]
        if evidence.original_payload_sha256 is None:
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_SOURCE_BODY_MISSING")
        requested_purpose = (
            prepared.capacity_requested_purpose
            if reference.kind in {"capacity_window", "execution_session_state"}
            else policy.industry_policy.requested_purpose
        )
        source_policy = (
            policy.capacity_policy
            if reference.kind in {"capacity_window", "execution_session_state"}
            else policy.industry_policy
        )
        qualification = qualify_portfolio_risk_source(
            evidence=evidence,
            requested_purpose=requested_purpose,
            allowed_observation_precisions=source_policy.allowed_observation_precisions,
            allowed_restrictions=source_policy.allowed_source_restrictions,
            as_of=prepared.as_of,
            expected_source_kind=reference.kind,
        )
        if not qualification.eligible:
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_SOURCE_NOT_QUALIFIED")
        baseline = prepared.baseline_source.policy
        policy_deadlines = tuple(
            value
            for value in (
                baseline.effective_until if baseline is not None else None,
                prepared.calendar.valid_until,
            )
            if value is not None
        )
        deadline = portfolio_risk_execution_deadline_for_evidence(
            evidence,
            policy,
            account_id=prepared.snapshot.account_id,
            business_timezone=business_timezone,
            additional_policy_deadlines=policy_deadlines,
            requested_purpose=requested_purpose,
        )
        if deadline is None:
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_SOURCE_NOT_QUALIFIED")
        proof = evidence.policy_clock_proof
        proof_hash = (
            portfolio_risk_content_hash(clock_evidence_proof_payload(proof))
            if proof is not None
            else None
        )
        precision = evidence.observation_precision.value
        if precision not in {"timestamp", "date"}:
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_SOURCE_PRECISION_UNKNOWN")
        output.append(
            TransitionPlanSourceBinding(
                kind=reference.kind,
                asset_code=reference.asset_code,
                security_id=reference.security_id,
                source_id=evidence.source_id,
                source_record_id=evidence.source_record_id,
                manifest_sha256=_digest(reference.raw_payload_hash),
                body_sha256=_digest(evidence.original_payload_sha256),
                observation_precision="timestamp" if precision == "timestamp" else "date",
                observed_at=evidence.observed_at,
                observed_on=evidence.observed_on,
                available_at=evidence.available_at,
                known_at=evidence.known_at,
                decision_cutoff=evidence.decision_cutoff,
                decision_date_cutoff=evidence.decision_date_cutoff,
                source_valid_until=evidence.valid_until,
                admission_until=deadline,
                qualification_proof_hash=proof_hash,
                source_purpose=evidence.source_purpose,
                requested_purpose=requested_purpose,
                allowed_purposes=evidence.allowed_purposes,
                restrictions=evidence.restrictions,
                coverage_status=evidence.coverage.status.value,
                qualified=True,
            )
        )
    if not output:
        raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_SOURCE_REFERENCES_MISSING")
    return tuple(output)


def _digest(value: str) -> str:
    result = value.removeprefix("sha256:")
    if len(result) != 64 or any(c not in "0123456789abcdef" for c in result):
        raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_SOURCE_DIGEST_INVALID")
    return result
