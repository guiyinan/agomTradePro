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
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Set


# 模块到测试的映射表
MODULE_TEST_MAP: Dict[str, List[str]] = {
    # 核心模块 - 这些变更运行更多测试
    "core": [
        "tests/guardrails/",
    ],

    # 宏观相关
    "macro": [
        "tests/integration/macro/",
    ],

    # Regime 模块
    "regime": [
        "tests/unit/regime/",
        "tests/integration/regime/",
        "tests/unit/regime/test_config_threshold_regression.py",
    ],

    # Policy 模块
    "policy": [
        "tests/unit/policy/",
        "tests/integration/policy/",
    ],

    # Signal 模块
    "signal": [
        "tests/integration/signal/",
    ],

    # Audit 模块
    "audit": [
        "tests/integration/audit/",
        "tests/unit/domain/audit/",
        "tests/unit/application/audit/",
    ],

    # Backtest 模块
    "backtest": [
        "tests/integration/backtest/",
        "tests/integration/test_backtesting_flow.py",
    ],

    # Alpha 模块
    "alpha": [
        "tests/integration/test_alpha_*.py",
        "tests/e2e/test_alpha_dashboard_e2e.py",
    ],

    "alpha_trigger": [
        "tests/integration/test_alpha_*.py",
    ],

    # Account 模块
    "account": [
        "tests/integration/account/",
        "tests/unit/account/",
    ],

    # Simulated Trading
    "simulated_trading": [
        "tests/integration/simulated_trading/",
        "tests/unit/domain/simulated_trading/",
    ],

    # Strategy
    "strategy": [
        "tests/integration/strategy/",
        "tests/unit/domain/strategy/",
        "tests/unit/application/strategy/",
    ],

    # Equity
    "equity": [
        "tests/integration/test_equity_*.py",
        "tests/unit/equity/",
    ],

    # Fund
    "fund": [
        "tests/integration/test_fund_*.py",
    ],

    # Decision Rhythm
    "decision_rhythm": [
        "tests/unit/decision_rhythm/",
        "tests/guardrails/test_decision_rhythm_api_error_mapping.py",
    ],

    # Events
    "events": [
        "tests/integration/events/",
    ],

    # Sector
    "sector": [
        "tests/unit/sector/",
    ],

    # Dashboard
    "dashboard": [
        "tests/e2e/",
    ],
}

# 始终运行的核心测试（无论哪个模块变更）
CORE_GUARDRAIL_TESTS = [
    "tests/guardrails/test_logic_guardrails.py",
    "tests/guardrails/test_no_501_on_primary_paths.py",
    "tests/guardrails/test_security_hardening_guardrails.py",
]

# 全量测试路径（当无法确定范围或检测到广泛变更时使用）
FULL_TEST_SUITES = [
    "tests/guardrails/",
    "tests/integration/",
]


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
        if module in MODULE_TEST_MAP:
            module_tests = MODULE_TEST_MAP[module]
            for test_pattern in module_tests:
                # 展开通配符
                if "*" in test_pattern:
                    base_path = test_pattern.split("*")[0].rsplit("/", 1)[0]
                    if os.path.exists(base_path):
                        for root, dirs, files in os.walk(base_path):
                            for f in files:
                                if f.startswith("test_") and f.endswith(".py"):
                                    tests.add(os.path.join(root, f))
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
