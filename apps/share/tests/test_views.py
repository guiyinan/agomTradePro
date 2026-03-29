from decimal import Decimal

import pytest
from django.contrib.auth.hashers import check_password
from django.utils import timezone
from rest_framework.test import APIClient

from apps.decision_rhythm.infrastructure.models import (
    DecisionFeatureSnapshotModel,
    DecisionRequestModel,
    DecisionResponseModel,
    UnifiedRecommendationModel,
)
from apps.share.infrastructure.models import ShareLinkModel, ShareSnapshotModel
from apps.simulated_trading.infrastructure.models import PositionModel, SimulatedTradeModel


@pytest.mark.django_db
def test_public_snapshot_requires_password(password_protected_share_link):
    client = APIClient()

    response = client.get(f"/api/share/public/{password_protected_share_link.short_code}/snapshot/")

    assert response.status_code == 401


@pytest.mark.django_db
def test_logs_endpoint_is_owner_scoped(active_share_link, other_user):
    client = APIClient()
    client.force_authenticate(user=other_user)

    response = client.get(f"/api/share/links/{active_share_link.id}/logs/")

    assert response.status_code == 404


@pytest.mark.django_db
def test_public_share_page_renders_snapshot_data(active_share_link, test_snapshot, client):
    response = client.get(f"/share/{active_share_link.short_code}/")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert active_share_link.title in content
    assert "收益曲线" in content
    assert "Powered by" in content
    assert "shareDisclaimerModal" in content


@pytest.mark.django_db
def test_public_share_page_renders_position_details_without_duplicate_risk_notice(
    active_share_link,
    test_account,
    client,
):
    PositionModel.objects.create(
        account=test_account,
        asset_code="000001.SH",
        asset_name="平安银行",
        asset_type="equity",
        quantity=100,
        available_quantity=100,
        avg_cost=Decimal("10.0000"),
        total_cost=Decimal("1000.00"),
        current_price=Decimal("10.5000"),
        market_value=Decimal("1050.00"),
        unrealized_pnl=Decimal("50.00"),
        unrealized_pnl_pct=5.0,
        first_buy_date=timezone.now().date(),
        entry_reason="政策回暖后试仓",
        invalidation_description="跌破 9.80 重新评估",
    )

    response = client.get(f"/share/{active_share_link.short_code}/")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "平安银行" in content
    assert "股票" in content
    assert "政策回暖后试仓" in content
    assert "跌破 9.80 重新评估" in content
    assert "本分享由" not in content
    assert "数据来源: AgomTradePro 个人投研平台" not in content


@pytest.mark.django_db
def test_public_share_page_uses_database_disclaimer_config(
    active_share_link,
    share_disclaimer_config,
    client,
):
    share_disclaimer_config.lines = ["第一条提示", "第二条提示"]
    share_disclaimer_config.modal_enabled = False
    share_disclaimer_config.save(update_fields=["lines", "modal_enabled", "updated_at"])

    response = client.get(f"/share/{active_share_link.short_code}/")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "第一条提示" in content
    assert "第二条提示" in content
    assert "shareDisclaimerModal" not in content


@pytest.mark.django_db
def test_password_protected_share_page_does_not_render_disclaimer_modal(
    password_protected_share_link,
    client,
):
    response = client.get(f"/share/{password_protected_share_link.short_code}/")

    assert response.status_code == 401
    content = response.content.decode("utf-8")
    assert 'id="passwordModal"' in content
    assert "shareDisclaimerModal" not in content


@pytest.mark.django_db
def test_share_manage_page_requires_login_and_renders(client, test_user):
    client.force_login(test_user)

    response = client.get("/share/manage/")

    assert response.status_code == 200
    assert "账户分享管理" in response.content.decode("utf-8")


@pytest.mark.django_db
def test_share_disclaimer_manage_page_requires_staff(client, test_user):
    client.force_login(test_user)

    response = client.get("/share/manage/disclaimer/")

    assert response.status_code == 403


@pytest.mark.django_db
def test_share_disclaimer_manage_page_updates_config(client, test_user, share_disclaimer_config):
    test_user.is_staff = True
    test_user.save(update_fields=["is_staff"])
    client.force_login(test_user)

    response = client.post(
        "/share/manage/disclaimer/",
        {
            "is_enabled": "on",
            "modal_enabled": "",
            "modal_title": "新的风险提示标题",
            "modal_confirm_text": "继续查看",
            "lines": "第一条\n第二条\n第三条",
        },
    )

    assert response.status_code == 302
    share_disclaimer_config.refresh_from_db()
    assert share_disclaimer_config.is_enabled is True
    assert share_disclaimer_config.modal_enabled is False
    assert share_disclaimer_config.modal_title == "新的风险提示标题"
    assert share_disclaimer_config.modal_confirm_text == "继续查看"
    assert share_disclaimer_config.lines == ["第一条", "第二条", "第三条"]


@pytest.mark.django_db
def test_share_manage_edit_page_renders_edit_state(client, test_user, active_share_link):
    client.force_login(test_user)

    response = client.get(f"/share/manage/{active_share_link.id}/edit/")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "编辑分享链接" in content
    assert "保存修改" in content
    assert active_share_link.title in content
    assert "模拟盘" in content
    assert "彭博终端风格" in content
    assert "大富翁游戏风格" in content


@pytest.mark.django_db
def test_share_manage_create_persists_selected_theme(client, test_user, test_account):
    client.force_login(test_user)

    response = client.post(
        "/share/manage/",
        {
            "account_id": test_account.id,
            "title": "客户围观页",
            "subtitle": "主题测试",
            "theme": "monopoly",
            "share_level": "observer",
            "show_positions": "on",
            "show_transactions": "on",
            "show_decision_summary": "on",
        },
    )

    assert response.status_code == 302
    latest = ShareLinkModel.objects.get(title="客户围观页")
    assert latest.theme == "monopoly"


@pytest.mark.django_db
def test_public_share_page_renders_selected_theme_class(active_share_link, client):
    active_share_link.theme = "monopoly"
    active_share_link.save(update_fields=["theme"])

    response = client.get(f"/share/{active_share_link.short_code}/")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert 'class="share-page theme-monopoly"' in content


@pytest.mark.django_db
def test_share_manage_edit_updates_theme(client, test_user, active_share_link):
    client.force_login(test_user)

    response = client.post(
        f"/share/manage/{active_share_link.id}/edit/",
        {
            "share_link_id": active_share_link.id,
            "account_id": active_share_link.account_id,
            "title": active_share_link.title,
            "subtitle": active_share_link.subtitle or "",
            "theme": "monopoly",
            "share_level": active_share_link.share_level,
            "show_positions": "on",
            "show_transactions": "on",
            "show_decision_summary": "on",
        },
    )

    assert response.status_code == 302
    active_share_link.refresh_from_db()
    assert active_share_link.theme == "monopoly"


@pytest.mark.django_db
def test_share_manage_edit_can_clear_password_with_explicit_toggle(
    client,
    test_user,
    password_protected_share_link,
):
    client.force_login(test_user)

    response = client.post(
        f"/share/manage/{password_protected_share_link.id}/edit/",
        {
            "share_link_id": password_protected_share_link.id,
            "account_id": password_protected_share_link.account_id,
            "title": password_protected_share_link.title,
            "subtitle": password_protected_share_link.subtitle or "",
            "theme": password_protected_share_link.theme,
            "share_level": password_protected_share_link.share_level,
            "show_positions": "on",
            "show_transactions": "on",
            "show_decision_summary": "on",
            "show_amounts": "on",
        },
    )

    assert response.status_code == 302
    password_protected_share_link.refresh_from_db()
    assert password_protected_share_link.password_hash is None


@pytest.mark.django_db
def test_share_manage_edit_can_replace_password_when_enabled(
    client,
    test_user,
    password_protected_share_link,
):
    client.force_login(test_user)

    response = client.post(
        f"/share/manage/{password_protected_share_link.id}/edit/",
        {
            "share_link_id": password_protected_share_link.id,
            "account_id": password_protected_share_link.account_id,
            "title": password_protected_share_link.title,
            "subtitle": password_protected_share_link.subtitle or "",
            "theme": password_protected_share_link.theme,
            "share_level": password_protected_share_link.share_level,
            "password_enabled": "on",
            "password": "newpass123",
            "show_positions": "on",
            "show_transactions": "on",
            "show_decision_summary": "on",
            "show_amounts": "on",
        },
    )

    assert response.status_code == 302
    password_protected_share_link.refresh_from_db()
    assert password_protected_share_link.password_hash is not None
    assert check_password("newpass123", password_protected_share_link.password_hash) is True


@pytest.mark.django_db
def test_public_snapshot_is_built_live_when_missing(active_share_link):
    client = APIClient()

    response = client.get(f"/api/share/public/{active_share_link.short_code}/snapshot/")

    assert response.status_code == 200
    assert response.data["summary"]["account_name"] == "Test Account"
    assert ShareSnapshotModel.objects.filter(share_link=active_share_link).exists()


@pytest.mark.django_db
def test_public_snapshot_includes_asset_allocation(active_share_link, test_account):
    PositionModel.objects.create(
        account=test_account,
        asset_code="000001.SH",
        asset_name="平安银行",
        asset_type="equity",
        quantity=100,
        available_quantity=100,
        avg_cost=Decimal("10.0000"),
        total_cost=Decimal("1000.00"),
        current_price=Decimal("10.5000"),
        market_value=Decimal("1050.00"),
        unrealized_pnl=Decimal("50.00"),
        unrealized_pnl_pct=5.0,
        first_buy_date=timezone.now().date(),
    )
    PositionModel.objects.create(
        account=test_account,
        asset_code="000311.SZ",
        asset_name="景顺长城沪深300",
        asset_type="fund",
        quantity=200,
        available_quantity=200,
        avg_cost=Decimal("2.0000"),
        total_cost=Decimal("400.00"),
        current_price=Decimal("2.1000"),
        market_value=Decimal("420.00"),
        unrealized_pnl=Decimal("20.00"),
        unrealized_pnl_pct=5.0,
        first_buy_date=timezone.now().date(),
    )

    client = APIClient()
    response = client.get(f"/api/share/public/{active_share_link.short_code}/snapshot/")

    assert response.status_code == 200
    allocation = response.data["positions"]["summary"]["asset_allocation"]
    labels = {item["label"] for item in allocation}
    assert {"股票", "基金", "现金"} <= labels


@pytest.mark.django_db
def test_public_share_page_preserves_ratio_metrics_when_amounts_hidden(active_share_link, client):
    active_share_link.show_amounts = False
    active_share_link.save(update_fields=["show_amounts", "updated_at"])

    response = client.get(f"/share/{active_share_link.short_code}/")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "10.50%" in content
    assert "胜率" in content
    assert "总资产" in content
    assert "--" in content


@pytest.mark.django_db
def test_refresh_share_link_creates_snapshot(client, test_user, active_share_link):
    client.force_login(test_user)

    response = client.post(f"/share/manage/{active_share_link.id}/refresh/")

    assert response.status_code == 302
    assert ShareSnapshotModel.objects.filter(share_link=active_share_link).exists()


@pytest.mark.django_db
def test_refresh_share_link_includes_decision_rhythm_chain(
    client, test_user, active_share_link, test_account
):
    client.force_login(test_user)
    now = timezone.now()

    PositionModel.objects.create(
        account=test_account,
        asset_code="000001.SH",
        asset_name="平安银行",
        asset_type="equity",
        quantity=100,
        available_quantity=100,
        avg_cost=Decimal("10.0000"),
        total_cost=Decimal("1000.00"),
        current_price=Decimal("10.5000"),
        market_value=Decimal("1050.00"),
        unrealized_pnl=Decimal("50.00"),
        unrealized_pnl_pct=5.0,
        first_buy_date=now.date(),
        entry_reason="基础持仓",
        invalidation_description="跌破 9.80 重新评估",
    )
    SimulatedTradeModel.objects.create(
        account=test_account,
        asset_code="000001.SH",
        asset_name="平安银行",
        asset_type="equity",
        action="buy",
        quantity=100,
        price=Decimal("10.0000"),
        amount=Decimal("1000.00"),
        total_cost=Decimal("1000.00"),
        reason="模型首次建仓",
        order_date=now.date(),
        execution_date=now.date(),
        status="executed",
    )

    feature_snapshot = DecisionFeatureSnapshotModel.objects.create(
        security_code="000001.SH",
        regime="risk_on",
        regime_confidence=0.82,
        policy_level="neutral",
        beta_gate_passed=True,
        sentiment_score=0.71,
        flow_score=0.66,
        technical_score=0.73,
        fundamental_score=0.61,
        alpha_model_score=0.69,
        extra_features={"macro": "stable"},
    )
    recommendation = UnifiedRecommendationModel.objects.create(
        account_id=str(test_account.id),
        security_code="000001.SH",
        side="BUY",
        regime="risk_on",
        regime_confidence=0.82,
        policy_level="neutral",
        beta_gate_passed=True,
        sentiment_score=0.71,
        flow_score=0.66,
        technical_score=0.73,
        fundamental_score=0.61,
        alpha_model_score=0.69,
        composite_score=0.74,
        confidence=0.78,
        reason_codes=["trend", "macro"],
        human_rationale="宏观和技术面共振，允许继续持有。",
        fair_value=Decimal("10.8000"),
        entry_price_low=Decimal("9.9000"),
        entry_price_high=Decimal("10.2000"),
        target_price_low=Decimal("11.3000"),
        target_price_high=Decimal("11.8000"),
        stop_loss_price=Decimal("9.8000"),
        position_pct=12.5,
        suggested_quantity=100,
        max_capital=Decimal("15000.00"),
        feature_snapshot=feature_snapshot,
    )
    decision_request = DecisionRequestModel.objects.create(
        request_id="share_chain_req_001",
        asset_code="000001.SH",
        asset_class="equity",
        direction="BUY",
        reason="趋势转强，申请继续执行持仓计划",
        expected_confidence=0.78,
        execution_target="SIMULATED",
        execution_status="executed",
        executed_at=now,
        execution_ref={"account_id": test_account.id, "trade_id": 1},
        unified_recommendation=recommendation,
        feature_snapshot=feature_snapshot,
    )
    DecisionResponseModel.objects.create(
        request=decision_request,
        approved=True,
        approval_reason="风控通过，允许执行",
        quota_status={"daily_remaining": 2},
        cooldown_status="ok",
        alternative_suggestions=["继续观察量能变化"],
    )

    response = client.post(f"/share/manage/{active_share_link.id}/refresh/")

    assert response.status_code == 302

    snapshot = ShareSnapshotModel.objects.filter(share_link=active_share_link).latest(
        "snapshot_version"
    )
    assert snapshot.decision_payload["items"][0]["asset_code"] == "000001.SH"
    assert snapshot.decision_payload["items"][0]["status"] == "executed"
    assert snapshot.decision_payload["items"][0]["get_status_display"] == "已执行"
    assert snapshot.decision_payload["items"][0]["rationale"] == "宏观和技术面共振，允许继续持有。"
    assert snapshot.decision_payload["items"][0]["invalidation_logic"] == "跌破 9.80 重新评估"
    assert snapshot.decision_payload["evidence"][0]["reason_codes"] == ["trend", "macro"]
    assert snapshot.decision_payload["evidence"][0]["regime"] == "risk_on"
    assert (
        snapshot.decision_payload["evidence"][0]["execution_ref"]["account_id"] == test_account.id
    )
