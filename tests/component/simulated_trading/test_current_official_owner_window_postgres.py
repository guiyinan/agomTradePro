"""Capture and verify one live, empty SZSE window without financial authority."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
from collections.abc import Iterator
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import requests
from django.db import connection
from django.test import override_settings
from django.utils import timezone

from apps.audit.security_disclosure_capture_composition import (
    capture_and_append_szse_distribution_window,
)
from apps.data_center.application.security_disclosure_event import (
    QuerySecurityDisclosureEventsUseCase,
    QuerySecurityDisclosureListingCoverageUseCase,
)
from apps.data_center.infrastructure.official_szse_announcement_listing import (
    CapturedOfficialSzseListingWindow,
)
from apps.portfolio.application.transition_plan_event_review import (
    TransitionPlanEventSnapshotReadRequest,
)
from apps.portfolio.domain.transition_plan_event_review import (
    TransitionPlanEventAssetSnapshot,
    TransitionPlanEventCoverageStatus,
)
from apps.simulated_trading import (
    corporate_action_current_official_window_composition as window_composition,
)
from apps.simulated_trading.application.corporate_action_current_official_window import (
    CorporateActionCurrentOfficialWindowReason,
)
from apps.simulated_trading.application.corporate_action_official_window_scope import (
    CorporateActionOfficialWindowScope,
)
from apps.simulated_trading.corporate_action_original_body_composition import (
    DataCenterCorporateActionOriginalBodyVerifier,
)
from apps.simulated_trading.corporate_action_ownership_history_composition import (
    build_corporate_action_ownership_history_repository,
)
from apps.simulated_trading.infrastructure.corporate_action_ownership_history_repository import (
    DjangoCorporateActionOwnershipHistoryRepository,
    VerifiedSimulatedAccountOriginCalendar,
)
from apps.simulated_trading.transition_plan_disclosure_runtime_policy import (
    ConfiguredTransitionPlanDisclosureRuntimePolicyReader,
)
from apps.simulated_trading.transition_plan_disclosure_runtime_policy import (
    TransitionPlanDisclosureRuntimePolicy as ConfiguredTransitionPlanDisclosureRuntimePolicy,
)
from tests.support.account_authority_generation_flush import (
    preserve_account_authority_generation as preserve_account_authority_generation,
)
from tests.support.ash05_owner_workflow_native_world import (
    build_owner_workflow_native_world,
)
from tests.support.ash07_owner_account_authority import ASH07_OWNER_ACCEPTANCE_AVAILABLE_APPS
from tests.support.simulated_tax_model_native_sources import isolated_task_channels

pytestmark = pytest.mark.django_db(
    transaction=True,
    available_apps=ASH07_OWNER_ACCEPTANCE_AVAILABLE_APPS,
)

_OFFICIAL_ASSET_CODE = "001211.SZ"
_EXPECTED_CAPTURE_PAGE_SHA256 = "623a2b4aa0de75d0685242ca41fe14e9eadb493315e17194845035fa58c6ef83"


@pytest.fixture(autouse=True)
def _isolated_current_window_runtime() -> Iterator[None]:
    """Use the actual bounded owner routes and isolated local task/cache channels."""
    with (
        isolated_task_channels(),
        override_settings(ROOT_URLCONF="tests.support.ash05_owner_workflow_test_urls"),
    ):
        yield


class _ObservedTrustedClock:
    """Count actual Django clock reads without changing or freezing their values."""

    def __init__(self) -> None:
        self.values: list[datetime] = []

    def now(self) -> datetime:
        """Return and retain one actual aware application clock value."""
        value = timezone.now()
        self.values.append(value)
        return value


class _CountingOriginReader:
    """Count calls while delegating every calendar query to the real repository."""

    def __init__(self, delegate: DjangoCorporateActionOwnershipHistoryRepository) -> None:
        self._delegate = delegate
        self.calendars: list[VerifiedSimulatedAccountOriginCalendar] = []

    def read_verified_zero_origin_calendar(
        self,
        *,
        account_id: int,
        owner_user_id: int,
        exchange: str,
        as_of: datetime,
    ) -> VerifiedSimulatedAccountOriginCalendar:
        """Read the actual owner calendar and retain its exact returned evidence."""
        result = self._delegate.read_verified_zero_origin_calendar(
            account_id=account_id,
            owner_user_id=owner_user_id,
            exchange=exchange,
            as_of=as_of,
        )
        self.calendars.append(result)
        return result


def test_current_owner_window_reads_live_complete_empty_official_coverage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Persist a current two-pass listing, then prove the public empty-window scope."""
    if os.environ.get("ASH05_LIVE_CURRENT_OFFICIAL_WINDOW") != "1":
        pytest.skip("Live official-source acceptance requires explicit opt-in")
    assert connection.vendor == "postgresql"
    assert connection.settings_dict["NAME"] in {
        "ash05_tax_payment_basis_qa",
        "ash05_owner_goldens_test_ci",
    }
    configured_output = os.environ.get("ASH05_LIVE_OFFICIAL_EVIDENCE_DIR")
    assert configured_output
    output = Path(configured_output).resolve()
    allowed = Path(__file__).resolve().parents[3] / "artifacts/ash05-owner-service-20261111"
    assert output.is_relative_to(allowed.resolve()) and not output.exists()
    real_session_send = requests.Session.send
    real_getaddrinfo = socket.getaddrinfo
    assert real_session_send.__module__ == "requests.sessions"
    with monkeypatch.context() as synthetic_setup:
        world = build_owner_workflow_native_world(
            monkeypatch=synthetic_setup,
            tmp_path=tmp_path,
            capture_kind="cash",
        )

    # The world helper's synthetic account, calendar, model, and consent setup
    # must not intercept the official listing request below.
    assert requests.Session.send is real_session_send
    assert socket.getaddrinfo is real_getaddrinfo
    assert world.owner.owner.is_staff is False

    environment = world.owner.environment
    policy_cutoff = timezone.now()
    expected_window_start = world.anchor_date
    expected_window_end = policy_cutoff.astimezone(ZoneInfo("Asia/Shanghai")).date()
    calendar = build_corporate_action_ownership_history_repository(
        runtime_environment=environment,
        using="default",
    ).read_verified_zero_origin_calendar(
        account_id=world.account_id,
        owner_user_id=world.owner.owner.pk,
        exchange="SZSE",
        as_of=policy_cutoff,
    )
    configured_policy_reader = ConfiguredTransitionPlanDisclosureRuntimePolicyReader(
        runtime_environment=environment,
    )
    configured_policy = configured_policy_reader.read_policy(
        decision_on=calendar.decision_on,
        earliest_required_on=calendar.origin_on,
        as_of=policy_cutoff,
    )
    assert configured_policy is not None
    assert calendar.origin_on == world.anchor_date == expected_window_start
    assert calendar.decision_on == expected_window_end
    assert configured_policy.start_on == expected_window_start
    assert configured_policy.end_on == expected_window_end
    assert configured_policy.body_store_root == world.action_body_store_root

    # This is the existing Data Center plus Audit/Outbox capture path. Its
    # request runs after the synthetic requests/DNS patches have been removed.
    captured = capture_and_append_szse_distribution_window(
        asset_code=_OFFICIAL_ASSET_CODE,
        start_on=configured_policy.start_on,
        end_on=configured_policy.end_on,
        body_store_root=configured_policy.body_store_root,
        using="default",
        audit_environment=world.audit_authority_seed.environment,
    )
    listing = captured.candidate.listing
    persisted = captured.coverage.record
    proof = persisted.proof
    assert type(listing) is CapturedOfficialSzseListingWindow
    assert listing.asset_code == _OFFICIAL_ASSET_CODE
    assert listing.start_on == expected_window_start
    assert listing.end_on == expected_window_end
    assert listing.announcement_count == 0
    assert listing.entries == ()
    assert listing.first_pass_page_body_sha256 == listing.page_body_sha256
    assert listing.first_pass_page_body_sha256 == (_EXPECTED_CAPTURE_PAGE_SHA256,)
    proof.__post_init__()
    assert len(listing.coverage_manifest_sha256) == 64
    assert proof == captured.candidate.proof
    assert proof.announcement_count == 0
    assert proof.entries == ()
    assert proof.first_observed_at <= proof.verified_at
    assert proof.verified_at == listing.observed_at
    assert proof.source_manifest_sha256 == listing.manifest_sha256
    assert proof.coverage_manifest_sha256 == listing.coverage_manifest_sha256
    assert persisted.recorded_at == captured.audit.commit.event.recorded_at
    assert captured.audit.commit.event.event_type == "data.disclosure_fact.appended"
    assert captured.audit.commit.event_id == captured.audit.commit.event.event_id

    for digest in proof.first_pass_page_body_sha256 + proof.second_pass_page_body_sha256:
        original_body = configured_policy.body_store_root / "listing" / f"{digest}.json"
        body = original_body.read_bytes()
        assert hashlib.sha256(body).hexdigest() == digest

    origin_readers: list[_CountingOriginReader] = []
    real_origin_factory = window_composition.build_corporate_action_ownership_history_repository

    def counted_origin_factory(
        *, runtime_environment: str, using: str = "default"
    ) -> _CountingOriginReader:
        delegate = real_origin_factory(runtime_environment=runtime_environment, using=using)
        reader = _CountingOriginReader(delegate)
        origin_readers.append(reader)
        return reader

    configured_results: list[ConfiguredTransitionPlanDisclosureRuntimePolicy | None] = []
    real_configured_reader = (
        window_composition.ConfiguredTransitionPlanDisclosureRuntimePolicyReader
    )

    class _CountingConfiguredPolicyReader(real_configured_reader):
        """Record all configured full-profile reads made by the real composition."""

        def __init__(self, *, runtime_environment: str) -> None:
            super().__init__(runtime_environment=runtime_environment)

        def read_policy(
            self,
            *,
            decision_on: date,
            earliest_required_on: date,
            as_of: datetime,
        ) -> ConfiguredTransitionPlanDisclosureRuntimePolicy | None:
            result = super().read_policy(
                decision_on=decision_on,
                earliest_required_on=earliest_required_on,
                as_of=as_of,
            )
            configured_results.append(result)
            return result

    real_snapshot_reader = window_composition.DataCenterTransitionPlanEventSnapshotReader
    snapshot_requests: list[TransitionPlanEventSnapshotReadRequest] = []
    snapshot_results: list[TransitionPlanEventAssetSnapshot | None] = []
    snapshot_reader_instances: list[None] = []

    class _TrackedSnapshotReader(real_snapshot_reader):
        """Retain actual latest-to-exact Data Center read results for the assertion."""

        def __init__(
            self,
            *,
            query_use_case: QuerySecurityDisclosureListingCoverageUseCase,
            event_query_use_case: QuerySecurityDisclosureEventsUseCase | None = None,
        ) -> None:
            super().__init__(
                query_use_case=query_use_case,
                event_query_use_case=event_query_use_case,
            )
            snapshot_reader_instances.append(None)

        def read_latest_snapshot(
            self, request: TransitionPlanEventSnapshotReadRequest
        ) -> TransitionPlanEventAssetSnapshot | None:
            snapshot_requests.append(request)
            result = super().read_latest_snapshot(request)
            snapshot_results.append(result)
            return result

    trusted_clock = _ObservedTrustedClock()
    scope = CorporateActionOfficialWindowScope(
        account_id=world.account_id,
        owner_user_id=world.owner.owner.pk,
        asset_code=_OFFICIAL_ASSET_CODE,
        security_id=_OFFICIAL_ASSET_CODE,
    )
    with monkeypatch.context() as counters:
        counters.setattr(
            window_composition,
            "build_corporate_action_ownership_history_repository",
            counted_origin_factory,
        )
        counters.setattr(
            window_composition,
            "ConfiguredTransitionPlanDisclosureRuntimePolicyReader",
            _CountingConfiguredPolicyReader,
        )
        counters.setattr(
            window_composition,
            "DataCenterTransitionPlanEventSnapshotReader",
            _TrackedSnapshotReader,
        )
        reader = window_composition.build_corporate_action_current_official_window_reader(
            runtime_environment=environment,
            original_body_verifier=DataCenterCorporateActionOriginalBodyVerifier(
                using="default",
            ),
            using="default",
            clock=trusted_clock,
        )
        evidence = reader.read_current_scope(scope, as_of=timezone.now())

    assert evidence.window_ready is True
    assert (
        evidence.reason_code
        is CorporateActionCurrentOfficialWindowReason.WINDOW_READY_PREREQUISITE_ONLY
    )
    assert evidence.scope == scope
    assert evidence.must_not_use_for_decision is True
    assert evidence.decision_use_reason == "coverage_evidence_only"
    assert evidence.checked_at is not None and evidence.expires_at is not None
    assert evidence.checked_at >= persisted.recorded_at
    assert evidence.checked_at < evidence.expires_at
    assert evidence.expires_at == proof.verified_at + configured_policy.lease_policy.ttl

    snapshot = evidence.snapshot
    policy = evidence.policy
    assert snapshot is not None and policy is not None
    assert snapshot.coverage_status is TransitionPlanEventCoverageStatus.COMPLETE
    assert snapshot.events == ()
    assert snapshot.asset_code == _OFFICIAL_ASSET_CODE
    assert snapshot.security_id == _OFFICIAL_ASSET_CODE
    assert snapshot.start_on == expected_window_start
    assert snapshot.end_on == expected_window_end
    assert snapshot.as_of == snapshot.proof_recorded_at == persisted.recorded_at
    assert snapshot.first_observed_at == proof.first_observed_at
    assert snapshot.source_observed_at == proof.verified_at
    assert snapshot.source_scope_sha256 == proof.coverage_manifest_sha256
    assert policy.start_on == expected_window_start
    assert policy.end_on == expected_window_end
    assert policy.body_store_root == configured_policy.body_store_root
    assert policy.profile_id == configured_policy.profile_id
    assert policy.profile_key == configured_policy.profile_key
    assert policy.profile_version == configured_policy.profile_version
    assert policy.profile_content_hash == configured_policy.profile_content_hash
    assert policy.snapshot_id == configured_policy.snapshot_id
    assert policy.snapshot_content_hash == configured_policy.snapshot_content_hash
    assert policy.policy_content_hash == configured_policy.policy_content_hash
    assert policy.known_at <= policy.effective_at <= policy.read_at <= evidence.checked_at
    assert evidence.calendar_policy_id == calendar.timezone_policy.policy_id
    assert evidence.calendar_policy_sha256 == calendar.timezone_policy.policy_sha256
    assert evidence.exchange_timezone_name == calendar.timezone_policy.timezone_name
    assert evidence.exchange_timezone_name == "Asia/Shanghai"

    assert len(origin_readers) == 1
    assert len(origin_readers[0].calendars) == 3
    assert all(
        item.origin_on == calendar.origin_on
        and item.decision_on == calendar.decision_on
        and item.timezone_policy == calendar.timezone_policy
        for item in origin_readers[0].calendars
    )
    assert len(configured_results) == 3
    assert all(item is not None for item in configured_results)
    configured_values = [item for item in configured_results if item is not None]
    assert len({item.profile_id for item in configured_values}) == 1
    assert len({item.profile_content_hash for item in configured_values}) == 1
    assert len({item.snapshot_id for item in configured_values}) == 1
    assert len({item.snapshot_content_hash for item in configured_values}) == 1
    assert len({item.policy_content_hash for item in configured_values}) == 1
    assert len(snapshot_reader_instances) == 1
    assert len(snapshot_requests) == 3
    assert len(snapshot_results) == 3
    assert all(item is not None and item == snapshot for item in snapshot_results)
    assert all(
        request.asset_code == _OFFICIAL_ASSET_CODE
        and request.security_id == _OFFICIAL_ASSET_CODE
        and request.start_on == expected_window_start
        and request.end_on == expected_window_end
        for request in snapshot_requests
    )
    assert len(trusted_clock.values) == 4
    assert tuple(sorted(trusted_clock.values)) == tuple(trusted_clock.values)
    assert trusted_clock.values[-1] == evidence.checked_at
    output.mkdir(parents=True)
    shutil.copytree(configured_policy.body_store_root / "listing", output / "listing")
    manifest = {
        "scope": asdict(scope),
        "actual_source_transport_mocked": False,
        "synthetic_account_calendar_model_context": True,
        "listing": asdict(listing),
        "coverage_proof": asdict(proof),
        "coverage_recorded_at": persisted.recorded_at.isoformat(),
        "audit_event_id": str(captured.audit.commit.event_id),
        "audit_recorded_at": captured.audit.commit.event.recorded_at.isoformat(),
        "current_scope_evidence": asdict(evidence),
        "reader_calls": {"calendar": 3, "policy": 3, "latest": 3, "trusted_clock": 4},
    }
    (output / "result.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8"
    )
