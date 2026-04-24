import json
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from apps.data_center.infrastructure.models import MacroFactModel, ProviderConfigModel


def _create_provider(*, name: str, source_type: str, priority: int, is_active: bool) -> None:
    ProviderConfigModel.objects.create(
        name=name,
        source_type=source_type,
        priority=priority,
        is_active=is_active,
    )


def _create_regime_macro_facts(*, source: str) -> None:
    today = date.today()
    observations = [
        (today - timedelta(days=60), Decimal("49.8"), Decimal("0.7")),
        (today - timedelta(days=30), Decimal("50.1"), Decimal("0.9")),
        (today, Decimal("50.4"), Decimal("1.3")),
    ]

    for reporting_period, pmi_value, cpi_value in observations:
        MacroFactModel.objects.create(
            indicator_code="CN_PMI",
            reporting_period=reporting_period,
            value=pmi_value,
            unit="指数",
            source=source,
            published_at=reporting_period,
        )
        MacroFactModel.objects.create(
            indicator_code="CN_CPI_NATIONAL_YOY",
            reporting_period=reporting_period,
            value=cpi_value,
            unit="%",
            source=source,
            published_at=reporting_period,
        )


def _get_response_context(response):
    assert response.status_code == 200
    assert response.context is not None

    context = response.context
    if hasattr(context, "flatten"):
        return context.flatten()
    if isinstance(context, list):
        last_context = context[-1]
        return last_context.flatten() if hasattr(last_context, "flatten") else last_context
    return context


@pytest.mark.django_db
def test_regime_dashboard_view_handles_invalid_raw_data_values(authenticated_client, monkeypatch):
    fake_response = SimpleNamespace(
        success=True,
        result=SimpleNamespace(
            regime=SimpleNamespace(value="Recovery"),
            growth_level=50.1,
            inflation_level=2.3,
            confidence=0.85,
            distribution={"Recovery": 0.6, "Expansion": 0.4},
        ),
        raw_data={
            "growth": [
                {"date": "2026-01", "value": "50.2"},
                {"date": "2026-02", "value": None},
                {"date": "2026-03", "value": ""},
                {"date": "2026-04", "value": "bad"},
            ],
            "inflation": [
                {"date": "2026-01", "value": "2.1"},
                {"date": "2026-02", "value": "N/A"},
            ],
        },
        warnings=[],
        error=None,
    )

    _create_provider(
        name="akshare_main",
        source_type="akshare",
        priority=1,
        is_active=True,
    )

    monkeypatch.setattr(
        "apps.regime.application.interface_services.CalculateRegimeV2UseCase.execute",
        lambda self, request_obj: fake_response,
    )

    response = authenticated_client.get("/regime/dashboard/")
    context = _get_response_context(response)

    assert context["error"] is None
    assert context["regime_result"] is not None
    assert json.loads(context["regime_result"]["growth_values"]) == [50.2, 0.0, 0.0, 0.0]
    assert json.loads(context["regime_result"]["inflation_values"]) == [2.1, 0.0]


@pytest.mark.django_db
def test_regime_dashboard_view_falls_back_to_available_source_when_default_has_no_data(
    authenticated_client,
):
    _create_provider(
        name="tushare_main",
        source_type="tushare",
        priority=1,
        is_active=True,
    )
    _create_provider(
        name="akshare_backup",
        source_type="akshare",
        priority=2,
        is_active=False,
    )
    _create_regime_macro_facts(source="akshare")

    response = authenticated_client.get("/regime/dashboard/")
    context = _get_response_context(response)

    assert context["error"] is None
    assert context["regime_result"] is not None
    assert context["current_source"] == "akshare"
    assert any("默认数据源 tushare 暂无 Regime 所需数据" in item for item in context["warnings"])
    assert any(source.source_type == "akshare" for source in context["available_sources"])


@pytest.mark.django_db
def test_regime_dashboard_view_preserves_explicit_source_selection(authenticated_client):
    _create_provider(
        name="tushare_main",
        source_type="tushare",
        priority=1,
        is_active=True,
    )
    _create_provider(
        name="akshare_backup",
        source_type="akshare",
        priority=2,
        is_active=False,
    )
    _create_regime_macro_facts(source="akshare")

    response = authenticated_client.get("/regime/dashboard/?source=tushare")
    context = _get_response_context(response)

    assert context["regime_result"] is None
    assert context["error"] == "数据不足：需要 PMI 和 CPI 数据"
    assert context["current_source"] == "tushare"
    assert context["warnings"] == []
