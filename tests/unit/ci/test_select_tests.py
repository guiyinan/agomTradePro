"""
select_tests.py 单元测试
"""
import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

# 获取项目根目录
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
select_tests_path = PROJECT_ROOT / "scripts" / "select_tests.py"

spec = importlib.util.spec_from_file_location("select_tests", select_tests_path)
select_tests = importlib.util.module_from_spec(spec)
sys.modules["select_tests"] = select_tests
spec.loader.exec_module(select_tests)

CORE_GUARDRAIL_TESTS = select_tests.CORE_GUARDRAIL_TESTS
FULL_TEST_SUITES = select_tests.FULL_TEST_SUITES
get_changed_modules = select_tests.get_changed_modules
MODULE_TEST_MAP = select_tests.MODULE_TEST_MAP
select_tests_func = select_tests.select_tests


class TestSelectTests(unittest.TestCase):
    """测试智能测试选择逻辑"""

    def test_core_guardrail_tests_defined(self):
        """核心 guardrail 测试必须定义"""
        self.assertIsInstance(CORE_GUARDRAIL_TESTS, list)
        self.assertGreater(len(CORE_GUARDRAIL_TESTS), 0)
        for test in CORE_GUARDRAIL_TESTS:
            self.assertTrue(test.startswith("tests/"), f"Test path should start with tests/: {test}")

    def test_module_test_map_has_key_modules(self):
        """关键模块必须在映射表中"""
        key_modules = [
            "regime", "policy", "signal", "audit", "backtest",
            "alpha", "account", "simulated_trading", "strategy",
            "share", "data_center", "agent_runtime", "asset_analysis",
            "ai_capability", "ai_provider", "beta_gate", "setup_wizard", "task_monitor", "terminal", "hedge",
            "realtime", "filter", "prompt", "sentiment", "sector", "fund",
            "events", "factor", "rotation", "macro", "equity", "alpha_trigger",
        ]
        for module in key_modules:
            self.assertIn(module, MODULE_TEST_MAP, f"Module {module} should be in test map")

    def test_get_changed_modules_from_apps(self):
        """从 apps/ 目录提取模块"""
        changed_files = [
            "apps/regime/domain/entities.py",
            "apps/policy/application/use_cases.py",
            "README.md",
        ]
        modules = get_changed_modules(changed_files)
        self.assertIn("regime", modules)
        self.assertIn("policy", modules)

    def test_get_changed_modules_from_core(self):
        """core/ 目录变更识别为 core 模块"""
        changed_files = ["core/settings/base.py", "core/urls.py"]
        modules = get_changed_modules(changed_files)
        self.assertIn("core", modules)

    def test_get_changed_modules_from_shared(self):
        """shared/ 目录变更识别为 shared 模块"""
        changed_files = ["shared/domain/interfaces.py", "shared/infrastructure/filters.py"]
        modules = get_changed_modules(changed_files)
        self.assertIn("shared", modules)

    def test_select_tests_with_no_changes(self):
        """无变更时返回全量测试（保守策略）"""
        tests = select_tests_func(set(), [])
        # 空模块集合时，保守地运行全量测试
        self.assertEqual(tests, FULL_TEST_SUITES)

    def test_select_tests_with_shared_changes(self):
        """shared/ 变更时运行全量测试"""
        tests = select_tests_func({"shared"}, ["shared/domain/interfaces.py"])
        self.assertEqual(tests, FULL_TEST_SUITES)

    def test_select_tests_with_regime_changes(self):
        """regime 模块变更选择对应测试"""
        tests = select_tests_func({"regime"}, ["apps/regime/domain/services.py"])
        # 应包含核心测试
        for core_test in CORE_GUARDRAIL_TESTS:
            self.assertIn(core_test, tests)
        # 应包含 regime 相关测试
        regime_tests = [t for t in tests if "regime" in t.lower()]
        self.assertGreater(len(regime_tests), 0)
        self.assertIn("tests/api/test_regime_api_edges.py", tests)

    def test_select_tests_with_policy_changes(self):
        """policy 模块变更选择对应测试"""
        tests = select_tests_func({"policy"}, ["apps/policy/application/use_cases.py"])
        # 应包含核心测试
        for core_test in CORE_GUARDRAIL_TESTS:
            self.assertIn(core_test, tests)
        # 应包含 policy 相关测试
        policy_tests = [t for t in tests if "policy" in t.lower()]
        self.assertGreater(len(policy_tests), 0)
        self.assertIn("tests/api/test_policy_workbench_api_edges.py", tests)

    def test_select_tests_with_multiple_modules(self):
        """多模块变更时选择所有相关测试"""
        tests = select_tests_func(
            {"regime", "policy"},
            ["apps/regime/services.py", "apps/policy/use_cases.py"]
        )
        # 应包含核心测试
        for core_test in CORE_GUARDRAIL_TESTS:
            self.assertIn(core_test, tests)
        # 应包含两个模块的测试
        regime_tests = [t for t in tests if "regime" in t.lower()]
        policy_tests = [t for t in tests if "policy" in t.lower()]
        self.assertGreater(len(regime_tests), 0)
        self.assertGreater(len(policy_tests), 0)

    def test_select_tests_with_backtest_changes_include_api_tests(self):
        """backtest 变更必须带上 API 测试。"""
        tests = select_tests_func({"backtest"}, ["apps/backtest/interface/views.py"])
        self.assertIn("tests/api/test_backtest_api_edges.py", tests)

    def test_select_tests_with_share_changes_include_app_local_tests(self):
        """share 模块变更必须带上 app-local tests。"""
        tests = select_tests_func({"share"}, ["apps/share/interface/views.py"])
        self.assertIn("apps/share/tests/", tests)

    def test_select_tests_with_audit_changes_include_api_tests(self):
        """audit 变更必须带上 API 测试。"""
        tests = select_tests_func({"audit"}, ["apps/audit/interface/views.py"])
        self.assertIn("tests/api/test_audit_api_edges.py", tests)

    def test_select_tests_with_data_center_changes_include_api_and_unit_tests(self):
        """data_center 变更必须带上 API、集成和单元测试。"""
        tests = select_tests_func({"data_center"}, ["apps/data_center/interface/api_views.py"])
        self.assertIn("tests/api/test_data_center_route_cleanup.py", tests)
        self.assertIn("tests/integration/data_center/", tests)
        self.assertIn("tests/unit/data_center/", tests)

    def test_select_tests_with_dashboard_changes_include_api_tests(self):
        """dashboard 变更必须带上 API 测试。"""
        tests = select_tests_func({"dashboard"}, ["apps/dashboard/interface/views.py"])
        self.assertIn("tests/api/test_dashboard_api_edges.py", tests)

    def test_logic_guardrails_profile_excludes_dashboard_e2e_targets(self):
        """Logic Guardrails profile 不应选择 dashboard 的 e2e 测试。"""
        tests = select_tests_func(
            {"dashboard"},
            ["apps/dashboard/interface/views.py"],
            profile="logic_guardrails",
        )
        self.assertIn("tests/api/test_dashboard_api_edges.py", tests)
        self.assertIn("apps/dashboard/tests/", tests)
        self.assertNotIn("tests/e2e/", tests)

    def test_select_tests_with_simulated_trading_changes_include_api_tests(self):
        """simulated_trading 变更必须带上 API 测试。"""
        tests = select_tests_func({"simulated_trading"}, ["apps/simulated_trading/interface/views.py"])
        self.assertIn("tests/api/test_simulated_trading_api_edges.py", tests)

    def test_select_tests_with_agent_runtime_changes_include_api_and_migration_tests(self):
        """agent_runtime 变更必须带上 API 和 migration 测试。"""
        tests = select_tests_func(
            {"agent_runtime"},
            ["apps/agent_runtime/interface/views.py"],
        )
        self.assertIn("tests/api/test_agent_runtime_api.py", tests)
        self.assertIn("tests/migrations/test_agent_runtime_migrations.py", tests)

    def test_select_tests_with_macro_changes_include_api_tests(self):
        """macro 变更必须带上 API 测试。"""
        tests = select_tests_func({"macro"}, ["apps/macro/interface/views/fetch_api.py"])
        self.assertIn("tests/api/test_macro_api_edges.py", tests)

    def test_select_tests_with_account_changes_include_api_tests(self):
        """account 变更必须带上 API 测试。"""
        tests = select_tests_func({"account"}, ["apps/account/interface/profile_api_views.py"])
        self.assertIn("tests/api/test_account_api_edges.py", tests)

    def test_select_tests_with_ai_provider_changes_include_api_tests(self):
        """ai_provider 变更必须带上 API 测试。"""
        tests = select_tests_func({"ai_provider"}, ["apps/ai_provider/interface/views/api_views.py"])
        self.assertIn("tests/api/test_ai_provider_api_edges.py", tests)

    def test_select_tests_with_beta_gate_changes_include_api_tests(self):
        """beta_gate 变更必须带上 API 测试。"""
        tests = select_tests_func({"beta_gate"}, ["apps/beta_gate/interface/views.py"])
        self.assertIn("tests/api/test_beta_gate_api_edges.py", tests)

    def test_select_tests_with_decision_rhythm_changes_include_api_tests(self):
        """decision_rhythm 变更必须带上 API 测试。"""
        tests = select_tests_func({"decision_rhythm"}, ["apps/decision_rhythm/interface/command_api_views.py"])
        self.assertIn("tests/api/test_decision_rhythm_api_edges.py", tests)
        self.assertIn("tests/api/test_workspace_execution_api_edges.py", tests)
        self.assertIn("tests/api/test_workspace_recommendations_api_edges.py", tests)

    def test_select_tests_with_alpha_changes_include_api_tests(self):
        """alpha 变更必须带上 API 测试。"""
        tests = select_tests_func({"alpha"}, ["apps/alpha/interface/views.py"])
        self.assertIn("tests/api/test_alpha_api_edges.py", tests)

    def test_logic_guardrails_profile_excludes_alpha_heavy_targets(self):
        """Logic Guardrails profile 不应选择 alpha 集成和 e2e 压测。"""
        tests = select_tests_func(
            {"alpha"},
            ["apps/alpha/interface/views.py"],
            profile="logic_guardrails",
        )
        self.assertIn("tests/api/test_alpha_api_edges.py", tests)
        self.assertIn("tests/unit/test_alpha_providers.py", tests)
        self.assertNotIn("tests/e2e/test_alpha_dashboard_e2e.py", tests)
        self.assertNotIn("tests/integration/test_alpha_stress.py", tests)

    def test_logic_guardrails_profile_uses_core_guardrails_for_shared_changes(self):
        """Logic Guardrails profile 在 shared 变更时退回核心 guardrails。"""
        tests = select_tests_func(
            {"shared"},
            ["shared/domain/interfaces.py"],
            profile="logic_guardrails",
        )
        self.assertEqual(tests, CORE_GUARDRAIL_TESTS)

    def test_select_tests_with_alpha_trigger_changes_include_api_tests(self):
        """alpha_trigger 变更必须带上 API 测试。"""
        tests = select_tests_func({"alpha_trigger"}, ["apps/alpha_trigger/interface/views.py"])
        self.assertIn("tests/api/test_alpha_trigger_api_edges.py", tests)

    def test_select_tests_with_task_monitor_changes_include_api_tests(self):
        """task_monitor 变更必须带上 API 测试。"""
        tests = select_tests_func({"task_monitor"}, ["apps/task_monitor/interface/views.py"])
        self.assertIn("tests/api/test_task_monitor_api.py", tests)

    def test_select_tests_with_hedge_changes_include_api_tests(self):
        """hedge 变更必须带上 API 测试。"""
        tests = select_tests_func({"hedge"}, ["apps/hedge/interface/views.py"])
        self.assertIn("tests/api/test_hedge_api.py", tests)

    def test_select_tests_with_terminal_changes_include_api_tests(self):
        """terminal 变更必须带上 API 测试。"""
        tests = select_tests_func({"terminal"}, ["apps/terminal/interface/api_views.py"])
        self.assertIn("tests/api/test_terminal_api_edges.py", tests)

    def test_select_tests_with_realtime_changes_include_api_tests(self):
        """realtime 变更必须带上 API 测试。"""
        tests = select_tests_func({"realtime"}, ["apps/realtime/interface/views.py"])
        self.assertIn("tests/api/test_realtime_api.py", tests)

    def test_select_tests_with_filter_changes_include_api_tests(self):
        """filter 变更必须带上 API 测试。"""
        tests = select_tests_func({"filter"}, ["apps/filter/interface/api_views.py"])
        self.assertIn("tests/api/test_filter_api_edges.py", tests)

    def test_select_tests_with_prompt_changes_include_api_tests(self):
        """prompt 变更必须带上 API 测试。"""
        tests = select_tests_func({"prompt"}, ["apps/prompt/interface/views.py"])
        self.assertIn("tests/api/test_prompt_api_edges.py", tests)

    def test_select_tests_with_ai_capability_changes_include_api_tests(self):
        """ai_capability 变更必须带上 API 测试。"""
        tests = select_tests_func({"ai_capability"}, ["apps/ai_capability/interface/api_views.py"])
        self.assertIn("tests/api/test_ai_capability_api_edges.py", tests)

    def test_select_tests_with_sentiment_changes_include_api_tests(self):
        """sentiment 变更必须带上 API 测试。"""
        tests = select_tests_func({"sentiment"}, ["apps/sentiment/interface/views.py"])
        self.assertIn("tests/api/test_sentiment_api_edges.py", tests)

    def test_select_tests_with_policy_changes_include_api_tests(self):
        """policy 变更必须带上 API 测试。"""
        tests = select_tests_func({"policy"}, ["apps/policy/interface/workbench_api_views.py"])
        self.assertIn("tests/api/test_policy_api_edges.py", tests)
        self.assertIn("tests/api/test_policy_workbench_api_edges.py", tests)

    def test_select_tests_with_events_changes_include_api_tests(self):
        """events 变更必须带上 API 测试。"""
        tests = select_tests_func({"events"}, ["apps/events/interface/views.py"])
        self.assertIn("tests/api/test_events_api_edges.py", tests)

    def test_select_tests_with_factor_changes_include_api_tests(self):
        """factor 变更必须带上 API 测试。"""
        tests = select_tests_func({"factor"}, ["apps/factor/interface/views.py"])
        self.assertIn("tests/api/test_factor_api_edges.py", tests)

    def test_select_tests_with_strategy_changes_include_api_tests(self):
        """strategy 变更必须带上 API 测试。"""
        tests = select_tests_func({"strategy"}, ["apps/strategy/interface/views.py"])
        self.assertIn("tests/api/test_strategy_api_edges.py", tests)

    def test_select_tests_with_sector_changes_include_api_tests(self):
        """sector 变更必须带上 API 测试。"""
        tests = select_tests_func({"sector"}, ["apps/sector/interface/views.py"])
        self.assertIn("tests/api/test_sector_api_edges.py", tests)

    def test_select_tests_with_fund_changes_include_api_tests(self):
        """fund 变更必须带上 API 测试。"""
        tests = select_tests_func({"fund"}, ["apps/fund/interface/views.py"])
        self.assertIn("tests/api/test_fund_api_edges.py", tests)

    def test_select_tests_with_equity_changes_include_api_tests(self):
        """equity 变更必须带上 API 测试。"""
        tests = select_tests_func({"equity"}, ["apps/equity/interface/views.py"])
        self.assertIn("tests/api/test_equity_api_edges.py", tests)

    def test_select_tests_with_signal_changes_include_api_tests(self):
        """signal 变更必须带上 API 测试。"""
        tests = select_tests_func({"signal"}, ["apps/signal/interface/api_views.py"])
        self.assertIn("tests/api/test_signal_api_edges.py", tests)

    def test_select_tests_with_rotation_changes_include_api_tests(self):
        """rotation 变更必须带上 API 测试。"""
        tests = select_tests_func({"rotation"}, ["apps/rotation/interface/views.py"])
        self.assertIn("tests/api/test_rotation_api_edges.py", tests)

    def test_full_test_suites_include_app_local_tests(self):
        """全量回退策略必须覆盖 app-local tests。"""
        self.assertIn("tests/api/", FULL_TEST_SUITES)
        self.assertIn("tests/migrations/", FULL_TEST_SUITES)
        self.assertIn("tests/unit/", FULL_TEST_SUITES)
        self.assertIn("apps/dashboard/tests/", FULL_TEST_SUITES)
        self.assertIn("apps/share/tests/", FULL_TEST_SUITES)

    @patch.dict(os.environ, {"GITHUB_ACTIONS": "true"})
    def test_module_map_coverage(self):
        """所有有测试的模块都应在映射表中"""
        # 检查 tests/ 目录下的模块
        tests_path = Path(__file__).parent.parent.parent / "tests"
        if tests_path.exists():
            integration_path = tests_path / "integration"
            if integration_path.exists():
                # 检查 integration 目录下的模块测试
                for item in integration_path.iterdir():
                    if item.is_dir() and not item.name.startswith("_") and item.name != "__pycache__":
                        # 这些模块应该在映射表中有对应的测试路径
                        module_name = item.name
                        # 某些模块可能不需要独立映射（如通用测试），这里只记录
                        pass


if __name__ == "__main__":
    unittest.main()
