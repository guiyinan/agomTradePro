import json
from datetime import UTC, date, datetime

import pytest
from django.contrib.auth.models import User
from django.test import Client

from apps.audit.application.data_decision_read_audit import (
    AppendDataDecisionReadAuditObservationUseCase,
)
from apps.audit.application.data_failover_audit import (
    AppendDataFailoverAuditObservationUseCase,
)
from apps.audit.application.data_fetch_audit import AppendDataFetchAuditObservationUseCase
from apps.audit.application.data_freshness_audit import (
    AppendDataFreshnessAuditObservationUseCase,
)
from apps.audit.application.data_provider_health_audit import (
    AppendDataProviderHealthAuditObservationUseCase,
)
from apps.audit.application.data_publication_audit import (
    AppendDataPublicationAuditObservationUseCase,
)
from apps.audit.application.data_quality_audit import AppendDataQualityAuditObservationUseCase
from apps.audit.application.data_validation_audit import (
    AppendDataValidationRejectedObservationUseCase,
)
from apps.audit.domain.system_audit_event import AuditScopeRef
from apps.audit.infrastructure.system_audit_event_outbox_coordinator import (
    DjangoSystemAuditEventOutboxCoordinator,
)
from apps.audit.infrastructure.system_audit_models import SystemAuditEventModel
from apps.data_center.infrastructure.catalog_models import DatasetPublicationPolicyModel
from apps.data_center.infrastructure.models import (
    FinancialFactModel,
    FundNavFactModel,
    MacroFactModel,
    ProviderConfigModel,
    QuoteSnapshotModel,
    RawAuditModel,
    ValuationFactModel,
)


class _AuditScopeProvider:
    def get_scope(self, *, as_of: datetime) -> AuditScopeRef:
        del as_of
        return AuditScopeRef("tenant:integration", "owner:data-center-test")


def _canonical_audit_writers() -> tuple[
    AppendDataFetchAuditObservationUseCase,
    AppendDataPublicationAuditObservationUseCase,
    AppendDataValidationRejectedObservationUseCase,
    AppendDataFailoverAuditObservationUseCase,
    AppendDataDecisionReadAuditObservationUseCase,
    AppendDataProviderHealthAuditObservationUseCase,
    AppendDataFreshnessAuditObservationUseCase,
    AppendDataQualityAuditObservationUseCase,
]:
    """Build real database writers behind an explicit isolated test scope."""

    coordinator = DjangoSystemAuditEventOutboxCoordinator()
    scope_provider = _AuditScopeProvider()
    return (
        AppendDataFetchAuditObservationUseCase(coordinator, scope_provider),
        AppendDataPublicationAuditObservationUseCase(coordinator, scope_provider),
        AppendDataValidationRejectedObservationUseCase(coordinator, scope_provider),
        AppendDataFailoverAuditObservationUseCase(coordinator, scope_provider),
        AppendDataDecisionReadAuditObservationUseCase(coordinator, scope_provider),
        AppendDataProviderHealthAuditObservationUseCase(coordinator, scope_provider),
        AppendDataFreshnessAuditObservationUseCase(coordinator, scope_provider),
        AppendDataQualityAuditObservationUseCase(coordinator, scope_provider),
    )


def _install_canonical_audit_writers(mocker) -> None:
    """Keep API integration tests on canonical audit persistence without authority fixtures."""

    mocker.patch(
        "core.integration.data_center_audit.get_data_reliability_audit_writers",
        return_value=_canonical_audit_writers(),
    )


def _seed_publication_policy(dataset_key: str, required_evidence: list[str]) -> None:
    """Register the real publication gate used by sync endpoints."""

    DatasetPublicationPolicyModel.objects.create(
        dataset_key=dataset_key,
        contract_version="integration-test",
        schema_version="1.0",
        minimum_coverage_ratio=1.0,
        allow_partial=False,
        conflict_action="block",
        required_evidence=required_evidence,
        retention_days=30,
        active=True,
    )


@pytest.fixture
def admin_client(db):
    user = User.objects.create_user(
        username="data_center_admin",
        password="pass1234",
        is_staff=True,
        is_superuser=True,
    )
    client = Client()
    client.force_login(user)
    return client


@pytest.mark.django_db
def test_data_center_query_financials_returns_json_contract(admin_client):
    FinancialFactModel.objects.create(
        asset_code="000001.SZ",
        period_end=date(2024, 12, 31),
        period_type="annual",
        metric_code="revenue",
        value=123.45,
        unit="元",
        source="tushare-main",
    )

    response = admin_client.get("/api/data-center/financials/?asset_code=000001.SZ")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["asset_code"] == "000001.SZ"
    assert payload["total"] == 1
    assert payload["data"][0]["metric_code"] == "revenue"


@pytest.mark.django_db
def test_data_center_query_fund_nav_returns_json_contract(admin_client):
    FundNavFactModel.objects.create(
        fund_code="110011.OF",
        nav_date=date(2025, 3, 1),
        nav=1.2345,
        acc_nav=1.5678,
        source="tushare-main",
    )

    response = admin_client.get("/api/data-center/funds/nav/?fund_code=110011.OF")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["fund_code"] == "110011.OF"
    assert payload["total"] == 1
    assert payload["data"][0]["nav"] == 1.2345


@pytest.mark.django_db
def test_data_center_query_valuations_returns_json_contract(admin_client):
    ValuationFactModel.objects.create(
        asset_code="000001.SZ",
        val_date=date(2025, 3, 1),
        pe_ttm=12.34,
        pb=1.23,
        source="akshare-main",
    )

    response = admin_client.get("/api/data-center/valuations/?asset_code=000001.SZ")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["asset_code"] == "000001.SZ"
    assert payload["total"] == 1
    assert payload["data"][0]["pe_ttm"] == 12.34


class _StubProvider:
    def provider_name(self) -> str:
        return "stub-provider"

    def fetch_macro_series(self, indicator_code, start_date, end_date):
        from apps.data_center.domain.entities import MacroFact

        return [
            MacroFact(
                indicator_code=indicator_code,
                reporting_period=date(2025, 3, 1),
                value=51.2,
                unit="指数",
                source="stub-provider",
                revision_number=1,
                published_at=date(2025, 3, 2),
            )
        ]

    def fetch_quote_snapshots(self, asset_codes):
        from apps.data_center.domain.entities import QuoteSnapshot

        return [
            QuoteSnapshot(
                asset_code=asset_codes[0],
                snapshot_at=datetime(2025, 3, 1, 9, 30, tzinfo=UTC),
                current_price=12.34,
                source="stub-provider",
            )
        ]

    def fetch_fund_nav(self, fund_code, start_date, end_date):
        from apps.data_center.domain.entities import FundNavFact

        return [
            FundNavFact(
                fund_code=fund_code,
                nav_date=date(2025, 3, 1),
                nav=1.234,
                acc_nav=1.567,
                source="stub-provider",
            )
        ]


class _StubRegistry:
    def get_by_id(self, provider_id):
        return _StubProvider()

    def record_success(self, provider_name, capability, latency_ms):
        return None

    def record_failure(self, provider_name, capability):
        return None


@pytest.mark.django_db
def test_sync_macro_endpoint_persists_fact_and_raw_audit(admin_client, mocker):
    _install_canonical_audit_writers(mocker)
    _seed_publication_policy(
        "macro.fact", ["source", "observed_at", "published_at", "payload_hash"]
    )
    provider = ProviderConfigModel.objects.create(
        name="stub-provider",
        source_type="tushare",
        is_active=True,
        priority=1,
    )
    mocker.patch(
        "apps.data_center.application.interface_services._get_provider_registry",
        return_value=_StubRegistry(),
    )

    response = admin_client.post(
        "/api/data-center/sync/macro/",
        data=json.dumps(
            {
                "provider_id": provider.id,
                "indicator_code": "CN_PMI",
                "start": "2025-03-01",
                "end": "2025-03-31",
            }
        ),
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    assert MacroFactModel.objects.filter(indicator_code="CN_PMI").count() == 1
    assert RawAuditModel.objects.filter(capability="macro", status="ok").count() == 1
    assert SystemAuditEventModel.objects.filter(event_type="data.fetch.completed").count() == 1


@pytest.mark.django_db
def test_sync_quotes_endpoint_persists_snapshot_and_raw_audit(admin_client, mocker):
    _install_canonical_audit_writers(mocker)
    _seed_publication_policy(
        "equity.quote.snapshot", ["source", "observed_at", "fetched_at", "payload_hash"]
    )
    provider = ProviderConfigModel.objects.create(
        name="stub-provider",
        source_type="tushare",
        is_active=True,
        priority=1,
    )
    mocker.patch(
        "apps.data_center.application.interface_services._get_provider_registry",
        return_value=_StubRegistry(),
    )

    response = admin_client.post(
        "/api/data-center/sync/quotes/",
        data=json.dumps({"provider_id": provider.id, "asset_codes": ["000001.SZ"]}),
        content_type="application/json",
    )

    assert response.status_code == 200
    assert QuoteSnapshotModel.objects.filter(asset_code="000001.SZ").count() == 1
    assert RawAuditModel.objects.filter(capability="realtime_quote", status="ok").count() == 1
    assert SystemAuditEventModel.objects.filter(event_type="data.fetch.completed").count() == 1


@pytest.mark.django_db
def test_sync_fund_nav_endpoint_persists_fact_and_raw_audit(admin_client, mocker):
    _seed_publication_policy("fund.nav", ["source", "observed_at", "payload_hash"])
    provider = ProviderConfigModel.objects.create(
        name="stub-provider",
        source_type="tushare",
        is_active=True,
        priority=1,
    )
    mocker.patch(
        "apps.data_center.application.interface_services._get_provider_registry",
        return_value=_StubRegistry(),
    )

    response = admin_client.post(
        "/api/data-center/sync/funds/nav/",
        data=json.dumps(
            {
                "provider_id": provider.id,
                "fund_code": "110011.OF",
                "start": "2025-03-01",
                "end": "2025-03-31",
            }
        ),
        content_type="application/json",
    )

    assert response.status_code == 200
    assert FundNavFactModel.objects.filter(fund_code="110011.OF").count() == 1
    assert RawAuditModel.objects.filter(capability="fund_nav", status="ok").count() == 1
