from pathlib import Path


def test_decision_workspace_templates_bind_simulated_accounts_and_step4_preview_mode():
    templates = [Path("core/templates/decision/workspace.html")]

    for template in templates:
        content = template.read_text(encoding="utf-8")

        assert "/api/account/accounts/" in content
        assert "/api/simulated-trading/accounts/" not in content
        assert "Array.isArray(data.accounts)" in content
        assert "acc.account_name" in content

    main_workspace = templates[0].read_text(encoding="utf-8")
    assert "active_only=false" in main_workspace
    assert 'id="workspace-account-selector"' in main_workspace
    assert "handleWorkspaceAccountChange()" in main_workspace
    assert "initializeDecisionWorkspace" in main_workspace
    assert "refreshWorkspaceDecisionLists()" in main_workspace
    assert "normalizeDecisionStepRequest" in main_workspace
    assert "canAccessDecisionStep" in main_workspace
    assert "syncDecisionFunnelGuardrails" in main_workspace
    assert "Step 4 仅用于查看推荐细节与风控预览" in main_workspace
    assert "approveRecommendation" not in main_workspace
    assert "rejectRecommendation" not in main_workspace
    assert "modal-portfolio-id" not in main_workspace
    assert 'class="workspace-shell"' in main_workspace
    assert 'id="workspace-position-list"' in main_workspace
    assert "loadWorkspaceAccountSnapshot()" in main_workspace
    assert 'hx-include="#workspace-account-selector"' in main_workspace
    assert "account_id: getSelectedWorkspaceAccountId()" in main_workspace
    assert "initializeLegacyWorkspace" not in main_workspace
    assert "currentTab" not in main_workspace


def test_decision_workspace_step_templates_show_account_context_as_system_level():
    environment = Path("core/templates/decision/steps/environment.html").read_text(
        encoding="utf-8"
    )
    direction = Path("core/templates/decision/steps/direction.html").read_text(
        encoding="utf-8"
    )
    sector = Path("core/templates/decision/steps/sector.html").read_text(encoding="utf-8")

    for content in [environment, direction, sector]:
        assert "data-workspace-account-name" in content

    assert "阶段 1: 宏观准入判断" in environment
    assert "只读判断" in environment
    assert "不在这里修改账户配置" in environment

    assert "阶段 2: 资产方向建议" in direction
    assert "建议风险敞口上限" in direction
    assert "不可在此处编辑" in direction
    assert "不是单笔交易限额" in direction
    assert "risk_budget_display_pct" in direction

    assert "系统级分析" in sector


def test_decision_workspace_step_templates_use_window_bound_actions():
    screen_template = Path("core/templates/decision/steps/screen.html").read_text(encoding="utf-8")
    plan_template = Path("core/templates/decision/steps/plan.html").read_text(encoding="utf-8")
    execute_template = Path("core/templates/decision/steps/execute.html").read_text(encoding="utf-8")
    workspace_template = Path("core/templates/decision/workspace.html").read_text(encoding="utf-8")

    assert "window.loadRecommendations()" in screen_template
    assert 'id="ignored-filter-toggle"' in screen_template
    assert "window.toggleIgnoredRecommendationsFilter()" in screen_template
    assert "window.loadTransitionPlanStep()" in plan_template
    assert "window.generateTransitionPlan()" in plan_template
    assert "window.saveTransitionPlan()" in plan_template
    assert "window.submitTransitionPlanForApproval()" in plan_template
    assert "window.loadExecutionPlanPanel()" in execute_template

    assert "Object.assign(window, {" in workspace_template
    assert "syncIgnoredRecommendationsFilterButton" in workspace_template
    assert "toggleIgnoredRecommendationsFilter," in workspace_template
    assert "include_ignored" in workspace_template
    assert "loadTransitionPlanStep," in workspace_template
    assert "generateTransitionPlan," in workspace_template
    assert "submitTransitionPlanForApproval," in workspace_template
    assert "纳入计划并前往 Step 5" in workspace_template


def test_decision_workspace_step6_is_execution_only():
    execute_template = Path("core/templates/decision/steps/execute.html").read_text(encoding="utf-8")

    assert "阶段 6: 审批执行" in execute_template
    assert "自动交易系统" in execute_template
    assert "审计与归因复盘" not in execute_template
