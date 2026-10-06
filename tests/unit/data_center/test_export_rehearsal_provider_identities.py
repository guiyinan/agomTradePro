"""Contract tests for adaptive S6 provider identity export."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.data_center.application.full_market_publication_preflight import (
    CHECK_PROVIDER_POLICY_AND_ROUTES,
    FullMarketPublicationPreflightReport,
    PreflightCheckOutcome,
)
from apps.data_center.infrastructure.rehearsal_identity import RehearsalProviderIdentity
from apps.data_center.management.commands import export_rehearsal_provider_identities as command


class _UseCase:
    def __init__(self, capabilities: list[dict[str, object]]) -> None:
        self._capabilities = capabilities

    def execute(self, checks: tuple[str, ...]) -> FullMarketPublicationPreflightReport:
        assert checks == (CHECK_PROVIDER_POLICY_AND_ROUTES,)
        return FullMarketPublicationPreflightReport(
            evaluated_at=datetime(2026, 10, 4, 13, 0, tzinfo=UTC),
            checks=(
                PreflightCheckOutcome(
                    name=CHECK_PROVIDER_POLICY_AND_ROUTES,
                    status="pass",
                    blocked_codes=(),
                    detail="",
                    evidence={"route_capabilities": self._capabilities},
                ),
            ),
        )


def _identity(*, provider_id: int, role: str) -> RehearsalProviderIdentity:
    source = "tencent" if provider_id == 3 else "tushare"
    return RehearsalProviderIdentity(
        role=role,
        provider_id=provider_id,
        source=source,
        version=f"version-{provider_id}",
        endpoint_id=f"provider-config-{provider_id}",
    )


def test_export_includes_each_real_failover_route_once(monkeypatch: pytest.MonkeyPatch) -> None:
    capabilities = [
        {"provider_id": 2, "source_type": "tushare"},
        {"provider_id": 3, "source_type": "akshare"},
        {"provider_id": 3, "source_type": "akshare"},
    ]
    monkeypatch.setattr(
        command,
        "build_full_market_publication_preflight_use_case",
        lambda **_kwargs: _UseCase(capabilities),
    )
    monkeypatch.setattr(command, "configured_rehearsal_identity", _identity)
    monkeypatch.setattr(command, "active_akshare_financial_provider_ids", lambda: (4,))
    monkeypatch.setattr(
        command,
        "configured_akshare_financial_identity",
        lambda *, provider_id: RehearsalProviderIdentity(
            role=f"akshare_financial_route:{provider_id}",
            provider_id=provider_id,
            source="akshare_financial",
            version="akshare-financial-v1-requests-2.32.5",
            endpoint_id=f"akshare-financial-{provider_id}",
        ),
    )

    identities = command.build_rehearsal_provider_identity_snapshot(
        quote_provider_id=2,
        valuation_provider_id=2,
        provider_settings={"status": "active"},
    )

    assert [identity.role for identity in identities] == [
        "quote",
        "valuation",
        "model_market_route:3",
        "akshare_financial_route:4",
    ]
    assert identities[2].source == "tencent"
    assert identities[3].source == "akshare_financial"


def test_command_writes_bounded_snapshot_and_refuses_overwrite(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = tmp_path / "provider-settings.json"
    settings.write_text('{"status":"active"}', encoding="utf-8")
    output = tmp_path / "provider-identities.json"
    identities = (
        _identity(provider_id=2, role="quote"),
        _identity(provider_id=2, role="valuation"),
        _identity(provider_id=3, role="model_market_route:3"),
        RehearsalProviderIdentity(
            "akshare_financial_route:4",
            4,
            "akshare_financial",
            "akshare-financial-v1-requests-2.32.5",
            "akshare-financial-4",
        ),
    )
    monkeypatch.setattr(
        command,
        "build_rehearsal_provider_identity_snapshot",
        lambda **_kwargs: identities,
    )

    call_command(
        "export_rehearsal_provider_identities",
        "--quote-provider-id=2",
        "--valuation-provider-id=2",
        f"--provider-settings-json={settings}",
        f"--output={output}",
    )

    assert len(json.loads(output.read_text(encoding="utf-8"))) == 4
    with pytest.raises(CommandError, match="identity output already exists"):
        call_command(
            "export_rehearsal_provider_identities",
            "--quote-provider-id=2",
            "--valuation-provider-id=2",
            f"--provider-settings-json={settings}",
            f"--output={output}",
        )
