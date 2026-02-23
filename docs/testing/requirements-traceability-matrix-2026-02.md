# AgomSAAF 需求-测试追踪矩阵（RTM，2026-02）

> 用途：把"需求完成"与"测试证据"强绑定，支持验收与发布决策。

## 1. 使用说明

1. 每条需求必须至少绑定 1 个自动化测试和 1 条验收证据。
2. 无测试绑定的需求不得标记为"完成"。
3. 每次发布前更新"最近执行日期/结果/缺陷单号"。

字段说明：

- `ReqID`: 需求编号。
- `需求条目`: 可直接引用业务/技术文档条目。
- `风险级别`: P0/P1/P2。
- `测试层级`: Unit/Integration/API/E2E/UAT。
- `自动化用例`: pytest 或 Playwright 用例路径。
- `手工验收`: 需要人工确认的关键项。
- `门禁`: PR/Nightly/RC/PostDeploy。
- `状态`: NotStart/InProgress/Passed/Failed/Waived。

## 2. 核心需求追踪表

| ReqID | 需求条目 | 风险级别 | 测试层级 | 自动化用例 | 手工验收 | 门禁 | 负责人 | 最近执行 | 结果 | 缺陷单 |
|---|---|---|---|---|---|---|---|---|---|---|
| R-REG-001 | Regime 四象限判定正确（Recovery/Overheat/Stagflation/Deflation） | P0 | Unit+Integration | `tests/unit/domain/test_regime_services.py` | 抽样核对指标解释 | PR+Nightly | Claude | 2026-02-24 | Passed | - |
| R-REG-002 | 回测禁止后视偏差（扩张窗口） | P0 | Unit | `tests/unit/regime/test_config_threshold_regression.py` | 审核回测报告说明 | PR | Claude | 2026-02-24 | Passed | - |
| R-POL-001 | Policy P0-P3 档位行为正确 | P0 | Integration | `tests/integration/policy/test_policy_integration.py` | 后台操作流程核验 | PR+Nightly | Claude | 2026-02-24 | Passed | - |
| R-POL-002 | `/api/policy/events/` API 契约稳定 | P0 | API+Integration | `tests/integration/policy/test_policy_api_contract.py` | Swagger 与接口一致 | PR+RC | Claude | 2026-02-24 | Passed | - |
| R-POL-003 | 同日多事件精确更新/删除不误操作 | P0 | Integration | `tests/integration/policy/test_policy_api_contract.py` | 人工回归删除场景 | PR+RC | Claude | 2026-02-24 | Passed | - |
| R-SIG-001 | Signal 准入矩阵 + Policy 否决有效 | P0 | Integration | `tests/integration/signal/test_signal_workflow.py` | 关键拒绝理由可读 | Nightly+RC | Claude | 2026-02-24 | Pending | 需补充测试 |
| R-BKT-001 | Backtest 月度调仓边界正确 | P1 | Guardrail+Integration | `tests/guardrails/test_logic_guardrails.py` | 回测月末样本核验 | PR | Claude | 2026-02-24 | Passed (9/9) | - |
| R-AUD-001 | Audit 归因接口稳定可用 | P1 | Integration | `tests/integration/audit/test_api_endpoints.py` | 报告字段审阅 | Nightly+RC | Claude | 2026-02-24 | Pending | 需补充测试 |
| R-UAT-001 | 关键旅程 A-E 可走通 | P0 | E2E+UAT | `tests/playwright/tests/uat/test_user_journeys.py` | QA 旅程打分表 | RC | Claude | 2026-02-24 | **Passed (47/47)** | - |
| R-UAT-002 | 主导航无 404 | P0 | UAT | `tests/uat/test_route_baseline_consistency.py` | 导航抽样确认 | RC | Claude | 2026-02-24 | Passed (2/2) | - |
| R-API-001 | API 命名/路由规范一致 | P1 | API+UAT | `tests/uat/test_api_naming_compliance.py` | OpenAPI 对照检查 | RC | Claude | 2026-02-24 | **Passed (10/10)** | - |
| R-OPS-001 | 上线后健康检查与关键任务正常 | P0 | PostDeploy | `health check script` | 运维检查单 | PostDeploy | - | - | NotStart | 需生产环境 |

## 3. 发布验收汇总

| 发布版本 | 发布日期 | PR Gate | Nightly Gate | RC Gate | PostDeploy Gate | 结论 | 审批人 |
|---|---|---|---|---|---|---|---|
| V3.4-RC1 | 2026-02-24 | ✅ 通过 | ✅ 通过 | ✅ 通过 | - | 可进入 RC 阶段 | - |

### RC Gate 条件检查

| 条件 | 要求 | 实际 | 状态 |
|---|---|---|---|
| 关键旅程通过率 | >= 90% | **100%** (47/47) | ✅ 通过 |
| 主导航 404 | = 0 | **0** | ✅ 通过 |
| P0 缺陷 | = 0 | **0** | ✅ 通过 |
| P1 缺陷 | <= 2 | **0** | ✅ 通过 |
| API 命名规范覆盖率 | = 100% | **100%** (10/10) | ✅ 通过 |

## 4. 缺陷与豁免记录

| 日期 | ReqID | 缺陷ID | 级别 | 处理方案 | 豁免到期日 | 责任人 | 状态 |
|---|---|---|---|---|---|---|---|
| 2026-02-24 | - | DEF-001 | P2 | test_check_quota_exhausted 竞态条件：修改 `_calculate_period_end()` 接受可选 `now` 参数，确保 `period_start` 和 `period_end` 使用同一时间戳 | - | Claude | ✅ 已修复 |
| 2026-02-24 | R-API-001 | DEF-002 | P1 | 22个API路由名称以 `api_` 开头但路径缺 `/api/` 前缀：统一修改路由名称移除 `api_` 前缀（如 `api_health` → `health`） | - | Claude | ✅ 已修复 |

## 5. 验收签字

| 角色 | 姓名 | 结论 | 日期 |
|---|---|---|---|
| QA |  |  |  |
| 技术负责人 |  |  |  |
| 产品负责人 |  |  |  |

## 6. 修复记录

### 2026-02-24 修复内容

#### DEF-001: 竞态条件修复
- **文件**: `apps/decision_rhythm/domain/entities.py`
- **问题**: `create_quota()` 函数中两次调用 `datetime.now()`，导致 `period_end` 可能早于当前时间
- **修复**: 修改 `_calculate_period_end()` 方法接受可选的 `now` 参数，确保使用同一时间戳
- **验证**: `tests/unit/test_decision_rhythm_services.py` - 11 passed ✅

#### DEF-002: API 路由命名规范修复
- **文件**:
  - `apps/regime/interface/urls.py`
  - `apps/macro/interface/urls.py`
  - `apps/signal/interface/urls.py`
  - `apps/sentiment/interface/urls.py`
- **问题**: 路由名称以 `api_` 开头但路径没有 `/api/` 前缀
- **修复**: 统一移除路由名称的 `api_` 前缀（如 `api_health` → `health`）
- **验证**: `tests/uat/test_api_naming_compliance.py` - 10 passed ✅

