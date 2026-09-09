"""Browser acceptance against real Django TUI and egress endpoints in a test database."""

import mimetypes
from pathlib import Path
from unittest.mock import Mock
from urllib.parse import urlsplit

import pytest
from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.db import connections
from django.test import Client
from playwright.sync_api import sync_playwright


@pytest.mark.django_db(transaction=True)
def test_egress_configuration_browser(settings, monkeypatch, tmp_path):
    settings.ALLOWED_HOSTS = ["testserver", "localhost"]
    settings.SECURE_SSL_REDIRECT = False
    settings.AGOMTRADEPRO_ENCRYPTION_KEY = "browser-test-encryption-only"
    monkeypatch.setenv("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    user = get_user_model().objects.create_user(username="egress-browser", is_staff=True)
    from apps.data_center.infrastructure.models import ProviderConfigModel

    provider = ProviderConfigModel.objects.create(
        name="Browser market provider", source_type="akshare", is_active=True
    )
    client = Client()
    client.force_login(user)
    from tests.playwright.runtime_compatibility import ensure_subprocess_event_loop_policy

    ensure_subprocess_event_loop_policy()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 1000})

            def serve(route):
                request = route.request
                target = urlsplit(request.url)
                if target.path.startswith("/static/"):
                    asset = finders.find(target.path.removeprefix("/static/"))
                    if asset:
                        route.fulfill(
                            body=Path(asset).read_bytes(),
                            content_type=mimetypes.guess_type(asset)[0]
                            or "application/octet-stream",
                        )
                    else:
                        route.fulfill(status=404, body="")
                    return
                response = client.generic(
                    request.method,
                    target.path + ("?" + target.query if target.query else ""),
                    data=request.post_data or "",
                    content_type=request.headers.get("content-type", "application/json"),
                )
                connections.close_all()
                route.fulfill(
                    status=response.status_code,
                    body=response.content,
                    headers={
                        key: value
                        for key, value in response.items()
                        if key.lower() not in {"content-length", "content-encoding"}
                    },
                )

            page.route("**/*", serve)
            page.goto(
                "http://testserver/tui/?screen=data-center.egress-config&action=data-center.egress-endpoint-create"
            )
            page.wait_for_load_state("networkidle")
            screen = client.get("/api/tui/screens/data-center.egress-config/").json()
            ui_key = next(
                a["ui_key"]
                for a in screen["actions"]
                if a["key"] == "data-center.egress-endpoint-create"
            )
            form = page.locator(f'form[data-action-ui-key="{ui_key}"]:visible').last
            form.wait_for(state="visible")
            for key, value in {
                "name": "Browser mainland exit",
                "region": "CN",
                "host": "frpc_egress_visitor",
                "port": "18080",
                "concurrency_limit": "2",
            }.items():
                form.locator(f'[name="{key}"]').fill(value)
            form.locator('[name="protocol"]').select_option("http")
            form.locator(".tui-action-button").click()
            page.locator("[data-confirm-action]").click()
            page.wait_for_load_state("networkidle")
            from apps.data_center.application import egress_service

            assert len(egress_service.list_endpoints()) == 1
            assert egress_service.list_endpoints()[0].name == "Browser mainland exit"
            assert egress_service.list_endpoints()[0].enabled is False
            page.goto("http://testserver/tui/?screen=data-center.egress-config")
            page.wait_for_load_state("networkidle")
            page.get_by_role("button", name="修改 Browser mainland exit", exact=True).click()
            edit_key = next(
                a["ui_key"]
                for a in screen["actions"]
                if a["key"] == "data-center.egress-endpoint-update"
            )
            edit = page.locator(f'form[data-action-ui-key="{edit_key}"]:visible').last
            assert (
                edit.locator('[name="name"]').input_value(timeout=5000) == "Browser mainland exit"
            )
            assert edit.locator('[name="host"]').input_value() == "frpc_egress_visitor"
            assert edit.locator('[name="port"]').input_value() == "18080"
            assert edit.locator('[name="password"]').input_value() == ""
            assert not edit.locator('[name="enabled"]').is_checked()
            edit.locator('[name="name"]').fill("Browser edited exit")
            edit.locator('[name="enabled"]').check()
            edit.locator(".tui-action-button").click()
            page.locator("[data-confirm-action]").click()
            page.wait_for_load_state("networkidle")
            assert egress_service.list_endpoints()[0].name == "Browser edited exit"
            assert egress_service.list_endpoints()[0].enabled is True
            assert page.get_by_text("Browser edited exit", exact=True).count() > 0
            page.get_by_role(
                "button", name="为 Browser market provider 新增规则", exact=True
            ).click()
            rule_key = next(
                a["ui_key"]
                for a in screen["actions"]
                if a["key"] == "data-center.egress-rule-create"
            )
            rule_form = page.locator(f'form[data-action-ui-key="{rule_key}"]:visible').last
            assert rule_form.locator('[name="provider_id"]').input_value() == str(provider.pk)
            for key, value in {
                "dataset_key": "equity.price.bar",
                "domain_pattern": "push2his.eastmoney.com",
                "deployment_region": "overseas",
                "fixed_egress_id": str(egress_service.list_endpoints()[0].id),
                "priority": "10",
            }.items():
                rule_form.locator(f'[name="{key}"]').fill(value)
            rule_form.locator('[name="strategy"]').select_option("fixed")
            rule_form.locator(".tui-action-button").click()
            page.locator("[data-confirm-action]").click()
            page.wait_for_load_state("networkidle")
            rule = egress_service.list_rules()[0]
            assert rule.enabled is False
            page.get_by_role("button", name=f"修改规则 {rule.rule_id}", exact=True).click()
            rule_edit_key = next(
                a["ui_key"]
                for a in screen["actions"]
                if a["key"] == "data-center.egress-rule-update"
            )
            rule_edit = page.locator(f'form[data-action-ui-key="{rule_edit_key}"]:visible').last
            assert rule_edit.locator('[name="strategy"]').input_value() == "fixed"
            assert rule_edit.locator('[name="dataset_key"]').input_value() == "equity.price.bar"
            assert not rule_edit.locator('[name="enabled"]').is_checked()
            rule_edit.locator('[name="enabled"]').check()
            rule_edit.locator(".tui-action-button").click()
            page.locator("[data-confirm-action]").click()
            page.wait_for_load_state("networkidle")
            assert egress_service.list_rules()[0].enabled is True
            page.screenshot(path=str(tmp_path / "egress-config.png"), full_page=True)
            transport = Mock()
            transport.request.return_value = egress_service.EgressTransportResult(
                outcome="failed",
                error_code="EGRESS_CONNECTION_FAILED",
                message="测试连接失败",
                retryable=False,
            )
            monkeypatch.setattr(egress_service, "_transport", transport)
            page.goto(
                "http://testserver/tui/?screen=data-center.egress-config&action=data-center.egress-diagnostics"
            )
            page.wait_for_load_state("networkidle")
            diag_key = next(
                a["ui_key"]
                for a in screen["actions"]
                if a["key"] == "data-center.egress-diagnostics"
            )
            page.get_by_text("展开诊断目标连接", exact=True).click()
            diag = page.locator(f'form[data-action-ui-key="{diag_key}"]:visible').last
            for key, value in {
                "provider_id": str(provider.pk),
                "dataset_key": "equity.price.bar",
                "url": "https://push2his.eastmoney.com/api/qt/stock/kline/get",
                "deployment_region": "overseas",
            }.items():
                diag.locator(f'[name="{key}"]').fill(value)
            diag.locator(".tui-action-button").click()
            page.locator("[data-confirm-action]").click()
            page.wait_for_load_state("networkidle")
            assert transport.request.call_count == 1
            assert "测试连接失败" in page.locator("[data-main-panel]").inner_text()
            assert "第 1 次" in page.locator("[data-main-panel]").inner_text()
            assert "未完成" in page.locator("[data-main-panel]").inner_text()
            print("Screenshot:", tmp_path / "egress-config.png")

        finally:
            browser.close()
            connections.close_all()
