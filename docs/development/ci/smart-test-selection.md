# 智能 CI 测试选择

## 概述

PR Gate 现在使用智能测试选择策略，根据代码变更自动选择相关测试，将 CI 运行时间控制在 10-15 分钟内。

## 工作原理

### 1. 变更检测 (`detect-changes` Job)

工作流首先检测变更的模块：

```bash
# 从 git diff 提取变更的模块
CHANGED_MODULES=$(git diff --name-only ${BASE}...${HEAD} | \
  grep -E "^apps/|^core/|^shared/" | \
  sed -E 's|^(apps/|core/|shared/)[^/]+.*|\1|' | \
  sort -u)
```

### 2. 测试选择 (`scripts/select_tests.py`)

根据变更的模块选择测试：

| 变更模块 | 运行的测试 |
|---------|----------|
| `regime` | `tests/unit/regime/`, `tests/integration/regime/` |
| `policy` | `tests/unit/policy/`, `tests/integration/policy/` |
| `audit` | `tests/integration/audit/`, `tests/unit/domain/audit/` |
| `alpha` | `tests/integration/test_alpha_*.py` |
| `shared` | **全量测试**（影响所有模块） |
| `core` | 核心测试 + guardrails |
| 无模块变更 | 核心测试（4 个 guardrail 测试） |

### 3. 核心测试（始终运行）

以下 4 个核心测试在任何情况下都会运行：

- `tests/guardrails/test_logic_guardrails.py` - 业务逻辑完整性
- `tests/guardrails/test_no_501_on_primary_paths.py` - 无 501 占位符
- `tests/guardrails/test_security_hardening_guardrails.py` - 安全加固
- `tests/guardrails/test_api_contract_minimal.py` - **API 合同最小集**

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
MODULE_TEST_MAP: Dict[str, List[str]] = {
    "your_new_module": [
        "tests/unit/your_new_module/",
        "tests/integration/your_new_module/",
    ],
    # ...
}
```

## 性能优化

| 场景 | 测试数量 | 预计时间 |
|-----|---------|---------|
| 仅文档变更 | 4 个核心测试 | ~3 分钟 |
| 单模块变更 | 6-10 个测试 | ~5-8 分钟 |
| 多模块变更 | 10-30 个测试 | ~10-15 分钟 |
| shared/ 变更 | 全量测试 | ~20 分钟 |

## 单元测试

```bash
# 运行测试选择逻辑的单元测试
pytest tests/unit/ci/test_select_tests.py -v

# 运行 API 合同最小集测试
pytest tests/guardrails/test_api_contract_minimal.py -v
```

## 相关文件

- `.github/workflows/logic-guardrails.yml` - PR Gate 工作流
- `scripts/select_tests.py` - 智能测试选择脚本
- `tests/unit/ci/test_select_tests.py` - 测试选择单元测试
- `tests/guardrails/test_api_contract_minimal.py` - API 合同最小集测试
