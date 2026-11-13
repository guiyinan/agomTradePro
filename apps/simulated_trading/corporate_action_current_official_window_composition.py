"""Compose current official-window evidence from Account, Config Center, and Data Center."""

from __future__ import annotations

from datetime import date, datetime

from django.utils import timezone

from apps.data_center.security_disclosure_capture_composition import (
    make_security_disclosure_event_reader,
    make_security_disclosure_listing_coverage_reader,
)
from apps.simulated_trading.application.corporate_action_current_official_window import (
    CorporateActionCurrentOfficialWindowClock,
    CorporateActionCurrentOfficialWindowReader,
    OriginalDisclosureBodyVerifier,
)
from apps.simulated_trading.application.corporate_action_current_official_window_contracts import (
    OfficialWindowRuntimePolicyReader,
)
from apps.simulated_trading.application.corporate_action_current_official_window_contracts import (
    TransitionPlanDisclosureRuntimePolicy as ApplicationRuntimePolicyEvidence,
)
from apps.simulated_trading.corporate_action_ownership_history_composition import (
    build_corporate_action_ownership_history_repository,
)
from apps.simulated_trading.transition_plan_disclosure_runtime_policy import (
    ConfiguredTransitionPlanDisclosureRuntimePolicyReader,
)
from apps.simulated_trading.transition_plan_disclosure_runtime_policy import (
    TransitionPlanDisclosureRuntimePolicy as ConfiguredRuntimePolicyEvidence,
)
from apps.simulated_trading.transition_plan_event_coverage_adapter import (
    DataCenterTransitionPlanEventSnapshotReader,
)


class _DjangoTimezoneClock:
    """Use Django's timezone-aware clock for current-window start and finish checks."""

    def now(self) -> datetime:
        """Return the current aware application time."""

        return timezone.now()


class _ConfiguredRuntimePolicyApplicationAdapter:
    """Copy the canonical configured policy into the Application-owned contract."""

    def __init__(self, reader: ConfiguredTransitionPlanDisclosureRuntimePolicyReader) -> None:
        """Bind the existing Config Center-backed configured-policy reader."""

        self._reader = reader

    def read_policy(
        self,
        *,
        decision_on: date,
        earliest_required_on: date,
        as_of: datetime,
    ) -> ApplicationRuntimePolicyEvidence | None:
        """Return a field-for-field Application evidence copy at the same cutoff."""

        configured = self._reader.read_policy(
            decision_on=decision_on,
            earliest_required_on=earliest_required_on,
            as_of=as_of,
        )
        if type(configured) is not ConfiguredRuntimePolicyEvidence:
            return None
        return ApplicationRuntimePolicyEvidence(
            source_id=configured.source_id,
            start_on=configured.start_on,
            end_on=configured.end_on,
            body_store_root=configured.body_store_root,
            lease_policy=configured.lease_policy,
            policy_version=configured.policy_version,
            runtime_environment=configured.runtime_environment,
            profile_id=configured.profile_id,
            profile_key=configured.profile_key,
            profile_version=configured.profile_version,
            profile_content_hash=configured.profile_content_hash,
            snapshot_id=configured.snapshot_id,
            snapshot_content_hash=configured.snapshot_content_hash,
            known_at=configured.known_at,
            effective_at=configured.effective_at,
            read_at=configured.read_at,
            policy_content_hash=configured.policy_content_hash,
        )


def build_corporate_action_current_official_window_reader(
    *,
    runtime_environment: str,
    original_body_verifier: OriginalDisclosureBodyVerifier | None,
    using: str = "default",
    clock: CorporateActionCurrentOfficialWindowClock | None = None,
) -> CorporateActionCurrentOfficialWindowReader:
    """Compose the existing public policy, owner-origin, and latest-to-exact readers."""

    if type(runtime_environment) is not str or not runtime_environment.strip():
        raise ValueError("current official-window runtime environment must be explicit")
    if type(using) is not str or not using.strip():
        raise ValueError("current official-window database alias must be explicit")
    origin_reader = build_corporate_action_ownership_history_repository(
        runtime_environment=runtime_environment,
        using=using,
    )
    policy_reader: OfficialWindowRuntimePolicyReader = _ConfiguredRuntimePolicyApplicationAdapter(
        ConfiguredTransitionPlanDisclosureRuntimePolicyReader(
            runtime_environment=runtime_environment,
        )
    )
    snapshot_reader = DataCenterTransitionPlanEventSnapshotReader(
        query_use_case=make_security_disclosure_listing_coverage_reader(using=using),
        event_query_use_case=make_security_disclosure_event_reader(using=using),
    )
    trusted_clock = _DjangoTimezoneClock() if clock is None else clock
    return CorporateActionCurrentOfficialWindowReader(
        origin_reader=origin_reader,
        policy_reader=policy_reader,
        snapshot_reader=snapshot_reader,
        original_body_verifier=original_body_verifier,
        runtime_environment=runtime_environment,
        clock=trusted_clock,
    )


__all__ = ("build_corporate_action_current_official_window_reader",)
