"""Request-scoped official SZSE capture before transition-plan proof pinning."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from apps.portfolio.domain.transition_plan_event_review import (
    TransitionPlanEventCoverageLeasePolicy,
)
from apps.risk_center.application.portfolio_risk_assets import PortfolioRiskAssetIdentity
from apps.simulated_trading.application.rebalance_journey_event_request_scope import (
    RebalanceJourneyEventRequestScope,
)
from apps.simulated_trading.application.rebalance_journey_public import RebalanceJourneyUnavailable
from apps.simulated_trading.infrastructure.corporate_action_ownership_history_repository import (
    QualifiedExchangeTimezone,
    VerifiedSimulatedAccountOriginCalendar,
)
from apps.simulated_trading.transition_plan_disclosure_runtime_policy import (
    TransitionPlanDisclosureRuntimePolicy,
)
from apps.simulated_trading.transition_plan_official_disclosure_source import (
    OfficialSzseDistributionRefresher,
)

AS_OF = datetime(2026, 11, 11, 10, 0, tzinfo=UTC)
SCOPE = RebalanceJourneyEventRequestScope(actor_user_id=9, account_id=12, owner_user_id=9)
IDENTITIES = (
    PortfolioRiskAssetIdentity(asset_code="002727.SZ", security_id="SZSE:002727"),
    PortfolioRiskAssetIdentity(asset_code="301237.SZ", security_id="SZSE:301237"),
)


@dataclass(slots=True)
class _OriginReader:
    calls: list[tuple[int, int, str, datetime]] = field(default_factory=list)

    def read_verified_zero_origin_calendar(
        self, *, account_id: int, owner_user_id: int, exchange: str, as_of: datetime
    ) -> VerifiedSimulatedAccountOriginCalendar:
        self.calls.append((account_id, owner_user_id, exchange, as_of))
        return VerifiedSimulatedAccountOriginCalendar(
            origin_on=date(2026, 10, 1),
            decision_on=date(2026, 11, 11),
            timezone_policy=QualifiedExchangeTimezone(
                exchange="SZSE",
                timezone_name="Asia/Shanghai",
                policy_id="test-zone-v1",
                policy_sha256="a" * 64,
            ),
            as_of=as_of,
        )


@dataclass(slots=True)
class _PolicyReader:
    result: TransitionPlanDisclosureRuntimePolicy | None
    calls: list[tuple[date, date, datetime]] = field(default_factory=list)

    def read_policy(
        self, *, decision_on: date, earliest_required_on: date, as_of: datetime
    ) -> TransitionPlanDisclosureRuntimePolicy | None:
        self.calls.append((decision_on, earliest_required_on, as_of))
        return self.result


@dataclass(slots=True)
class _Capture:
    fail_on: str | None = None
    recorded_at: datetime = AS_OF + timedelta(seconds=1)
    calls: list[tuple[str, date, date, Path, str, str]] = field(default_factory=list)

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
        self.calls.append((asset_code, start_on, end_on, body_store_root, using, audit_environment))
        if asset_code == self.fail_on:
            raise RuntimeError("official capture failed")
        return self.recorded_at


def _policy() -> TransitionPlanDisclosureRuntimePolicy:
    return TransitionPlanDisclosureRuntimePolicy(
        source_id="szse_official",
        start_on=date(2026, 10, 1),
        end_on=date(2026, 11, 11),
        body_store_root=Path.cwd() / "official-pdf-test-store",
        lease_policy=TransitionPlanEventCoverageLeasePolicy(
            policy_version="official-v1",
            ttl=timedelta(seconds=60),
            maximum_ttl=timedelta(seconds=60),
        ),
        policy_version="official-v1",
        runtime_environment="development",
        profile_id="profile-1",
        profile_key="profile-key",
        profile_version=1,
        profile_content_hash="b" * 64,
        snapshot_id="snapshot-1",
        snapshot_content_hash="c" * 64,
        known_at=AS_OF - timedelta(days=1),
        effective_at=AS_OF - timedelta(hours=1),
        read_at=AS_OF,
        policy_content_hash="d" * 64,
    )


def test_official_capture_uses_verified_account_window_and_exact_identities() -> None:
    origin = _OriginReader()
    policy = _PolicyReader(_policy())
    capture = _Capture()
    refresher = OfficialSzseDistributionRefresher(
        origin_reader=origin,
        policy_reader=policy,
        capture=capture,
        using="default",
        audit_environment="development",
    )

    assert (
        refresher.refresh(asset_identities=IDENTITIES, request_scope=SCOPE, as_of=AS_OF)
        == IDENTITIES
    )
    assert origin.calls == [(12, 9, "SZSE", AS_OF)]
    assert policy.calls == [(date(2026, 11, 11), date(2026, 10, 1), AS_OF)]
    assert capture.calls == [
        (
            identity.asset_code,
            date(2026, 10, 1),
            date(2026, 11, 11),
            _policy().body_store_root,
            "default",
            "development",
        )
        for identity in IDENTITIES
    ]


@pytest.mark.parametrize(
    "policy",
    [
        None,
        replace(_policy(), start_on=date(2026, 10, 2)),
        replace(_policy(), end_on=date(2026, 11, 10)),
    ],
)
def test_missing_or_incomplete_policy_blocks_before_network(
    policy: TransitionPlanDisclosureRuntimePolicy | None,
) -> None:
    capture = _Capture()
    refresher = OfficialSzseDistributionRefresher(
        origin_reader=_OriginReader(),
        policy_reader=_PolicyReader(policy),
        capture=capture,
        using="default",
        audit_environment="development",
    )

    with pytest.raises(RebalanceJourneyUnavailable):
        refresher.refresh(asset_identities=IDENTITIES, request_scope=SCOPE, as_of=AS_OF)
    assert capture.calls == []


def test_unsupported_asset_and_partial_multi_asset_capture_cannot_complete() -> None:
    capture = _Capture(fail_on="301237.SZ")
    refresher = OfficialSzseDistributionRefresher(
        origin_reader=_OriginReader(),
        policy_reader=_PolicyReader(_policy()),
        capture=capture,
        using="default",
        audit_environment="development",
    )

    with pytest.raises(RebalanceJourneyUnavailable):
        refresher.refresh(
            asset_identities=(
                PortfolioRiskAssetIdentity(asset_code="600036.SH", security_id="SSE:600036"),
            ),
            request_scope=SCOPE,
            as_of=AS_OF,
        )
    assert capture.calls == []

    with pytest.raises(RebalanceJourneyUnavailable):
        refresher.refresh(asset_identities=IDENTITIES, request_scope=SCOPE, as_of=AS_OF)
    assert [call[0] for call in capture.calls] == ["002727.SZ", "301237.SZ"]


def test_replayed_old_proof_cannot_be_reported_as_fresh_capture() -> None:
    capture = _Capture(recorded_at=AS_OF - timedelta(seconds=1))
    refresher = OfficialSzseDistributionRefresher(
        origin_reader=_OriginReader(),
        policy_reader=_PolicyReader(_policy()),
        capture=capture,
        using="default",
        audit_environment="development",
    )

    with pytest.raises(RebalanceJourneyUnavailable):
        refresher.refresh(asset_identities=IDENTITIES[:1], request_scope=SCOPE, as_of=AS_OF)
