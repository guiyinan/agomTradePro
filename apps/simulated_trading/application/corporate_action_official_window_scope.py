"""Read-only account/security coverage requests without invented financial events."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from apps.portfolio.domain.transition_plan_event_review import TransitionPlanEventAssetSnapshot
from apps.simulated_trading.application.corporate_action_current_official_window_contracts import (
    TransitionPlanDisclosureRuntimePolicy,
)
from apps.simulated_trading.application.corporate_action_official_window_evidence import (
    CorporateActionCurrentOfficialWindowReason,
    _is_aware,
    _is_sha256,
    _is_token,
)


@dataclass(frozen=True, slots=True)
class CorporateActionOfficialWindowScope:
    """An actual owned physical account and exact security; no selected event facts."""

    account_id: int
    owner_user_id: int
    asset_code: str
    security_id: str

    def __post_init__(self) -> None:
        """Reject coercive identities and unsupported or inconsistent security scopes."""
        if (
            type(self.account_id) is not int
            or self.account_id <= 0
            or type(self.owner_user_id) is not int
            or self.owner_user_id <= 0
            or type(self.asset_code) is not str
            or re.fullmatch(r"[0-9]{6}\.SZ", self.asset_code) is None
            or self.security_id != self.asset_code
        ):
            raise ValueError(
                "official-window scope must contain exact owner and SZSE security identities"
            )


@dataclass(frozen=True, slots=True)
class CorporateActionOfficialWindowScopeEvidence:
    """Complete actual coverage, including a truly empty window; never financial authority."""

    scope: CorporateActionOfficialWindowScope
    window_ready: bool
    reason_code: CorporateActionCurrentOfficialWindowReason
    checked_at: datetime | None
    expires_at: datetime | None = None
    snapshot: TransitionPlanEventAssetSnapshot | None = None
    policy: TransitionPlanDisclosureRuntimePolicy | None = None
    calendar_policy_id: str | None = None
    calendar_policy_sha256: str | None = None
    exchange_timezone_name: str | None = None
    must_not_use_for_decision: Literal[True] = True
    decision_use_reason: Literal["coverage_evidence_only"] = "coverage_evidence_only"

    def __post_init__(self) -> None:
        """Keep readiness bound to the full original complete snapshot and finite clocks."""
        if (
            type(self.scope) is not CorporateActionOfficialWindowScope
            or type(self.window_ready) is not bool
            or type(self.reason_code) is not CorporateActionCurrentOfficialWindowReason
            or self.must_not_use_for_decision is not True
            or self.decision_use_reason != "coverage_evidence_only"
            or self.window_ready
            != (
                self.reason_code
                is CorporateActionCurrentOfficialWindowReason.WINDOW_READY_PREREQUISITE_ONLY
            )
        ):
            raise ValueError("official-window scope evidence flags are invalid")
        self.scope.__post_init__()
        if not self.window_ready:
            if any(
                value is not None
                for value in (
                    self.snapshot,
                    self.policy,
                    self.expires_at,
                    self.calendar_policy_id,
                    self.calendar_policy_sha256,
                    self.exchange_timezone_name,
                )
            ):
                raise ValueError("blocked coverage cannot publish ready proof fields")
            return
        if (
            type(self.snapshot) is not TransitionPlanEventAssetSnapshot
            or type(self.policy) is not TransitionPlanDisclosureRuntimePolicy
            or not _is_aware(self.checked_at)
            or not _is_aware(self.expires_at)
            or not _is_token(self.calendar_policy_id)
            or not _is_sha256(self.calendar_policy_sha256)
            or not _is_token(self.exchange_timezone_name)
        ):
            raise ValueError("ready scope coverage lacks original evidence")
        self.snapshot.__post_init__()
        if (
            self.snapshot.asset_code != self.scope.asset_code
            or self.snapshot.security_id != self.scope.security_id
            or self.snapshot.start_on != self.policy.start_on
            or self.snapshot.end_on != self.policy.end_on
            or self.snapshot.source_scope_sha256 is None
            or not self.snapshot.proof_recorded_at <= self.checked_at < self.expires_at
        ):
            raise ValueError("ready scope coverage crosses scope or has expired")
