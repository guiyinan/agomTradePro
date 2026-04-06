#!/usr/bin/env python
"""
根据 git diff 选择相关测试

用法:
    python scripts/select_tests.py --base origin/main --head HEAD
    python scripts/select_tests.py --changed-modules regime,policy

输出:
    空格分隔的测试路径列表，适合直接传给 pytest
"""

import argparse
import glob
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Set


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_LOCAL_TEST_DIRS = sorted(
    f"{path.relative_to(PROJECT_ROOT).as_posix()}/"
    for path in (PROJECT_ROOT / "apps").glob("*/tests")
    if path.is_dir()
)


# 模块到测试的映射表
MODULE_TEST_MAP: Dict[str, List[str]] = {
    # 核心模块 - 这些变更运行更多测试
    "core": [
        "tests/guardrails/",
    ],

    # 宏观相关
    "macro": [
        "tests/api/test_macro_api_edges.py",
        "tests/integration/macro/",
        "tests/unit/domain/test_macro_entities.py",
    ],

    # Regime 模块
    "regime": [
        "tests/api/test_regime_action_api.py",
        "tests/api/test_regime_navigator_api.py",
        "tests/api/test_regime_api_edges.py",
        "tests/unit/regime/",
        "tests/integration/regime/",
        "tests/unit/regime/test_config_threshold_regression.py",
    ],

    # Policy 模块
    "policy": [
        "tests/api/test_policy_api_edges.py",
        "tests/api/test_policy_workbench_api_edges.py",
        "tests/unit/policy/",
        "tests/integration/policy/",
    ],

    # Signal 模块
    "signal": [
        "tests/integration/signal/",
    ],

    # Audit 模块
    "audit": [
        "tests/api/test_audit_api_edges.py",
        "tests/integration/audit/",
        "tests/unit/domain/audit/",
        "tests/unit/application/audit/",
    ],

    # Backtest 模块
    "backtest": [
        "tests/api/test_backtest_api_edges.py",
        "tests/integration/backtest/",
        "tests/integration/test_backtesting_flow.py",
        "tests/unit/domain/test_backtest_services.py",
    ],

    # Alpha 模块
    "alpha": [
        "tests/api/test_alpha_api_edges.py",
        "tests/integration/test_alpha_*.py",
        "tests/unit/test_alpha*.py",
        "tests/e2e/test_alpha_dashboard_e2e.py",
    ],

    "alpha_trigger": [
        "tests/api/test_alpha_trigger_api_edges.py",
        "tests/unit/test_alpha_trigger*.py",
    ],

    # Account 模块
    "account": [
        "tests/api/test_account_api_edges.py",
        "tests/integration/account/",
        "tests/integration/test_account_*.py",
        "tests/integration/test_unified_account_api.py",
        "tests/unit/test_account*.py",
    ],

    # Agent Runtime
    "agent_runtime": [
        "tests/api/test_agent_runtime_api.py",
        "tests/migrations/test_agent_runtime_migrations.py",
        "tests/unit/agent_runtime/",
        "tests/unit/test_agent_runtime*.py",
    ],

    # AI Capability
    "ai_capability": [
        "tests/api/test_ai_capability_api_edges.py",
        "tests/unit/test_ai_capability/",
    ],

    # AI Provider
    "ai_provider": [
        "tests/api/test_ai_provider_api_edges.py",
        "tests/unit/test_ai_provider*.py",
        "tests/unit/domain/test_ai_provider*.py",
    ],

    # Simulated Trading
    "simulated_trading": [
        "tests/api/test_simulated_trading_api_edges.py",
        "tests/integration/simulated_trading/",
        "tests/unit/domain/simulated_trading/",
    ],

    # Strategy
    "strategy": [
        "tests/api/test_strategy_api_edges.py",
        "tests/integration/strategy/",
        "tests/unit/domain/strategy/",
        "tests/unit/strategy/",
    ],

    # Equity
    "equity": [
        "tests/api/test_equity_api_edges.py",
        "tests/integration/test_equity_*.py",
        "tests/unit/equity/",
        "tests/unit/test_equity*.py",
        "tests/unit/domain/test_equity*.py",
    ],

    # Fund
    "fund": [
        "tests/api/test_fund_api_edges.py",
        "tests/integration/test_fund_*.py",
        "tests/unit/domain/test_fund*.py",
    ],

    # Beta Gate
    "beta_gate": [
        "tests/api/test_beta_gate_api_edges.py",
        "tests/unit/test_beta_gate*.py",
    ],

    # Decision Rhythm
    "decision_rhythm": [
        "tests/api/test_decision_rhythm_api_edges.py",
        "tests/api/test_workspace_execution_api_edges.py",
        "tests/api/test_workspace_recommendations_api_edges.py",
        "tests/unit/decision_rhythm/",
        "tests/unit/test_decision_rhythm*.py",
        "tests/unit/test_decision_workspace*.py",
        "tests/guardrails/test_decision_rhythm_api_error_mapping.py",
    ],

    # Events
    "events": [
        "tests/api/test_events_api_edges.py",
        "tests/integration/events/",
        "tests/unit/domain/test_events_services.py",
    ],

    # Factor
    "factor": [
        "tests/api/test_factor_api_edges.py",
        "tests/integration/test_factor_*.py",
        "tests/unit/domain/test_factor*.py",
    ],

    # Asset Analysis
    "asset_analysis": [
        "tests/integration/asset_analysis/",
        "tests/integration/test_*asset_analysis*.py",
        "tests/unit/test_asset_analysis.py",
    ],

    # Filter
    "filter": [
        "tests/api/test_filter_api_edges.py",
        "tests/api/test_macro_filter_compat_api.py",
        "tests/unit/domain/test_filter*.py",
    ],

    # Hedge
    "hedge": [
        "tests/api/test_hedge_api.py",
        "tests/unit/domain/test_hedge*.py",
    ],

    # Prompt
    "prompt": [
        "tests/api/test_prompt_api_edges.py",
        "tests/unit/domain/test_prompt*.py",
    ],

    # Pulse
    "pulse": [
        "tests/api/test_pulse_api.py",
    ],

    # Realtime
    "realtime": [
        "tests/api/test_realtime_api.py",
        "tests/integration/test_realtime_*.py",
        "tests/unit/test_realtime*.py",
    ],

    # Sector
    "sector": [
        "tests/api/test_sector_api_edges.py",
        "tests/unit/sector/",
        "tests/unit/domain/test_sector*.py",
    ],

    # Setup Wizard
    "setup_wizard": [
        "tests/integration/test_setup_wizard*.py",
        "tests/unit/test_setup_wizard*.py",
    ],

    # Task Monitor
    "task_monitor": [
        "tests/api/test_task_monitor_api.py",
        "tests/unit/test_task_monitor.py",
    ],

    # Terminal
    "terminal": [
        "tests/api/test_terminal_api_edges.py",
        "tests/unit/test_terminal*.py",
    ],

    # Dashboard
    "dashboard": [
        "tests/api/test_dashboard_api_edges.py",
        "apps/dashboard/tests/",
        "tests/e2e/",
    ],

    # Data Center
    "data_center": [
        "tests/api/test_data_center_route_cleanup.py",
        "tests/integration/data_center/",
        "tests/unit/data_center/",
    ],

    # Share
    "share": [
        "apps/share/tests/",
    ],

    # Sentiment
    "sentiment": [
        "tests/api/test_sentiment_api_edges.py",
        "tests/unit/test_sentiment*.py",
        "tests/unit/domain/test_sentiment*.py",
    ],

    # Rotation
    "rotation": [
        "tests/api/test_rotation_api_edges.py",
        "tests/unit/test_rotation_integration_service.py",
        "tests/unit/domain/test_rotation*.py",
    ],

    # Signal
    "signal": [
        "tests/api/test_signal_api_edges.py",
        "tests/integration/signal/",
        "tests/unit/domain/test_signal*.py",
    ],
}

# 始终运行的核心测试（无论哪个模块变更）
CORE_GUARDRAIL_TESTS = [
    "tests/guardrails/test_architecture_boundaries.py",
    "tests/guardrails/test_logic_guardrails.py",
    "tests/guardrails/test_no_501_on_primary_paths.py",
    "tests/guardrails/test_security_hardening_guardrails.py",
    "tests/guardrails/test_api_contract_minimal.py",  # API 合同最小集测试
]

# 全量测试路径（当无法确定范围或检测到广泛变更时使用）
FULL_TEST_SUITES = [
    "tests/api/",
    "tests/migrations/",
    "tests/unit/",
    "tests/guardrails/",
    "tests/integration/",
] + APP_LOCAL_TEST_DIRS


def get_app_local_tests(module: str) -> List[str]:
    """Return app-local pytest directories for a changed module."""
    app_tests_dir = PROJECT_ROOT / "apps" / module / "tests"
    if not app_tests_dir.exists():
        return []
    return [f"{app_tests_dir.relative_to(PROJECT_ROOT).as_posix()}/"]


def get_changed_files(base: str, head: str) -> List[str]:
    """获取变更的文件列表"""
    try:
        cmd = ["git", "diff", "--name-only", f"{base}...{head}"]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        files = result.stdout.strip().split("\n")
        return [f for f in files if f]
    except subprocess.CalledProcessError:
        # 如果 git 命令失败，返回空列表（默认运行全量）
        return []


def get_changed_modules(changed_files: List[str]) -> Set[str]:
    """从变更文件提取模块名"""
    modules = set()

    for f in changed_files:
        parts = Path(f).parts

        # apps/ 下的模块
        if len(parts) >= 2 and parts[0] == "apps":
            modules.add(parts[1])

        # core/ 变更视为核心模块
        if len(parts) >= 1 and parts[0] == "core":
            modules.add("core")

        # shared/ 变更
        if len(parts) >= 1 and parts[0] == "shared":
            modules.add("shared")

        # CI 配置变更
        if ".github" in parts:
            modules.add("ci")

    return modules


def select_tests(modules: Set[str], changed_files: List[str]) -> List[str]:
    """
    根据变更的模块选择相关测试

    Args:
        modules: 变更的模块集合
        changed_files: 变更的文件列表

    Returns:
        测试路径列表
    """
    tests = set()

    # 始终添加核心 guardrail 测试
    tests.update(CORE_GUARDRAIL_TESTS)

    # 如果没有检测到模块变更，运行全量测试
    if not modules:
        return FULL_TEST_SUITES

    # CI 配置变更 -> 运行全量测试
    if "ci" in modules or ".github" in str(changed_files):
        return FULL_TEST_SUITES

    # shared/ 变变更 -> 运行全量测试（影响所有模块）
    if "shared" in modules:
        return FULL_TEST_SUITES

    # core/ 变更 -> 运行 guardrail 测试
    if "core" in modules:
        tests.update(MODULE_TEST_MAP.get("core", []))

    # 根据模块映射选择测试
    for module in modules:
        tests.update(get_app_local_tests(module))
        if module in MODULE_TEST_MAP:
            module_tests = MODULE_TEST_MAP[module]
            for test_pattern in module_tests:
                # 展开通配符
                if glob.has_magic(test_pattern):
                    for match in glob.glob(test_pattern, recursive=True):
                        tests.add(match.replace("\\", "/"))
                else:
                    tests.add(test_pattern)

    # 过滤掉不存在的测试路径
    existing_tests = [t for t in tests if os.path.exists(t)]

    return sorted(existing_tests) if existing_tests else CORE_GUARDRAIL_TESTS


def main():
    parser = argparse.ArgumentParser(
        description="根据代码变更智能选择相关测试"
    )
    parser.add_argument(
        "--base",
        default="origin/main",
        help="基准分支 (默认: origin/main)",
    )
    parser.add_argument(
        "--head",
        default="HEAD",
        help="当前提交 (默认: HEAD)",
    )
    parser.add_argument(
        "--changed-modules",
        help="直接指定变更的模块（逗号分隔），跳过 git 检测",
    )
    parser.add_argument(
        "--output-format",
        choices=["space", "json", "newline"],
        default="space",
        help="输出格式 (默认: space，适合直接传给 pytest)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="输出详细变更信息",
    )

    args = parser.parse_args()

    if args.changed_modules:
        modules = set(args.changed_modules.split(","))
        changed_files = []
    else:
        changed_files = get_changed_files(args.base, args.head)
        modules = get_changed_modules(changed_files)

    tests = select_tests(modules, changed_files)

    if args.verbose:
        print(f"# Detected changed modules: {', '.join(sorted(modules))}", file=sys.stderr)
        print(f"# Selected {len(tests)} test files", file=sys.stderr)

    if args.output_format == "json":
        print(json.dumps({"modules": sorted(modules), "tests": tests}))
    elif args.output_format == "newline":
        print("\n".join(tests))
    else:
        # 空格分隔，适合 shell 传递
        print(" ".join(tests))


if __name__ == "__main__":
    main()
