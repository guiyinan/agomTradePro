# 测试覆盖薄弱环节整改实施记录

> **启动日期**：2026-07-24
> **实施分支**：`dev/test-coverage-remediation-20260724`
> **冻结基准提交**：`5ba332c59ab94fd89ba3b6517d589b9e02fab609`
> **对应计划**：`test-coverage-weakness-remediation-2026-07-24.md`

## 当前阶段目标

当前分支已按独立批次推进以下测试主线：

1. T0：在固定提交上重采可追溯基线，显式记录失败、skip、xfail 和未运行套件。
2. T1：建立 `apps/core/shared/sdk` 独立机器报告和前端 Node 契约结果。
3. T2：启用分支采集，先建立可见基线，不用降低既有行覆盖门槛换取通过。
4. T3A 首批：只对 `data_center/account/decision_rhythm` 的高损失半径补行为测试。
5. T3B：`alpha/policy/simulated_trading` 的模型、政策、交易失败边界。
6. T4A：`prompt/terminal/dashboard/ai_provider` 的用户入口、敏感信息和错误恢复。
7. T4B 第一批：`fund/hedge/sector/sentiment` 的数据源降级、任务结果和空态。
8. T3A 收口：把 `data_center/account/decision_rhythm` 三个 P0 模块和关键
   Domain 分支补到正式门槛。

生产部署修复和其他治理主线不在 T3B/T4A 扩散。

## 分支与并行工作隔离

启动时 `dev/next-development` 存在未提交的 Celery 任务结果契约改动。为避免污染，
本批从当时已提交的 `5ba332c5` 创建独立 worktree 和独立 `dev/test-*` 分支。
另一主线完成前不合并其未提交文件；本批形成独立、可验证提交后，再按提交依赖选择
merge 或 cherry-pick。

实施期间桌面 Git 客户端曾自动 stash 本 worktree 并切换到另一 goal 的分支；变更已从
`0bd3a81f` 完整恢复到本分支。该事件没有丢失文件，但证明另一主线结束前不应在共享
桌面会话中直接合并。

## T0 初次证据

首次 Unit 分片仍使用整改前的 `apps` 行覆盖口径，用于确认固定提交是否可验收：

- 结果：`5236 passed, 3 failed, 7 warnings`
- 时间：`418.04s`
- `apps` Unit 行覆盖率：`59.2%`（`73,469 / 124,165`）
- 报告：`reports/quality/coverage-t0-unit.xml`
- 日志：`reports/quality/t0-unit.stdout.log`

三个失败均为测试数据未同步当前生产契约：

- Prompt history 缺少当前必需的非空 `content`；
- Alpha exit loop 的 fake `FeeConfig` 缺少必需 `min_commission`（两例）。

测试数据已按实体和 serializer 真实契约修正，三例定向回归为 `3 passed`。该 Unit
分片不是完整并集，`59.2%` 不用于修改仓库覆盖阈值。

## T0 分层重采结果

| 套件 | 结果 | 说明 |
|---|---:|---|
| Unit | 5,283 passed | branch-aware 完整重采；后续新增 5 个 Backtest 测试另行定向通过 |
| Component | 1,747 passed, 4 skipped | skip 均为需要迁移 `0003_failed_event` 的显式 fault-injection 场景 |
| API + Migration | 611 passed | — |
| Critical | 18 passed | — |
| Integration | 947 passed, 18 failed | 失败均为 `min_commission` 测试 fixture 漂移；修复后相关 24 项通过 |
| App-local | 301 passed | — |
| Django E2E | 97 passed | — |
| Guardrails | 146 passed, 1 failed | 固定 SHA 已存在超大文件治理回退，见“阻断项” |
| SDK | 412 passed | 并行、离线 |
| MCP | 686 passed | 修复测试角色/审计边界后并行通过 |
| Frontend Node | 16 passed | 独立 JUnit，不并入 Python coverage |

全仓未发现 `xfail`。SDK/MCP 首次并行执行暴露出依赖全局 dispatcher 角色和本地 HTTP
审计端点的测试污染；测试 fixture 已改为每例显式 staff 角色和审计 fake，MCP 全量
耗时从超过 15 分钟预算降至 193.13 秒。

## 最新覆盖基线

同一份 branch-aware `.coverage` 已投影为以下机器报告：

| Scope | 行覆盖率 | 分支覆盖率 | 初始 ratchet |
|---|---:|---:|---|
| `apps` | 81.84% | 64.20% | line 80.0 / branch 62.8 |
| `core` | 69.47% | 51.33% | line 69.4 / branch 51.3 |
| `shared` | 69.25% | 50.29% | line 69.0 / branch 50.2 |
| SDK/MCP | 72.16% | 52.38% | line 72.1 / branch 52.3 |

架构层当前值：

| 层 | 行覆盖率 | 分支覆盖率 | 未覆盖行 |
|---|---:|---:|---:|
| Domain | 94.83% | 85.16% | 857 |
| Application | 82.38% | 63.65% | 7,108 |
| Infrastructure | 77.07% | 57.29% | 8,750 |
| Interface | 80.79% | 57.57% | 4,339 |
| Management Commands | 75.96% | 65.82% | 1,194 |

所有有实质分支的 Domain 模块已写入逐模块只升不降基线。完成目标仍是每个关键
Domain 分支覆盖率至少 80%，当前 `data_center=67.97%`、
`decision_rhythm=76.09%`、`account=84.81%`。

## 已完成项

- `.coveragerc` 开启 branch measurement，并把 `apps/core/shared/sdk` 纳入同一采集真源。
- 覆盖率 ratchet 可解析行和分支，并能拒绝缺失 scope 报告或未采集 branch 的报告。
- 新增统一报告生成器，从同一个 `.coverage` 生成：
  - `coverage-final.xml`
  - `coverage-apps.xml`
  - `coverage-core.xml`
  - `coverage-shared.xml`
  - `coverage-sdk.xml`
  - `coverage-final-details.json`
  - `coverage-inventory.json`
  - `coverage-manifest.json`
- manifest 记录提交 SHA、UTC 时间、配置 SHA-256 和各报告 SHA-256。
- Nightly 增加 SDK/MCP、Django E2E、前端 Node contract 测试和独立工件。
- RC Playwright 不再采集 Django import coverage，避免把浏览器旅程冒充 Python 行覆盖。
- 覆盖工具和质量报告定向测试通过。
- 前述三个基线失败的定向回归通过：`3 passed`。
- T3A 首批新增并验证：
  - Data Center 高频 fetcher 的缺失、畸形、上游异常、缓存和 no-op 行为；
  - Decision Rhythm 的 fail-closed 风控、跨用户拒绝、执行闸门、部分失败和缓存隔离；
  - Account 波动率调整的所有权、非法快照、幂等、不落库和设置边界。
- 修复模拟交易集成 fixture 的必需 `min_commission`，相关 `24 passed`。
- 为 Backtest 补齐 Audit gateway fail-closed 和 interface service 契约，恢复既有
  核心模块 80% 门槛。
- T3B 已按独立批次完成：
  - Alpha 覆盖运行时刷新、Qlib 缓存降级、空预测、组合隔离、投递锁回滚、
    运维摘要、基本面完整性与行情/model 失败；
  - Policy 覆盖 Celery 重试耗尽、RSS 两阶段保存、AI/关键词降级、内容提取、
    事件身份更新/删除、告警和新闻源失败；
  - Simulated Trading 覆盖账户所有权、组合/成交查询、持仓关闭、日检分支、
    绩效部分失败、邮件通知和 Repository 初始化失败；
  - 三个模块分别建立 85% 机器阈值，`scripts/check_coverage_ratchet.py`
    支持逐模块 `module_minimums`，避免抬高尚未收口的其他核心模块门槛；
  - T3B 新增/调整测试整批 `84 passed`，三个目标模块相关 Unit 回归
    `248 passed, 6 warnings`。
- T3B 后的模块覆盖率：
  - `alpha=85.05%`（`5,133 / 6,035`），分支 `70.71%`；
  - `policy=85.06%`（`4,373 / 5,141`），分支 `67.71%`；
  - `simulated_trading=85.01%`（`5,018 / 5,903`），分支 `69.28%`。
- T4A 已按独立批次完成：
  - Prompt 覆盖模板缺失、占位符来源优先级、AI 失败、串行/并行/工具链、
    报告/信号 facade、追踪日志截断与持久化失败；
  - Terminal 覆盖状态/Regime/chat 三条路由、低置信度确认、分类器畸形输出、
    普通用户技术细节屏蔽和 AI 失败恢复；
  - Dashboard 将原零覆盖的 161 行 serializers 全部纳入嵌套、空态、只读字段和
    非法 mutation 契约；
  - AI Provider 覆盖密钥迁移命令的 unavailable/noop/dry-run/force/skip/error，
    断言明文密钥不会写入输出；
  - 修复 Prompt 旧版 `provider_name` 在 `provider_ref=None` 时无法降级，以及
    Chain 结果重建重复传参导致所有执行失败的两个生产缺陷；
  - Prompt 生产文件通过增量 mypy，未添加 `type: ignore` 或债务豁免；
  - T4A 新增测试整批 `47 passed`，相关 Unit 交叉回归
    `400 passed`，固定高风险链路 `229 passed`。
- T4A 后的模块覆盖率：
  - `prompt=80.15%`（`2,621 / 3,270`），分支 `58.23%`；
  - `terminal=83.80%`（`4,256 / 5,079`），分支 `69.06%`；
  - `dashboard=81.46%`（`4,241 / 5,206`），分支 `66.18%`；
  - `ai_provider=80.81%`（`1,554 / 1,923`），分支 `58.03%`。
- 四个 T4A 模块均建立 80% 机器阈值；代表性零覆盖生产文件已变为
  `dashboard serializers=100%`、`terminal chat_router=99.16%`。
- T4B 第一批已完成：
  - Fund 覆盖显式/持久化 Regime、筛选空态、风格/业绩数据不足、保存失败、
    data-center NAV 优先和 AKShare/Tushare failover；
  - Hedge 覆盖代码标准化、持久化价格、缓存/实时回退、全源耗尽、singleton，
    以及效果、相关性、组合、告警和比例 payload 的空态；
  - Sector 覆盖两个 Celery 任务的业务失败和异常、Tushare 兼容字段、
    成分股空态/代码规范化、股票板块映射去重及 Repository 写入失败；
  - Sentiment 覆盖政策/新闻逐项隔离、已存新闻评分、空文本、批量部分失败、
    事件不存在和 freshness 的 missing/current/stale/error；
  - 新增测试整批 `42 passed`，相关 Unit 交叉回归
    `408 passed, 1 CacheKeyWarning`；未修改生产代码。
- T4B 第一批后的模块覆盖率：
  - `fund=80.34%`（`1,291 / 1,607`），分支 `54.59%`；
  - `hedge=80.09%`（`1,356 / 1,693`），分支 `60.77%`；
  - `sector=80.55%`（`642 / 797`），分支 `65.38%`；
  - `sentiment=80.57%`（`626 / 777`），分支 `61.02%`。
- 四个模块均建立 80% 机器阈值；Hedge 和 Sector 使用精确覆盖分子越过门槛，
  未依赖报告四舍五入。
- T4B 第二批已完成：
  - Task Monitor 覆盖 Celery 技术状态、规范化业务 `outcome`、重试/失败/撤销、
    备份校验、清理任务和 Worker 心跳缺失；
  - 修复 Task Monitor 将 `outcome=failed/partial/blocked` 误记为成功，以及
    Broker/Backend 可达但没有 Worker 心跳时仍报告健康的两个生产缺陷；
  - Events 覆盖失败事件保存/读取、未知事件显式映射 `UNKNOWN`、指数退避、
    重试耗尽、批量统计和 singleton；
  - AI Capability 覆盖目录初始化、同步、治理 dry-run/apply、JSON 输出、
    unsafe/MCP 缺失告警及按来源决定是否治理；
  - Factor 覆盖 CRUD/filter、组合持仓 payload、解释空态、表单数值规范化、
    页面上下文和组合动作；
  - Pulse 覆盖周任务成功/业务失败和完整/非法快照 serializer 契约；
  - 新增测试整批 `44 passed`，五个目标模块相关 Unit 交叉回归
    `829 passed`；Task Monitor 修改文件增量 mypy 与架构边界均为 0 回退。
- T4B 第二批后的模块覆盖率：
  - `task_monitor=80.45%`（`1,362 / 1,693`），分支 `55.37%`；
  - `factor=80.06%`（`1,397 / 1,745`），分支 `59.20%`；
  - `events=80.10%`（`2,053 / 2,563`），分支 `63.48%`；
  - `ai_capability=83.89%`（`2,646 / 3,154`），分支 `63.53%`；
  - `pulse=83.27%`（`712 / 855`），分支 `68.28%`。
- 五个模块均建立 80% 机器阈值；当前 `apps=82.14%`
  （`102,020 / 124,200`），分支 `64.56%`。
- T3A 已完成收口：
  - Decision Rhythm 覆盖审批/拒绝、批量部分失败、配额状态与重置、队列、
    状态机和调度器，新增 `33 passed`；
  - Account 覆盖 RBAC fail-closed、文档导入导出、备份/止损/止盈任务失败、
    账户配置、Token、资金流水和回测落仓，完整模块单测 `151 passed`；
  - Data Center 覆盖宏观 fetcher 矩阵、连接探针、Domain 验证、统一 Provider
    转换、Sync 失败审计、QMT/Tushare 降级；新增两批共 `118 passed`，
    完整模块单测 `386 passed`；
  - 六个 P0 模块全部达到 85%：`data_center=85.06%`
    （`9,912 / 11,653`）、`account=85.00%`（`6,711 / 7,895`）、
    `decision_rhythm=85.00%`（`7,154 / 8,416`）、`alpha=85.05%`、
    `policy=85.06%`、`simulated_trading=85.01%`；
  - Data Center Domain 提升到 `98.05%` 行覆盖和 `89.06%` 分支覆盖，
    Decision Rhythm Domain 分支为 `80.43%`；
  - 三个 T3A 模块均建立逐模块 85% 机器阈值，Data Center Domain 分支
    棘轮为 89.0%；覆盖率 ratchet 通过。
- T3A 收口后的总体覆盖率为 `apps=83.16%`
  （`103,284 / 124,200`），分支 `66.02%`。
- Fast suite：`3,578 passed in 31.03s`，总耗时 `45.22s`，低于 120 秒预算。
- 固定高风险链路：`229 passed`。
- 最终 coverage ratchet 已通过。

## T5 真实运行时验收

- Playwright RC 通过 `scripts/run_live_server_pytest.py` 启动真实 Django 服务：
  `33 passed in 147.54s`。首次运行发现隔离 SQLite 尚未迁移，完成迁移后全量重跑
  通过；证据为 `reports/quality/t5-playwright-smoke.xml` 及对应 server/pytest 日志。
- PostgreSQL 使用唯一临时容器、空数据库和正式迁移链验证：
  - 空库全量迁移通过；
  - 针对 PostgreSQL 暴露的修复回归 `3 passed`；
  - Critical + Research migration 全量 `21 passed`；
  - 修复 `select_for_update()` 对 nullable outer join 的 PostgreSQL 锁定错误，并
    修正迁移测试的事务隔离方式；
  - 本机已有镜像为 PostgreSQL 15.15，拉取 PostgreSQL 16 超时，因此该项存在
    “15.15 而非计划 16”的明确环境偏差，但使用的是真实 PostgreSQL，不是 SQLite
    伪装。
- Celery 使用唯一临时 Redis、真实 worker、真实 broker/backend 和临时 PostgreSQL：
  - `inspect ping` 成功；
  - 安全清理任务重复投递两次均返回规范化 `success/noop`；
  - 非法 `older_than_days` 的 AsyncResult 技术状态为 `SUCCESS`，业务 payload
    明确为 `success=false`，证明监控可区分技术完成与业务失败；
  - worker 按精确 node 名优雅关闭。
- 所有本批临时 PostgreSQL/Redis 容器均已删除，未停止或改动另一 goal 的容器。

## T6 最终回归与覆盖验收

同一份从空 `.coverage` 开始的 branch-aware 数据完成以下全量/分层回归：

| 套件 | 最终结果 |
|---|---:|
| Unit | 5,990 passed |
| Component | 1,747 passed, 4 skipped |
| API + Migration | 611 passed |
| Critical | 18 passed |
| Integration | 965 passed, 13 deselected |
| App-local | 301 passed |
| SDK/MCP | 1,120 passed |
| Django E2E | 97 passed |
| Guardrails | 146 passed, 1 个冻结基线已知失败 |
| Frontend Node | 通过，JUnit 已生成 |
| Fast suite | 3,722 passed，61.81s / 120s |
| 固定高风险回归包 | 229 passed |
| Sentiment 定向回归 | 124 passed |
| 覆盖边界追加回归 | 292 passed + 13 passed |

T6 期间发现并修复两处测试基础设施缺陷：

- 仓库存在同名测试模块，默认 import 模式导致 Unit 全量收集冲突；`pytest.ini`
  改为 `--import-mode=importlib` 后 `5,990` 项完整收集并通过。
- SDK 扩展工具 smoke 的统一 fake 列表遗漏 `policy_tools`，使
  `create_policy_event` 可能访问 `127.0.0.1:8000`；补齐隔离后定向 `1 passed`，
  完整 xdist 套件 `1,120 passed`。

最终覆盖门槛均由机器 ratchet 校验，不降低阈值、不扩大 omit：

- `apps` 行覆盖率达到 `85.0%`；
- `core=80.1%`、`shared=80.6%`、`sdk=80.2%`；
- 六个 P0：`data_center=86.3%`、`account=86.7%`、
  `decision_rhythm>=85.0%`、`alpha=85.1%`、`policy=85.1%`、
  `simulated_trading=86.6%`；
- 其余业务模块均不低于 `80%`；
- 所有 Domain 模块行覆盖率不低于 `90%`，机器登记的关键 Domain 分支门槛通过；
- Sentiment 最终为 `88.4%`，畸形 `keywords` payload 已有生产修复和回归；
- mypy 总债务从 `3,197 / 616 files` 降至 `3,157 / 611 files`，基线只收紧不放宽；
- 架构增量与全量扫描均为 `0 boundary / 0 audit` 违规。

完整 Guardrail 的唯一失败仍是下述冻结基线超大文件债务；本分支相对
`5ba332c5` 没有修改这两个文件。真实 Celery 业务结果由 T5 证据覆盖。

## 当前未完成项

- 本计划范围内的覆盖率、真实运行时、分层回归和机器治理目标已完成。
- AGENTS 指定的 `agomtradepro` conda 环境在本机不可用；最终证据来自
  Python 3.13.5 / Django 5.2.12。Python 3.11 CI 仍属于合并后的远端环境验证。
- 原工作区的另一 goal 仍在运行，因此本分支只形成可合并提交，不在共享工作区
  自动 merge；待另一 goal 收口后再 merge 或按提交依赖 cherry-pick。

## 阻断项

固定 SHA 的 Guardrail 仍有一个非本分支引入的失败：

- `apps/broker_execution/infrastructure/repositories.py` 从允许的 2,790 行增长到
  2,897 行；
- `apps/strategy/infrastructure/repositories.py` 为 1,225 行，未登记治理基线。

本批未通过抬高允许行数或扩大豁免隐藏该回退。另一 goal 的原工作区仍有未提交修改，
因此当前分支暂不合并；应先由对应主线完成结构整改或给出经审核的治理决策。

## 回滚点

本批不修改数据库 schema。T4A 的 Prompt 生产修复与覆盖率治理、行为测试分别提交，
可独立回滚；若 branch/multi-scope 采集影响 Nightly，也可单独回滚 coverage/CI
提交而保留测试和缺陷修复。
