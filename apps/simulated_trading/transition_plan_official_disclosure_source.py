"""Compose request-scoped official SZSE capture before a plan's final proof pin."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Protocol

from apps.audit.application.security_disclosure_audit import SecurityDisclosureAuditAppendResult
from apps.audit.security_disclosure_capture_composition import (
    SzseDistributionWindowIngestion,
    capture_and_append_szse_distribution_cohort,
)
from apps.data_center.domain.security_disclosure_event import (
    SecurityDisclosureExchange,
    SecurityDisclosureListingCoverageAppendResult,
    SecurityDisclosureSource,
)
from apps.data_center.security_disclosure_capture_composition import (
    SzseDistributionWindowRequest,
)
from apps.portfolio.domain.transition_plan_event_review import (
    TransitionPlanEventCoverageLeasePolicy,
)
from apps.risk_center.application.portfolio_risk_assets import PortfolioRiskAssetIdentity
from apps.simulated_trading.application.rebalance_journey_event_refresh import (
    RebalanceJourneyOfficialEventRefreshReceipt,
)
from apps.simulated_trading.application.rebalance_journey_event_request_scope import (
    RebalanceJourneyEventRequestScope,
)
from apps.simulated_trading.application.rebalance_journey_public import RebalanceJourneyUnavailable
from apps.simulated_trading.infrastructure.corporate_action_ownership_history_repository import (
    QualifiedExchangeTimezone,
    VerifiedSimulatedAccountOriginCalendar,
)
from apps.simulated_trading.transition_plan_disclosure_runtime_policy import (
    ConfiguredTransitionPlanDisclosureRuntimePolicyReader,
    TransitionPlanDisclosureRuntimePolicy,
)
from core.exceptions import AgomTradeProException

_SZSE_ASSET_CODE = re.compile(r"[0-9]{6}\.SZ")
_MAXIMUM_LEASE = timedelta(seconds=60)


def transition_plan_disclosure_fingerprint(
    *,
    request_scope: RebalanceJourneyEventRequestScope,
    calendar: VerifiedSimulatedAccountOriginCalendar,
    policy: TransitionPlanDisclosureRuntimePolicy,
) -> str:
    """Hash request scope, active Config Center evidence, window, and timezone policy."""

    if (
        type(request_scope) is not RebalanceJourneyEventRequestScope
        or type(calendar) is not VerifiedSimulatedAccountOriginCalendar
        or type(policy) is not TransitionPlanDisclosureRuntimePolicy
    ):
        raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_EVENT_POLICY_UNAVAILABLE")
    timezone_policy = calendar.timezone_policy
    payload: dict[str, object] = {
        "request_scope": {
            "actor_user_id": request_scope.actor_user_id,
            "account_id": request_scope.account_id,
            "owner_user_id": request_scope.owner_user_id,
        },
        "calendar": {
            "origin_on": calendar.origin_on.isoformat(),
            "decision_on": calendar.decision_on.isoformat(),
            "exchange": timezone_policy.exchange,
            "timezone_name": timezone_policy.timezone_name,
            "policy_id": timezone_policy.policy_id,
            "policy_sha256": timezone_policy.policy_sha256,
        },
        "policy": {
            "runtime_environment": policy.runtime_environment,
            "source_id": policy.source_id,
            "start_on": policy.start_on.isoformat(),
            "end_on": policy.end_on.isoformat(),
            "body_store_root": str(policy.body_store_root),
            "configured_version": policy.policy_version,
            "content_sha256": policy.policy_content_hash,
            "profile": {
                "profile_id": policy.profile_id,
                "profile_key": policy.profile_key,
                "version": policy.profile_version,
                "content_sha256": policy.profile_content_hash,
                "known_at": policy.known_at.isoformat(),
            },
            "snapshot": {
                "snapshot_id": policy.snapshot_id,
                "content_sha256": policy.snapshot_content_hash,
                "effective_at": policy.effective_at.isoformat(),
            },
            "lease": {
                "configured_version": policy.lease_policy.policy_version,
                "ttl_microseconds": _timedelta_microseconds(policy.lease_policy.ttl),
                "maximum_ttl_microseconds": _timedelta_microseconds(
                    policy.lease_policy.maximum_ttl
                ),
            },
        },
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class VerifiedOriginCalendarReader(Protocol):
    """Read the account origin and decision date under one exchange timezone policy."""

    def read_verified_zero_origin_calendar(
        self,
        *,
        account_id: int,
        owner_user_id: int,
        exchange: str,
        as_of: datetime,
    ) -> VerifiedSimulatedAccountOriginCalendar:
        """Return a sealed account origin and exchange-local decision calendar."""
        ...


class OfficialDisclosurePolicyReader(Protocol):
    """Read one active, versioned official coverage policy for a known account."""

    def read_policy(
        self,
        *,
        decision_on: date,
        earliest_required_on: date,
        as_of: datetime,
    ) -> TransitionPlanDisclosureRuntimePolicy | None:
        """Return the exact configured window or None if not decision-usable."""
        ...


class OfficialSzseWindowCapture(Protocol):
    """Persist an official window with Audit/Outbox outside the account lock."""

    def capture_cohort(
        self,
        *,
        asset_codes: tuple[str, ...],
        start_on: date,
        end_on: date,
        body_store_root: Path,
        lease_ttl: timedelta,
        using: str,
        audit_environment: str,
    ) -> datetime:
        """Capture and atomically append all listed securities with one record clock."""
        ...

    def capture_window(
        self,
        *,
        asset_code: str,
        start_on: date,
        end_on: date,
        body_store_root: Path,
        using: str,
        audit_environment: str,
    ) -> datetime:
        """Return the durable proof clock after atomic fact and Audit commit."""
        ...


class AuditBackedSzseWindowCapture:
    """Call the existing source and Audit composition and inspect its committed receipt."""

    def capture_window(
        self,
        *,
        asset_code: str,
        start_on: date,
        end_on: date,
        body_store_root: Path,
        using: str,
        audit_environment: str,
    ) -> datetime:
        """Return the exact persisted proof clock only for a matching Audit batch."""

        return self.capture_cohort(
            asset_codes=(asset_code,),
            start_on=start_on,
            end_on=end_on,
            body_store_root=body_store_root,
            lease_ttl=_MAXIMUM_LEASE,
            using=using,
            audit_environment=audit_environment,
        )

    def capture_cohort(
        self,
        *,
        asset_codes: tuple[str, ...],
        start_on: date,
        end_on: date,
        body_store_root: Path,
        lease_ttl: timedelta,
        using: str,
        audit_environment: str,
    ) -> datetime:
        """Verify the complete durable cohort and return its common persisted clock."""

        if (
            type(asset_codes) is not tuple
            or not asset_codes
            or len(set(asset_codes)) != len(asset_codes)
        ):
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_EVENT_CAPTURE_SCOPE_INVALID")
        windows = tuple(
            SzseDistributionWindowRequest(
                asset_code=asset_code,
                start_on=start_on,
                end_on=end_on,
                body_store_root=body_store_root,
            )
            for asset_code in asset_codes
        )
        results = capture_and_append_szse_distribution_cohort(
            windows,
            lease_ttl=lease_ttl,
            using=using,
            audit_environment=audit_environment,
        )
        if type(results) is not tuple or len(results) != len(asset_codes):
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_EVENT_CAPTURE_INVALID")
        verified_clocks: set[datetime] = set()
        recorded_clocks: set[datetime] = set()
        for asset_code, result in zip(asset_codes, results, strict=True):
            if (
                type(result) is not SzseDistributionWindowIngestion
                or type(result.coverage) is not SecurityDisclosureListingCoverageAppendResult
                or type(result.audit) is not SecurityDisclosureAuditAppendResult
            ):
                raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_EVENT_CAPTURE_INVALID")
            record = result.coverage.record
            proof = record.proof
            if (
                proof.source is not SecurityDisclosureSource.SZSE_OFFICIAL
                or proof.exchange is not SecurityDisclosureExchange.SZSE
                or proof.asset_code != asset_code
                or proof.start_on != start_on
                or proof.end_on != end_on
                or result.candidate.proof != proof
                or result.candidate.listing.asset_code != asset_code
                or result.audit.commit.event.event_type != "data.disclosure_fact.appended"
                or result.audit.commit.event.recorded_at != record.recorded_at
                or record.recorded_at < proof.verified_at
            ):
                raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_EVENT_CAPTURE_MISMATCH")
            verified_clocks.add(proof.verified_at)
            recorded_clocks.add(record.recorded_at)
        if len(verified_clocks) != 1 or len(recorded_clocks) != 1:
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_EVENT_CAPTURE_CLOCK_MISMATCH")
        return next(iter(recorded_clocks))


class OfficialSzseDistributionRefresher:
    """Capture every requested SZSE security under one account-bound policy window."""

    def __init__(
        self,
        *,
        origin_reader: VerifiedOriginCalendarReader,
        policy_reader: OfficialDisclosurePolicyReader,
        capture: OfficialSzseWindowCapture,
        using: str,
        audit_environment: str,
    ) -> None:
        """Bind explicit evidence providers without retaining mutable request state."""

        if (
            not callable(getattr(origin_reader, "read_verified_zero_origin_calendar", None))
            or not callable(getattr(policy_reader, "read_policy", None))
            or not callable(getattr(capture, "capture_cohort", None))
            or type(using) is not str
            or not using
            or type(audit_environment) is not str
            or not audit_environment
        ):
            raise ValueError("official disclosure refresher dependencies are invalid")
        self._origin_reader = origin_reader
        self._policy_reader = policy_reader
        self._capture = capture
        self._using = using
        self._audit_environment = audit_environment

    def refresh(
        self,
        *,
        asset_identities: tuple[PortfolioRiskAssetIdentity, ...],
        request_scope: RebalanceJourneyEventRequestScope,
        as_of: datetime,
    ) -> RebalanceJourneyOfficialEventRefreshReceipt:
        """Return a non-proof policy receipt only after all audited captures complete."""

        if (
            type(request_scope) is not RebalanceJourneyEventRequestScope
            or type(as_of) is not datetime
            or as_of.tzinfo is None
            or as_of.utcoffset() is None
            or type(asset_identities) is not tuple
            or not asset_identities
            or any(type(item) is not PortfolioRiskAssetIdentity for item in asset_identities)
        ):
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_EVENT_REFRESH_SCOPE_INVALID")
        asset_codes: set[str] = set()
        for identity in asset_identities:
            if (
                _SZSE_ASSET_CODE.fullmatch(identity.asset_code) is None
                or type(identity.security_id) is not str
                or not identity.security_id
                or identity.asset_code in asset_codes
            ):
                raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_EVENT_SOURCE_UNSUPPORTED")
            asset_codes.add(identity.asset_code)

        calendar = self._origin_reader.read_verified_zero_origin_calendar(
            account_id=request_scope.account_id,
            owner_user_id=request_scope.owner_user_id,
            exchange="SZSE",
            as_of=as_of,
        )
        if (
            type(calendar) is not VerifiedSimulatedAccountOriginCalendar
            or calendar.as_of != as_of
            or type(calendar.timezone_policy) is not QualifiedExchangeTimezone
            or calendar.timezone_policy.exchange != "SZSE"
            or calendar.origin_on > calendar.decision_on
            or type(calendar.timezone_policy.policy_id) is not str
            or not calendar.timezone_policy.policy_id
            or type(calendar.timezone_policy.policy_sha256) is not str
            or not calendar.timezone_policy.policy_sha256
        ):
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_EVENT_ORIGIN_UNAVAILABLE")
        policy = self._policy_reader.read_policy(
            decision_on=calendar.decision_on,
            earliest_required_on=calendar.origin_on,
            as_of=as_of,
        )
        if (
            type(policy) is not TransitionPlanDisclosureRuntimePolicy
            or type(policy.lease_policy) is not TransitionPlanEventCoverageLeasePolicy
            or policy.runtime_environment != self._audit_environment
            or policy.source_id != "szse_official"
            or policy.start_on > calendar.origin_on
            or policy.end_on != calendar.decision_on
            or policy.read_at != as_of
            or policy.lease_policy.policy_version != policy.policy_version
            or policy.lease_policy.ttl <= timedelta(0)
            or policy.lease_policy.ttl > _MAXIMUM_LEASE
            or policy.lease_policy.maximum_ttl > _MAXIMUM_LEASE
        ):
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_EVENT_POLICY_UNAVAILABLE")

        policy_fingerprint = transition_plan_disclosure_fingerprint(
            request_scope=request_scope,
            calendar=calendar,
            policy=policy,
        )
        effective_lease_policy = TransitionPlanEventCoverageLeasePolicy(
            policy_version=policy_fingerprint,
            ttl=policy.lease_policy.ttl,
            maximum_ttl=policy.lease_policy.maximum_ttl,
        )

        try:
            recorded_at = self._capture.capture_cohort(
                asset_codes=tuple(sorted(asset_codes)),
                start_on=policy.start_on,
                end_on=policy.end_on,
                body_store_root=policy.body_store_root,
                lease_ttl=policy.lease_policy.ttl,
                using=self._using,
                audit_environment=self._audit_environment,
            )
        except (
            AgomTradeProException,
            ArithmeticError,
            AttributeError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as error:
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_EVENT_REFRESH_FAILED") from error
        if (
            type(recorded_at) is not datetime
            or recorded_at.tzinfo is None
            or recorded_at.utcoffset() is None
            or recorded_at < as_of
        ):
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_EVENT_CAPTURE_INVALID")
        return RebalanceJourneyOfficialEventRefreshReceipt(
            request_scope=request_scope,
            asset_pairs=tuple(
                sorted(
                    (identity.asset_code, identity.security_id or "")
                    for identity in asset_identities
                )
            ),
            source_id=policy.source_id,
            start_on=policy.start_on,
            end_on=policy.end_on,
            policy_fingerprint=policy_fingerprint,
            lease_policy=effective_lease_policy,
        )


def build_official_szse_distribution_refresher(
    *, runtime_environment: str, using: str = "default"
) -> OfficialSzseDistributionRefresher:
    """Compose the real account, Config Center, and Audit source adapters lazily."""

    from apps.simulated_trading.corporate_action_ownership_history_composition import (
        build_corporate_action_ownership_history_repository,
    )

    return OfficialSzseDistributionRefresher(
        origin_reader=build_corporate_action_ownership_history_repository(
            runtime_environment=runtime_environment, using=using
        ),
        policy_reader=ConfiguredTransitionPlanDisclosureRuntimePolicyReader(
            runtime_environment=runtime_environment
        ),
        capture=AuditBackedSzseWindowCapture(),
        using=using,
        audit_environment=runtime_environment,
    )


def _timedelta_microseconds(value: timedelta) -> int:
    """Convert an exact duration without a floating-point intermediate."""

    return ((value.days * 86_400 + value.seconds) * 1_000_000) + value.microseconds


__all__ = (
    "AuditBackedSzseWindowCapture",
    "OfficialSzseDistributionRefresher",
    "build_official_szse_distribution_refresher",
    "transition_plan_disclosure_fingerprint",
)
