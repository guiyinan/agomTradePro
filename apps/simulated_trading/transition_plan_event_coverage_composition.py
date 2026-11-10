"""Compose official event scope reads from account, Config Center, and Data Center ports."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from apps.data_center.security_disclosure_capture_composition import (
    make_security_disclosure_event_reader,
    make_security_disclosure_listing_coverage_reader,
)
from apps.portfolio.application.transition_plan_event_review import (
    TransitionPlanEventSnapshotReader,
    TransitionPlanEventSnapshotReadError,
    TransitionPlanEventSnapshotReadRequest,
    TransitionPlanEventSourceRevisionChanged,
)
from apps.portfolio.domain.transition_plan_event_review import (
    TransitionPlanEventAssetSnapshot,
    TransitionPlanEventCoverageLeasePolicy,
    TransitionPlanEventCoverageStatus,
)
from apps.simulated_trading.application.rebalance_journey_event_coverage import (
    PinRebalanceJourneyEventCoverage,
    RebalanceJourneyEventCoverageScope,
    RebalanceJourneyEventCoverageScopeSelection,
)
from apps.simulated_trading.application.rebalance_journey_event_refresh import (
    RebalanceJourneyOfficialEventRefreshReceipt,
)
from apps.simulated_trading.application.rebalance_journey_event_request_scope import (
    RebalanceJourneyEventRequestScope,
)
from apps.simulated_trading.application.rebalance_journey_public import RebalanceJourneyUnavailable
from apps.simulated_trading.corporate_action_ownership_history_composition import (
    build_corporate_action_ownership_history_repository,
)
from apps.simulated_trading.infrastructure.corporate_action_ownership_history_repository import (
    QualifiedExchangeTimezone,
    VerifiedSimulatedAccountOriginCalendar,
)
from apps.simulated_trading.transition_plan_disclosure_runtime_policy import (
    ConfiguredTransitionPlanDisclosureRuntimePolicyReader,
    TransitionPlanDisclosureRuntimePolicy,
)
from apps.simulated_trading.transition_plan_event_coverage_adapter import (
    DataCenterTransitionPlanEventSnapshotReader,
)
from apps.simulated_trading.transition_plan_official_disclosure_source import (
    OfficialDisclosurePolicyReader,
    VerifiedOriginCalendarReader,
    transition_plan_disclosure_fingerprint,
)
from core.exceptions import AgomTradeProException

_SZSE_OFFICIAL_SOURCE_ID = "szse_official"
_MAXIMUM_OWNER_LEASE = timedelta(seconds=60)


class ConfiguredRebalanceJourneyEventCoverageScopeReader:
    """Select latest exact SZSE proofs under the same active policy that authorized capture."""

    def __init__(
        self,
        *,
        origin_reader: VerifiedOriginCalendarReader,
        policy_reader: OfficialDisclosurePolicyReader,
        snapshot_reader: TransitionPlanEventSnapshotReader,
        runtime_environment: str,
    ) -> None:
        """Bind read-only public ports and one explicit Config Center environment."""

        if (
            not callable(getattr(origin_reader, "read_verified_zero_origin_calendar", None))
            or not callable(getattr(policy_reader, "read_policy", None))
            or not callable(getattr(snapshot_reader, "read_latest_snapshot", None))
            or type(runtime_environment) is not str
            or not runtime_environment
            or runtime_environment.strip() != runtime_environment
        ):
            raise ValueError("event coverage scope reader dependencies are invalid")
        self._origin_reader = origin_reader
        self._policy_reader = policy_reader
        self._snapshot_reader = snapshot_reader
        self._runtime_environment = runtime_environment

    def read_scopes(
        self,
        *,
        asset_identities: tuple[tuple[str, str], ...],
        request_scope: RebalanceJourneyEventRequestScope,
        as_of: datetime,
        refresh_receipt: RebalanceJourneyOfficialEventRefreshReceipt | None = None,
    ) -> RebalanceJourneyEventCoverageScopeSelection | None:
        """Re-read active provenance, then select every fresh latest-to-exact durable proof."""

        if (
            type(request_scope) is not RebalanceJourneyEventRequestScope
            or type(as_of) is not datetime
            or as_of.tzinfo is None
            or as_of.utcoffset() is None
            or type(asset_identities) is not tuple
            or not asset_identities
            or any(
                type(pair) is not tuple
                or len(pair) != 2
                or any(type(value) is not str or not value for value in pair)
                for pair in asset_identities
            )
            or len(asset_identities) != len(set(asset_identities))
            or type(refresh_receipt) is not RebalanceJourneyOfficialEventRefreshReceipt
            or refresh_receipt.request_scope != request_scope
            or tuple(sorted(refresh_receipt.asset_pairs)) != tuple(sorted(asset_identities))
            or refresh_receipt.source_id != _SZSE_OFFICIAL_SOURCE_ID
        ):
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_EVENT_REFRESH_SCOPE_MISMATCH")

        try:
            calendar = self._origin_reader.read_verified_zero_origin_calendar(
                account_id=request_scope.account_id,
                owner_user_id=request_scope.owner_user_id,
                exchange="SZSE",
                as_of=as_of,
            )
            if not _valid_calendar(calendar, as_of=as_of):
                raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_EVENT_ORIGIN_UNAVAILABLE")
            policy = self._policy_reader.read_policy(
                decision_on=calendar.decision_on,
                earliest_required_on=calendar.origin_on,
                as_of=as_of,
            )
            if not _valid_policy(
                policy,
                calendar=calendar,
                as_of=as_of,
                runtime_environment=self._runtime_environment,
            ):
                raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_EVENT_POLICY_UNAVAILABLE")
            if policy is None:
                raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_EVENT_POLICY_UNAVAILABLE")
            fingerprint = transition_plan_disclosure_fingerprint(
                request_scope=request_scope,
                calendar=calendar,
                policy=policy,
            )
            lease_policy = TransitionPlanEventCoverageLeasePolicy(
                policy_version=fingerprint,
                ttl=policy.lease_policy.ttl,
                maximum_ttl=policy.lease_policy.maximum_ttl,
            )
            if (
                fingerprint != refresh_receipt.policy_fingerprint
                or policy.source_id != refresh_receipt.source_id
                or policy.start_on != refresh_receipt.start_on
                or policy.end_on != refresh_receipt.end_on
                or lease_policy != refresh_receipt.lease_policy
            ):
                raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_EVENT_POLICY_CHANGED")

            scopes = tuple(
                self._read_one_scope(
                    asset_identity=pair,
                    start_on=policy.start_on,
                    end_on=policy.end_on,
                    as_of=as_of,
                    lease_policy=lease_policy,
                )
                for pair in asset_identities
            )
            return RebalanceJourneyEventCoverageScopeSelection(
                scopes=scopes,
                policy_fingerprint=fingerprint,
                lease_policy=lease_policy,
            )
        except RebalanceJourneyUnavailable:
            raise
        except (
            AgomTradeProException,
            ArithmeticError,
            AttributeError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as error:
            raise RebalanceJourneyUnavailable(
                code="REBALANCE_PLAN_EVENT_SCOPE_UNAVAILABLE"
            ) from error

    def _read_one_scope(
        self,
        *,
        asset_identity: tuple[str, str],
        start_on: date,
        end_on: date,
        as_of: datetime,
        lease_policy: TransitionPlanEventCoverageLeasePolicy,
    ) -> RebalanceJourneyEventCoverageScope:
        """Use the action-cutoff latest read and pin only its exact fresh durable proof clock."""

        asset_code, security_id = asset_identity
        request = TransitionPlanEventSnapshotReadRequest(
            asset_code=asset_code,
            security_id=security_id,
            source_id=_SZSE_OFFICIAL_SOURCE_ID,
            start_on=start_on,
            end_on=end_on,
            as_of=as_of,
        )
        try:
            snapshot = self._snapshot_reader.read_latest_snapshot(request)
        except TransitionPlanEventSourceRevisionChanged as error:
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_EVENT_SOURCE_CHANGED") from error
        except TransitionPlanEventSnapshotReadError as error:
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_EVENT_PROOF_INVALID") from error
        if not _valid_latest_snapshot(
            snapshot,
            asset_code=asset_code,
            security_id=security_id,
            start_on=start_on,
            end_on=end_on,
            as_of=as_of,
            lease_policy=lease_policy,
        ):
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_EVENT_PROOF_INCOMPLETE")
        if snapshot is None:
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_EVENT_PROOF_MISSING")
        proof_at = snapshot.proof_recorded_at
        try:
            expires_at = proof_at + lease_policy.ttl
        except OverflowError as error:
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_EVENT_LEASE_INVALID") from error
        if not proof_at <= as_of < expires_at:
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_EVENT_LEASE_EXPIRED")
        return RebalanceJourneyEventCoverageScope(
            asset_code=asset_code,
            security_id=security_id,
            source_id=_SZSE_OFFICIAL_SOURCE_ID,
            start_on=start_on,
            end_on=end_on,
            first_observed_at=snapshot.first_observed_at,
            source_observed_at=snapshot.source_observed_at,
            proof_recorded_at=proof_at,
            lease_policy_version=lease_policy.policy_version,
            lease_issued_at=proof_at,
            lease_ttl_microseconds=_timedelta_microseconds(lease_policy.ttl),
            lease_expires_at=expires_at,
        )


def build_configured_rebalance_journey_event_coverage_pinner(
    *, runtime_environment: str, using: str = "default"
) -> PinRebalanceJourneyEventCoverage:
    """Compose request-scoped latest/exact proof readers without capture or implicit policy."""

    origin_reader = build_corporate_action_ownership_history_repository(
        runtime_environment=runtime_environment,
        using=using,
    )
    policy_reader = ConfiguredTransitionPlanDisclosureRuntimePolicyReader(
        runtime_environment=runtime_environment
    )
    snapshot_reader = DataCenterTransitionPlanEventSnapshotReader(
        query_use_case=make_security_disclosure_listing_coverage_reader(using=using),
        event_query_use_case=make_security_disclosure_event_reader(using=using),
    )
    scope_reader = ConfiguredRebalanceJourneyEventCoverageScopeReader(
        origin_reader=origin_reader,
        policy_reader=policy_reader,
        snapshot_reader=snapshot_reader,
        runtime_environment=runtime_environment,
    )
    return PinRebalanceJourneyEventCoverage(
        scope_reader=scope_reader,
        snapshot_reader=snapshot_reader,
        lease_policy=None,
    )


def _valid_calendar(
    value: VerifiedSimulatedAccountOriginCalendar,
    *,
    as_of: datetime,
) -> bool:
    """Require one account-local SZSE date pair under exact immutable timezone evidence."""

    return (
        type(value) is VerifiedSimulatedAccountOriginCalendar
        and value.as_of == as_of
        and type(value.origin_on) is date
        and type(value.decision_on) is date
        and value.origin_on <= value.decision_on
        and type(value.timezone_policy) is QualifiedExchangeTimezone
        and value.timezone_policy.exchange == "SZSE"
        and type(value.timezone_policy.timezone_name) is str
        and bool(value.timezone_policy.timezone_name)
        and type(value.timezone_policy.policy_id) is str
        and bool(value.timezone_policy.policy_id)
        and type(value.timezone_policy.policy_sha256) is str
        and len(value.timezone_policy.policy_sha256) == 64
    )


def _valid_policy(
    value: TransitionPlanDisclosureRuntimePolicy | None,
    *,
    calendar: VerifiedSimulatedAccountOriginCalendar,
    as_of: datetime,
    runtime_environment: str,
) -> bool:
    """Require an active exact decision-day window and the Owner-bounded lease policy."""

    if type(value) is not TransitionPlanDisclosureRuntimePolicy:
        return False
    lease = value.lease_policy
    return (
        type(lease) is TransitionPlanEventCoverageLeasePolicy
        and value.runtime_environment == runtime_environment
        and value.source_id == _SZSE_OFFICIAL_SOURCE_ID
        and value.read_at == as_of
        and value.start_on <= calendar.origin_on <= calendar.decision_on
        and value.end_on == calendar.decision_on
        and value.policy_version == lease.policy_version
        and lease.ttl > timedelta(0)
        and lease.maximum_ttl <= _MAXIMUM_OWNER_LEASE
        and lease.ttl <= lease.maximum_ttl
    )


def _valid_latest_snapshot(
    value: TransitionPlanEventAssetSnapshot | None,
    *,
    asset_code: str,
    security_id: str,
    start_on: date,
    end_on: date,
    as_of: datetime,
    lease_policy: TransitionPlanEventCoverageLeasePolicy,
) -> bool:
    """Check every latest proof identity and clock before an exact pin can be formed."""

    return (
        type(value) is TransitionPlanEventAssetSnapshot
        and value.asset_code == asset_code
        and value.security_id == security_id
        and value.source_id == _SZSE_OFFICIAL_SOURCE_ID
        and value.start_on == start_on
        and value.end_on == end_on
        and value.as_of == value.proof_recorded_at
        and value.proof_recorded_at <= as_of
        and value.source_observed_at <= value.proof_recorded_at
        and value.first_observed_at <= value.source_observed_at
        and value.coverage_status is TransitionPlanEventCoverageStatus.COMPLETE
        and value.source_scope_sha256 is not None
        and not any(event.event_type.upper() == "UNKNOWN" for event in value.events)
        and lease_policy.ttl > timedelta(0)
        and lease_policy.ttl <= lease_policy.maximum_ttl
    )


def _timedelta_microseconds(value: timedelta) -> int:
    """Convert an exact duration without a floating-point intermediate."""

    return ((value.days * 86_400 + value.seconds) * 1_000_000) + value.microseconds


__all__ = (
    "ConfiguredRebalanceJourneyEventCoverageScopeReader",
    "build_configured_rebalance_journey_event_coverage_pinner",
)
