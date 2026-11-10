"""Identity and lease guards for official event refresh during plan preparation."""

from __future__ import annotations

from datetime import datetime

from apps.portfolio.domain.transition_plan_event_review import (
    SECURITY_DISCLOSURE_EVENT_COVERAGE_RECORD_ID,
    SECURITY_DISCLOSURE_EVENT_SOURCE_KIND,
)
from apps.portfolio.domain.transition_plan_revision_basis import TransitionPlanSourceBinding
from apps.risk_center.application.portfolio_risk_assets import (
    PortfolioRiskAssetIdentity,
    PortfolioRiskAssetInputs,
)
from apps.simulated_trading.application.portfolio_risk_context import PreparedPortfolioRisk
from apps.simulated_trading.application.rebalance_journey_public import RebalanceJourneyUnavailable


def _event_asset_identities(
    prepared: PreparedPortfolioRisk,
) -> tuple[PortfolioRiskAssetIdentity, ...]:
    """Return every unique exact risk asset/security pair in canonical order."""

    identities: list[PortfolioRiskAssetIdentity] = []
    for asset in prepared.assets.assets:
        if type(asset) is not PortfolioRiskAssetInputs or type(asset.security_id) is not str:
            raise RebalanceJourneyUnavailable(
                code="REBALANCE_PLAN_EVENT_ASSET_IDENTITY_UNAVAILABLE"
            )
        try:
            identities.append(
                PortfolioRiskAssetIdentity(
                    asset_code=asset.asset_code,
                    security_id=asset.security_id,
                )
            )
        except (TypeError, ValueError) as error:
            raise RebalanceJourneyUnavailable(
                code="REBALANCE_PLAN_EVENT_ASSET_IDENTITY_UNAVAILABLE"
            ) from error
    if not identities or len(identities) != len(
        {(identity.asset_code, identity.security_id) for identity in identities}
    ):
        raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_EVENT_ASSET_IDENTITY_AMBIGUOUS")
    return tuple(
        sorted(identities, key=lambda identity: (identity.asset_code, identity.security_id or ""))
    )


def _require_refresh_context_stable(
    *,
    initial: PreparedPortfolioRisk,
    refreshed: PreparedPortfolioRisk,
    expected_identities: tuple[PortfolioRiskAssetIdentity, ...],
    refreshed_identities: tuple[PortfolioRiskAssetIdentity, ...],
) -> None:
    """Reject a changed owner, account or event identity across official capture."""

    initial_account_identity = (
        initial.actor_user_id,
        initial.snapshot.account_id,
        initial.snapshot.owner_user_id,
    )
    refreshed_account_identity = (
        refreshed.actor_user_id,
        refreshed.snapshot.account_id,
        refreshed.snapshot.owner_user_id,
    )
    initial_holding_identities = _holding_identities(initial)
    refreshed_holding_identities = _holding_identities(refreshed)
    if (
        initial_account_identity != refreshed_account_identity
        or initial_holding_identities != refreshed_holding_identities
        or expected_identities != refreshed_identities
    ):
        raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_EVENT_REFRESH_CONTEXT_CHANGED")


def _holding_identities(
    prepared: PreparedPortfolioRisk,
) -> tuple[tuple[str, str | None], ...]:
    """Retain account-held identity pairs, including unresolved security IDs."""

    identities = tuple(
        (holding.asset_code, holding.security_id) for holding in prepared.snapshot.holdings
    )
    return tuple(
        sorted(
            identities,
            key=lambda identity: (
                identity[0],
                identity[1] or "",
                identity[1] is None,
            ),
        )
    )


def _validate_event_sources(
    event_sources: tuple[TransitionPlanSourceBinding, ...],
    *,
    expected_identities: tuple[tuple[str, str], ...],
    plan_clock: datetime,
) -> None:
    """Require complete exact proof pins and leases valid at the final plan clock."""

    if (
        type(event_sources) is not tuple
        or not event_sources
        or any(type(source) is not TransitionPlanSourceBinding for source in event_sources)
        or any(source.kind != SECURITY_DISCLOSURE_EVENT_SOURCE_KIND for source in event_sources)
    ):
        raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_EVENT_PROVIDER_CONTRACT_INVALID")
    expected = set(expected_identities)
    coverage_sources = tuple(
        source
        for source in event_sources
        if source.source_record_id == SECURITY_DISCLOSURE_EVENT_COVERAGE_RECORD_ID
    )
    coverage_identities = tuple(
        (source.asset_code, source.security_id) for source in coverage_sources
    )
    if (
        len(coverage_identities) != len(expected)
        or len(set(coverage_identities)) != len(coverage_identities)
        or set(coverage_identities) != expected
    ):
        raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_EVENT_SCOPE_INCOMPLETE")
    for source in event_sources:
        if (
            (source.asset_code, source.security_id) not in expected
            or source.decision_cutoff != plan_clock
            or source.known_at is not None
            and source.known_at > plan_clock
            or source.admission_until <= plan_clock
        ):
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_EVENT_SCOPE_MISMATCH")
    for source in coverage_sources:
        if (
            source.known_at is None
            or source.available_at != source.known_at
            or source.coverage_lease_issued_at is None
            or source.coverage_lease_issued_at > plan_clock
            or source.coverage_lease_ttl_microseconds is None
            or source.coverage_lease_ttl_microseconds <= 0
        ):
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_EVENT_PROOF_INCOMPLETE")
