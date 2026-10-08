"""JSON and management-command contracts for reviewed scope-discovery approvals."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone

from apps.data_center.application.financial_scope_discovery_governance import (
    parse_financial_scope_discovery_authorization,
)
from apps.data_center.domain.financial_scope_discovery import (
    FinancialScopeDiscoveryAuthorization,
    FinancialScopeDiscoveryBinding,
    FinancialScopeDiscoveryError,
)
from apps.data_center.infrastructure import financial_scope_discovery_reader as reader_module
from apps.data_center.infrastructure.models import (
    FinancialCapacityGovernanceRecordModel,
    FinancialCapacityOwnerApprovalEventModel,
)
from apps.data_center.infrastructure.rehearsal_identity import RehearsalProviderIdentity


def _authorization_payload(
    *, candidate_sha: str, recorded_by: str, approved_at: datetime, expires_at: datetime
) -> dict[str, object]:
    """Build the exact externally reviewed JSON shape consumed by the commands."""

    return {
        "schema_version": "data-center.financial-scope-discovery-authorization.v1",
        "approval_id": "review:financial-scope-discovery:unit-test",
        "approved_by": "owner-financial-data",
        "recorded_by": recorded_by,
        "event_id": "owner-event:financial-scope-discovery-unit-test",
        "approved_at": approved_at.isoformat(),
        "approval_receipt_sha256": "b" * 64,
        "expires_at": expires_at.isoformat(),
        "approved": True,
        "binding": {
            "candidate_sha": candidate_sha,
            "provider_id": 19,
            "provider_name": "akshare",
            "provider_identity_sha256": "c" * 64,
            "contract_id": "akshare.financial-scope.latest-notice",
            "contract_version": "2026-10-09.v1",
            "contract_sha256": "d" * 64,
            "parser_id": "akshare-financial-scope-parser.v1",
            "parser_sha256": "e" * 64,
            "deployment_region": "isolated-test",
        },
        "universe": {"asset_count": 1, "sha256": "f" * 64},
        "budget": {
            "maximum_logical_requests": 2,
            "maximum_physical_attempts": 4,
            "maximum_rows_per_asset": 200,
        },
    }


def _write_build_identity(path: Path, candidate_sha: str) -> None:
    """Write the runtime identity file required by the management commands."""

    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "app_version": "3.4.0",
                "source_commit": candidate_sha,
            }
        ),
        encoding="utf-8",
    )


def test_parser_accepts_complete_json_authorization() -> None:
    """Recorded-by and event identities required by typed authorization parse successfully."""

    approved_at = datetime(2026, 10, 9, 1, tzinfo=UTC)
    payload = _authorization_payload(
        candidate_sha="a" * 40,
        recorded_by="scope-reviewer",
        approved_at=approved_at,
        expires_at=approved_at + timedelta(hours=4),
    )
    decoded: object = json.loads(json.dumps(payload))

    parsed = parse_financial_scope_discovery_authorization(decoded)

    assert isinstance(parsed, FinancialScopeDiscoveryAuthorization)
    assert parsed.recorded_by == "scope-reviewer"
    assert parsed.event_id == "owner-event:financial-scope-discovery-unit-test"
    assert parsed.maximum_physical_attempts == 4


def test_parser_rejects_json_missing_required_owner_event_identity() -> None:
    """The repaired parser still rejects records missing required approval evidence."""

    approved_at = datetime(2026, 10, 9, 1, tzinfo=UTC)
    payload = _authorization_payload(
        candidate_sha="a" * 40,
        recorded_by="scope-reviewer",
        approved_at=approved_at,
        expires_at=approved_at + timedelta(hours=4),
    )
    payload.pop("event_id")

    with pytest.raises(FinancialScopeDiscoveryError):
        parse_financial_scope_discovery_authorization(json.loads(json.dumps(payload)))


@pytest.mark.django_db
def test_scope_discovery_json_flows_through_record_and_owner_commands(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both governance commands parse the reviewed JSON and persist its exact identities."""

    user_model = get_user_model()
    recorder = user_model._default_manager.create_user(
        **{user_model.USERNAME_FIELD: "scope-recorder"},
        password="recorder-password",
        is_superuser=True,
    )
    owner = user_model._default_manager.create_user(
        **{user_model.USERNAME_FIELD: "owner-financial-data"},
        password="owner-password",
        is_superuser=True,
    )
    candidate_sha = "a" * 40
    now = timezone.now()
    payload = _authorization_payload(
        candidate_sha=candidate_sha,
        recorded_by=recorder.get_username(),
        approved_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=4),
    )
    approval_path = tmp_path / "scope-discovery-approval.json"
    approval_path.write_text(json.dumps(payload), encoding="utf-8")
    identity_path = tmp_path / ".agom-build-identity.json"
    _write_build_identity(identity_path, candidate_sha)
    monkeypatch.setattr(
        "apps.data_center.management.commands.record_financial_capacity_governance.getpass",
        lambda _prompt: "recorder-password",
    )

    with override_settings(AGOM_BUILD_IDENTITY_PATH=identity_path):
        call_command(
            "record_financial_capacity_governance",
            record_file=approval_path,
            stage="scope_discovery",
            actor=recorder.get_username(),
        )

    record = FinancialCapacityGovernanceRecordModel._default_manager.get(
        approval_id=payload["approval_id"]
    )
    assert record.stage == "scope_discovery"
    assert record.record == payload
    assert record.created_by == recorder.get_username()
    assert not FinancialCapacityOwnerApprovalEventModel._default_manager.filter(
        governance_record=record
    ).exists()

    monkeypatch.setattr(
        "apps.data_center.management.commands.approve_financial_capacity_governance.getpass",
        lambda _prompt: "owner-password",
    )
    with override_settings(AGOM_BUILD_IDENTITY_PATH=identity_path):
        call_command(
            "approve_financial_capacity_governance",
            approval_id=record.approval_id,
            owner=owner.get_username(),
        )

    owner_event = FinancialCapacityOwnerApprovalEventModel._default_manager.get(
        governance_record=record
    )
    assert owner_event.event_id == payload["event_id"]
    assert owner_event.approved_by == owner.get_username()
    assert owner_event.approval_receipt_sha256 == payload["approval_receipt_sha256"]


def test_scope_discovery_reader_uses_the_shared_exact_route_preflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Scope discovery delegates its route gate to the AKShare rehearsal validator."""

    provider = SimpleNamespace(id=19, source_type="akshare", is_active=True)
    identity = RehearsalProviderIdentity(
        role="akshare_financial_route:19",
        provider_id=19,
        source="akshare_financial",
        version="fixture-v1",
        endpoint_id="fixture-endpoint",
    )
    identity_sha256 = hashlib.sha256(
        json.dumps(
            {
                "role": identity.role,
                "provider_id": identity.provider_id,
                "source": identity.source,
                "version": identity.version,
                "endpoint_id": identity.endpoint_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    monkeypatch.setattr(
        reader_module,
        "configured_akshare_financial_identity",
        lambda *, provider_id: identity,
    )
    monkeypatch.setattr(
        reader_module,
        "_load_scope_discovery_contract",
        lambda: {
            "contract_id": "akshare.financial-scope.latest-notice",
            "contract_version": "2026-10-09.v1",
            "contract_sha256": "d" * 64,
        },
    )
    route_calls: list[tuple[object, str | None]] = []
    monkeypatch.setattr(
        reader_module,
        "require_akshare_financial_egress_routes",
        lambda route_provider, *, deployment_region=None: route_calls.append(
            (route_provider, deployment_region)
        ),
    )
    discovery_reader = object.__new__(reader_module.AkshareFinancialScopeDiscoveryReader)
    discovery_reader._provider = provider
    discovery_reader._deployment_region = "isolated-test"
    discovery_reader._candidate_sha = "a" * 40
    binding = FinancialScopeDiscoveryBinding(
        candidate_sha="a" * 40,
        provider_id=19,
        provider_name="akshare",
        provider_identity_sha256=identity_sha256,
        contract_id="akshare.financial-scope.latest-notice",
        contract_version="2026-10-09.v1",
        contract_sha256="d" * 64,
        parser_id="akshare-financial-scope-parser.v1",
        parser_sha256=reader_module.financial_scope_discovery_parser_sha256(),
        deployment_region="isolated-test",
    )

    discovery_reader.preflight(binding=binding)

    assert route_calls == [(provider, "isolated-test")]


def test_scope_discovery_reader_maps_route_preflight_failure_to_stable_blocker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing route repository blocks discovery before provider access."""

    provider = SimpleNamespace(id=19, source_type="akshare", is_active=True)
    identity = RehearsalProviderIdentity(
        role="akshare_financial_route:19",
        provider_id=19,
        source="akshare_financial",
        version="fixture-v1",
        endpoint_id="fixture-endpoint",
    )
    identity_sha256 = hashlib.sha256(
        json.dumps(
            {
                "role": identity.role,
                "provider_id": identity.provider_id,
                "source": identity.source,
                "version": identity.version,
                "endpoint_id": identity.endpoint_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    monkeypatch.setattr(
        reader_module,
        "configured_akshare_financial_identity",
        lambda *, provider_id: identity,
    )
    monkeypatch.setattr(
        reader_module,
        "_load_scope_discovery_contract",
        lambda: {
            "contract_id": "akshare.financial-scope.latest-notice",
            "contract_version": "2026-10-09.v1",
            "contract_sha256": "d" * 64,
        },
    )
    monkeypatch.setattr(
        reader_module,
        "require_akshare_financial_egress_routes",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("unconfigured")),
    )
    discovery_reader = object.__new__(reader_module.AkshareFinancialScopeDiscoveryReader)
    discovery_reader._provider = provider
    discovery_reader._deployment_region = "isolated-test"
    discovery_reader._candidate_sha = "a" * 40
    binding = FinancialScopeDiscoveryBinding(
        candidate_sha="a" * 40,
        provider_id=19,
        provider_name="akshare",
        provider_identity_sha256=identity_sha256,
        contract_id="akshare.financial-scope.latest-notice",
        contract_version="2026-10-09.v1",
        contract_sha256="d" * 64,
        parser_id="akshare-financial-scope-parser.v1",
        parser_sha256=reader_module.financial_scope_discovery_parser_sha256(),
        deployment_region="isolated-test",
    )

    with pytest.raises(FinancialScopeDiscoveryError) as caught:
        discovery_reader.preflight(binding=binding)

    assert caught.value.code == "FINANCIAL_SCOPE_DISCOVERY_EGRESS_ROUTE_REQUIRED"
