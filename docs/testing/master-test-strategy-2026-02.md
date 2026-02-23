# AgomSAAF 全面测试策略（2026-02）

> 目标：让系统“可演示”升级为“可验收、可发布、可回滚”。

## 1. 范围与原则

1. 业务核心优先：Regime + Policy 双重过滤链路必须优先保障。  
2. 架构分层验证：Domain/Application/Infrastructure/Interface 分层测试，不跨层替代。  
3. 工程护栏前置：配置唯一来源、两阶段入库、环境无关测试作为门禁。  
4. 验收指标量化：所有结论以可计算指标输出，不接受“主观通过”。

## 2. 测试分层模型

1. L0 静态质量层  
- 内容：ruff/black/mypy、基础安全扫描、依赖检查。  
- 目标：快速阻断低级问题。

2. L1 单元层  
- 内容：Domain 规则、算法、边界值、容错分支。  
- 资产：`tests/unit/`。

3. L2 组件层  
- 内容：use_case + repository + serializer/view 契约。  
- 资产：`tests/unit/application/`、`tests/unit/infrastructure/`。

4. L3 集成层  
- 内容：模块内/模块间流程（policy/regime/backtest/audit/decision_platform）。  
- 资产：`tests/integration/`。

5. L4 API 合同层  
- 内容：OpenAPI、鉴权、状态码、字段契约、兼容性。  
- 资产：`tests/uat/test_api_naming_compliance.py` + 新增合同测试集。

6. L5 E2E 层  
- 内容：真实浏览器关键路径与关键动作断言。  
- 资产：`tests/playwright/tests/smoke/test_critical_paths.py`、`tests/playwright/tests/uat/test_user_journeys.py`。

7. L6 UAT 层  
- 内容：旅程 A-E、手工可用性、视觉一致性、缺陷分级验收。  
- 资产：`tests/uat/run_uat.py`、`tests/uat/uat_acceptance_checklist.md`。

8. L7 生产守护层  
- 内容：上线后冒烟、关键任务、监控告警、回滚演练。

## 3. 质量门禁（Release Gates）

### 3.1 PR Gate（10~15 分钟）

必须通过：

1. Guardrail 回归（含 policy/regime 关键集）。  
2. 变更影响范围单元测试。  
3. 关键 API 合同测试（至少覆盖本次改动接口）。

建议命令：

```bash
pytest -q \
  tests/guardrails/test_logic_guardrails.py \
  tests/integration/policy/test_policy_integration.py \
  tests/integration/policy/test_policy_api_contract.py \
  tests/unit/policy/test_fetch_rss_use_case.py \
  tests/unit/regime/test_config_threshold_regression.py
```

### 3.2 Nightly Gate（30~60 分钟）

必须通过：

1. 全量 `tests/unit`。  
2. 核心 `tests/integration`。  
3. Playwright smoke。

### 3.3 RC Gate（发布前）

通过条件（全部满足）：

1. 关键旅程通过率 >= 90%。  
2. 主导航 404 = 0。  
3. P0 缺陷 = 0。  
4. P1 缺陷 <= 2。  
5. API 命名规范覆盖率 = 100%。

### 3.4 Post-Deploy Gate（上线后 30 分钟）

必须通过：

1. `/api/health/` 正常。  
2. 核心读写路径可用（policy/signal/backtest 最小流程）。  
3. Celery 关键任务执行成功。  
4. 告警链路可触发。  

任一失败：立即触发回滚流程。

## 4. E2E/UAT 执行方案

## 4.1 旅程覆盖

1. A 新用户入门。  
2. B 研究与选标的。  
3. C 决策与执行。  
4. D 交易与持仓。  
5. E 复盘与运营。

## 4.2 每条旅程三类断言

1. 功能断言：页面/动作完成。  
2. 数据断言：前端结果与数据库/API 一致。  
3. 风控断言：Regime/Policy 约束真实生效。

## 4.3 执行命令

```bash
# 1) Playwright smoke
pytest -q tests/playwright/tests/smoke/test_critical_paths.py

# 2) UAT journeys
pytest -q tests/playwright/tests/uat/test_user_journeys.py -v

# 3) UAT API 命名和路由一致性
pytest -q tests/uat/test_api_naming_compliance.py tests/uat/test_route_baseline_consistency.py
```

## 5. 风险与整改优先级

P0（立即修）：

1. UAT 统计与退出码不可信（解析逻辑为占位实现）。  
2. 基线路由与真实路由不一致导致误报。

P1（本迭代修）：

1. 仅 guardrail CI，缺少 Nightly/RC 自动门禁。  
2. API 合同自动校验覆盖不足。

P2（持续优化）：

1. 视觉一致性自动化程度提升。  
2. 性能与容量测试纳入固定周期。

## 6. 角色与责任

1. Dev：补测试、修缺陷、维护合同兼容。  
2. QA：维护 UAT 旅程与缺陷基线、出具验收结论。  
3. Tech Lead：把关发布门禁、审批豁免。  
4. Product：确认业务验收标准与优先级。

## 7. 执行节奏（4 周）

1. 第 1 周：修 UAT runner 可信度与路由基线。  
2. 第 2 周：补 API 合同测试和 PR/Nightly 门禁。  
3. 第 3 周：补旅程深断言（数据+风控）。  
4. 第 4 周：执行 RC Gate + UAT 签字 + 发布演练。

## 8. 交付物清单

1. 本文档：`docs/testing/master-test-strategy-2026-02.md`。
2. 追踪矩阵：`docs/testing/requirements-traceability-matrix-2026-02.md`。
3. 每次发布的测试证据包：日志、报告、截图、缺陷清单。

## 9. 测试执行记录

### 2026-02-24 V3.4-RC1 测试执行

#### 执行结果汇总

| 层级 | 测试集 | 通过 | 失败 | 通过率 |
|------|--------|------|------|--------|
| L0 | 静态质量 | - | - | ⚠️ 有警告（代码风格问题） |
| L1 | 单元测试 | 1,345 | 0 | 100% |
| L3 | 集成测试 | 35 | 0 | 100% |
| L3 | Guardrails | 9 | 0 | 100% |
| L4 | 路由基线 | 2 | 0 | 100% |
| L4 | API命名规范 | 10 | 0 | 100% |
| L5 | Smoke 测试 | 16 | 0 | 100% |
| L6 | UAT 旅程 | 31 | 0 | 100% |
| **总计** | - | **1,448** | **0** | **100%** |

#### RC Gate 检查结果

| 条件 | 要求 | 实际 | 状态 |
|------|------|------|------|
| 关键旅程通过率 | >= 90% | **100%** (47/47) | ✅ 通过 |
| 主导航 404 | = 0 | **0** | ✅ 通过 |
| P0 缺陷 | = 0 | **0** | ✅ 通过 |
| P1 缺陷 | <= 2 | **0** | ✅ 通过 |
| API 命名规范覆盖率 | = 100% | **100%** | ✅ 通过 |

#### 修复记录

1. **DEF-001 (P2)**: 修复 `test_check_quota_exhausted` 竞态条件
   - 文件: `apps/decision_rhythm/domain/entities.py`
   - 修改: `_calculate_period_end()` 接受可选 `now` 参数

2. **DEF-002 (P1)**: 修复 22 个 API 路由命名规范问题
   - 文件: `apps/regime/interface/urls.py`, `apps/macro/interface/urls.py`, `apps/signal/interface/urls.py`, `apps/sentiment/interface/urls.py`
   - 修改: 统一移除路由名称的 `api_` 前缀

#### 结论

**✅ V3.4-RC1 通过 RC Gate，可进入 RC 阶段**  

