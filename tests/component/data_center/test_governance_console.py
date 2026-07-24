from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.data_center.application.dtos import SyncResult
from apps.data_center.application.interface_services import load_macro_governance_payload
from apps.data_center.infrastructure.models import (
    IndicatorCatalogModel,
    MacroFactModel,
    ProviderConfigModel,
)


@pytest.fixture
def admin_user(db):
    user = get_user_model().objects.create_user(
        username="dc_governance_admin",
        password="testpass123",
        email="dc-governance@example.com",
    )
    user.is_staff = True
    user.is_superuser = True
    user.save(update_fields=["is_staff", "is_superuser"])
    return user


@pytest.fixture
def admin_client(client, admin_user):
    client.force_login(admin_user)
    return client


@pytest.mark.django_db
def test_governance_console_renders_audit_rows(admin_client):
    IndicatorCatalogModel.objects.update_or_create(
        code="CN_GDP",
        defaults={
            "name_cn": "GDP 国内生产总值累计值",
            "default_unit": "亿元",
            "default_period_type": "Q",
            "category": "growth",
            "is_active": True,
            "extra": {
                "series_semantics": "cumulative_level",
                "paired_indicator_code": "CN_GDP_YOY",
                "governance_scope": "macro_console",
                "governance_sync_supported": True,
                "governance_sync_source_type": "akshare",
            },
        },
    )
    IndicatorCatalogModel.objects.update_or_create(
        code="CN_GDP_YOY",
        defaults={
            "name_cn": "GDP同比增速",
            "default_unit": "%",
            "default_period_type": "Q",
            "category": "growth",
            "is_active": True,
            "extra": {
                "series_semantics": "yoy_rate",
                "paired_indicator_code": "CN_GDP",
                "governance_scope": "macro_console",
                "governance_sync_supported": True,
                "governance_sync_source_type": "akshare",
            },
        },
    )
    MacroFactModel.objects.create(
        indicator_code="CN_GDP",
        reporting_period="2026-03-31",
        value="31875860000.000000",
        unit="元",
        source="AKShare Public",
        revision_number=1,
        quality="valid",
        extra={
            "original_unit": "亿元",
            "display_unit": "亿元",
            "source_type": "akshare",
            "period_type": "Q",
        },
    )

    response = admin_client.get(reverse("data_center:dc-governance-page"))

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "CN_GDP" in content
    assert "AKShare Public" in content
    assert "legacy source" in content


@pytest.mark.django_db
def test_governance_console_can_canonicalize_legacy_sources(admin_client):
    MacroFactModel.objects.create(
        indicator_code="CN_GDP",
        reporting_period="2026-03-31",
        value="31875860000.000000",
        unit="元",
        source="AKShare Public",
        revision_number=1,
        quality="valid",
        extra={
            "original_unit": "亿元",
            "display_unit": "亿元",
            "source_type": "akshare",
            "period_type": "Q",
        },
    )

    response = admin_client.post(
        reverse("data_center:dc-governance-page"),
        data={"action": "canonicalize_sources"},
    )

    assert response.status_code == 200
    fact = MacroFactModel.objects.get(indicator_code="CN_GDP")
    assert fact.source == "akshare"


@pytest.mark.django_db
def test_governance_console_sync_action_invokes_macro_sync(admin_client, monkeypatch):
    captured: dict[str, object] = {}
    provider = ProviderConfigModel.objects.create(
        name="AKShare Public",
        source_type="akshare",
        is_active=True,
        priority=1,
        extra_config={},
    )
    IndicatorCatalogModel.objects.update_or_create(
        code="TEST_SYNC",
        defaults={
            "name_cn": "测试同步指标",
            "default_unit": "%",
            "default_period_type": "M",
            "category": "test",
            "is_active": True,
            "extra": {
                "governance_scope": "macro_console",
                "governance_sync_supported": True,
                "governance_sync_source_type": "akshare",
            },
        },
    )
    monkeypatch.setattr(
        "apps.data_center.infrastructure.repositories.MacroGovernanceRepository.build_snapshot",
        lambda self, **kwargs: {
            "governed_indicator_codes": ["TEST_SYNC"],
            "supported_sync_codes": ["TEST_SYNC"],
            "indicator_rows": [
                {
                    "code": "TEST_SYNC",
                    "tags": ["missing_supported"],
                    "sync_source_type": "akshare",
                }
            ],
        },
    )

    def fake_make_sync_macro_use_case():
        def execute(request):
            captured["request"] = request
            return SyncResult("macro", "AKShare Public", 7, "success")

        return SimpleNamespace(execute=execute)

    monkeypatch.setattr(
        "apps.data_center.application.interface_services.make_sync_macro_use_case",
        fake_make_sync_macro_use_case,
    )

    response = admin_client.post(
        reverse("data_center:dc-governance-page"),
        data={"action": "sync_missing_series"},
    )

    assert response.status_code == 200
    request = captured["request"]
    assert request.provider_id == provider.id
    assert request.indicator_code == "TEST_SYNC"


@pytest.mark.django_db
def test_governance_console_full_repair_runs_all_repair_steps(admin_client, monkeypatch):
    provider = ProviderConfigModel.objects.create(
        name="AKShare Public",
        source_type="akshare",
        is_active=True,
        priority=1,
        extra_config={},
    )
    IndicatorCatalogModel.objects.update_or_create(
        code="TEST_SYNC",
        defaults={
            "name_cn": "测试同步指标",
            "default_unit": "%",
            "default_period_type": "M",
            "category": "test",
            "is_active": True,
            "extra": {
                "governance_scope": "macro_console",
                "governance_sync_supported": True,
                "governance_sync_source_type": "akshare",
            },
        },
    )
    captured = {"canonicalize": 0, "normalize": 0, "sync_requests": []}
    monkeypatch.setattr(
        "apps.data_center.infrastructure.repositories.MacroGovernanceRepository.build_snapshot",
        lambda self, **kwargs: {
            "governed_indicator_codes": ["TEST_SYNC"],
            "supported_sync_codes": ["TEST_SYNC"],
            "indicator_rows": [
                {
                    "code": "TEST_SYNC",
                    "tags": ["missing_supported"],
                    "sync_source_type": "akshare",
                }
            ],
        },
    )

    def fake_normalize(self, *, indicator_codes=None, dry_run=False):
        captured["normalize"] += 1
        return {
            "updated_count": 1,
            "unchanged_count": 0,
            "skipped_count": 0,
            "dry_run": dry_run,
            "messages": [],
        }

    def fake_make_sync_macro_use_case():
        def execute(request):
            captured["sync_requests"].append(request)
            return SyncResult("macro", "AKShare Public", 3, "success")

        return SimpleNamespace(execute=execute)

    def fake_canonicalize(self, **kwargs):
        captured["canonicalize"] += 1
        return {"updated_rows": 1}

    monkeypatch.setattr(
        "apps.data_center.infrastructure.repositories.MacroGovernanceRepository.canonicalize_sources",
        fake_canonicalize,
    )
    monkeypatch.setattr(
        "apps.data_center.infrastructure.repositories.MacroGovernanceRepository.normalize_macro_fact_units",
        fake_normalize,
    )
    monkeypatch.setattr(
        "apps.data_center.application.interface_services.make_sync_macro_use_case",
        fake_make_sync_macro_use_case,
    )

    response = admin_client.post(
        reverse("data_center:dc-governance-page"),
        data={"action": "run_full_repair"},
    )

    assert response.status_code == 200
    assert captured["canonicalize"] == 1
    assert captured["normalize"] == 1
    assert len(captured["sync_requests"]) == 1
    assert captured["sync_requests"][0].provider_id == provider.id


@pytest.mark.django_db
def test_governance_payload_excludes_compat_alias_scope_from_macro_console():
    IndicatorCatalogModel.objects.update_or_create(
        code="TEST_CANON",
        defaults={
            "name_cn": "测试 canonical 指标",
            "default_unit": "%",
            "default_period_type": "M",
            "category": "test",
            "is_active": True,
            "extra": {
                "series_semantics": "yoy_rate",
                "governance_scope": "macro_console",
                "governance_sync_supported": True,
                "governance_sync_source_type": "akshare",
            },
        },
    )
    IndicatorCatalogModel.objects.update_or_create(
        code="TEST_ALIAS",
        defaults={
            "name_cn": "测试兼容别名",
            "default_unit": "%",
            "default_period_type": "M",
            "category": "test",
            "is_active": True,
            "extra": {
                "series_semantics": "yoy_rate",
                "alias_of_indicator_code": "TEST_CANON",
                "governance_scope": "macro_compat_alias",
                "governance_sync_supported": False,
            },
        },
    )

    payload = load_macro_governance_payload()

    codes = {row["code"] for row in payload["indicator_rows"]}
    assert "TEST_CANON" in codes
    assert "TEST_ALIAS" not in codes
