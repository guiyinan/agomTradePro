"""Tushare wire formats respect live egress rules across all supported modes."""

import os
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest

from apps.data_center.application import egress_service
from apps.data_center.application.financial_response_artifact import (
    RetainedFinancialResponsePayload,
)
from apps.data_center.domain.egress_routing import EgressRouteDecision, EgressStrategy
from apps.data_center.domain.financial_response_artifact import FinancialResponseArtifactRef
from apps.data_center.domain.financial_response_evidence import (
    FinancialRequestScope,
    FinancialResponseEvidence,
    FinancialResponseScope,
    FinancialResponseScopeBasis,
)
from apps.data_center.infrastructure import tushare_client


def _retained_financial_reference() -> FinancialResponseArtifactRef:
    """Build one exact retained response reference for all routed modes."""

    return FinancialResponseArtifactRef(
        capture_id=UUID("20000000-0000-4000-8000-000000000006"),
        location="financial-response/routed-modes.bin",
        evidence=FinancialResponseEvidence(
            body_sha256="a" * 64,
            body_size_bytes=128,
            response_completed_at=datetime(2026, 9, 22, 4, 0, tzinfo=UTC),
            request_scope=FinancialRequestScope(
                provider_name="Tushare Pro",
                dataset_key="equity.financial.fact",
                asset_code="000001.SZ",
                period_limit=2,
            ),
            response_scope=FinancialResponseScope(
                asset_codes=("000001.SZ",),
                period_ends=(date(2025, 12, 31),),
                row_count=1,
            ),
            response_scope_basis=FinancialResponseScopeBasis.PROVIDER_BODY_VERIFIED,
        ),
        format_version="financial-response-artifact.v1",
        encryption_algorithm="fernet",
        encryption_key_ref="config_center.data02.test-key",
        encryption_key_version="v1",
    )


@pytest.mark.parametrize("mode", ["sdk_path", "rest_path", "unified_relay"])
def test_configured_provider_routes_real_query_with_original_wire_format(monkeypatch, mode):
    settings = tushare_client.TushareRuntimeSettings(
        token="test-private-token", http_url="https://market.example.com/pro", request_mode=mode
    )
    monkeypatch.setattr(
        tushare_client, "resolve_tushare_runtime_settings", lambda **_kwargs: settings
    )
    sdk = Mock()
    sdk._DataApi__http_url = settings.http_url
    sdk_module = SimpleNamespace(pro_api=lambda _token: sdk)
    original_import = tushare_client.import_module
    monkeypatch.setattr(
        tushare_client,
        "import_module",
        lambda name: sdk_module if name == "tushare" else original_import(name),
    )
    session = Mock()
    session.headers = {}
    monkeypatch.setattr(tushare_client, "_create_requests_session", lambda: session)
    route = EgressRouteDecision(
        rule_id=5, strategy=EgressStrategy.FIXED, candidates=(9,), reason="matched_rule"
    )
    preview = Mock(return_value=route)
    monkeypatch.setattr(egress_service, "preview_route", preview)
    execute = Mock(
        return_value={
            "code": 0,
            "data": {"fields": ["ts_code", "close"], "items": [["000001.SZ", 12.3]]},
        }
    )
    monkeypatch.setattr(egress_service, "execute_provider_request", execute)
    before = dict(os.environ)
    client = tushare_client.create_tushare_pro_client(
        provider_id=3, deployment_region="overseas", dataset_key="equity.price.bar"
    )
    result = client.daily(ts_code="000001.SZ")
    assert result.iloc[0]["close"] == 12.3
    context = execute.call_args.args[0]
    assert context.provider_id == 3
    assert context.dataset_key == "equity.price.bar"
    expected_suffix = "/daily" if mode == "rest_path" else ""
    assert context.target_url == settings.http_url + expected_suffix
    assert execute.call_args.kwargs["method"] == ("GET" if mode == "rest_path" else "POST")
    assert execute.call_args.kwargs["max_attempts"] == 2
    assert dict(os.environ) == before
    sdk.query.assert_not_called()
    session.get.assert_not_called()
    session.post.assert_not_called()


@pytest.mark.parametrize("mode", ["sdk_path", "rest_path", "unified_relay"])
@pytest.mark.parametrize("provider_code", [False, 0.0, "0", None])
def test_routed_clients_reject_non_integer_provider_codes(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    provider_code: object,
) -> None:
    """JSON values merely equal to zero cannot authorize a provider success."""

    settings = tushare_client.TushareRuntimeSettings(
        token="test-private-token",
        http_url="https://market.example.com/pro",
        request_mode=mode,
    )
    monkeypatch.setattr(
        tushare_client,
        "resolve_tushare_runtime_settings",
        lambda **_kwargs: settings,
    )
    sdk = Mock()
    sdk._DataApi__http_url = settings.http_url
    sdk_module = SimpleNamespace(pro_api=lambda _token: sdk)
    original_import = tushare_client.import_module
    monkeypatch.setattr(
        tushare_client,
        "import_module",
        lambda name: sdk_module if name == "tushare" else original_import(name),
    )
    session = Mock()
    session.headers = {}
    monkeypatch.setattr(tushare_client, "_create_requests_session", lambda: session)
    monkeypatch.setattr(
        egress_service,
        "preview_route",
        Mock(
            return_value=EgressRouteDecision(
                rule_id=5,
                strategy=EgressStrategy.FIXED,
                candidates=(9,),
                reason="matched_rule",
            )
        ),
    )
    monkeypatch.setattr(
        egress_service,
        "execute_provider_request",
        Mock(
            return_value={
                "code": provider_code,
                "data": {"fields": ["ts_code"], "items": [["000001.SZ"]]},
            }
        ),
    )
    client = tushare_client.create_tushare_pro_client(
        provider_id=3,
        deployment_region="overseas",
        dataset_key="equity.price.bar",
    )

    with pytest.raises(tushare_client.TushareError) as caught:
        client.daily(ts_code="000001.SZ")

    assert caught.value.code == "TUSHARE_INVALID_PAYLOAD"


@pytest.mark.parametrize("mode", ["sdk_path", "rest_path", "unified_relay"])
def test_routed_financial_clients_preserve_retained_artifact_reference(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    """Every routed financial mode carries the retained reference to its frame."""

    settings = tushare_client.TushareRuntimeSettings(
        token="test-private-token",
        http_url="https://market.example.com/pro",
        request_mode=mode,
    )
    monkeypatch.setattr(
        tushare_client,
        "resolve_tushare_runtime_settings",
        lambda **_kwargs: settings,
    )
    sdk = Mock()
    sdk._DataApi__http_url = settings.http_url
    sdk_module = SimpleNamespace(pro_api=lambda _token: sdk)
    original_import = tushare_client.import_module
    monkeypatch.setattr(
        tushare_client,
        "import_module",
        lambda name: sdk_module if name == "tushare" else original_import(name),
    )
    session = Mock()
    session.headers = {}
    monkeypatch.setattr(tushare_client, "_create_requests_session", lambda: session)
    monkeypatch.setattr(
        egress_service,
        "preview_route",
        Mock(
            return_value=EgressRouteDecision(
                rule_id=5,
                strategy=EgressStrategy.FIXED,
                candidates=(9,),
                reason="matched_rule",
            )
        ),
    )
    reference = _retained_financial_reference()
    handler = Mock(
        return_value=RetainedFinancialResponsePayload(
            payload={
                "code": 0,
                "data": {
                    "fields": ["ts_code", "end_date", "ann_date", "roe"],
                    "items": [["000001.SZ", "20251231", "20260330", 12.5]],
                },
            },
            reference=reference,
        )
    )
    client = tushare_client.create_tushare_pro_client(
        provider_id=3,
        deployment_region="overseas",
        dataset_key="equity.financial.fact",
        financial_response_handler=handler,
    )

    result = client.fina_indicator(ts_code="000001.SZ", limit=2)

    assert result.artifact_reference is reference
    assert result.to_dict("records") == [
        {
            "ts_code": "000001.SZ",
            "end_date": "20251231",
            "ann_date": "20260330",
            "roe": 12.5,
        }
    ]
    handler.assert_called_once()
    sdk.query.assert_not_called()
    session.get.assert_not_called()
    session.post.assert_not_called()


def test_sdk_rechecks_rule_when_existing_client_is_reused(monkeypatch):
    sdk = Mock()
    sdk.query.return_value = "legacy-result"
    client = tushare_client._RoutedSdkClient(
        sdk_client=sdk,
        token="test-token",
        http_url="https://market.example.com/pro",
        provider_id=3,
        deployment_region="overseas",
        dataset_key="",
    )
    direct = EgressRouteDecision(
        rule_id=None, strategy=EgressStrategy.DIRECT, candidates=(None,), reason="no_matching_rule"
    )
    fixed = EgressRouteDecision(
        rule_id=5, strategy=EgressStrategy.FIXED, candidates=(9,), reason="matched_rule"
    )
    monkeypatch.setattr(egress_service, "preview_route", Mock(side_effect=[direct, fixed]))
    execute = Mock(return_value={"code": 0, "data": {"fields": ["name"], "items": [["example"]]}})
    monkeypatch.setattr(egress_service, "execute_provider_request", execute)
    assert client.stock_basic() == "legacy-result"
    assert client.stock_basic().iloc[0]["name"] == "example"
    assert sdk.query.call_count == 1
    assert execute.call_args.args[0].dataset_key == "tushare.stock_basic"
