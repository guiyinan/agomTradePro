"""Bounded target interval, stop-line and recovery orchestration tests."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast

import pytest

from scripts import evid09_live_image_preflight as gate
from scripts import evid09_web_only_action as action


def _target_reports(now: datetime) -> tuple[dict[str, object], dict[str, object]]:
    evidence = gate._read_sealed_json(gate.NEWS_EVIDENCE)
    binding = cast(dict[str, object], evidence["new_current_news"])
    rowsets = cast(
        dict[str, dict[str, object]],
        cast(dict[str, object], evidence["read_only_preservation"])["rowsets"],
    )
    preservation = {
        "transaction": "REPEATABLE READ READ ONLY; ROLLBACK",
        "candidate_commit": "891c40c5769897931b2b513e92df6f9ba72631ea",
        "target_commit": "6760c9aa1607c55e9ae0fd0bcb5435ca32080b0b",
        "expected_news_identity": binding,
        "news_current_identity": binding,
        "expected_counts_match": True,
        "four_immutable_authority_root_hashes_match": True,
        "raw_row_values_emitted": False,
        "decision": "PASS_READ_ONLY",
        "news_current_id_hash_and_member_count_match": True,
        "business_dml_performed": False,
        "rows": {
            label: {"count": item["count"], "rowset_sha256": item["sha256"]}
            for label, item in rowsets.items()
        },
        "observed_at_utc": now.isoformat(),
    }
    https = {
        "decision": "PASS_READ_ONLY",
        "base_url": "https://demo.agomtrade.pro",
        "tls_default_trust_used": True,
        "secret_values_emitted": False,
        "decision_gate_cleared": False,
        "https_statuses": gate.REQUIRED_HTTPS_STATUSES,
        "protected_query_authenticated_status": 200,
        "protected_query_unauthenticated_status": 401,
        "retained_up_target": {
            "job": "agomtradepro",
            "instance": "web:8000",
            "value": 1,
            "sample_at_utc": now.isoformat(),
        },
        "observed_at_utc": now.isoformat(),
    }
    return preservation, https


class FakeHandle:
    def __init__(
        self, now: datetime, *, fail_recovery: bool = False, recovery_response: str | None = None
    ) -> None:
        self.now = now
        self.fail_recovery = fail_recovery
        self.recovery_response = recovery_response
        self.recovery_requests = 0
        self.recovered = False

    def first_line(self) -> str:
        """Return one exact target Docker event."""

        return (
            "TARGET_READY image=sha256:f5647b6d4a17c81963a41dd4d66dee70ccfc4b18e881b368db4b89dda7bf86fd "
            f"started_at={self.now.isoformat()} health=healthy fifo=/tmp/evid09-web-recovery-ABC123/recovery.fifo\n"
        )

    def request_recovery(self) -> gate.RemoteResult:
        """Model the exact interactive forward-recovery event."""

        self.recovery_requests += 1
        if self.fail_recovery:
            raise OSError("channel closed")
        if self.recovery_response == "nonzero":
            return gate.RemoteResult(1, "RECOVERY_TRAP_FAILED previous_exit=1\n")
        if self.recovery_response == "missing_event":
            return gate.RemoteResult(0, "PASS: shell exited without a Docker recovery event\n")
        if self.recovery_response == "wrong_image":
            return gate.RemoteResult(
                0,
                "FORWARD_RECOVERED image=sha256:"
                + "0" * 64
                + f" started_at={(self.now + timedelta(seconds=3)).isoformat()} health=healthy\n",
            )
        self.recovered = True
        return _recovery(self.now)


def _recovery(now: datetime) -> gate.RemoteResult:
    recovered_at = (now + timedelta(seconds=3)).isoformat()
    return gate.RemoteResult(
        0,
        "FORWARD_RECOVERED image=sha256:554f816b6dd2a7155742d3260f1df3eab94864de7aec47c0e67ad5d5738c164d "
        f"started_at={recovered_at} health=healthy\nPASS: target Web-only interval and original-image forward recovery\n",
    )


class FakeSession:
    def __init__(
        self,
        now: datetime,
        *,
        bad_https: bool = False,
        fail_recovery: bool = False,
        raw_count: int = 0,
        old_post_up: bool = False,
        stale_preservation: bool = False,
        preservation_drift: str | None = None,
        interval_image_drift: str | None = None,
        recovery_response: str | None = None,
        manual_recovery_failure: bool = False,
        manual_recovery_wrong_image: bool = False,
    ) -> None:
        self.now = now
        self.bad_https = bad_https
        self.raw_count = raw_count
        self.old_post_up = old_post_up
        self.stale_preservation = stale_preservation
        self.preservation_drift = preservation_drift
        self.interval_image_drift = interval_image_drift
        self.handle = FakeHandle(
            now, fail_recovery=fail_recovery, recovery_response=recovery_response
        )
        self.manual_recovery_failure = manual_recovery_failure
        self.manual_recovery_wrong_image = manual_recovery_wrong_image
        self.manual_recovery_requests = 0
        self.begin_requests = 0
        self.transport_refreshes = 0

    def stream(self, command: str, source: str, timeout: int = 120) -> gate.RemoteResult:
        """Return only fake read-only PostgreSQL or HTTPS reports."""

        if "raw-observation-preflight" in source:
            return gate.RemoteResult(
                0 if self.raw_count == 0 else 1,
                json.dumps(
                    {
                        "decision": (
                            "PASS_NO_RAW_SAMPLE"
                            if self.raw_count == 0
                            else "DENY_RAW_SAMPLE_OR_QUERY"
                        ),
                        "authenticated_https_status": 200,
                        "raw_vector_count": self.raw_count,
                        "raw_series_values_or_labels_emitted": False,
                        "secret_values_emitted": False,
                        "observed_at_utc": self.now.isoformat(),
                    }
                ),
            )
        moment = self.now + timedelta(seconds=4 if self.handle.recovered else 2)
        if "web-interval-identity-probe" in source:
            image = (
                "sha256:554f816b6dd2a7155742d3260f1df3eab94864de7aec47c0e67ad5d5738c164d"
                if self.handle.recovered
                else "sha256:f5647b6d4a17c81963a41dd4d66dee70ccfc4b18e881b368db4b89dda7bf86fd"
            )
            if self.interval_image_drift == (
                "post-recovery" if self.handle.recovered else "target-period"
            ):
                image = "sha256:" + "0" * 64
            return gate.RemoteResult(
                0,
                json.dumps(
                    {
                        "schema": "evid09.web-interval-identity.v1",
                        "decision": "PASS_READ_ONLY",
                        "image_id": image,
                        "started_at_utc": (
                            self.now + timedelta(seconds=3) if self.handle.recovered else self.now
                        ).isoformat(),
                        "health": "healthy",
                        "status": "running",
                        "release_manifest_sha256": (
                            "b0b58b749ef1488695bb32e158f5d2ead8d83c90d5c5050e1e69d3f5a88b6bb6"
                            if self.handle.recovered
                            else "b5fcfa71f5635fa95e8d24b4822894e5f4ce4bf0b4c99ee8e3fa5be5cd154167"
                        ),
                        "observed_at_utc": moment.isoformat(),
                        "business_dml_performed": False,
                    }
                ),
            )
        preservation, https = _target_reports(moment)
        if "--expected-news-id" in command:
            if self.stale_preservation and not self.handle.recovered:
                preservation["observed_at_utc"] = (self.now - timedelta(seconds=1)).isoformat()
            if self.preservation_drift and not self.handle.recovered:
                if self.preservation_drift == "root_hash":
                    preservation["four_immutable_authority_root_hashes_match"] = False
                elif self.preservation_drift == "news_hash":
                    cast(dict[str, object], preservation["news_current_identity"])[
                        "publication_hash"
                    ] = ("0" * 64)
                elif self.preservation_drift == "extra_rowset":
                    cast(dict[str, object], preservation["rows"])["unexpected"] = {
                        "count": 0,
                        "rowset_sha256": "0" * 64,
                    }
            return gate.RemoteResult(0, json.dumps(preservation))
        if self.bad_https and not self.handle.recovered:
            https["protected_query_authenticated_status"] = 401
        if self.old_post_up and self.handle.recovered:
            cast(dict[str, object], https["retained_up_target"])["sample_at_utc"] = (
                self.now + timedelta(seconds=2)
            ).isoformat()
        return gate.RemoteResult(0, json.dumps(https))

    def begin_interval(self, source: str, preflight_digest: str) -> FakeHandle:
        """Record that a source-bound digest was supplied before target start."""

        assert source.startswith("#!/usr/bin/env bash")
        assert len(preflight_digest) == 64
        self.begin_requests += 1
        return self.handle

    def manual_recover(self, source: str) -> gate.RemoteResult:
        """Model the independent recovery mode after a channel failure."""

        self.manual_recovery_requests += 1
        if self.manual_recovery_failure:
            return gate.RemoteResult(1, "DENY: independent recovery did not verify current Web\n")
        if self.manual_recovery_wrong_image:
            return gate.RemoteResult(
                0,
                "FORWARD_RECOVERED image=sha256:"
                + "0" * 64
                + f" started_at={(self.now + timedelta(seconds=3)).isoformat()} health=healthy\n",
            )
        self.handle.recovered = True
        return _recovery(self.now)

    def refresh_transport(self) -> None:
        """Record the production transport-refresh boundary."""

        self.transport_refreshes += 1


def _preflight(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        gate,
        "collect_preflight",
        lambda session: {
            "decision": "PASS_PRE_ACTION_ONLY",
            "production_commit": "891c40c5769897931b2b513e92df6f9ba72631ea",
            "target_commit": "6760c9aa1607c55e9ae0fd0bcb5435ca32080b0b",
        },
    )


def test_exact_target_period_recovers_original_and_marks_tui_reset_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _preflight(monkeypatch)
    session = FakeSession(datetime.now(UTC))

    report = action.exercise_once(session, accept_interruption=True, accept_tui_reset=True)

    assert session.begin_requests == 1
    assert session.handle.recovery_requests == 1
    assert session.manual_recovery_requests == 0
    assert session.transport_refreshes == 1
    assert report["decision"] == "LIVE_WEB_ONLY_RECOVERED_TUI_RESET_PENDING"
    assert report["post_recovery_stop_lines"]["all_eight_rowset_sha256_match"] is True
    assert report["tui02_candidate_reset_required"] is True
    assert report["tui02_candidate_reset_performed"] is False


def test_post_action_preflight_gets_one_bounded_retry_after_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def transient_post(session: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise gate.LiveImagePreflightError("retained scrape race")
        return {
            "decision": "PASS_PRE_ACTION_ONLY",
            "production_commit": "891c40c5769897931b2b513e92df6f9ba72631ea",
            "target_commit": "6760c9aa1607c55e9ae0fd0bcb5435ca32080b0b",
        }

    monkeypatch.setattr(gate, "collect_preflight", transient_post)
    monkeypatch.setattr(action.time, "sleep", lambda seconds: None)

    report = action.exercise_once(
        FakeSession(datetime.now(UTC)),
        accept_interruption=True,
        accept_tui_reset=True,
    )

    assert calls == 3
    assert report["decision"] == "LIVE_WEB_ONLY_RECOVERED_TUI_RESET_PENDING"


def test_target_https_failure_still_sends_forward_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _preflight(monkeypatch)
    session = FakeSession(datetime.now(UTC), bad_https=True)

    with pytest.raises(action.RecoveredIntervalDenied, match="target-period") as caught:
        action.exercise_once(session, accept_interruption=True, accept_tui_reset=True)
    assert session.handle.recovery_requests == 1
    assert "protected HTTPS" in str(caught.value.__cause__)
    assert caught.value.report["decision"] == "DENY_TARGET_PERIOD_RECOVERED_CURRENT"
    assert caught.value.report["target_failure_type"] == "WebOnlyActionError"
    assert "protected HTTPS" in caught.value.report["target_failure_reason"]
    assert caught.value.report["post_recovery_stop_lines"]["all_eight_rowset_sha256_match"] is True


def test_channel_failure_uses_independent_manual_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _preflight(monkeypatch)
    session = FakeSession(datetime.now(UTC), fail_recovery=True)

    report = action.exercise_once(session, accept_interruption=True, accept_tui_reset=True)

    assert report["forward_recovered_web"]["image_id"].startswith("sha256:554f816b")
    assert session.manual_recovery_requests == 1


@pytest.mark.parametrize("response", ["nonzero", "missing_event", "wrong_image"])
def test_unverified_interactive_recovery_always_tries_independent_manual_entry(
    monkeypatch: pytest.MonkeyPatch, response: str
) -> None:
    _preflight(monkeypatch)
    session = FakeSession(datetime.now(UTC), recovery_response=response)

    report = action.exercise_once(session, accept_interruption=True, accept_tui_reset=True)

    assert session.handle.recovery_requests == 1
    assert session.manual_recovery_requests == 1
    assert report["recovery_path"] == "independent_manual"
    assert report["post_recovery_stop_lines"]["all_eight_rowset_sha256_match"] is True


@pytest.mark.parametrize("manual_failure", ["nonzero", "wrong_image"])
def test_both_recovery_paths_unverified_remains_deny(
    monkeypatch: pytest.MonkeyPatch, manual_failure: str
) -> None:
    _preflight(monkeypatch)
    session = FakeSession(
        datetime.now(UTC),
        recovery_response="nonzero",
        manual_recovery_failure=manual_failure == "nonzero",
        manual_recovery_wrong_image=manual_failure == "wrong_image",
    )

    with pytest.raises(action.WebOnlyActionError, match="forward recovery"):
        action.exercise_once(session, accept_interruption=True, accept_tui_reset=True)
    assert session.handle.recovery_requests == 1
    assert session.manual_recovery_requests == 1


def test_target_failure_and_interactive_failure_reports_only_verified_manual_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _preflight(monkeypatch)
    session = FakeSession(datetime.now(UTC), bad_https=True, recovery_response="nonzero")

    with pytest.raises(action.RecoveredIntervalDenied) as caught:
        action.exercise_once(session, accept_interruption=True, accept_tui_reset=True)
    assert caught.value.report["decision"] == "DENY_TARGET_PERIOD_RECOVERED_CURRENT"
    assert caught.value.report["recovery_path"] == "independent_manual"
    assert session.manual_recovery_requests == 1


def test_no_acceptance_means_no_interval_even_if_sources_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _preflight(monkeypatch)
    session = FakeSession(datetime.now(UTC))

    with pytest.raises(action.WebOnlyActionError, match="must be accepted"):
        action.exercise_once(session, accept_interruption=True, accept_tui_reset=False)
    assert session.begin_requests == 0


def test_existing_tui_raw_sample_denies_before_web_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _preflight(monkeypatch)
    session = FakeSession(datetime.now(UTC), raw_count=4)

    with pytest.raises(action.WebOnlyActionError, match="active TUI-02 raw observation"):
        action.exercise_once(
            session,
            accept_interruption=True,
            accept_tui_reset=True,
            accept_active_tui_observation_invalidation=False,
        )
    assert session.begin_requests == 0
    assert session.handle.recovery_requests == 0


def test_authorized_existing_tui_raw_sample_is_bound_before_web_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _preflight(monkeypatch)
    session = FakeSession(datetime.now(UTC), raw_count=4)

    report = action.exercise_once(
        session,
        accept_interruption=True,
        accept_tui_reset=True,
        accept_active_tui_observation_invalidation=True,
    )

    invalidated = cast(dict[str, object], report["invalidated_tui02_observation"])
    assert invalidated["raw_vector_count"] == 4
    assert invalidated["active_observation_invalidation_accepted"] is True
    assert invalidated["checkpoint_sha256"] == action.TUI_CHECKPOINT_SHA256


def test_recovery_period_rejects_up_sample_from_target_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _preflight(monkeypatch)
    session = FakeSession(datetime.now(UTC), old_post_up=True)

    with pytest.raises(action.WebOnlyActionError, match="post-recovery"):
        action.exercise_once(session, accept_interruption=True, accept_tui_reset=True)
    assert session.handle.recovery_requests == 1


@pytest.mark.parametrize("period", ["target-period", "post-recovery"])
def test_period_denies_if_docker_web_image_changes_during_stop_line_collection(
    monkeypatch: pytest.MonkeyPatch, period: str
) -> None:
    _preflight(monkeypatch)
    session = FakeSession(datetime.now(UTC), interval_image_drift=period)

    expected = (
        action.RecoveredIntervalDenied if period == "target-period" else action.WebOnlyActionError
    )
    with pytest.raises(expected, match=period):
        action.exercise_once(session, accept_interruption=True, accept_tui_reset=True)
    assert session.handle.recovery_requests == 1


def test_target_period_rejects_preservation_before_web_start_but_recovers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _preflight(monkeypatch)
    session = FakeSession(datetime.now(UTC), stale_preservation=True)

    with pytest.raises(action.RecoveredIntervalDenied, match="target-period") as caught:
        action.exercise_once(session, accept_interruption=True, accept_tui_reset=True)
    assert session.handle.recovery_requests == 1
    assert caught.value.report["target_stop_lines_verified"] is False


@pytest.mark.parametrize("drift", ["root_hash", "news_hash", "extra_rowset"])
def test_target_period_identity_drift_is_denied_after_verified_recovery(
    monkeypatch: pytest.MonkeyPatch, drift: str
) -> None:
    _preflight(monkeypatch)
    session = FakeSession(datetime.now(UTC), preservation_drift=drift)

    with pytest.raises(action.RecoveredIntervalDenied) as caught:
        action.exercise_once(session, accept_interruption=True, accept_tui_reset=True)
    assert session.handle.recovery_requests == 1
    assert caught.value.report["decision"] == "DENY_TARGET_PERIOD_RECOVERED_CURRENT"


def test_operator_exit_one_still_emits_verified_recovery_checkpoint(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class Client:
        def load_host_keys(self, path: str) -> None:
            return None

        def set_missing_host_key_policy(self, policy: object) -> None:
            return None

        def connect(self, host: str, **kwargs: object) -> None:
            return None

        def close(self) -> None:
            return None

    fake_paramiko = SimpleNamespace(SSHClient=Client, RejectPolicy=object)
    monkeypatch.setattr(action.importlib, "import_module", lambda name: fake_paramiko)

    def denied(session: object, **kwargs: object) -> dict[str, object]:
        raise action.RecoveredIntervalDenied({"decision": "DENY_TARGET_PERIOD_RECOVERED_CURRENT"})

    monkeypatch.setattr(action, "exercise_once", denied)
    monkeypatch.setattr(sys, "argv", ["evid09_web_only_action.py", "--exercise"])
    for name in ("AGOM_VPS_HOST", "AGOM_VPS_PORT", "AGOM_VPS_USER", "AGOM_VPS_PASS"):
        monkeypatch.setenv(name, "1" if name == "AGOM_VPS_PORT" else "test")

    assert action.main() == 1
    assert json.loads(capsys.readouterr().out)["decision"] == "DENY_TARGET_PERIOD_RECOVERED_CURRENT"


def test_recovery_event_before_target_start_cannot_claim_recovered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _preflight(monkeypatch)
    session = FakeSession(datetime.now(UTC))
    earlier = (session.now - timedelta(seconds=1)).isoformat()
    session.handle.request_recovery = lambda: gate.RemoteResult(
        0,
        "FORWARD_RECOVERED image=sha256:554f816b6dd2a7155742d3260f1df3eab94864de7aec47c0e67ad5d5738c164d "
        f"started_at={earlier} health=healthy\n",
    )

    with pytest.raises(action.WebOnlyActionError, match="did not start after"):
        action.exercise_once(session, accept_interruption=True, accept_tui_reset=True)
