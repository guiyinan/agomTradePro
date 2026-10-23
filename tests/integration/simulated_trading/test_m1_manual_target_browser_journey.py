"""Rendered owner journey for a manual target with confirmed strategy absence.

The browser uses a single-process Playwright route to Django's test Client. The
journey uses synthetic typed source fixtures and is local development evidence,
not live HTTP or production M1 acceptance.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from django.conf import settings
from django.db import connections
from django.test import Client
from playwright.sync_api import Browser, BrowserContext, Page, Route, sync_playwright

from apps.simulated_trading.infrastructure.models import (
    DailyInspectionReportModel,
    RebalanceProposalModel,
)
from apps.strategy.infrastructure.models import (
    PortfolioStrategyAssignmentModel,
    PositionManagementRuleModel,
    StrategyModel,
)
from apps.terminal.infrastructure.models import TerminalAuditLogORM
from apps.terminal.infrastructure.tui_adapters import TuiInternalActionExecutor
from tests.integration.simulated_trading import (
    test_m1_temporary_target_browser_journey as r2_browser,
)
from tests.playwright.runtime_compatibility import ensure_subprocess_event_loop_policy
from tests.support.account_authority_generation_flush import (
    preserve_account_authority_generation as preserve_account_authority_generation,
)
from tests.support.native_postgres_database import assert_native_postgres_test_database

pytestmark = pytest.mark.django_db(transaction=True)

owner_case = r2_browser.owner_case
ACTION_KEY = r2_browser.ACTION_KEY
SCREEN_KEY = r2_browser.SCREEN_KEY
DASHBOARD_PANEL_KEY = r2_browser.DASHBOARD_PANEL_KEY
ACTION_URL = r2_browser.ACTION_URL
ASSET_BUY = owner_case.ASSET_BUY
TARGET_TEXT = f"{ASSET_BUY},10"
EXPECTED_TARGET_WEIGHTS = {ASSET_BUY: "0.1"}
EXPECTED_CASH_REMAINDER = "0.9"
EVIDENCE_KIND = "local_synthetic_fixture_api_transport_development_evidence"


@pytest.fixture
def subprocess_policy() -> Iterator[None]:
    """Use the repository's Playwright-compatible Windows process policy."""

    original_policy = asyncio.get_event_loop_policy()
    changed = ensure_subprocess_event_loop_policy()
    try:
        yield
    finally:
        if changed:
            asyncio.set_event_loop_policy(original_policy)


def _account_configuration_snapshot() -> tuple[tuple[tuple[object, ...], ...], ...]:
    """Snapshot strategy, rule and assignment rows without changing them."""

    return tuple(
        r2_browser._model_rows_snapshot(model, filters={})
        for model in (
            StrategyModel,
            PositionManagementRuleModel,
            PortfolioStrategyAssignmentModel,
        )
    )


def _write_success_artifacts(
    *,
    repository_root: Path,
    screenshot: bytes,
    view_model: dict[str, Any],
    receipt: dict[str, object],
) -> Path:
    """Write a bounded synthetic receipt, rendered view model and viewport image."""

    run_key = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid4().hex[:8]
    run_directory = repository_root / ".tmp" / "m1-manual-target-browser-r9" / "runs" / run_key
    run_directory.mkdir(parents=True, exist_ok=False)
    (run_directory / "positive-first-viewport.png").write_bytes(screenshot)
    (run_directory / "actual-view-model.json").write_text(
        json.dumps(view_model, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (run_directory / "receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return run_directory


@pytest.mark.django_db(transaction=True)
def test_m1_local_empty_account_manual_buy_browser_owner_route_and_projector(
    monkeypatch: pytest.MonkeyPatch,
    subprocess_policy: None,
) -> None:
    """Render one 10% BUY preview for an ordinary owner with confirmed no strategy."""

    assert_native_postgres_test_database()
    monkeypatch.setenv("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    user, account = owner_case._create_owner_account(
        username=f"m1-manual-target-browser-r9-{uuid4().hex}",
        positions=(),
        cash=Decimal("100000.00"),
        max_position_pct=20.0,
        max_total_position_pct=95.0,
        stop_loss_pct=8.0,
    )
    assert user.is_staff is False
    assert user.is_superuser is False
    assert account.account_type == "simulated"
    assert not PortfolioStrategyAssignmentModel.objects.filter(
        portfolio_id=account.pk,
        is_active=True,
    ).exists()
    assert not PositionManagementRuleModel.objects.filter(
        metadata__account_id=account.pk,
        is_active=True,
    ).exists()

    monkeypatch.setattr(owner_case, "PRICE_SOURCE", "fixture-current-market-price")
    prices, identities, fees, quantity_rules = owner_case._install_preview_ports(
        monkeypatch,
        account=account,
        user_id=user.pk,
        classification_asset_types={ASSET_BUY: "equity"},
    )
    owner_calls: list[dict[str, Any]] = []
    browser_requests: list[dict[str, Any]] = []
    browser_idempotency_keys: list[str] = []
    browser_csrf_tokens: list[str] = []
    bootstrap_observations: list[dict[str, Any]] = []
    route_dispatches: list[dict[str, str | int | bool]] = []
    projector_calls: list[dict[str, Any]] = []
    page_errors: list[str] = []

    from apps.terminal.application import tui_workbench_result_models  # noqa: PLC0415
    from apps.terminal.application.tui_account_inspection_result import (  # noqa: PLC0415
        project_account_inspection_result as production_projector,
    )
    from apps.terminal.interface import api_views  # noqa: PLC0415

    def observed_projector(
        payload: object,
        *,
        requested_account_id: object,
        http_status: int,
    ) -> dict[str, object]:
        projected = production_projector(
            payload,
            requested_account_id=requested_account_id,
            http_status=http_status,
        )
        projector_calls.append(
            {
                "payload": payload,
                "requested_account_id": requested_account_id,
                "http_status": http_status,
                "projected": projected,
            }
        )
        return projected

    monkeypatch.setattr(
        tui_workbench_result_models,
        "project_account_inspection_result",
        observed_projector,
    )
    observed_executor = r2_browser._ObservedExecutor(TuiInternalActionExecutor(), owner_calls)
    monkeypatch.setattr(api_views, "get_tui_action_executor", lambda: observed_executor)

    financial_before = owner_case._financial_snapshot()
    report_count_before = DailyInspectionReportModel.objects.filter(account_id=account.pk).count()
    proposal_count_before = RebalanceProposalModel.objects.filter(account_id=account.pk).count()
    configuration_before = _account_configuration_snapshot()
    audit_before = r2_browser._model_rows_snapshot(
        TerminalAuditLogORM,
        filters={"user_id": user.pk, "command_name": ACTION_KEY},
    )

    client = Client(enforce_csrf_checks=True)
    client.force_login(user)
    host = "testserver"
    landing = client.get(f"/tui/?screen={SCREEN_KEY}", HTTP_HOST=host)
    assert landing.status_code == 200
    assert "agomtui-runtime-core.js" in landing.content.decode("utf-8")
    connections.close_all()
    repository_root = Path(settings.BASE_DIR).resolve()

    with sync_playwright() as playwright:
        browser: Browser = playwright.chromium.launch(headless=True)
        context: BrowserContext = browser.new_context(viewport={"width": 1440, "height": 1000})
        context.add_cookies(r2_browser._playwright_cookies(client, host=host))
        page: Page = context.new_page()
        page.on("pageerror", lambda error: page_errors.append(type(error).__name__))

        def dispatch_browser_request(route: Route) -> None:
            r2_browser._dispatch_browser_request(
                route,
                client=client,
                host=host,
                browser_requests=browser_requests,
                route_dispatches=route_dispatches,
                bootstrap_observations=bootstrap_observations,
                browser_idempotency_keys=browser_idempotency_keys,
                browser_csrf_tokens=browser_csrf_tokens,
            )

        page.route("**/*", dispatch_browser_request)
        try:
            page.goto(
                f"http://{host}/tui/?screen={SCREEN_KEY}",
                wait_until="networkidle",
            )
            assert any(
                observation["status"] == 200
                and observation["contract"] == "tui-bootstrap.v1"
                and observation["requested_screen"] == SCREEN_KEY
                and observation["resolved_screen"] == SCREEN_KEY
                and observation["screen_key"] == SCREEN_KEY
                for observation in bootstrap_observations
            )
            ui_key = r2_browser._action_ui_key(ACTION_KEY)
            action_form = page.locator(
                f'[data-main-panel] [data-dashboard-panel="{DASHBOARD_PANEL_KEY}"] '
                f'form[data-action-ui-key="{ui_key}"]'
            )
            assert action_form.count() == 1
            action_form.wait_for(state="visible")
            account_select = action_form.locator('select[name="account_id"]')
            option_values = account_select.locator("option").evaluate_all(
                "options => options.map(option => option.value).filter(Boolean)"
            )
            assert str(account.pk) in option_values
            assert account_select.locator(f'option[value="{account.pk}"]').count() == 1
            assert (
                account.account_name
                in account_select.locator(f'option[value="{account.pk}"]').inner_text()
            )
            account_select.select_option(str(account.pk))
            target_textarea = action_form.locator('textarea[name="temporary_target_weights"]')
            target_textarea.fill(TARGET_TEXT)
            assert target_textarea.input_value() == TARGET_TEXT
            form_keys = page.locator(
                f'[data-main-panel] [data-dashboard-panel="{DASHBOARD_PANEL_KEY}"] '
                "form[data-action-ui-key]"
            ).evaluate_all("forms => forms.map(form => form.dataset.actionUiKey)")
            assert form_keys == [ui_key]

            with page.expect_response(
                lambda response: urlsplit(response.url).path == ACTION_URL
            ) as confirm_response_info:
                action_form.locator(".tui-action-submit").click()
            confirm_response = confirm_response_info.value
            assert confirm_response.status == 200
            assert confirm_response.json()["confirmation_required"] is True
            assert owner_calls == []
            assert owner_case._financial_snapshot() == financial_before
            assert DailyInspectionReportModel.objects.filter(account_id=account.pk).count() == (
                report_count_before
            )
            assert RebalanceProposalModel.objects.filter(account_id=account.pk).count() == (
                proposal_count_before
            )

            confirmation = page.locator("[data-confirm-action]")
            confirmation.wait_for(state="visible")
            with page.expect_response(
                lambda response: urlsplit(response.url).path == ACTION_URL
            ) as result_response_info:
                confirmation.click()
            result_response = result_response_info.value
            assert result_response.status == 200
            envelope = result_response.json()
            assert envelope["outcome"] in {"success", "partial"}
            assert envelope["response"]["status_code"] == 200
            view_model = envelope["view_model"]
            assert isinstance(view_model, dict)
            assert view_model["kind"] == "detail"
            assert view_model["title"] == "账户调仓预览"
            assert view_model["business_summary"]
            assert view_model["status"]
            result_summary = page.locator("[data-main-panel] [data-task-result-summary]")
            result_summary.wait_for(state="visible")
            assert view_model["business_summary"] in result_summary.inner_text()
            assert action_form.count() == 0
            assert view_model.get("next_steps") == []
            assert page.locator("[data-main-panel] [data-next-step-index]").count() == 0
            assert len(owner_calls) == 1
            owner_call = owner_calls[0]
            assert owner_call["method"] == "POST"
            assert owner_call["endpoint"] == (
                f"/api/account/accounts/{account.pk}/inspections/run/"
            )
            assert owner_call["status_code"] == 200
            assert owner_call["body"]["temporary_target_weights"] == TARGET_TEXT
            assert "strategy_id" not in owner_call["body"]
            assert owner_call["body"].get("auto_create_proposal", False) is False
            assert len(browser_idempotency_keys) == 2
            assert all(browser_idempotency_keys)
            assert browser_csrf_tokens[-1]
            expected_key_hash = hashlib.sha256(
                browser_idempotency_keys[-1].encode("utf-8")
            ).hexdigest()
            assert owner_call["idempotency_key_sha256"] == expected_key_hash
            assert len(projector_calls) == 1
            projector_call = projector_calls[0]
            assert projector_call["requested_account_id"] == account.pk
            assert projector_call["http_status"] == 200
            assert projector_call["payload"] == owner_call["payload"]
            projected_sections = projector_call["projected"]["sections"]
            assert view_model["sections"][: len(projected_sections)] == projected_sections

            owner_payload = owner_call["payload"]
            assert isinstance(owner_payload, dict)
            report = owner_payload["reports"][0]
            plan = report["plan"]
            assert report["account_id"] == account.pk
            assert report["strategy_id"] is None
            assert report["position_rule_id"] is None
            assert report["strategy_selection_state"] == "confirmed_unconfigured"
            assert report["summary"]["temporary_target"]["target_weights"] == (
                EXPECTED_TARGET_WEIGHTS
            )
            assert report["summary"]["temporary_target"]["residual_cash_weight"] == (
                EXPECTED_CASH_REMAINDER
            )
            assert plan["plan_kind"] == "rebalance_preview"
            assert plan["read_only"] is True
            assert plan["execution_submitted"] is False
            assert plan["status"] == "ready"
            assert plan["funding_status"] == "known"
            assert plan["sell_before_buy"]["required"] is False
            risk_context = plan["risk_context"]
            assert risk_context["strategy_selection_state"] == "confirmed_unconfigured"
            assert risk_context["strategy_policy_applicability"] == "not_applicable"
            assert risk_context["strategy_max_position_pct"] is None
            assert risk_context["strategy_max_total_position_pct"] is None
            assert Decimal(str(risk_context["account_max_position_pct"])) == Decimal("20")
            assert Decimal(str(risk_context["account_max_total_position_pct"])) == Decimal("95")
            rows = {row["asset_code"]: row for row in plan["asset_items"]}
            assert set(rows) == {ASSET_BUY}
            buy = rows[ASSET_BUY]
            assert buy["target_mode"] == "user_target_difference"
            assert buy["action"] == "buy"
            assert buy["status"] == "ready"
            assert Decimal(buy["target_weight"]) == Decimal("0.1")
            assert Decimal(buy["suggested_quantity"]) > 0
            assert Decimal(buy["actionable_quantity"]) == Decimal(buy["suggested_quantity"])
            assert Decimal(buy["actionable_quantity"]) % Decimal("100") == 0
            assert buy["quantity_rule"]["rule_id"].startswith("fixture-")
            assert buy["quantity_rule"]["buy"]["step"] == "100"
            assert buy["classification_evidence"]["simulated_asset_type"] == "equity"
            assert buy["classification_evidence"]["must_not_use_for_decision"] is True
            assert buy["classification_evidence"]["must_not_execute"] is True
            assert buy["identity"]["must_not_use_for_decision"] is True
            assert buy["identity"]["must_not_execute"] is True
            assert buy["price_source"] == "fixture-current-market-price"
            assert buy["price_freshness"] == "realtime"
            assert buy["price_observed_at"] == prices.observed_at.isoformat()
            assert buy["price_observed_at"] != plan["as_of"]
            assert identities.calls
            assert quantity_rules.calls
            assert fees.calls

            fee = buy["fee"]
            fee_total = Decimal(fee["total"])
            fee_components = sum(
                (
                    Decimal(fee[key])
                    for key in ("commission", "transfer_fee", "stamp_duty", "slippage")
                ),
                Decimal("0"),
            )
            assert fee["policy_id"] == "m1-read-only-preview-fixture"
            assert fee["content_hash"]
            assert fee["transaction_case"]["asset_type"] == "equity"
            assert fee["transaction_case"]["side"] == "buy"
            assert fee_total == fee_components
            assert fee_total > 0
            assert Decimal(plan["cash_before"]) == Decimal("100000.00")
            assert Decimal(plan["available_cash_before"]) == Decimal("100000.00")
            assert Decimal(plan["estimated_buy_fees"]) == fee_total
            assert Decimal(plan["estimated_buy_total"]) == (
                Decimal(plan["estimated_buy_gross"]) + fee_total
            )
            assert Decimal(plan["projected_cash_after_buys"]) == (
                Decimal(plan["cash_before"]) - Decimal(plan["estimated_buy_total"])
            )

            sections = {section["key"]: section for section in view_model["sections"]}
            target_fields = r2_browser._field_map(sections["temporary_target_context"]["fields"])
            target_values = {field["label"]: field["value"] for field in target_fields.values()}
            assert target_values == {
                "目标来源": "用户本次填写；未保存为策略配置或自动交易规则",
                f"{ASSET_BUY} 目标比例": "10%",
                "未分配目标现金权重": "90%",
            }
            risk_fields = r2_browser._field_map(
                sections["selected_strategy_and_risk_limits"]["fields"]
            )
            assert risk_fields["strategy_selection"]["value"] == (
                "未配置；本次按你提供的目标估算差额"
            )
            assert risk_fields["strategy_max_position_pct"]["value"] == "不适用（未配置策略）"
            assert risk_fields["strategy_max_total_position_pct"]["value"] == (
                "不适用（未配置策略）"
            )
            assert Decimal(
                risk_fields["account_max_position_pct"]["value"].removesuffix("%")
            ) == Decimal("20")
            assert Decimal(
                risk_fields["account_max_total_position_pct"]["value"].removesuffix("%")
            ) == Decimal("95")
            assert Decimal(
                risk_fields["account_stop_loss_pct"]["value"].removesuffix("%")
            ) == Decimal("8")
            assert risk_fields["strategy_stop_loss_pct"]["value"] == "不适用（未配置策略）"

            quantity_rows = r2_browser._row_map(sections["asset_quantity_plan"]["rows"])
            buy_row = quantity_rows[ASSET_BUY]
            assert buy_row["direction"] == "建议增加"
            assert Decimal(buy_row["suggested"]) > 0
            assert Decimal(buy_row["actionable"]) > 0
            fee_rows = r2_browser._row_map(sections["asset_cost_identity_review"]["rows"])
            buy_fee_text = fee_rows[ASSET_BUY]["fees"]
            for term in ("佣金", "过户费", "印花税", "滑点估算", "费用合计"):
                assert term in buy_fee_text
            provenance_fields = r2_browser._field_map(sections["asset_source_times"]["fields"])
            classification_text = provenance_fields["classification"]["value"]
            assert "不可用于通用决策 是" in classification_text
            assert "禁止执行 是" in classification_text
            cash_fields = r2_browser._field_map(sections["cash_and_cost_estimates"]["fields"])
            for key in (
                "cash_before",
                "reserved_cash",
                "available_cash_before",
                "estimated_buy_fees",
                "estimated_buy_total",
                "projected_cash_after_buys",
            ):
                assert cash_fields[key]["value"] not in {"未提供", "格式未确认"}

            primary_fields = r2_browser._assert_primary_fields_in_first_viewport(page, view_model)
            assert "只读预览，未提交交易" in primary_fields["p0_scope_time"]["value"]
            top_fields = r2_browser._field_map(view_model.get("fields"))
            assert (
                top_fields["inspection_date"]["value"] in primary_fields["p0_scope_time"]["value"]
            )
            assert top_fields["as_of"]["value"] in primary_fields["p0_scope_time"]["value"]
            assert (
                provenance_fields["observed_at"]["value"]
                in primary_fields["p0_scope_time"]["value"]
            )
            snapshot_read_at = cash_fields.get("financial_snapshot_read_at", {}).get(
                "value", "未提供"
            )
            assert snapshot_read_at in primary_fields["p0_scope_time"]["value"]
            assert "10%" in primary_fields["p0_target_cash"]["value"]
            assert "90%" in primary_fields["p0_target_cash"]["value"]
            assert primary_fields["p0_first_asset"]["value"].find(ASSET_BUY) >= 0
            for key in (
                "direction",
                "current",
                "sellable",
                "target",
                "suggested",
                "actionable",
            ):
                assert buy_row[key] in primary_fields["p0_first_asset"]["value"]
            for key in (
                "available_cash_before",
                "estimated_sell_fees",
                "estimated_buy_fees",
                "projected_cash_after_buys",
            ):
                assert cash_fields[key]["value"] in primary_fields["p0_fees_cash"]["value"]
            assert "本次未提供" in primary_fields["p0_fees_cash"]["value"]
            assert "币种本次未提供" in primary_fields["p0_fees_cash"]["value"]
            assert (
                risk_fields["strategy_selection"]["value"]
                in primary_fields["p0_applicable_limits"]["value"]
            )
            for key in (
                "account_max_position_pct",
                "account_max_total_position_pct",
                "account_stop_loss_pct",
                "strategy_max_position_pct",
                "strategy_max_total_position_pct",
                "strategy_stop_loss_pct",
            ):
                assert risk_fields[key]["value"] in primary_fields["p0_applicable_limits"]["value"]
            assert top_fields["currency"]["value"] == "本次未提供"
            assert top_fields["risk_falsification"]["value"] == "本次响应未提供"

            main_panel = page.locator("[data-main-panel]")
            assert page.evaluate("() => window.scrollY") == 0
            assert main_panel.evaluate("element => element.scrollTop") == 0
            assert main_panel.locator("[data-detail-section][open]").count() == 0
            viewport = page.viewport_size
            assert viewport is not None
            for text in (view_model["business_summary"], view_model["status"]):
                locator = main_panel.get_by_text(text, exact=True).first
                locator.wait_for(state="visible")
                box = locator.bounding_box()
                assert box is not None
                assert box["width"] > 0 and box["height"] > 0
                assert 0 <= box["x"] and box["x"] + box["width"] <= viewport["width"]
                assert 0 <= box["y"] and box["y"] + box["height"] <= viewport["height"]
            first_viewport_screenshot = page.screenshot(
                full_page=False,
                animations="disabled",
            )

            action_posts = [
                request
                for request in browser_requests
                if request["method"] == "POST" and request["path"] == ACTION_URL
            ]
            assert len(action_posts) == 2
            assert action_posts[0]["json_body"] == {
                "params": {"account_id": account.pk, "temporary_target_weights": TARGET_TEXT},
                "confirmed": False,
            }
            assert action_posts[1]["json_body"]["confirmed"] is True
            assert action_posts[1]["json_body"]["params"] == {
                "account_id": account.pk,
                "temporary_target_weights": TARGET_TEXT,
            }

            # Only inspect detailed sections after preserving the unscrolled first viewport.
            for title in (
                "单标的数量建议",
                "单标的费用、来源与限制",
                "金额与资金估算",
                "本次采用的策略与风险限制",
                "本次临时目标",
                "单标的来源时间与依据",
            ):
                matched = False
                detail_sections = page.locator("[data-main-panel] [data-detail-section]")
                for index in range(detail_sections.count()):
                    detail = detail_sections.nth(index)
                    if title in detail.locator("summary").inner_text():
                        if detail.get_attribute("open") is None:
                            detail.locator("summary").click()
                        matched = True
                        break
                assert matched, f"Rendered preview section is missing: {title}"
            main_text = main_panel.inner_text()
            assert "未配置；本次按你提供的目标估算差额" in main_text
            assert "不适用（未配置策略）" in main_text
            assert "账户设置的单标的持仓上限" in main_text
            assert "账户设置的总持仓上限" in main_text
            assert "不可用于通用决策 是" in main_text
            assert "禁止执行 是" in main_text
            assert ASSET_BUY in main_text
            button_labels = page.locator("[data-main-panel] button").all_inner_texts()
            assert not any(
                any(token in label for token in ("下单", "买入", "卖出", "提交委托", "执行交易"))
                for label in button_labels
            )
            assert page_errors == []

            report_count_after_first = DailyInspectionReportModel.objects.filter(
                account_id=account.pk
            ).count()
            proposal_count_after_first = RebalanceProposalModel.objects.filter(
                account_id=account.pk
            ).count()
            financial_after_first = owner_case._financial_snapshot()
            configuration_after_first = _account_configuration_snapshot()
            audit_after_first = r2_browser._model_rows_snapshot(
                TerminalAuditLogORM,
                filters={"user_id": user.pk, "command_name": ACTION_KEY},
            )
            report_rows_after_first = r2_browser._model_rows_snapshot(
                DailyInspectionReportModel,
                filters={"account_id": account.pk},
            )
            report_updated_at_after_first = tuple(
                DailyInspectionReportModel._base_manager.filter(account_id=account.pk)
                .order_by("pk")
                .values_list("updated_at", flat=True)
            )
            assert financial_after_first == financial_before
            assert report_count_after_first == report_count_before + 1
            assert proposal_count_after_first == proposal_count_before
            assert configuration_after_first == configuration_before
            assert len(audit_after_first) == len(audit_before) + 2

            replay_key = browser_idempotency_keys[-1]
            replay_response = page.evaluate(
                """async ({actionUrl, requestBody, idempotencyKey, csrfToken}) => {
                    const response = await fetch(actionUrl, {
                        method: "POST",
                        credentials: "same-origin",
                        headers: {
                            "Content-Type": "application/json",
                            "X-CSRFToken": csrfToken,
                            "Idempotency-Key": idempotencyKey
                        },
                        body: JSON.stringify(requestBody)
                    });
                    let payload = {};
                    try { payload = await response.json(); } catch (_) {}
                    return {
                        status: response.status,
                        outcome: typeof payload.outcome === "string" ? payload.outcome : "",
                        confirmation_required: payload.confirmation_required === true,
                        view_model: payload && typeof payload.view_model === "object"
                            ? payload.view_model : null
                    };
                }""",
                {
                    "actionUrl": ACTION_URL,
                    "requestBody": action_posts[1]["json_body"],
                    "idempotencyKey": replay_key,
                    "csrfToken": browser_csrf_tokens[-1],
                },
            )
            assert replay_response["status"] == 200
            assert replay_response["outcome"] in {"success", "partial"}
            assert replay_response["confirmation_required"] is False
            assert len(browser_idempotency_keys) == 3
            assert browser_idempotency_keys[-1] == replay_key
            replay_view_model = replay_response["view_model"]
            assert isinstance(replay_view_model, dict)
            replay_sections = {section["key"]: section for section in replay_view_model["sections"]}
            replay_targets = r2_browser._field_map(
                replay_sections["temporary_target_context"]["fields"]
            )
            assert {field["label"]: field["value"] for field in replay_targets.values()} == (
                target_values
            )
            replay_owner_calls = owner_calls[1:]
            assert len(replay_owner_calls) in {0, 1}
            if replay_owner_calls:
                replay_owner_call = replay_owner_calls[0]
                assert replay_owner_call["endpoint"] == owner_call["endpoint"]
                assert replay_owner_call["status_code"] == 200
                assert replay_owner_call["idempotency_key_sha256"] == expected_key_hash
                assert replay_owner_call["body"]["temporary_target_weights"] == TARGET_TEXT
                assert "strategy_id" not in replay_owner_call["body"]
                replay_report = replay_owner_call["payload"]["reports"][0]
                assert replay_report["summary"]["temporary_target"]["target_weights"] == (
                    EXPECTED_TARGET_WEIGHTS
                )
                assert replay_report["summary"]["temporary_target"]["residual_cash_weight"] == (
                    EXPECTED_CASH_REMAINDER
                )

            report_count_after_replay = DailyInspectionReportModel.objects.filter(
                account_id=account.pk
            ).count()
            proposal_count_after_replay = RebalanceProposalModel.objects.filter(
                account_id=account.pk
            ).count()
            financial_after_replay = owner_case._financial_snapshot()
            configuration_after_replay = _account_configuration_snapshot()
            audit_after_replay = r2_browser._model_rows_snapshot(
                TerminalAuditLogORM,
                filters={"user_id": user.pk, "command_name": ACTION_KEY},
            )
            report_rows_after_replay = r2_browser._model_rows_snapshot(
                DailyInspectionReportModel,
                filters={"account_id": account.pk},
            )
            report_updated_at_after_replay = tuple(
                DailyInspectionReportModel._base_manager.filter(account_id=account.pk)
                .order_by("pk")
                .values_list("updated_at", flat=True)
            )
            assert report_count_after_replay == report_count_after_first
            assert proposal_count_after_replay == proposal_count_before
            assert financial_after_replay == financial_before
            assert configuration_after_replay == configuration_before

            return_to_workspace = page.locator(
                "[data-main-panel] [data-return-dashboard-workspace]"
            )
            return_to_workspace.wait_for(state="visible")
            assert return_to_workspace.inner_text().strip() == "返回账户调仓预览"
            owner_call_count_before_reentry = len(owner_calls)
            action_post_count_before_reentry = sum(
                request["method"] == "POST" and request["path"] == ACTION_URL
                for request in browser_requests
            )
            return_to_workspace.click()
            action_form.wait_for(state="visible")
            assert action_form.count() == 1
            account_select = action_form.locator('select[name="account_id"]')
            account_select.select_option(str(account.pk))
            target_textarea = action_form.locator('textarea[name="temporary_target_weights"]')
            target_textarea.fill(TARGET_TEXT)
            assert account_select.input_value() == str(account.pk)
            assert target_textarea.input_value() == TARGET_TEXT
            assert len(owner_calls) == owner_call_count_before_reentry
            assert (
                sum(
                    request["method"] == "POST" and request["path"] == ACTION_URL
                    for request in browser_requests
                )
                == action_post_count_before_reentry
            )

            _write_success_artifacts(
                repository_root=repository_root,
                screenshot=first_viewport_screenshot,
                view_model=view_model,
                receipt={
                    "evidence_kind": EVIDENCE_KIND,
                    "production_m1_acceptance": False,
                    "transport": "single-process Playwright route to Django test Client; not live HTTP",
                    "ordinary_owner": True,
                    "account_type": account.account_type,
                    "strategy_selection_state": report["strategy_selection_state"],
                    "strategy_policy_applicability": risk_context["strategy_policy_applicability"],
                    "target_weights": EXPECTED_TARGET_WEIGHTS,
                    "residual_cash_weight": EXPECTED_CASH_REMAINDER,
                    "buy_status": buy["status"],
                    "suggested_quantity": buy["suggested_quantity"],
                    "actionable_quantity": buy["actionable_quantity"],
                    "fee_total": fee["total"],
                    "projected_cash_after_buys": plan["projected_cash_after_buys"],
                    "first_viewport_screenshot": "positive-first-viewport.png",
                    "replay_observation": {
                        "same_idempotency_key_replayed": True,
                        "owner_call_count_after_replay": len(owner_calls),
                        "report_count_after_first": report_count_after_first,
                        "report_count_after_replay": report_count_after_replay,
                        "report_snapshot_changed": (
                            report_rows_after_replay != report_rows_after_first
                        ),
                        "report_updated_at_changed": (
                            report_updated_at_after_replay != report_updated_at_after_first
                        ),
                        "terminal_audit_count_after_first": len(audit_after_first),
                        "terminal_audit_count_after_replay": len(audit_after_replay),
                        "terminal_audit_snapshot_changed": audit_after_replay != audit_after_first,
                        "request_deduplication_claim": False,
                    },
                    "financial_ledgers_unchanged_after_replay": (
                        financial_after_replay == financial_before
                    ),
                    "proposal_count_before": proposal_count_before,
                    "proposal_count_after_first": proposal_count_after_first,
                    "proposal_count_after_replay": proposal_count_after_replay,
                    "strategy_configuration_unchanged_after_replay": (
                        configuration_after_replay == configuration_before
                    ),
                    "browser_page_errors": page_errors,
                },
            )
        finally:
            context.close()
            browser.close()
