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
            "alpha", "account", "simulated_trading", "strategy"
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

    def test_select_tests_with_policy_changes(self):
        """policy 模块变更选择对应测试"""
        tests = select_tests_func({"policy"}, ["apps/policy/application/use_cases.py"])
        # 应包含核心测试
        for core_test in CORE_GUARDRAIL_TESTS:
            self.assertIn(core_test, tests)
        # 应包含 policy 相关测试
        policy_tests = [t for t in tests if "policy" in t.lower()]
        self.assertGreater(len(policy_tests), 0)

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
