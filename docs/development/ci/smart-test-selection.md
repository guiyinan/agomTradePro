# 智能 CI 测试选择

> 最近更新：2026-07-22

## 概述

PR Gate 使用智能测试选择策略，根据代码变更自动选择相关测试，同时固定运行关键可靠性集合。选择器以“漏跑风险优先”为原则：无法识别范围时扩大测试面，不允许静默退化为少量通用护栏。

## 工作原理

### 1. 变更检测 (`detect-tests` Job)

工作流首先检测变更的模块：

```bash
# 从 git diff 提取变更的模块
CHANGED_MODULES=$(git diff --name-only ${BASE}...${HEAD} | \
  awk -F/ '
    /^apps\/[^\/]+\// { print $2; next }
    /^core\// { print "core"; next }
    /^shared\// { print "shared"; next }
    /^\.github\// { print "ci"; next }
  ' | sort -u)
```

### 2. 测试选择 (`scripts/select_tests.py`)

根据变更的模块选择测试：

| 变更模块 | 运行的测试 |
|---------|----------|
| `regime` | `tests/unit/regime/`, `tests/integration/regime/` |
| `policy` | `tests/unit/policy/`, `tests/integration/policy/` |
| `audit` | `tests/integration/audit/`, `tests/unit/domain/audit/` |
| `alpha` | `tests/integration/test_alpha_*.py` |
| `broker_execution` | Broker 单元/集成、关键可靠性、研究完整性迁移 |
| `operational_readiness` | Readiness 单元测试、关键迁移验证 |
| `risk_center` | Risk API/集成/单元、Broker 风险与关键可靠性 |
| `portfolio` | Portfolio 单元/API/集成、关键可靠性与迁移 |
| `research` | Research API/单元、PIT、关键可靠性与迁移 |
| `valuation` | Valuation 单元/API/集成与关键迁移验证 |
| `config_center` | Config Center 单元/API/集成与关键迁移验证 |
| `shared` | **全量测试**（影响所有模块） |
| `core` | 核心测试 + guardrails |
| `.github` / CI 变更 | 默认档回退全量；快速档运行完整轻量范围 |
| 未映射的 `apps/*` | **保守回退全量测试**，选择器自测同时失败提醒补映射 |
| 无模块变更 | 默认档回退全量；快速档运行始终测试集合 |

### 3. 始终运行的测试

以下测试在已识别模块变更时始终运行：

- `tests/guardrails/test_architecture_boundaries.py` - 四层架构和循环依赖边界
- `tests/guardrails/test_logic_guardrails.py` - 业务逻辑完整性
- `tests/guardrails/test_alpha_workspace_consistency_guardrail.py` - Alpha/工作台一致性
- `tests/guardrails/test_no_501_on_primary_paths.py` - 无 501 占位符
- `tests/guardrails/test_security_hardening_guardrails.py` - 安全加固
- `tests/guardrails/test_api_contract_minimal.py` - **API 合同最小集**
- `tests/critical/` - **数据→决策→风险→审批→Agent→回报对账关键可靠性链路**

`tests/critical/` 只使用 SQLite、Fake Agent 和本地状态文件，不连接真实 QMT、Redis 或外部数据源。

### 4. API 合同最小集测试

`test_api_contract_minimal.py` 验证所有关键 API 端点的基本契约：

- 不返回 501 占位符响应
- 成功时返回正确的 Content-Type (application/json)
- 覆盖核心业务 API（Regime, Policy, Signal, Events, Audit, Alpha 等）

## 使用方法

### 本地测试选择脚本

```bash
# 查看当前变更会触发哪些测试
python scripts/select_tests.py --base origin/main --head HEAD -v

# 手动指定模块
python scripts/select_tests.py --changed-modules regime,policy -v

# 输出 JSON 格式
python scripts/select_tests.py --changed-modules alpha --output-format json
```

### 执行选定的测试

```bash
# 获取测试路径并执行
TESTS=$(python scripts/select_tests.py --changed-modules regime,policy)
pytest $TESTS -v
```

### 运行 API 合同最小集测试

```bash
# 单独运行 API 合同测试
pytest tests/guardrails/test_api_contract_minimal.py -v
```

## 模块映射表

所有模块测试映射定义在 `scripts/select_tests.py` 的 `MODULE_TEST_MAP` 字典中。

添加新模块时，更新此映射：

```python
MODULE_TEST_MAP: dict[str, list[str]] = {
    "your_new_module": [
        "tests/unit/your_new_module/",
        "tests/integration/your_new_module/",
    ],
    # ...
}
```

同时必须运行选择器自测。测试会扫描所有带 `apps/<name>/__init__.py` 的生产 App；任何未映射 App 都会使自测失败。运行时若先检测到未知 App，则保守回退全量测试，避免新增模块在补映射前漏测。

## 性能优化

| 场景 | 测试范围 | 预计时间 |
|-----|---------|---------|
| 仅文档变更 | 始终测试集合 | 取决于测试库初始化，通常数分钟 |
| 单模块变更 | 模块映射 + 始终测试集合 | 通常 5-15 分钟 |
| 多模块变更 | 多模块映射并集 + 始终测试集合 | 通常 10-30 分钟 |
| `shared/`、CI 或未知 App 变更 | 保守扩大范围 | 以 Fast Feedback 45 分钟超时为上限 |

## 单元测试

```bash
# 运行测试选择逻辑的单元测试
pytest tests/unit/ci/test_select_tests.py -v

# 单独运行关键可靠性集合（SQLite + Fake Agent）
pytest tests/critical/ -v

# 运行 API 合同最小集测试
pytest tests/guardrails/test_api_contract_minimal.py -v
```

## 相关文件

- `.github/workflows/ci-fast-feedback.yml` - PR Gate 工作流
- `scripts/select_tests.py` - 智能测试选择脚本
- `tests/unit/ci/test_select_tests.py` - 测试选择单元测试
- `tests/guardrails/test_api_contract_minimal.py` - API 合同最小集测试
- `tests/critical/` - 关键可靠性发布阻断集合
- `tests/migrations/test_research_integrity_migrations.py` - 研究完整性关键迁移验证
- `docs/plans/critical-reliability-test-closure-2026-07-22.md` - 本轮实施与验证记录
