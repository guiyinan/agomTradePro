"""Composition tests for the current official-window read-only ports."""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from apps.portfolio.application.transition_plan_event_review import (
    TransitionPlanEventSnapshotReadRequest,
)
from apps.portfolio.domain.transition_plan_event_review import (
    TransitionPlanEventAssetSnapshot,
    TransitionPlanEventCoverageLeasePolicy,
)
from apps.simulated_trading import (
    corporate_action_current_official_window_composition as composition,
)
from apps.simulated_trading.application.corporate_action_current_official_window import (
    CorporateActionCurrentOfficialWindowReader,
)
from apps.simulated_trading.application.corporate_action_current_official_window_contracts import (
    TransitionPlanDisclosureRuntimePolicy as ApplicationRuntimePolicyEvidence,
)
from apps.simulated_trading.transition_plan_disclosure_runtime_policy import (
    TransitionPlanDisclosureRuntimePolicy as ConfiguredRuntimePolicyEvidence,
)

_NOW = datetime(2026, 11, 13, 4, 0, tzinfo=UTC)


class _OriginReader:
    def read_verified_zero_origin_calendar(self, **kwargs: object) -> object:
        raise AssertionError("composition test does not read the owner database")


class _RuntimePolicyReader:
    def __init__(self, *, runtime_environment: str) -> None:
        self.runtime_environment = runtime_environment

    def read_policy(self, **kwargs: object) -> None:
        raise AssertionError("composition test does not read Config Center")


class _ConfiguredPolicyStub:
    def __init__(self, policy: ConfiguredRuntimePolicyEvidence) -> None:
        self.policy = policy

    def read_policy(self, **kwargs: object) -> ConfiguredRuntimePolicyEvidence:
        assert kwargs == {
            "decision_on": date(2026, 11, 13),
            "earliest_required_on": date(2026, 10, 1),
            "as_of": _NOW,
        }
        return self.policy


class _Query:
    def execute(self, scope: object) -> object:
        raise AssertionError("composition test does not query Data Center")


class _SnapshotReader:
    def __init__(self, *, query_use_case: object, event_query_use_case: object) -> None:
        self.query_use_case = query_use_case
        self.event_query_use_case = event_query_use_case

    def read_latest_snapshot(
        self, request: TransitionPlanEventSnapshotReadRequest
    ) -> TransitionPlanEventAssetSnapshot | None:
        raise AssertionError("composition test does not read a snapshot")


class _Verifier:
    def verify_original_body(self, *, event: object, body_store_root: Path) -> bool:
        return True


class _Clock:
    def now(self) -> datetime:
        return _NOW


def test_builder_wires_exact_environment_alias_snapshot_queries_and_required_ports(
    monkeypatch,
) -> None:
    origin = _OriginReader()
    listing = _Query()
    events = _Query()
    calls: dict[str, object] = {}

    def build_origin(*, runtime_environment: str, using: str) -> _OriginReader:
        calls["origin"] = (runtime_environment, using)
        return origin

    def make_listing_reader(*, using: str) -> _Query:
        calls["listing"] = using
        return listing

    def make_event_reader(*, using: str) -> _Query:
        calls["events"] = using
        return events

    monkeypatch.setattr(
        composition,
        "build_corporate_action_ownership_history_repository",
        build_origin,
    )
    monkeypatch.setattr(
        composition, "make_security_disclosure_listing_coverage_reader", make_listing_reader
    )
    monkeypatch.setattr(composition, "make_security_disclosure_event_reader", make_event_reader)
    monkeypatch.setattr(
        composition,
        "ConfiguredTransitionPlanDisclosureRuntimePolicyReader",
        _RuntimePolicyReader,
    )
    monkeypatch.setattr(composition, "DataCenterTransitionPlanEventSnapshotReader", _SnapshotReader)

    verifier = _Verifier()
    clock = _Clock()
    reader = composition.build_corporate_action_current_official_window_reader(
        runtime_environment="test-env",
        original_body_verifier=verifier,
        using="qa-window",
        clock=clock,
    )

    assert type(reader) is CorporateActionCurrentOfficialWindowReader
    assert reader._origin_reader is origin
    assert reader._policy_reader._reader.runtime_environment == "test-env"
    assert reader._snapshot_reader.query_use_case is listing
    assert reader._snapshot_reader.event_query_use_case is events
    assert reader._original_body_verifier is verifier
    assert reader._clock is clock
    assert calls == {
        "origin": ("test-env", "qa-window"),
        "listing": "qa-window",
        "events": "qa-window",
    }


def test_builder_defaults_to_django_timezone_now_and_keeps_missing_verifier_explicit(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        composition,
        "build_corporate_action_ownership_history_repository",
        lambda **kwargs: _OriginReader(),
    )
    monkeypatch.setattr(
        composition, "make_security_disclosure_listing_coverage_reader", lambda **kwargs: _Query()
    )
    monkeypatch.setattr(
        composition, "make_security_disclosure_event_reader", lambda **kwargs: _Query()
    )
    monkeypatch.setattr(
        composition, "ConfiguredTransitionPlanDisclosureRuntimePolicyReader", _RuntimePolicyReader
    )
    monkeypatch.setattr(composition, "DataCenterTransitionPlanEventSnapshotReader", _SnapshotReader)
    monkeypatch.setattr(composition.timezone, "now", lambda: _NOW)

    reader = composition.build_corporate_action_current_official_window_reader(
        runtime_environment="test-env",
        original_body_verifier=None,
    )

    assert reader._clock.now() == _NOW
    assert reader._original_body_verifier is None


def test_configured_policy_adapter_copies_exact_application_evidence() -> None:
    configured = ConfiguredRuntimePolicyEvidence(
        source_id="szse_official",
        start_on=date(2026, 10, 1),
        end_on=date(2026, 11, 13),
        body_store_root=Path(__file__).resolve().parent / "synthetic-official-pdf-store",
        lease_policy=TransitionPlanEventCoverageLeasePolicy(
            policy_version="szse-window-v1",
            ttl=timedelta(seconds=60),
            maximum_ttl=timedelta(seconds=60),
        ),
        policy_version="szse-window-v1",
        runtime_environment="test-env",
        profile_id="profile-1",
        profile_key="profile-key",
        profile_version=1,
        profile_content_hash="2" * 64,
        snapshot_id="snapshot-1",
        snapshot_content_hash="3" * 64,
        known_at=_NOW - timedelta(days=2),
        effective_at=_NOW - timedelta(days=1),
        read_at=_NOW,
        policy_content_hash="4" * 64,
    )
    adapter = composition._ConfiguredRuntimePolicyApplicationAdapter(
        _ConfiguredPolicyStub(configured)
    )

    result = adapter.read_policy(
        decision_on=date(2026, 11, 13),
        earliest_required_on=date(2026, 10, 1),
        as_of=_NOW,
    )

    assert type(result) is ApplicationRuntimePolicyEvidence
    assert asdict(result) == asdict(configured)
