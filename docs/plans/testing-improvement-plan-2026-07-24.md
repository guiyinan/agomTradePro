# 分层测试与 TDD 反馈环提升计划

> **文档日期**: 2026-07-24
> **状态**: 已完成（T0-T5，2026-07-24）
> **适用对象**: 开发负责人 / 测试负责人 / 模块维护人
> **范围**: Python/Django Unit、API 契约、Integration、Django E2E、Playwright/UAT 与 CI 门禁
> **目标**: 在不以测试数量替代质量的前提下，恢复全绿基线、缩短 TDD 反馈环，并按风险提升 Domain、应用边界和关键用户旅程的有效覆盖

## 1. 当前基线

### 1.1 2026-07-23 覆盖率快照

覆盖率采集排除了 `migrations` 和测试代码，四类中央测试套件独立运行后按执行行取并集：

| 指标 | 当前值 | 解释 |
|---|---:|---|
| Unit 行覆盖率 | 63.4% | `tests/unit/` 对 `apps/` 生产代码 |
| API/迁移契约行覆盖率 | 42.2% | `tests/api/` + `tests/migrations/` |
| Integration 行覆盖率 | 47.1% | `tests/integration/` |
| Django E2E 行覆盖率 | 39.7% | `tests/e2e/`，不含 Playwright 服务器进程 |
| 四类测试并集覆盖率 | 73.3% | 相同行只计一次 |
| Domain Unit 行覆盖率 | 85.0% | 低于项目 Domain ≥90% 要求 |
| `tests/unit/` 数据库型文件占比 | 约 30% | 520 个文件中约 156 个依赖 Django DB/TestCase |

上述百分比只能表示代码执行，不等同于需求覆盖。Django 启动时会导入所有 Installed Apps，API/E2E 套件存在导入命中的覆盖率底噪；后续验收必须同时检查断言语义、契约矩阵与用户旅程。

本快照未合并 `apps/*/tests`、guardrail 和 Playwright 覆盖率。采集期间 `dashboard` 存在并发工作区改动，因此其模块值只作为优先级参考，正式提升批次开始前须重采。

### 1.2 2026-07-24 红灯修复

上一轮全量 Unit 结果为 `5917 passed / 3 failed / 4 skipped`。本批修复：

1. 恢复 `MacroSizingConfigModel` 在 Account 唯一 Admin 入口的 typed 注册，并以运行时 registry 契约替代旧文件字符串扫描。
2. 将 QMT 实盘桥新增的 `broker-execution.overview` 与 `broker-execution.audit` 纳入 TUI IA runtime-source 契约。
3. 按真实所有权更新 Decision Rhythm ORM owner 清单：transition-plan ORM 归 `portfolio`，Decision Input Snapshot 作为本地 owner 发布明确 `__all__`。

定向结果：相关 3 个测试文件 `10 passed`。全量 Unit 结果为
`5920 passed / 4 skipped / 0 failed`，T0 已恢复最终 Green。

## 2. 目标与硬门槛

### 2.1 最终目标

| 维度 | 门槛 |
|---|---|
| 主线健康 | 默认 CI 套件 0 个非预期失败；禁止用新增 skip/xfail 隐藏回归 |
| Domain | 每个包含实质业务规则的模块 Unit 行覆盖率 ≥90% |
| 综合覆盖 | 所有业务模块先达到 ≥70%；金融核心与执行/风控模块达到 ≥80% |
| 仓库并集覆盖 | 排除 migrations/tests 后从 73.3% 逐批提升到 ≥80% |
| 快速 TDD 环 | 无数据库的 Domain/纯 Application 快速套件在标准 CI runner 上 ≤120 秒 |
| Unit 隔离性 | `tests/unit/` 中数据库型文件占比逐步降至 ≤15%，迁移后的测试进入 component/integration 分组 |
| API 契约 | 发布端点覆盖成功、鉴权、权限、校验错误、Content-Type 与关键副作用 |
| E2E | 关键资金/订单/决策旅程有少量稳定的 Django E2E 与 Playwright smoke，不追求全模块页面遍历 |
| 可追溯性 | 每个提升批次记录基线、命令、结果、未验证项和回滚点 |

### 2.2 核心模块定义

优先按真实损失半径排序：

1. 金融规则：`macro`、`regime`、`policy`、`signal`、`alpha`、`backtest`。
2. 资金与执行：`account`、`portfolio`、`simulated_trading`、`broker_execution`。
3. 决策与风控：`decision_rhythm`、`strategy`、`risk_center`、`beta_gate`、`alpha_trigger`、`valuation`。
4. 证据与运行：`audit`、`events`、`research`、`operational_readiness`。

## 3. 执行原则

1. 测试先描述行为或契约，再修改实现；Bug 修复必须留下可复现的回归测试。
2. 不以测试函数数量、文件数量或无差别覆盖率冲高作为验收标准。
3. Domain 测试不得依赖 Django ORM、网络、时钟实况或全局配置；时间与外部数据通过显式输入或 fake 注入。
4. API 测试验证 HTTP 边界；Integration 验证 Repository、事务和跨模块协作；E2E 只保护高价值用户旅程。
5. 对外部数据源使用确定性 fixture/fake 验证 failover、一致性容差、单位和缺失值，不在默认 CI 访问真实网络。
6. 覆盖率门禁采用只升不降的 ratchet；不得为了接受新增缺口而降低阈值或扩大 omit。
7. `terminal/tui/mcp/sdk/deploy` 测试变更遵守固定最小回归包和“已验证/未验证”显式交接要求。

## 4. 分批实施

### T0 恢复全绿基线

| 项 | 内容 |
|---|---|
| 状态 | 完成 |
| 范围 | Account Admin、TUI IA、Decision Rhythm ORM owner 契约 |
| 验收 | 相关文件全绿；全量 `tests/unit/` 无失败；无新增 skip/xfail |
| 回滚 | 三个根因按模块独立回滚，不与后续覆盖提升混合 |

### T1 建立秒级 TDD 快速环

| 项 | 内容 |
|---|---|
| 范围 | 盘点 `tests/unit/` 的 DB 依赖；新增可机读测试分层清单；把纯 Domain/纯 Application 测试组成 fast suite |
| 动作 | 将实际依赖 ORM、Django client、migration 或 transaction 的用例逐批迁到 component/integration；保留原 test ID 到新位置的映射 |
| CI | PR 必跑 fast suite；受影响模块再跑 targeted suite；nightly 继续跑完整分层回归 |
| 验收 | fast suite ≤120 秒且不创建测试数据库；迁移前后断言语义不减少；无批量改名导致的历史定位丢失 |

### T2 Domain 90% 收口

第一批处理当前低于 80% 或金融风险最高的 Domain：

| 批次 | 模块 | 当前参考值 | 重点 |
|---|---|---:|---|
| T2A | `backtest` | 49.5% | 扩张窗口、无后视偏差、手续费、空数据和时间边界 |
| T2A | `prompt` | 69.7% | 模板选择、版本、降级和非法变量 |
| T2A | `beta_gate` | 69.9% | 闸门边界、拒绝原因、UNKNOWN/缺失输入 |
| T2A | `alpha_trigger` | 74.3% | 触发、去重、失效和证伪条件 |
| T2B | `events`、`equity`、`valuation` | 74.6% / 75.4% / 77.1% | 事件未知类型、实体边界、估值质量/新鲜度 |
| T2B | `dashboard`、`realtime`、`strategy` | 78.9% / 79.3% / 79.7% | 只补真实业务规则；UI/ORM 分支不伪装成 Domain 测试 |
| T2C | 其余低于 90% 模块 | 80%–89% | 参数化边界、异常路径与不可变约束 |

每个模块先生成 missing-line 报告，再按规则风险选择用例；禁止只为执行行而调用无断言代码。

### T3 Application/Infrastructure/API 契约补强

优先处理综合覆盖率低于 70% 的模块：

`share`、`macro`、`alpha`、`alpha_trigger`、`dashboard`、`sentiment`、`fund`、`prompt`、`signal`、`policy`。

每个模块至少完成：

1. Application UseCase：成功、业务拒绝、依赖失败、幂等/重试和权限上下文。
2. Repository：持久化往返、排序/分页、事务、唯一约束、用户隔离和 timezone-aware 时间。
3. API：状态码、Content-Type、认证、角色权限、参数边界、错误映射和关键数据库副作用。
4. 外部适配器：确定性 fake、超时、主备切换、1% 一致性容差、单位归一与审计原值。

### T4 关键旅程与浏览器验收

只保留高价值、跨边界旅程：

1. 登录与初始化 → 数据源/AI 配置 → 首页可用。
2. 宏观/Regime/Pulse → 候选/信号 → 决策工作台。
3. 建议 → 风控 → 用户确认 → 模拟或实盘订单。
4. 成交/持仓 → 对账 → 审计与复盘。
5. observer/admin 权限与跨用户拒绝。

Django E2E 验证服务端工作流和数据库结果；Playwright 验证真实 Chromium 中的可见状态、操作、导航和错误恢复。浏览器测试不得只断言 HTTP 200。

### T5 覆盖率与质量门禁

1. 覆盖率配置统一排除 migrations、tests、generated/vendor，禁止各工作流自定义不同口径。
2. 生成按模块、按层报告，同时保留 Unit 与分层并集两个指标。
3. Domain 门禁从“仅变更文件 ≥70%”逐批收紧到模块 ≥90%；每次只升不降。
4. 综合覆盖先设置仓库 73.3% ratchet，再随 T2/T3 提升到 75%、78%、80%。
5. CI 失败报告必须显示失败 test ID、慢测试 Top N、模块覆盖变化和未执行套件。
6. Playwright 单独报告用户旅程，不用 Django import coverage 冒充浏览器覆盖。

## 5. 建议执行顺序

| 周期 | 主线 | 交付 |
|---|---|---|
| 第 1 批 | T0 + T1 inventory | 全绿基线、fast-suite 清单、DB 型 Unit 迁移清单 |
| 第 2 批 | T2A | backtest/prompt/beta_gate/alpha_trigger Domain 回归 |
| 第 3 批 | T2B/T2C | 其余 Domain ≥90% |
| 第 4 批 | T3 前五个高风险模块 | Repository/API 契约矩阵与综合覆盖提升 |
| 第 5 批 | T3 其余模块 + T4 | 关键旅程与浏览器 smoke |
| 第 6 批 | T5 | CI ratchet、报告与文档收口 |

单日只推进一个测试主线加一个小收口；不要把大规模测试迁移、业务实现、部署和治理文档混成同一提交。

## 6. 标准验证命令

```powershell
# T0 定向回归
python -m pytest `
  tests/unit/account/test_macro_sizing_import_contract.py `
  tests/unit/terminal/test_tui_information_architecture.py `
  tests/unit/test_decision_rhythm_models_structure.py -q

# Unit 与 Domain 覆盖
python -m pytest tests/unit/ -q --cov=apps --cov-report=term-missing

# API / migration / integration
python -m pytest tests/api/ tests/migrations/ -q
python -m pytest tests/integration/ -m "not live_required and not optional_runtime and not diagnostic" -q

# Guardrail 与 App-local
python -m pytest tests/guardrails/ -q
python -m pytest apps/*/tests -q

# 终端/TUI 高风险链路固定回归
python -m pytest tests/unit/test_tui_workbench.py -q
python -m pytest tests/unit/test_terminal_agent_service.py -q
python -m pytest sdk/tests/test_sdk/test_client.py -q
python -m pytest tests/unit/test_internal_ssl_redirect.py -q
```

Playwright 必须通过 `scripts/run_live_server_pytest.py` 管理 live server，并保存 server log、pytest log、JUnit 与截图工件。

## 7. 每批完成定义

一批测试提升只有同时满足以下条件才算完成：

- 新增测试在修复前能够稳定复现目标缺口，或有明确的契约快照依据。
- 实现与测试全部通过，没有新增 skip/xfail。
- 覆盖率提升来自有意义断言，不是导入、空调用或扩大 omit。
- 相关模块的成功、失败、权限、边界与副作用得到与风险相称的验证。
- 执行时间没有不可解释的显著回退；新增慢测试有归属和原因。
- 文档记录已完成项、未完成项、已验证测试、未验证风险和回滚点。
- 涉及 TUI/MCP/SDK/deploy 时完成相应固定最小回归包，或明确记录未执行原因。

## 8. 风险与回滚

| 风险 | 控制 |
|---|---|
| 为冲覆盖率写脆弱实现细节测试 | 优先断言公开行为、Domain 规则和边界契约 |
| 大量移动测试导致定位困难 | 每模块/每测试族独立提交，保存旧 ID → 新 ID 映射 |
| DB 测试误归 Unit | 通过 fixture/marker/静态扫描建立分层门禁 |
| E2E 不稳定 | 固定数据、稳定选择器、显式等待、失败截图和 server log |
| 外部数据源造成随机失败 | 默认 fake；真实源验证进入 optional/live 套件 |
| 覆盖率口径漂移 | 单一 coverage 配置和报告脚本，CI 只读取该真源 |
| 门槛一次性收紧阻塞开发 | 使用只升不降的分阶段 ratchet，不降低既有基线 |

## 9. 跟踪表

| 批次 | 状态 | 结果 |
|---|---|---|
| T0 定向修复 | 完成 | 相关 3 文件 `10 passed`；全量 Unit `5920 passed / 4 skipped` |
| T1 快速反馈环 | 完成 | 158 个数据库型 Unit 文件迁入 `tests/component/`；旧 ID 映射已落盘；Unit DB 文件占比 `1.36%`；fast suite `3500 passed / 40.06s`，未创建测试数据库 |
| T2 Domain 90% | 完成 | 覆盖率 ratchet 验证所有 42 个业务模块 Domain 均 ≥90%，最低值仍高于门限 |
| T3 边界契约 | 完成 | Unit `5169 passed`、Component `1707 passed / 4 skipped`、API+Migration `565 passed`、Integration `958 passed / 13 deselected`、App-local `288 passed`；补齐成功、失败、权限、边界和副作用契约 |
| T4 关键旅程 | 完成 | Django E2E `97 passed`；Chromium smoke `33 passed`；Chromium UAT `74 passed`，均无 skip/failure/error |
| T5 CI ratchet | 完成 | 仓库并集覆盖率 `80.1%`；核心模块 ≥80%、其余模块 ≥70%、Domain ≥90%；PR/Nightly/RC 已接入统一配置与报告；guardrail+critical `165 passed` |

## 10. 完成证据（2026-07-24）

### 10.1 机器真源与 CI

- 覆盖率唯一口径：`.coveragerc`。
- 测试质量门限：`governance/testing_quality_baseline.json`。
- 分层清单：`governance/test_tier_inventory.json`。
- 旧测试 ID 到新位置映射：`governance/test_id_migrations_2026-07-24.json`。
- 覆盖率门禁：`scripts/check_coverage_ratchet.py`。
- fast suite：`scripts/run_fast_tests.py`，由 `tests/support/fast_suite_guard.py` 阻止数据库初始化。
- PR、Nightly、RC 工作流统一使用上述真源，不再各自维护覆盖率 omit 或门限。

### 10.2 最终验收结果

| 验收项 | 结果 |
|---|---:|
| 仓库行覆盖率 | `80.1%` |
| Unit DB 文件占比 | `6 / 440 = 1.36%` |
| fast suite | `3500 passed / 40.06s` |
| Unit | `5169 passed / 7 warnings` |
| Component | `1707 passed / 4 skipped` |
| API + Migration | `565 passed` |
| Integration（排除 live/optional/diagnostic） | `958 passed / 13 deselected` |
| Django E2E | `97 passed` |
| App-local | `288 passed` |
| Playwright smoke | `33 passed` |
| Playwright UAT | `74 passed` |
| Guardrail + Critical | `165 passed` |
| TUI workbench / Terminal service / SDK client / SSL redirect | `194 / 11 / 22 / 2 passed` |
| 增量 mypy | `14 source files / 0 regressions` |
| 全仓 mypy 债务上限 | `3916 errors / 658 files`，只降不升 |

覆盖率报告保存在 `reports/quality/coverage-final.xml`；浏览器 JUnit、server log 和 pytest log 保存在 `reports/quality/local-smoke*` 与 `reports/quality/local-uat*`。

### 10.3 已知非阻断项与回滚点

- Component 的 4 个既有 skip 与 Integration 的 13 个 marker deselection 未由本计划新增；没有新增 skip/xfail 隐藏回归。
- 本地 SQLite 运行仍会出现少量既有 Django/第三方弃用与资源警告；本批未发现由警告导致的失败或数据污染。
- 覆盖率 XML 在删除不可达的 `apps/macro/interface/views.py` 后使用 `--ignore-errors` 跳过旧 coverage data 中的已删除路径；门禁读取的当前生产文件口径仍为 `80.1%`。
- 回滚按主线执行：CI/ratchet 回滚三个 workflow 与治理脚本；测试迁移按 `test_id_migrations_2026-07-24.json` 反向恢复；业务缺陷修复按对应模块独立回滚，禁止整体回退覆盖率和依赖预算基线。
