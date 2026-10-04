"""Unit tests for the production policy parity rehearsal collector."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.data_center.application.full_market_publication_preflight import (
    CHECK_PROVIDER_POLICY_AND_ROUTES,
    FullMarketPublicationPreflightReport,
    PreflightCheckOutcome,
)
from apps.data_center.infrastructure import policy_parity_rehearsal_runner as runner

CANDIDATE = "a" * 40
UNIVERSE = "b" * 64
PROVIDER_DIGEST = "c" * 64
IMAGE_ID = f"sha256:{'d' * 64}"
TRADE_DATE = date(2026, 10, 9)
NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
SETTINGS = {
    "status": "active",
    "default_source": "tushare",
    "enable_failover": True,
    "failover_tolerance": 0.01,
}


def _settings_digest(payload: Any) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _write_settings(tmp_path, payload: object = SETTINGS):
    path = tmp_path / "provider-settings.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _report(status: str = "pass") -> FullMarketPublicationPreflightReport:
    return FullMarketPublicationPreflightReport(
        evaluated_at=NOW,
        checks=(
            PreflightCheckOutcome(
                name=CHECK_PROVIDER_POLICY_AND_ROUTES,
                status=status,
                blocked_codes=(
                    () if status == "pass" else ("MODEL_MARKET_BULK_PREPARATION_REQUIRED",)
                ),
                detail="" if status == "pass" else "blocked",
                evidence=(
                    {
                        "default_source": "tushare",
                        "provider_settings_sha256": _settings_digest(SETTINGS),
                        "preferred_route": "tushare",
                        "probe_asset_count": 2,
                        "route_capabilities": [
                            {
                                "route": "tushare",
                                "batch_preparation": True,
                                "audited_per_asset_fetch": False,
                                "provider_identity": True,
                            }
                        ],
                    }
                    if status == "pass"
                    else {}
                ),
            ),
        ),
    )


@pytest.fixture(autouse=True)
def _image_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGOM_CANDIDATE_IMAGE_ID", IMAGE_ID)


@pytest.fixture
def fake_use_case(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    class _UseCase:
        def __init__(self, report: FullMarketPublicationPreflightReport) -> None:
            self._report = report

        def execute(self, checks=None):
            captured["checks"] = checks
            return self._report

    def factory(**kwargs: Any) -> _UseCase:
        captured.update(kwargs)
        return _UseCase(_report(captured.get("status", "pass")))

    monkeypatch.setattr(runner, "build_full_market_publication_preflight_use_case", factory)
    return captured


def _collect(tmp_path, settings_path=None):
    selected_path = settings_path or _write_settings(tmp_path)
    raw = selected_path.read_bytes()
    payload = json.loads(raw)
    return runner.collect_production_policy_parity(
        candidate_sha=CANDIDATE,
        target_trade_date=TRADE_DATE,
        universe_sha256=UNIVERSE,
        provider_identities_sha256=PROVIDER_DIGEST,
        expected_provider_settings_raw_file_sha256=hashlib.sha256(raw).hexdigest(),
        expected_provider_settings_canonical_payload_sha256=_settings_digest(payload),
        provider_settings_path=selected_path,
        output_dir=tmp_path / "output",
    )


def test_parity_report_binds_snapshot_and_gate_evidence(tmp_path, fake_use_case) -> None:
    payload = _collect(tmp_path)

    assert fake_use_case["provider_settings_override"] == SETTINGS
    assert fake_use_case["checks"] == (CHECK_PROVIDER_POLICY_AND_ROUTES,)
    assert payload["schema"] == runner.POLICY_PARITY_REPORT_SCHEMA
    assert payload["kind"] == runner.POLICY_PARITY_REPORT_KIND
    assert payload["outcome"] == "success"
    assert payload["evidence_mode"] == "production_policy_snapshot"
    assert payload["candidate_image_id"] == IMAGE_ID
    assert payload["candidate_source_attestation"] == "image_release_manifest"
    raw = (tmp_path / "provider-settings.json").read_bytes()
    assert payload["provider_settings_raw_file_sha256"] == hashlib.sha256(raw).hexdigest()
    assert payload["provider_settings_canonical_payload_sha256"] == _settings_digest(SETTINGS)
    assert payload["preflight"]["status"] == "pass"
    artifact = tmp_path / "output" / runner.POLICY_PARITY_REPORT_NAME
    assert json.loads(artifact.read_text(encoding="utf-8"))["provider_settings"] == SETTINGS


def test_blocked_gate_fails_closed_without_artifact(tmp_path, fake_use_case) -> None:
    fake_use_case["status"] = "blocked"

    with pytest.raises(ValueError, match="REHEARSAL_POLICY_PARITY_BLOCKED"):
        _collect(tmp_path)
    assert not (tmp_path / "output").exists()


def test_existing_output_is_rejected(tmp_path, fake_use_case) -> None:
    (tmp_path / "output").mkdir()

    with pytest.raises(ValueError, match="REHEARSAL_POLICY_PARITY_OUTPUT_EXISTS"):
        _collect(tmp_path)


def test_invalid_identity_is_rejected(tmp_path, fake_use_case) -> None:
    settings_path = _write_settings(tmp_path)

    with pytest.raises(ValueError, match="REHEARSAL_POLICY_PARITY_IDENTITY_INVALID"):
        runner.collect_production_policy_parity(
            candidate_sha="not-a-sha",
            target_trade_date=TRADE_DATE,
            universe_sha256=UNIVERSE,
            provider_identities_sha256=PROVIDER_DIGEST,
            expected_provider_settings_raw_file_sha256="1" * 64,
            expected_provider_settings_canonical_payload_sha256="2" * 64,
            provider_settings_path=settings_path,
            output_dir=tmp_path / "output",
        )


def test_missing_image_identity_fails_closed(tmp_path, fake_use_case, monkeypatch) -> None:
    monkeypatch.delenv("AGOM_CANDIDATE_IMAGE_ID")

    with pytest.raises(ValueError, match="REHEARSAL_POLICY_PARITY_IMAGE_IDENTITY_UNAVAILABLE"):
        _collect(tmp_path)


def test_invalid_settings_snapshot_is_rejected(tmp_path, fake_use_case) -> None:
    settings_path = _write_settings(tmp_path, payload=["not", "an", "object"])

    with pytest.raises(ValueError, match="REHEARSAL_POLICY_SETTINGS_INVALID"):
        _collect(tmp_path, settings_path=settings_path)


def test_raw_whitespace_change_preserves_canonical_hash_but_fails_expected_raw_hash(
    tmp_path, fake_use_case
) -> None:
    settings_path = _write_settings(tmp_path)
    startup_raw = settings_path.read_bytes()
    startup_payload = json.loads(startup_raw)
    expected_raw_digest = hashlib.sha256(startup_raw).hexdigest()
    expected_canonical_digest = _settings_digest(startup_payload)
    replacement_raw = (json.dumps(startup_payload, sort_keys=True, indent=2) + "\n").encode()
    assert replacement_raw != startup_raw
    assert _settings_digest(json.loads(replacement_raw)) == expected_canonical_digest
    settings_path.write_bytes(replacement_raw)

    with pytest.raises(ValueError, match="REHEARSAL_POLICY_SETTINGS_MISMATCH"):
        runner.collect_production_policy_parity(
            candidate_sha=CANDIDATE,
            target_trade_date=TRADE_DATE,
            universe_sha256=UNIVERSE,
            provider_identities_sha256=PROVIDER_DIGEST,
            expected_provider_settings_raw_file_sha256=expected_raw_digest,
            expected_provider_settings_canonical_payload_sha256=expected_canonical_digest,
            provider_settings_path=settings_path,
            output_dir=tmp_path / "output",
        )
    assert not (tmp_path / "output").exists()


def test_command_writes_report_and_prints_digest(tmp_path, fake_use_case) -> None:
    settings_path = _write_settings(tmp_path)

    call_command(
        "rehearse_production_policy_parity",
        f"--candidate-sha={CANDIDATE}",
        f"--target-trade-date={TRADE_DATE.isoformat()}",
        f"--universe-sha256={UNIVERSE}",
        f"--provider-identities-sha256={PROVIDER_DIGEST}",
        f"--expected-provider-settings-raw-file-sha256={hashlib.sha256(settings_path.read_bytes()).hexdigest()}",
        f"--expected-provider-settings-canonical-payload-sha256={_settings_digest(SETTINGS)}",
        f"--provider-settings-json={settings_path}",
        f"--output-dir={tmp_path / 'output'}",
    )

    assert (tmp_path / "output" / runner.POLICY_PARITY_REPORT_NAME).is_file()


def test_command_fails_closed_on_invalid_snapshot(tmp_path, fake_use_case) -> None:
    settings_path = _write_settings(tmp_path, payload=["not", "an", "object"])

    with pytest.raises(CommandError, match="REHEARSAL_POLICY_SETTINGS_INVALID"):
        call_command(
            "rehearse_production_policy_parity",
            f"--candidate-sha={CANDIDATE}",
            f"--target-trade-date={TRADE_DATE.isoformat()}",
            f"--universe-sha256={UNIVERSE}",
            f"--provider-identities-sha256={PROVIDER_DIGEST}",
            f"--expected-provider-settings-raw-file-sha256={hashlib.sha256(settings_path.read_bytes()).hexdigest()}",
            f"--expected-provider-settings-canonical-payload-sha256={_settings_digest(['not', 'an', 'object'])}",
            f"--provider-settings-json={settings_path}",
            f"--output-dir={tmp_path / 'output'}",
        )
