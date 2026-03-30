# AgomTradePro 全面测试策略（2026-02）

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

### 4.4 正式库快照回归约束

1. 禁止把 `pytest` 直接指向正在运行的正式 `db.sqlite3`，避免测试写入污染 live 数据。
2. 需要使用正式数据验证时，先复制 `db.sqlite3` 生成快照，再通过 `DATABASE_URL=sqlite:///...` 拉起隔离实例。
3. Playwright 回归必须显式传入 `--base-url`，并确保全局测试配置与运行时 base URL 同步，避免误打到默认 `localhost:8000`。
4. 允许在快照库中重置测试账号口令或补齐只影响测试的配置，但不得回写正式库。

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

### 2026-03-30 测试基线收口

#### 基础设施修复

1. `pytest.ini` 默认收集范围从仅 `tests/` 扩展到 `tests/` + `apps/`，避免 `apps/*/tests` 被漏跑。
2. `tests/uat/run_uat.py` 改为基于 `--junitxml` 解析真实结果，不再使用占位统计。
3. UAT runner 现在同时执行 `tests/uat/test_api_naming_compliance.py` 与 `tests/uat/test_route_baseline_consistency.py`。
4. 路由基线将 `policy/manage` 的标准入口修正为 `/policy/workbench/`。

#### 用例质量修复

1. `tests/playwright/tests/uat/test_user_journeys.py` 中多处 `assert True`/仅校验非 404 的断言已替换为页面可用性、关键区块和错误页检测。
2. `tests/playwright/tests/smoke/test_critical_paths.py` 增加页面正文非空、错误页排除等最小可用性断言。
3. `tests/e2e/test_navigation_404.py` 改为校验成功/重定向状态与目标，而不再只判断“不是 404”。
4. `tests/uat/test_api_naming_compliance.py` 增加前端源码中的 API 调用路径扫描，防止页面层绕过 `/api/` 约定。

#### 定向验证

```bash
pytest tests/uat/test_route_baseline_consistency.py tests/e2e/test_navigation_404.py tests/uat/test_api_naming_compliance.py -q
pytest --collect-only apps/share/tests apps/market_data/tests apps/dashboard/tests -q
python tests/uat/run_uat.py --generate-report
```

结果：

1. 定向契约/导航测试通过。
2. `apps/share/tests`、`apps/market_data/tests`、`apps/dashboard/tests` 已可被默认收集。
3. UAT runner 可生成报告文件，统计来源改为真实 JUnit XML。

#### 正式库快照回归

```bash
pytest tests/playwright/tests/smoke/test_critical_paths.py --base-url http://127.0.0.1:8001 -q
pytest tests/playwright/tests/uat/test_user_journeys.py --base-url http://127.0.0.1:8001 -q
```

结果：

1. 基于正式库快照的隔离实例 `8001` 上，Playwright smoke `28 passed`。
2. 修复 `tests/playwright/conftest.py` 后，`--base-url` 会同步覆盖全局 `config.base_url`，不再误打默认 `8000`。
3. 基于正式库快照的 Playwright UAT `31 passed`，验证真实数据下的登录、导航和关键旅程可用。

### 2026-03-28 Strategy 页面保存回归

#### 覆盖新增

新增页面级回归测试：`tests/integration/strategy/test_strategy_page_save_flow.py`

覆盖场景：

1. `/strategy/create/` 可创建策略并保存规则、脚本配置。
2. `/strategy/<id>/edit/` 可保存修改并替换规则、脚本配置。
3. 编辑页清空脚本后会删除旧 `ScriptConfigModel`，不再残留历史脚本。
4. 多个策略允许复用相同脚本内容，不再因 `script_hash` 全局唯一而保存失败。
5. 非法规则 JSON 会返回 400，且编辑过程保持原子性，不会删掉旧规则。

#### 执行结果

```bash
pytest tests/integration/strategy/test_strategy_page_save_flow.py -q
```

结果：`5 passed`

### 2026-03-28 多模块一致性回归

#### 覆盖新增

新增回归测试：

1. `tests/integration/strategy/test_strategy_binding_consistency.py`
2. `tests/unit/test_beta_gate_activation_consistency.py`
3. `tests/unit/test_regime_activation_consistency.py`
4. `tests/integration/account/test_registration_consistency.py`
5. `tests/unit/domain/test_prompt_init_command_consistency.py`
6. `tests/guardrails/test_consistency_write_guardrails.py`

覆盖场景：

1. 策略绑定/解绑失败时不破坏原激活状态。
2. Beta Gate 创建、编辑、激活失败时保持单一激活配置。
3. Regime 激活失败不污染状态，缓存仅在事务提交后失效。
4. 注册失败时 `User/Profile/Portfolio` 与默认账户整体回滚。
5. Prompt 强制覆盖失败时保留旧模板/链配置，不再 delete-then-create。
6. `beta_gate` 允许不同 `risk_profile` 各保留一个激活配置，但拒绝同画像重复激活。
7. `regime` 数据库层拒绝多个激活阈值配置。

#### 审计记录

同步文档：`docs/development/consistency-audit-2026-03-28.md`

### 2026-03-30 Alpha Dashboard 用户隔离回归

#### 覆盖新增

新增回归测试：

1. `apps/dashboard/tests/test_alpha_queries.py`
2. `apps/dashboard/tests/test_alpha_views.py`

覆盖场景：

1. `AlphaVisualizationQuery.execute()` 必须将当前登录用户透传给 `AlphaService.get_stock_scores(...)`。
2. `GET /api/dashboard/alpha/stocks/` 必须使用 `request.user` 读取用户级 Alpha 缓存。
3. Dashboard 因子面板必须与股票列表使用同一用户上下文，避免页面列表有数据但侧边因子为空。
4. 当前序 Provider 失败、后序只有过期缓存时，系统必须回退到最佳 `degraded` 结果，而不是返回空白列表。

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
