"""Transport status must remain visible even when the HTTP envelope is successful."""

from apps.terminal.application.tui_egress_result import build_egress_result


def test_blocked_diagnostic_renders_failure_and_attempts_without_arbitrary_fields():
    result = build_egress_result(
        {
            "outcome": "blocked",
            "message": "出口尚未启用",
            "error_code": "EGRESS_DISABLED",
            "route": {"rule_id": 4, "strategy": "fixed", "egress_id": 3},
            "attempts": [
                {
                    "egress_id": 3,
                    "outcome": "blocked",
                    "error_code": "EGRESS_DISABLED",
                    "password": "never-render",
                }
            ],
            "password": "never-render",
        },
        title="测试出口",
        status_code=200,
    )
    assert result["status"] == "已阻断"
    assert result["blocking_reason"] == "出口尚未启用"
    fields = {field["key"]: field["value"] for field in result["fields"]}
    assert "出口 3" in fields["attempts"] and "阻断" in fields["attempts"]
    assert "never-render" not in str(result)


def test_preview_distinguishes_no_match_from_connection_success():
    result = build_egress_result(
        {"rule_id": None, "strategy": "direct", "egress_id": None, "reason": "no_matching_rule"},
        title="预览",
        status_code=200,
    )
    assert result["status"] == "路由预览"
    assert "连接成功" not in str(result)
    assert "默认直连路径" in str(result)


def test_success_retains_every_attempt_and_observed_time():
    result = build_egress_result(
        {
            "outcome": "success",
            "checked_at": "2026-09-09T00:00:00Z",
            "route": {"strategy": "direct_fallback", "egress_id": None},
            "attempts": [
                {"egress_id": None, "outcome": "failed", "latency_ms": 0},
                {"egress_id": 2, "outcome": "success", "observed_ip": "203.0.113.2"},
            ],
        },
        title="诊断",
        status_code=200,
    )
    assert result["status"] == "连接成功"
    fields = {field["key"]: field["value"] for field in result["fields"]}
    assert "第 1 次：直连 · 失败 · 0 ms" in fields["attempts"]
    assert "第 2 次：出口 2 · 成功" in fields["attempts"]
    assert fields["checked_at"] == "2026-09-09T00:00:00Z"


def test_saved_rule_receipt_names_dataset_and_enabled_state():
    from apps.terminal.application.tui_egress_result import build_egress_saved_result

    result = build_egress_saved_result(
        {
            "id": 1,
            "enabled": False,
            "dataset_key": "equity.price.bar",
            "strategy": "fixed",
            "strategy_label": "固定出口",
            "password": "hidden",
        },
        title="保存规则",
        status_code=201,
    )
    assert result["status"] == "已保存"
    assert {field["label"]: field["value"] for field in result["fields"]} == {
        "记录编号": "1",
        "启用状态": "否",
        "数据集": "equity.price.bar",
        "出网策略": "固定出口",
    }
    assert "hidden" not in str(result)
