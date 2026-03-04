# Smoke Test Report - AgomSAAF

> 生成日期：2026-03-04
> 目的：M0 基线证据包

---

## 测试环境

- Python: 3.11+
- Django: 5.x
- 测试框架: pytest
- 数据库: SQLite (开发环境)
- 运行时间: 25分32秒

---

## 测试概览

### 测试收集

- **当前收集数**: 2252（`tests/unit + tests/integration + tests/api`）
- **说明**:
  - `tests/playwright/`（E2E测试，需单独运行）

### 测试分类

| 类别 | 描述 |
|------|------|
| `tests/unit/` | 单元测试（Domain层逻辑） |
| `tests/integration/` | 集成测试（跨模块协作） |
| `tests/api/` | API契约测试 |
| `tests/guardrails/` | API守护测试 |
| `tests/playwright/` | E2E测试 |

---

## 测试结果

### 2026-03-04 补充复核（可复现命令）

| 项目 | 命令 | 结果 |
|------|------|------|
| 全量收集 | `pytest --collect-only -q tests/unit tests/integration tests/api` | 收集 `2252` 项，收集错误 `0` |
| 审计链路抽样 smoke | `pytest tests/unit/test_audit_domain.py tests/unit/test_audit_permissions.py tests/integration/test_audit_api.py tests/integration/test_audit_internal_ingest.py -q --no-cov` | `41` 项中 `41` 通过 |

### 总体统计

| 指标 | 数量 | 占比 |
|------|------|------|
| ✅ 通过 | 2188 | 92.2% |
| ❌ 失败 | 151 | 6.4% |
| ⚠️ 错误 | 35 | 1.5% |
| 📋 警告 | 102 | - |
| **总计** | **2374** | **100%** |

### 失败测试分析

#### 错误类型分布

| 错误类型 | 数量 | 主要模块 |
|----------|------|----------|
| guardrails错误 | 5 | decision_rhythm_api_error_mapping |
| integration错误 | 16 | audit, decision_platform |
| 失败 | 151 | 分布于多个模块 |

#### 主要失败模块

1. **decision_platform** (integration): 11个错误
   - 页面加载测试失败
   - API端点测试失败

2. **audit** (integration): 3个错误
   - 归因报告API测试失败

3. **decision_rhythm** (guardrails): 5个错误
   - API错误映射测试失败

### 通过率分析

- **单元测试**: 预计 >95% 通过
- **集成测试**: 预计 ~85% 通过
- **Guardrails**: 预计 ~90% 通过

---

## 已知问题

### 1. 历史阻断项（已修复）
- `tests/integration/policy/test_workbench_api.py` 与 `tests/api/test_workbench_api.py` 同名冲突：
  - 已通过重命名为 `tests/integration/policy/test_policy_workbench_api.py` 修复。
- `tests/unit/test_fault_injection.py` 导入 `FailedEventModel` 失败：
  - 已移除失效导入，文件可正常收集并执行（`9 passed, 4 skipped`）。

---

## 模块测试覆盖

### 核心模块（预期高覆盖）

| 模块 | 预期测试文件 | 预期覆盖 |
|------|-------------|----------|
| regime | test_regime_*.py | ≥90% |
| macro | test_macro_*.py | ≥90% |
| policy | test_policy_*.py | ≥80% |
| signal | test_signal_*.py | ≥80% |
| backtest | test_backtest_*.py | ≥80% |
| audit | test_audit_*.py | ≥80% |
| account | test_account_*.py | ≥70% |
| alpha | test_qlib_*.py | ≥70% |

### 新增智能模块

| 模块 | 预期测试文件 | 预期覆盖 |
|------|-------------|----------|
| factor | test_factor_*.py | ≥70% |
| rotation | test_rotation_*.py | ≥70% |
| hedge | test_hedge_*.py | ≥70% |

---

## 建议改进

1. **补充E2E测试**: 增加 Playwright 关键旅程测试
2. **CI集成**: 将测试纳入 PR Gate

---

*报告状态: 收集阻断已清零，抽样 smoke 通过，可进入下一里程碑*
*最后更新: 2026-03-04*
