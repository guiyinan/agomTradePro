# 测试覆盖薄弱环节整改计划

> **文档日期**：2026-07-24
> **状态**：待实施
> **适用对象**：开发负责人、测试负责人、模块维护人、CI 维护人
> **范围**：生产 Python、SDK、关键前端交互、外部数据源、异步任务和生产集成
> **关联基线**：
> `governance/testing_quality_baseline.json`、
> `governance/governance_baseline.json`、
> `reports/quality/coverage-final.xml`

## 1. 计划目标

本计划承接已完成的
`docs/archive/plans/testing-improvement-plan-2026-07-24.md`，不重复建设测试分层体系，
重点解决以下剩余问题：

1. 当前仓库行覆盖率刚越过门槛，新增少量未覆盖代码即可导致门禁回退。
2. 覆盖率主要统计 `apps/`，`core/`、`shared/`、SDK 和前端尚未进入统一可见口径。
3. 当前只采集行覆盖率，没有采集分支覆盖率，异常、权限、拒绝、降级和 failover
   的未执行分支无法量化。
4. 未覆盖代码主要集中在 Infrastructure、Application、Interface 和管理命令，
   与数据可靠性、持久化、权限、异步任务和外部依赖高度相关。
5. 测试数量较多，但仍需持续区分“代码被执行”和“关键行为被有效断言”。

本计划的最终结果不是单纯提高百分比，而是形成可持续的覆盖率真源、风险驱动测试矩阵
和只升不降的 CI 门禁。

## 2. 当前证据快照

### 2.1 代码规模

以下数据是 2026-07-24 当前工作区的盘点快照，不作为长期动态真源：

| 口径 | 文件数 | 物理行 | 非空行 |
|---|---:|---:|---:|
| 核心生产 Python（排除测试和迁移） | 1,822 | 379,883 | 320,431 |
| SDK Python | 207 | 49,091 | 43,505 |
| 运维和工程脚本 Python | 113 | 27,199 | 23,057 |
| 前端 JS/TS/HTML/CSS | 288 | 127,433 | 113,612 |
| Python 测试 | 1,085 | 247,837 | 210,116 |

业务模块数量和静态测试函数数量必须实时读取
`governance/governance_baseline.json`，本文不把快照数值作为后续判定依据。

### 2.2 最新已验证覆盖率

`reports/quality/coverage-final.xml` 是 2026-07-24 14:22 生成的最新完整并集报告：

| 指标 | 快照值 |
|---|---:|
| `apps/` 行覆盖率 | 80.1% |
| 可执行行 | 122,943 |
| 已覆盖行 | 98,456 |
| 未覆盖行 | 24,487 |
| Domain 总体覆盖率 | 94.8% |
| Domain 未覆盖行 | 860 |
| 分支覆盖率 | 未采集 |

该报告生成后仓库仍有生产代码提交和工作区改动。相关定向测试已通过，但未重新生成完整
并集报告。因此上述数据是“最新已验证基线”，不是后续工作区状态的假精确实时值。
正式实施本计划前必须执行 T0 重采。

### 2.3 缺口按架构层分布

| 架构层 | 覆盖率快照 | 未覆盖行 | 当前判断 |
|---|---:|---:|---|
| Infrastructure | 75.3% | 9,370 | 第一优先：数据源、Repository、缓存和外部适配器 |
| Application | 79.4% | 8,204 | 第一优先：拒绝、失败、幂等、重试和权限上下文 |
| Interface | 79.2% | 4,651 | 第二优先：认证、权限、参数和错误映射 |
| Management Commands | 73.7% | 1,367 | 第二优先：批处理、dry-run、失败退出和审计 |
| Domain | 94.8% | 860 | 保持 ≥90%，只补高风险规则分支 |

### 2.4 高缺口模块

按未覆盖绝对行数优先处理：

| 优先级 | 模块 | 未覆盖行快照 | 主要测试方向 |
|---|---|---:|---|
| P0 | `data_center` | 2,721 | 数据源失败、单位、完整性、PIT、主备切换 |
| P0 | `decision_rhythm` | 1,604 | 决策输入、建议执行、幂等、用户确认 |
| P0 | `account` | 1,524 | 用户隔离、资金、持仓读取、失败一致性 |
| P0 | `alpha` | 1,142 | 多级降级、数据覆盖、模型失败、缓存 |
| P0 | `policy` | 1,003 | 任务结果、政策状态、未知输入和审计 |
| P0 | `simulated_trading` | 1,015 | 订单不变量、账本、手续费、失败回滚 |
| P1 | `dashboard` | 1,180 | 查询编排、序列化、空态和权限 |
| P1 | `equity` | 966 | 估值同步、配置、任务结果和数据质量 |
| P1 | `terminal` | 941 | 命令路由、权限、异常恢复和运行时边界 |
| P1 | `prompt` | 888 | 模板选择、版本、变量校验和降级 |

以下模块的百分比低于 80%，即使符合现有非核心模块 70% 门槛，也属于低余量区域：

`sector`、`sentiment`、`prompt`、`fund`、`hedge`、`task_monitor`、
`ai_provider`、`data_center`、`dashboard`、`factor`、`events`、
`ai_capability`、`pulse`。

### 2.5 零覆盖和低覆盖代表文件

以下文件来自覆盖率快照，只用于确定测试批次，实施前必须重新确认路径和职责：

| 文件 | 快照问题 |
|---|---|
| `apps/dashboard/interface/serializers.py` | 161 条可执行行零覆盖 |
| `apps/terminal/application/chat_router.py` | 119 条可执行行零覆盖 |
| `apps/prompt/application/use_cases.py` | 166 行未覆盖，覆盖率约 25% |
| `apps/data_center/infrastructure/macro_sources/fetchers/high_frequency_fetchers.py` | 162 行未覆盖 |
| `apps/data_center/infrastructure/macro_sources/fetchers/base_fetchers.py` | 160 行未覆盖 |
| `apps/agent_runtime/infrastructure/terminal_agent_service.py` | 166 行未覆盖 |
| `apps/alpha_trigger/interface/views.py` | 180 行未覆盖 |
| `apps/fund/infrastructure/repositories.py` | 158 行未覆盖 |

零覆盖文件不得直接按数量清零。必须先分类为：

- 生产关键路径；
- Admin/管理命令；
- 兼容入口或 composition root；
- 不可达或应删除的遗留代码；
- 仅由可选运行时或生产环境触发的代码。

## 3. 完成标准

### 3.1 覆盖率目标

| 范围 | 当前门槛 | 本计划完成目标 |
|---|---:|---:|
| `apps/` 仓库行覆盖率 | ≥80% | ≥85% |
| 金融、资金、执行、决策核心模块 | ≥80% | 每模块 ≥85% |
| 其他业务模块 | ≥70% | 每模块 ≥80% |
| 含实质业务规则的 Domain | ≥90% | 保持每模块 ≥90% |
| `core/` | 未统一统计 | 建立独立报告并达到 ≥80% |
| `shared/` | 未统一统计 | 建立独立报告并达到 ≥80% |
| SDK | 未统一统计 | 建立独立报告并达到 ≥80% |
| 关键 Domain 分支覆盖率 | 未采集 | 建立报告并达到 ≥80% |
| 全仓分支覆盖率 | 未采集 | 建立基线并执行只升不降 ratchet |

若 T0 重采发现新增范围的初始覆盖率与目标差距超过 15 个百分点，不得通过扩大 omit
或降低既有门槛处理。应拆成独立批次，每批设定只升不降的中间阈值，并在本计划跟踪表中
记录最终收口日期。

### 3.2 行为与契约目标

核心模块必须覆盖与自身职责相关的以下行为：

1. 正常成功路径。
2. 参数边界、空输入、缺失数据和非法状态。
3. 业务拒绝与明确拒绝原因。
4. 外部依赖超时、异常、空响应和畸形响应。
5. 主备数据源切换及 1% 一致性容差。
6. 幂等、重复执行、重试和部分失败。
7. 用户隔离、角色权限和跨用户拒绝。
8. timezone-aware 时间边界。
9. 事务提交、回滚、唯一约束和并发冲突。
10. 审计记录、任务业务结果和可观测指标。

## 4. 分阶段实施

### T0：重新采集真实基线

**目标**：消除覆盖率报告与当前代码状态的时间差。

任务：

1. 在干净、固定提交上运行 Unit、Component、API、Migration、Integration、E2E 和
   App-local 测试。
2. 使用唯一 `.coveragerc` 合并 coverage data，重新生成
   `reports/quality/coverage-final.xml`。
3. 运行 `scripts/check_coverage_ratchet.py`。
4. 生成模块、架构层、文件和 missing-line 清单。
5. 记录 skip、xfail、deselected、live/optional 套件及原因。
6. 将快照后新增的生产代码纳入报告，不用旧 XML 推算新覆盖率。

验收：

- 全量报告与当前验收提交一致；
- 报告生成命令、提交 SHA、时间和测试结果可追溯；
- 无新增 skip/xfail 隐藏失败；
- 现有门槛不下降。

### T1：扩展覆盖率统计边界

**目标**：解决 `apps/` 之外的盲区。

任务：

1. 为 `core/`、`shared/`、SDK 分别生成覆盖率报告和阈值。
2. 保持 Python 服务端与浏览器前端报告分离，不把 import coverage 当作浏览器覆盖。
3. 为前端关键交互建立 JS 单元测试或 Node contract 测试。
4. Playwright 只统计用户旅程和浏览器行为，不并入 Python 行覆盖率。
5. 评估 `scripts/` 和生产管理命令，区分工程脚本与生产运行脚本。
6. 将新增范围接入 PR、Nightly 和 RC，但按范围独立显示结果。

验收：

- `apps/core/shared/sdk` 均有机器可读报告；
- CI 能显示每个范围的覆盖变化；
- 报告不得因目录扩展而降低既有 `apps/` 门槛；
- 前端关键交互有独立结果和失败工件。

### T2：启用分支覆盖率

**目标**：量化仅执行一行但未验证全部逻辑分支的问题。

任务：

1. 在独立 CI 试运行中启用 coverage.py branch measurement。
2. 先对 Domain、Application 关键规则和外部适配器建立分支基线。
3. 优先覆盖：
   - `if/elif/else` 边界；
   - `try/except/finally`；
   - 权限允许与拒绝；
   - 幂等首次执行与重复执行；
   - 数据源主路径、备用路径和拒绝切换；
   - Celery 技术成功但业务失败；
   - UNKNOWN、缺失输入和证伪条件。
4. 建立分支覆盖率 ratchet，禁止新增未覆盖分支。
5. Domain 分支覆盖率逐模块收口到 ≥80%。

验收：

- XML/JSON 报告中 `branches-valid` 大于 0；
- 关键 Domain 模块分支覆盖率 ≥80%；
- PR 能显示新增未覆盖分支；
- 不使用 `pragma: no branch` 批量隐藏真实逻辑。

### T3：P0 模块风险补测

**范围**：

`data_center`、`decision_rhythm`、`account`、`alpha`、`policy`、
`simulated_trading`。

每个模块执行相同闭环：

1. 输出 missing-line 和 missing-branch 清单。
2. 标注高损失半径路径，而不是按文件顺序补测试。
3. Domain 使用纯输入和 fake，禁止依赖 ORM、网络和实时时钟。
4. Application 测试成功、业务拒绝、依赖失败、幂等和重试。
5. Repository 测试事务、约束、分页、用户隔离和时区。
6. API 测试状态码、Content-Type、鉴权、权限、错误映射和数据库副作用。
7. 外部数据源测试超时、主备切换、容差、单位和审计原值。
8. Celery 任务区分技术执行状态和业务结果。

验收：

- 每个 P0 模块行覆盖率 ≥85%；
- Domain 保持 ≥90%，关键 Domain 分支覆盖率 ≥80%；
- 不新增 live network 依赖到默认 CI；
- 每个新增测试有明确业务行为或契约断言。

### T4：低覆盖模块收口

**范围**：

`sector`、`sentiment`、`prompt`、`fund`、`hedge`、`task_monitor`、
`ai_provider`、`dashboard`、`factor`、`events`、`ai_capability`、
`pulse`、`terminal`。

任务：

1. 优先处理零覆盖生产关键文件。
2. 对仅为兼容或不可达的文件，先确认引用再删除，不为保留死代码编写空调用测试。
3. 对 Admin 和管理命令覆盖权限、dry-run、失败退出、批处理边界和审计。
4. 对 Dashboard、Terminal、Prompt、AI Provider 覆盖空态、降级、敏感信息保护
   和错误恢复。
5. 对 Events 覆盖 UNKNOWN 类型，不得把未知事件映射为业务事件。
6. 对 Task Monitor 覆盖技术状态、业务结果、超时和丢失心跳。

验收：

- 每个范围模块行覆盖率 ≥80%；
- 零覆盖生产关键文件清零；
- 剩余零覆盖文件均有可审计分类和原因；
- 无新增宽泛 mock 掩盖跨层契约。

### T5：真实集成和关键用户旅程

**目标**：覆盖行覆盖率无法证明的生产协作风险。

任务：

1. PostgreSQL Nightly 验证约束、事务、锁和迁移。
2. Redis/Celery 验证重试、超时、重复投递和业务失败结果。
3. 外部数据源使用录制 fixture 或确定性 fake；真实网络进入受控 live 套件。
4. Qlib、券商执行桥和可选运行时单独报告，不静默跳过。
5. 保留以下关键旅程：
   - 初始化和登录；
   - 数据源/AI 配置；
   - 宏观/Regime/Pulse 到信号和决策；
   - 风控、用户确认和订单；
   - 成交、持仓、对账和审计；
   - observer/admin 权限及跨用户拒绝。
6. Playwright 必须断言可见状态、操作结果、导航、错误恢复和关键副作用。

验收：

- live/optional 测试有单独状态，不与默认套件混为“通过”；
- PostgreSQL、Celery 和关键浏览器旅程有最新成功证据；
- 失败时保存日志、JUnit、截图或 trace；
- 不只断言 HTTP 200 或页面可打开。

### T6：CI 门禁和长期治理

任务：

1. `scripts/check_coverage_ratchet.py` 同时读取行覆盖率和分支覆盖率。
2. PR 显示仓库、模块、Domain、架构层和新增代码覆盖变化。
3. Nightly 运行完整分层套件，RC 增加 PostgreSQL、Playwright 和可选运行时验收。
4. 新增代码覆盖率不得低于所属模块门槛。
5. 禁止通过以下方式让 CI 变绿：
   - 降低阈值；
   - 扩大 omit；
   - 新增无理由 skip/xfail；
   - 使用 import-only 测试冲覆盖率；
   - 使用无业务断言的空调用；
   - 宽泛 mock 掉被测模块核心行为。
6. 每次阈值提升后更新机器基线和计划跟踪表，不在多个工作流复制阈值。

验收：

- `apps/` 行覆盖率 ≥85%；
- 核心模块 ≥85%，其余业务模块 ≥80%；
- `core/shared/sdk` 分别 ≥80%；
- Domain 行覆盖率每模块 ≥90%，关键 Domain 分支覆盖率 ≥80%；
- 默认 CI 0 个非预期失败；
- 覆盖率和测试结果可从同一提交复现。

## 5. 推荐实施顺序

| 批次 | 主线 | 建议范围 | 交付 |
|---|---|---|---|
| 1 | T0 | 当前工作区收口后 | 新鲜全量基线 |
| 2 | T1 + T2 基础设施 | coverage 配置和 CI | 多范围报告、分支基线 |
| 3 | T3A | `data_center/account/decision_rhythm` | 数据、资金、决策风险补测 |
| 4 | T3B | `alpha/policy/simulated_trading` | 模型、政策、交易不变量补测 |
| 5 | T4A | `prompt/terminal/dashboard/ai_provider` | 用户入口和 AI 边界补测 |
| 6 | T4B | 其余低覆盖模块 | 所有业务模块 ≥80% |
| 7 | T5 | PostgreSQL/Celery/Playwright/live | 生产协作证据 |
| 8 | T6 | PR/Nightly/RC | 最终 ratchet 和收口记录 |

遵守仓库开发节奏：单日一个测试主线加一个小收口。不要把大规模补测、业务重构、
部署修复和治理文档混在同一批提交。

## 6. 标准验证命令

以下命令为实施入口；运行前应按当前 CI 脚本确认最终参数：

```powershell
# Fast suite
python scripts/run_fast_tests.py

# Unit
python -m pytest tests/unit/ -q --cov=apps --cov-config=.coveragerc

# Component
python -m pytest tests/component/ -q --cov=apps --cov-config=.coveragerc --cov-append

# API and migrations
python -m pytest tests/api/ tests/migrations/ -q `
  --cov=apps --cov-config=.coveragerc --cov-append

# Integration without controlled live/optional/diagnostic tests
python -m pytest tests/integration/ `
  -m "not live_required and not optional_runtime and not diagnostic" `
  -q --cov=apps --cov-config=.coveragerc --cov-append

# Django E2E and app-local tests
python -m pytest tests/e2e/ -q --cov=apps --cov-config=.coveragerc --cov-append
python -m pytest apps/*/tests -q --cov=apps --cov-config=.coveragerc --cov-append

# Generate and enforce the merged report
python -m coverage xml -o reports/quality/coverage-final.xml
python scripts/check_coverage_ratchet.py reports/quality/coverage-final.xml

# Existing critical chains
python -m pytest tests/unit/test_tui_workbench.py -q
python -m pytest tests/unit/test_terminal_agent_service.py -q
python -m pytest sdk/tests/test_sdk/test_client.py -q
python -m pytest tests/unit/test_internal_ssl_redirect.py -q
```

Playwright 必须继续通过 `scripts/run_live_server_pytest.py` 管理 live server，
并保存 server log、pytest log、JUnit、截图或 trace。

## 7. 每批提交要求

每个覆盖提升批次必须记录：

- 当前阶段目标；
- 目标模块和目标行为；
- 修改前覆盖率与 missing-line/missing-branch 证据；
- 新增或调整的测试；
- 已完成项；
- 未完成项；
- 已运行测试及结果；
- 未运行测试和未验证风险；
- 覆盖率变化；
- 回滚点。

提交应按职责拆分：

- `test:` 行为或契约覆盖；
- `fix:` 测试复现后修复的业务缺陷；
- `chore:` coverage/CI 门禁；
- `docs:` 计划、证据和收口记录。

不得把大规模测试补齐、生产逻辑修改、CI 重构和文档治理堆入同一个提交。

## 8. 风险与控制

| 风险 | 控制措施 |
|---|---|
| 为提高百分比编写脆弱测试 | 优先断言公开行为、业务不变量和副作用 |
| Django 自动 import 形成覆盖率底噪 | 同时检查断言语义、分支和契约矩阵 |
| 启用分支统计导致门禁突降 | 先独立采集基线，再分阶段 ratchet |
| 外部数据源导致随机失败 | 默认使用确定性 fake/fixture，真实源进入 live 套件 |
| PostgreSQL 与 SQLite 行为不一致 | Nightly/RC 强制 PostgreSQL 验证 |
| 过度 mock 导致虚假通过 | mock 只停在外部边界，Repository 和应用协作使用集成测试 |
| 零覆盖文件被无差别补测 | 先分类关键路径、管理入口、兼容代码和死代码 |
| 与其他开发主线冲突 | 独立分支、独立 commit 组，先冻结目标模块 |
| 覆盖率口径漂移 | `.coveragerc` 和机器基线保持唯一真源 |

## 9. 跟踪表

| 阶段 | 状态 | 完成证据 | 未完成项 |
|---|---|---|---|
| T0 真实基线重采 | 待开始 | — | 全量并集报告 |
| T1 扩展统计边界 | 待开始 | — | `core/shared/sdk/frontend` 报告 |
| T2 分支覆盖 | 待开始 | — | 分支基线和 ratchet |
| T3 P0 模块补测 | 待开始 | — | 六个高风险模块 |
| T4 低覆盖模块收口 | 待开始 | — | 所有业务模块 ≥80% |
| T5 生产集成和旅程 | 待开始 | — | PostgreSQL/Celery/live/Playwright |
| T6 CI 和治理收口 | 待开始 | — | 最终阈值和可复现证据 |

## 10. 启动条件

本计划进入实施前必须同时满足：

1. 当前正在进行的 Celery 任务结果契约主线完成或冻结，避免测试计划与生产代码持续漂移。
2. 选择独立 `dev/test-*` 分支，禁止直接在 `main` 开发。
3. 固定 T0 的提交 SHA。
4. 明确首批只推进 `data_center/account/decision_rhythm`，不同时扩散到所有模块。
5. 确认完整 coverage 采集的 CI 时间预算和报告保存位置。

满足启动条件后，先执行 T0，不直接从补零覆盖文件开始。
