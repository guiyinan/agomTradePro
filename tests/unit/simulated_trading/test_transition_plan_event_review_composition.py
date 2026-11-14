"""Current policy and instrument evidence gate for unpinned plan revisions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from apps.config_center.domain.runtime_config import hash_public_runtime_projection
from apps.portfolio.domain.transition_plan_event_review import (
    TransitionPlanEventCoverageLeasePolicy,
    TransitionPlanEventReviewState,
)
from apps.simulated_trading.domain.execution_current_reference import (
    ExecutionInstrumentIdentityEvidenceV2,
)
from apps.simulated_trading.domain.execution_instrument_classification import (
    SimulatedInstrumentClassificationEvidenceV1,
)
from apps.simulated_trading.infrastructure.corporate_action_ownership_history_repository import (
    QualifiedExchangeTimezone,
    VerifiedSimulatedAccountOriginCalendar,
)
from apps.simulated_trading.transition_plan_disclosure_runtime_policy import (
    DISCLOSURE_COVERAGE_POLICY_KEY,
    RuntimeDisclosurePolicyEvidence,
    TransitionPlanDisclosureRuntimePolicy,
)
from apps.simulated_trading.transition_plan_event_review_composition import (
    ConfiguredTransitionPlanEventReviewValidator,
)
from tests.unit.portfolio.test_transition_plan_revision_asset_identity import (
    _NOW,
    _revision,
)
from tests.unit.simulated_trading import (
    test_execution_instrument_classification as classification_fixtures,
)

_HASH_A = "a" * 64
_HASH_B = "b" * 64
_HASH_C = "c" * 64
_ENVIRONMENT = "development"


@dataclass(frozen=True, slots=True)
class _Profile:
    """Minimal Config Center profile read matching its public protocol."""

    profile_id: str
    profile_key: str
    environment: str
    version: int
    status: str
    content_hash: str
    created_at: datetime
    activated_at: datetime | None

    def __post_init__(self) -> None:
        """Keep the synthetic active profile internally coherent."""


@dataclass(frozen=True, slots=True)
class _Snapshot:
    """Minimal immutable Config Center snapshot read matching its public protocol."""

    snapshot_id: str
    profile_id: str
    profile_key: str
    profile_version: int
    snapshot_hash: str
    resolved_values: Mapping[str, object]
    generated_at: datetime
    effective_from: datetime | None

    def __post_init__(self) -> None:
        """Keep the synthetic snapshot tied to one active profile."""


class _PolicyEvidenceReader:
    """Return one stable synthetic Config Center policy value at a fixed cutoff."""

    def __init__(self, enabled: object | None, *, as_of: datetime) -> None:
        self._enabled = enabled
        self._as_of = as_of

    def read_active_evidence(
        self, *, runtime_environment: str, definition_key: str, as_of: datetime
    ) -> RuntimeDisclosurePolicyEvidence | None:
        """Return exact environment/key/cutoff evidence or the configured missing result."""

        if self._enabled is None:
            return None
        value: dict[str, object] = {
            "schema_version": "simulated-disclosure-coverage-policy.v1",
            "enabled": self._enabled,
            "source_id": "szse_official",
            "start_on": "2026-10-01",
            "end_on_mode": "through_decision_date",
            "body_store_root": str(Path(__file__).resolve().parent / "synthetic-disclosure-store"),
            "policy_version": "coverage-r1",
            "lease_ttl_seconds": 30,
        }
        profile = _Profile(
            profile_id="profile-1",
            profile_key="market-simulated",
            environment=runtime_environment,
            version=2,
            status="active",
            content_hash=_HASH_A,
            created_at=self._as_of - timedelta(hours=2),
            activated_at=self._as_of - timedelta(hours=1),
        )
        snapshot = _Snapshot(
            snapshot_id="snapshot-1",
            profile_id=profile.profile_id,
            profile_key=profile.profile_key,
            profile_version=profile.version,
            snapshot_hash=hash_public_runtime_projection({definition_key: value}),
            resolved_values={definition_key: value},
            generated_at=self._as_of - timedelta(minutes=30),
            effective_from=self._as_of - timedelta(hours=1),
        )
        if (runtime_environment, definition_key, as_of) != (
            _ENVIRONMENT,
            DISCLOSURE_COVERAGE_POLICY_KEY,
            self._as_of,
        ):
            return None
        return RuntimeDisclosurePolicyEvidence(
            runtime_environment=runtime_environment,
            definition_key=definition_key,
            value=value,
            profile=profile,
            snapshot=snapshot,
            read_at=as_of,
        )


class _OriginReader:
    """Return one account-scoped origin and exchange timezone policy."""

    def __init__(self, as_of: datetime) -> None:
        self.calendar = VerifiedSimulatedAccountOriginCalendar(
            origin_on=date(2026, 10, 1),
            decision_on=date(2026, 11, 5),
            timezone_policy=QualifiedExchangeTimezone(
                exchange="SZSE",
                timezone_name="Asia/Shanghai",
                policy_id="synthetic-szse-timezone-r1",
                policy_sha256=_HASH_C,
            ),
            as_of=as_of,
        )

    def read_verified_zero_origin_calendar(
        self,
        *,
        account_id: int,
        owner_user_id: int,
        exchange: str,
        as_of: datetime,
    ) -> VerifiedSimulatedAccountOriginCalendar:
        """Return the fixed test calendar only for its exact owner scope."""

        assert (account_id, owner_user_id, exchange, as_of) == (17, 23, "SZSE", self.calendar.as_of)
        return self.calendar


class _PolicyReader:
    """Return one synthetic policy whose identity matches its Config Center evidence."""

    def __init__(self, as_of: datetime) -> None:
        self.policy = TransitionPlanDisclosureRuntimePolicy(
            source_id="szse_official",
            start_on=date(2026, 10, 1),
            end_on=date(2026, 11, 5),
            body_store_root=Path(__file__).resolve().parent / "synthetic-disclosure-store",
            lease_policy=TransitionPlanEventCoverageLeasePolicy(
                policy_version="coverage-r1",
                ttl=timedelta(seconds=30),
                maximum_ttl=timedelta(seconds=60),
            ),
            policy_version="coverage-r1",
            runtime_environment=_ENVIRONMENT,
            profile_id="profile-1",
            profile_key="market-simulated",
            profile_version=2,
            profile_content_hash=_HASH_A,
            snapshot_id="snapshot-1",
            snapshot_content_hash=_PolicyEvidenceReader(True, as_of=as_of)
            .read_active_evidence(
                runtime_environment=_ENVIRONMENT,
                definition_key=DISCLOSURE_COVERAGE_POLICY_KEY,
                as_of=as_of,
            )
            .snapshot.snapshot_hash,
            known_at=as_of - timedelta(hours=2),
            effective_at=as_of - timedelta(hours=1),
            read_at=as_of,
            policy_content_hash=_HASH_C,
        )

    def read_policy(
        self, *, decision_on: date, earliest_required_on: date, as_of: datetime
    ) -> TransitionPlanDisclosureRuntimePolicy:
        """Return the fixed policy for its exact origin/date cutoff."""

        assert (decision_on, earliest_required_on, as_of) == (
            self.policy.end_on,
            self.policy.start_on,
            self.policy.read_at,
        )
        return self.policy


class _SnapshotReader:
    """Expose the existing snapshot port without reading it on an unpinned plan."""

    def read_latest_snapshot(self, request: object) -> None:
        """Return no event snapshot; this fixture never contains event pins."""

        return None


def _classification(
    *,
    as_of: datetime,
    source_exchange: str,
    rule_market: str,
    simulated_asset_type: str = "equity",
) -> SimulatedInstrumentClassificationEvidenceV1:
    """Build actual sealed current-classification evidence for the plan order."""

    security_id = "SH.TEST.600000"
    asset_code = "600000.SH"
    template_selector = classification_fixtures._selector()
    selector_item = replace(
        template_selector.items[0],
        security_id=security_id,
        asset_code=asset_code,
        source_code=asset_code,
        simulated_asset_type=simulated_asset_type,
    )
    selector = replace(template_selector, items=(selector_item,))
    template_identity = classification_fixtures._identity(template_selector)
    reference_at = as_of - timedelta(minutes=10)
    snapshot_at = as_of - timedelta(minutes=5)
    mapping_at = as_of - timedelta(minutes=6)
    activated_at = as_of - timedelta(hours=2)
    selection = replace(
        template_identity.selection,
        selector_content_hash=selector.content_hash,
        profile_activated_at=activated_at,
        runtime_snapshot_generated_at=as_of - timedelta(hours=1),
        selected_at=as_of,
    )
    source = replace(
        template_identity.source_evidence,
        security_id=security_id,
        asset_code=asset_code,
        source_code=asset_code,
        source_exchange=source_exchange,
        source_market=source_exchange,
        rule_market=rule_market,
        board="MAIN",
        first_seen_at=reference_at,
        snapshot_recorded_at=snapshot_at,
        mapping_recorded_at=mapping_at,
        response_completed_at=reference_at,
        source_observed_at=None,
        source_available_at=None,
        identity_valid_from=max(activated_at, snapshot_at, mapping_at),
        identity_valid_until=reference_at
        + timedelta(seconds=selection.max_local_reference_age_seconds),
        must_not_use_for_decision=False,
        must_not_execute=False,
    )
    identity: ExecutionInstrumentIdentityEvidenceV2 = replace(
        template_identity,
        source_evidence=source,
        selection=selection,
        reference_response_completed_at=reference_at,
    )
    return SimulatedInstrumentClassificationEvidenceV1(
        selector=selector,
        identity_evidence=identity,
        read_at=as_of,
    )


class _ClassificationReader:
    """Return one exact classification for the only identity in the plan fixture."""

    def __init__(self, evidence: SimulatedInstrumentClassificationEvidenceV1 | None) -> None:
        self.evidence = evidence

    def resolve_simulated_instrument_classification(
        self, *, security_id: str, asset_code: str, as_of: datetime
    ) -> SimulatedInstrumentClassificationEvidenceV1 | None:
        """Return classification only for the exact identity and cutoff."""

        if self.evidence is None:
            return None
        assert (security_id, asset_code, as_of) == (
            self.evidence.identity_evidence.security_id,
            self.evidence.identity_evidence.asset_code,
            self.evidence.read_at,
        )
        return self.evidence


def _validator(
    *,
    as_of: datetime,
    enabled: object | None,
    classification: SimulatedInstrumentClassificationEvidenceV1 | None,
) -> ConfiguredTransitionPlanEventReviewValidator:
    """Compose the real validator with synthetic public read ports."""

    return ConfiguredTransitionPlanEventReviewValidator(
        origin_reader=_OriginReader(as_of),
        policy_reader=_PolicyReader(as_of),
        snapshot_reader=_SnapshotReader(),
        runtime_environment=_ENVIRONMENT,
        policy_evidence_reader=_PolicyEvidenceReader(enabled, as_of=as_of),
        classification_reader=_ClassificationReader(classification),
        clock=SimpleNamespace(now=lambda: as_of),
    )


def test_enabled_szse_scope_requires_new_event_bound_successor() -> None:
    """An active official-event policy sends an unpinned A-share plan to review."""

    as_of = _NOW + timedelta(seconds=10)
    classification = _classification(
        as_of=as_of,
        source_exchange="SZSE",
        rule_market="SZ",
    )
    revision = _revision(classification_hash=classification.content_hash)

    result = _validator(as_of=as_of, enabled=True, classification=classification).assess(
        revision, as_of=as_of
    )

    assert result.state is TransitionPlanEventReviewState.REVIEW_REQUIRED
    assert result.reason_code == "EVENT_COVERAGE_PIN_MISSING"


def test_explicitly_disabled_policy_preserves_unbound_legacy_review() -> None:
    """Only a verified explicit disabled Config Center value keeps old plans unchanged."""

    as_of = _NOW + timedelta(seconds=10)
    result = _validator(as_of=as_of, enabled=False, classification=None).assess(
        _revision(), as_of=as_of
    )

    assert result.state is TransitionPlanEventReviewState.UNCHANGED


def test_verified_us_classification_is_unrelated_to_szse_policy() -> None:
    """A currently pinned US classification stays outside the SZSE review scope."""

    as_of = _NOW + timedelta(seconds=10)
    classification = _classification(
        as_of=as_of,
        source_exchange="NASDAQ",
        rule_market="US",
    )
    revision = _revision(classification_hash=classification.content_hash)

    result = _validator(as_of=as_of, enabled=True, classification=classification).assess(
        revision, as_of=as_of
    )

    assert result.state is TransitionPlanEventReviewState.UNCHANGED


def test_sse_equity_is_blocked_until_its_source_is_supported() -> None:
    """An A-share on an unsupported exchange cannot be treated as unrelated."""

    as_of = _NOW + timedelta(seconds=10)
    classification = _classification(
        as_of=as_of,
        source_exchange="SSE",
        rule_market="SH",
    )

    result = _validator(as_of=as_of, enabled=True, classification=classification).assess(
        _revision(classification_hash=classification.content_hash), as_of=as_of
    )

    assert result.state is TransitionPlanEventReviewState.BLOCKED
    assert result.reason_code == "EVENT_SOURCE_UNSUPPORTED_MARKET"


def test_unknown_source_market_cannot_be_treated_as_unrelated() -> None:
    """An explicit but unsupported source exchange fails closed like SSE."""

    as_of = _NOW + timedelta(seconds=10)
    classification = _classification(
        as_of=as_of,
        source_exchange="OTHER",
        rule_market="OTHER",
    )

    result = _validator(as_of=as_of, enabled=True, classification=classification).assess(
        _revision(classification_hash=classification.content_hash), as_of=as_of
    )

    assert result.state is TransitionPlanEventReviewState.BLOCKED
    assert result.reason_code == "EVENT_SOURCE_UNSUPPORTED_MARKET"


def test_missing_policy_or_classification_fails_closed() -> None:
    """Missing current policy or identity evidence never means a disabled feature."""

    as_of = _NOW + timedelta(seconds=10)
    missing_policy = _validator(
        as_of=as_of,
        enabled=None,
        classification=None,
    ).assess(_revision(), as_of=as_of)
    missing_classification = _validator(
        as_of=as_of,
        enabled=True,
        classification=None,
    ).assess(_revision(), as_of=as_of)

    assert missing_policy.state is TransitionPlanEventReviewState.BLOCKED
    assert missing_policy.reason_code == "EVENT_CURRENT_POLICY_UNAVAILABLE"
    assert missing_classification.state is TransitionPlanEventReviewState.BLOCKED
    assert missing_classification.reason_code == "EVENT_CLASSIFICATION_UNAVAILABLE"


def test_non_boolean_enabled_value_is_not_a_disabled_policy() -> None:
    """A malformed policy value cannot be interpreted as a feature-off decision."""

    as_of = _NOW + timedelta(seconds=10)
    result = _validator(as_of=as_of, enabled=0, classification=None).assess(
        _revision(), as_of=as_of
    )

    assert result.state is TransitionPlanEventReviewState.BLOCKED
    assert result.reason_code == "EVENT_CURRENT_POLICY_UNAVAILABLE"


def test_current_policy_snapshot_must_match_config_center_evidence() -> None:
    """A different active policy profile cannot certify an unbound plan as unaffected."""

    as_of = _NOW + timedelta(seconds=10)
    classification = _classification(
        as_of=as_of,
        source_exchange="SZSE",
        rule_market="SZ",
    )
    validator = _validator(as_of=as_of, enabled=True, classification=classification)
    validator._policy_reader.policy = replace(
        validator._policy_reader.policy, snapshot_id="other-snapshot"
    )

    result = validator.assess(
        _revision(classification_hash=classification.content_hash),
        as_of=as_of,
    )

    assert result.state is TransitionPlanEventReviewState.BLOCKED
    assert result.reason_code == "EVENT_CURRENT_POLICY_UNAVAILABLE"
