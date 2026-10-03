"""Unit tests for the read-only full-market publication preflight."""

from __future__ import annotations

import io
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.data_center.application.current_publication_candidate import (
    CurrentPublicationPreview,
)
from apps.data_center.application.full_market_publication_preflight import (
    CURRENT_PUBLICATION_PREVIEW_FAILED,
    PREFLIGHT_AUTHORITY_CAPTURE_UNAVAILABLE,
    PREFLIGHT_MODEL_MARKET_ROUTES_UNAVAILABLE,
    PREFLIGHT_PROVIDER_SETTINGS_BLOCKED,
    PREFLIGHT_PUBLICATION_BUNDLE_UNAVAILABLE,
    PREFLIGHT_PUBLICATION_POLICY_MISSING,
    PREFLIGHT_PUBLICATION_POLICY_NOT_VERSIONED,
    PREFLIGHT_PUBLICATION_POLICY_UNAVAILABLE,
    PREFLIGHT_PUBLICATION_REBUILDERS_INCOMPLETE,
    PREFLIGHT_PUBLICATION_UNIVERSE_UNAVAILABLE,
    PREFLIGHT_TASK_ATTEMPT_IDENTITY_UNAVAILABLE,
    AuthorityCaptureProbeEvidence,
    FullMarketPublicationPreflightPorts,
    RunFullMarketPublicationPreflightUseCase,
    TaskAttemptIdentityProbeEvidence,
)
from apps.data_center.application.model_market_data import (
    ModelMarketDataService,
    ModelMarketRoute,
)
from apps.data_center.application.model_market_data_preparation import (
    evaluate_model_market_bulk_preparation,
)
from apps.data_center.domain.raw_audit_manifest import CURRENT_MARKET_PUBLICATION_DATASETS
from core.exceptions import ConfigurationError
from core.integration.data_center_audit import SystemAuditCompositionUnavailable

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)
DATASETS = tuple(sorted(CURRENT_MARKET_PUBLICATION_DATASETS))


class _BatchCapablePort:
    """Provider port with audited batch preparation capability."""

    def prepare_stock_history(self, asset_codes, start_date, end_date):
        return None

    def has_prepared_model_history(self, asset_code, start_date, end_date):
        return True

    def drain_model_history_prepared_fetches(self):
        return ()

    def stock_history(self, asset_code, start_date, end_date):
        return ()


class _ReadOnlyPort:
    """Provider port without any audited preparation capability."""

    def stock_history(self, asset_code, start_date, end_date):
        return ()


def _service_with_routes(
    routes: tuple[ModelMarketRoute, ...],
    *,
    per_asset_limit: int | None = None,
) -> ModelMarketDataService:
    return ModelMarketDataService(
        routes,
        enable_failover=True,
        tolerance=0.01,
        reference_history=lambda *_: (),
        max_per_asset_preparation_assets=per_asset_limit,
    )


def _batch_service() -> ModelMarketDataService:
    return _service_with_routes(
        (
            ModelMarketRoute(
                "vendor",
                _BatchCapablePort(),
                source_type="tushare",
                provider_id=17,
            ),
        )
    )


@dataclass(frozen=True)
class _FakePolicy:
    dataset_key: str
    policy_version: str = "p2"
    minimum_coverage_ratio: float = 0.99
    allow_partial: bool = False

    @property
    def uses_versioned_evidence(self) -> bool:
        return self.policy_version != "legacy"

    @property
    def identity(self) -> str:
        return f"p2:{self.policy_version}:hash"


class _FakePolicyRepository:
    def __init__(self, policies: dict[str, _FakePolicy | None], *, raises: bool = False) -> None:
        self._policies = policies
        self._raises = raises

    def get_active(self, dataset_key: str) -> _FakePolicy | None:
        if self._raises:
            raise RuntimeError("policy store unavailable")
        return self._policies.get(dataset_key)


def _preview(dataset_key: str) -> CurrentPublicationPreview:
    return CurrentPublicationPreview(
        dataset_key=dataset_key,
        requested_asset_count=2,
        covered_asset_count=2,
        member_count=2,
        missing_asset_codes=(),
        unexpected_asset_codes=(),
        oldest_observed_at=NOW,
        newest_observed_at=NOW,
    )


@dataclass(frozen=True)
class _FakeDataset:
    dataset_key: str


@dataclass(frozen=True)
class _FakeRebuilder:
    dataset: _FakeDataset


class _FakePreviewer:
    def __init__(
        self,
        dataset_keys: tuple[str, ...] = DATASETS,
        *,
        preview_error: Exception | None = None,
    ) -> None:
        self.rebuilders = tuple(_FakeRebuilder(_FakeDataset(key)) for key in dataset_keys)
        self._preview_error = preview_error

    def preview(self, *, asset_codes, published_at):
        if self._preview_error is not None:
            raise self._preview_error
        return type(
            "Preview",
            (),
            {"datasets": tuple(_preview(key) for key in DATASETS)},
        )()


class _FakeBundle:
    def __init__(
        self,
        previewer: _FakePreviewer | None = None,
        *,
        database_alias: str = "default",
    ) -> None:
        self.database_alias = database_alias
        self.previewer = previewer or _FakePreviewer()

    def authority_capture(self, *, as_of, preflight_context):
        raise AssertionError("preflight must never capture an authority fence")


def _authority_evidence() -> AuthorityCaptureProbeEvidence:
    return AuthorityCaptureProbeEvidence(
        environment="production",
        mode="required",
        scope_schema="account.owner_tenant_authority.v3",
        snapshot_id="snapshot-1",
    )


def _attempt_evidence() -> TaskAttemptIdentityProbeEvidence:
    return TaskAttemptIdentityProbeEvidence(
        repository="DjangoTaskRecordRepository",
        resolution="expected_unavailable_outside_task",
    )


def _ports(
    *,
    settings: dict[str, Any] | None = None,
    service: ModelMarketDataService | None = None,
    bundle: _FakeBundle | None = None,
    policies: dict[str, _FakePolicy | None] | None = None,
    universe: tuple[str, ...] = ("000001.SZ", "600000.SH"),
    authority_probe: Any = None,
    attempt_probe: Any = None,
    settings_loader: Any = None,
    service_builder: Any = None,
    bundle_builder: Any = None,
    policy_repository: Any = None,
) -> FullMarketPublicationPreflightPorts:
    active_settings = settings or {
        "status": "active",
        "default_source": "tushare",
        "enable_failover": True,
        "failover_tolerance": 0.01,
    }
    active_policies = (
        policies
        if policies is not None
        else {key: _FakePolicy(dataset_key=key) for key in DATASETS}
    )
    return FullMarketPublicationPreflightPorts(
        load_provider_settings=settings_loader or (lambda: active_settings),
        build_model_market_service=service_builder
        or (lambda _settings: service or _batch_service()),
        build_publication_bundle=bundle_builder or (lambda: bundle or _FakeBundle()),
        publication_policies=policy_repository or _FakePolicyRepository(active_policies),
        load_active_universe=lambda: universe,
        probe_authority_capture=authority_probe or _authority_evidence,
        probe_task_attempt_identity=attempt_probe or _attempt_evidence,
        clock=lambda: NOW,
    )


def _run(ports: FullMarketPublicationPreflightPorts):
    return RunFullMarketPublicationPreflightUseCase(ports).execute()


def _check(report, name: str):
    return next(check for check in report.checks if check.name == name)


def test_all_checks_pass():
    report = _run(_ports())

    assert report.outcome == "pass"
    assert report.blocked_codes == ()
    provider_check = _check(report, "provider_policy_and_routes")
    assert provider_check.status == "pass"
    capabilities = provider_check.evidence["route_capabilities"]
    assert capabilities == [
        {
            "route": "vendor",
            "batch_preparation": True,
            "audited_per_asset_fetch": False,
            "provider_identity": True,
        }
    ]
    gates_check = _check(report, "current_publication_gates")
    assert gates_check.status == "pass"
    assert gates_check.evidence["universe_asset_count"] == 2
    assert set(gates_check.evidence["preview"]) == set(DATASETS)
    assert _check(report, "account_authority_capture").status == "pass"
    assert _check(report, "task_attempt_identity").status == "pass"
    payload = report.to_dict()
    assert payload["schema"] == "data_center.full_market_publication_preflight.v1"
    json.dumps(payload, allow_nan=False)


def test_shared_gate_matches_preparation_rule_for_batch_route():
    service = _batch_service()
    gate = evaluate_model_market_bulk_preparation(
        routes=service.configured_routes,
        requested_count=5001,
        max_per_asset_preparation_assets=service.max_per_asset_preparation_assets,
    )
    assert gate.preferred_route_is_batch
    assert gate.preferred_route == "vendor"


def test_blocked_provider_settings_payload():
    report = _run(
        _ports(
            settings={
                "status": "blocked",
                "blocked_reason": "provider_runtime_default_source_missing",
            }
        )
    )

    check = _check(report, "provider_policy_and_routes")
    assert check.status == "blocked"
    assert check.blocked_codes == (PREFLIGHT_PROVIDER_SETTINGS_BLOCKED,)
    assert check.detail == "provider_runtime_default_source_missing"
    assert report.outcome == "blocked"


def test_model_market_config_unavailable_is_reused():
    def _builder(_settings):
        raise ConfigurationError("no routes", code="MODEL_MARKET_CONFIG_UNAVAILABLE")

    report = _run(_ports(service_builder=_builder))

    check = _check(report, "provider_policy_and_routes")
    assert check.blocked_codes == ("MODEL_MARKET_CONFIG_UNAVAILABLE",)


def test_model_market_builder_unexpected_error():
    def _builder(_settings):
        raise RuntimeError("boom")

    report = _run(_ports(service_builder=_builder))

    check = _check(report, "provider_policy_and_routes")
    assert check.blocked_codes == (PREFLIGHT_MODEL_MARKET_ROUTES_UNAVAILABLE,)
    assert check.detail == "RuntimeError"


def test_bulk_preparation_required_is_reused():
    service = _service_with_routes(
        (
            ModelMarketRoute(
                "akshare-primary",
                _ReadOnlyPort(),
                source_type="akshare",
                provider_id=17,
            ),
        )
    )

    report = _run(_ports(service=service))

    check = _check(report, "provider_policy_and_routes")
    assert check.blocked_codes == ("MODEL_MARKET_BULK_PREPARATION_REQUIRED",)


def test_bulk_preparation_required_above_per_asset_limit():
    service = _service_with_routes(
        (
            ModelMarketRoute(
                "per-asset",
                _ReadOnlyPort(),
                source_type="akshare",
                provider_id=17,
            ),
        ),
        per_asset_limit=50,
    )

    report = _run(_ports(service=service))

    check = _check(report, "provider_policy_and_routes")
    # The probe scope is limit + 1, so a per-asset-only route blocks full market.
    assert check.blocked_codes == ("MODEL_MARKET_BULK_PREPARATION_REQUIRED",)


def test_batch_route_without_provider_identity_is_blocked():
    service = _service_with_routes(
        (
            ModelMarketRoute(
                "vendor",
                _BatchCapablePort(),
                source_type="tushare",
                provider_id=None,
            ),
        )
    )

    report = _run(_ports(service=service))

    check = _check(report, "provider_policy_and_routes")
    assert check.blocked_codes == ("MODEL_MARKET_AUDIT_PROVIDER_ID_MISSING",)


def test_publication_bundle_composition_unavailable():
    def _builder():
        raise SystemAuditCompositionUnavailable(
            "bundle unavailable", reason_code="composition_alias_mismatch"
        )

    report = _run(_ports(bundle_builder=_builder))

    gates = _check(report, "current_publication_gates")
    assert gates.blocked_codes == (PREFLIGHT_PUBLICATION_BUNDLE_UNAVAILABLE,)
    assert gates.detail == "composition_alias_mismatch"
    authority = _check(report, "account_authority_capture")
    assert authority.blocked_codes == (PREFLIGHT_AUTHORITY_CAPTURE_UNAVAILABLE,)


def test_publication_rebuilders_incomplete():
    bundle = _FakeBundle(_FakePreviewer(dataset_keys=("equity.quote.snapshot",)))

    report = _run(_ports(bundle=bundle))

    check = _check(report, "current_publication_gates")
    assert check.blocked_codes == (PREFLIGHT_PUBLICATION_REBUILDERS_INCOMPLETE,)


def test_publication_policy_missing():
    policies = {key: _FakePolicy(dataset_key=key) for key in DATASETS}
    policies["equity.price.bar"] = None

    report = _run(_ports(policies=policies))

    check = _check(report, "current_publication_gates")
    assert check.blocked_codes == (PREFLIGHT_PUBLICATION_POLICY_MISSING,)
    assert "equity.price.bar" in check.evidence["policies"]


def test_publication_policy_not_versioned():
    policies = {key: _FakePolicy(dataset_key=key) for key in DATASETS}
    policies["equity.valuation.fact"] = _FakePolicy(
        dataset_key="equity.valuation.fact", policy_version="legacy"
    )

    report = _run(_ports(policies=policies))

    check = _check(report, "current_publication_gates")
    assert check.blocked_codes == (PREFLIGHT_PUBLICATION_POLICY_NOT_VERSIONED,)


def test_publication_policy_read_failure():
    report = _run(_ports(policy_repository=_FakePolicyRepository({}, raises=True)))

    check = _check(report, "current_publication_gates")
    assert check.blocked_codes == (PREFLIGHT_PUBLICATION_POLICY_UNAVAILABLE,)


def test_publication_universe_unavailable():
    report = _run(_ports(universe=()))

    check = _check(report, "current_publication_gates")
    assert check.blocked_codes == (PREFLIGHT_PUBLICATION_UNIVERSE_UNAVAILABLE,)
    assert check.detail == "active_universe_empty"


def test_publication_preview_failure_reuses_production_code():
    bundle = _FakeBundle(_FakePreviewer(preview_error=ValueError("coverage invalid")))

    report = _run(_ports(bundle=bundle))

    check = _check(report, "current_publication_gates")
    assert check.blocked_codes == (CURRENT_PUBLICATION_PREVIEW_FAILED,)
    assert check.detail == "ValueError"


def test_authority_capture_probe_unavailable():
    def _probe():
        raise SystemAuditCompositionUnavailable(
            "capture unavailable", reason_code="authority_selector_missing"
        )

    report = _run(_ports(authority_probe=_probe))

    check = _check(report, "account_authority_capture")
    assert check.blocked_codes == (PREFLIGHT_AUTHORITY_CAPTURE_UNAVAILABLE,)
    assert check.detail == "authority_selector_missing"


def test_task_attempt_identity_probe_unavailable():
    def _probe():
        raise RuntimeError("monitor store down")

    report = _run(_ports(attempt_probe=_probe))

    check = _check(report, "task_attempt_identity")
    assert check.blocked_codes == (PREFLIGHT_TASK_ATTEMPT_IDENTITY_UNAVAILABLE,)
    assert check.detail == "RuntimeError"


def test_all_checks_run_and_aggregate_blocked_codes():
    def _builder():
        raise SystemAuditCompositionUnavailable("bundle", reason_code="composition_not_wired")

    def _probe():
        raise RuntimeError("down")

    report = _run(
        _ports(
            settings={"status": "blocked", "blocked_reason": "missing"},
            bundle_builder=_builder,
            attempt_probe=_probe,
        )
    )

    assert report.outcome == "blocked"
    assert [check.name for check in report.checks] == [
        "provider_policy_and_routes",
        "current_publication_gates",
        "account_authority_capture",
        "task_attempt_identity",
    ]
    assert report.blocked_codes == tuple(
        sorted(
            {
                PREFLIGHT_PROVIDER_SETTINGS_BLOCKED,
                PREFLIGHT_PUBLICATION_BUNDLE_UNAVAILABLE,
                PREFLIGHT_AUTHORITY_CAPTURE_UNAVAILABLE,
                PREFLIGHT_TASK_ATTEMPT_IDENTITY_UNAVAILABLE,
            }
        )
    )


def _stub_use_case(report):
    class _UseCase:
        def execute(self):
            return report

    return _UseCase()


def test_command_prints_json_and_exits_zero_on_pass(monkeypatch):
    report = _run(_ports())
    monkeypatch.setattr(
        "apps.data_center.management.commands.preflight_full_market_publication"
        ".build_full_market_publication_preflight_use_case",
        lambda: _stub_use_case(report),
    )
    stdout = io.StringIO()

    call_command("preflight_full_market_publication", stdout=stdout)

    payload = json.loads(stdout.getvalue())
    assert payload["outcome"] == "pass"
    assert payload["blocked_codes"] == []
    assert [check["status"] for check in payload["checks"]] == ["pass"] * 4


def test_command_prints_json_and_fails_on_blocked(monkeypatch):
    report = _run(_ports(settings={"status": "blocked", "blocked_reason": "missing"}))
    monkeypatch.setattr(
        "apps.data_center.management.commands.preflight_full_market_publication"
        ".build_full_market_publication_preflight_use_case",
        lambda: _stub_use_case(report),
    )
    stdout = io.StringIO()

    with pytest.raises(CommandError):
        call_command("preflight_full_market_publication", stdout=stdout)

    payload = json.loads(stdout.getvalue())
    assert payload["outcome"] == "blocked"
    assert payload["blocked_codes"] == [PREFLIGHT_PROVIDER_SETTINGS_BLOCKED]
