# 测试覆盖薄弱环节整改实施记录

> **启动日期**：2026-07-24
> **实施分支**：`dev/test-coverage-remediation-20260724`
> **冻结基准提交**：`5ba332c59ab94fd89ba3b6517d589b9e02fab609`
> **对应计划**：`test-coverage-weakness-remediation-2026-07-24.md`

## 当前阶段目标

本批只推进以下主线：

1. T0：在固定提交上重采可追溯基线，显式记录失败、skip、xfail 和未运行套件。
2. T1：建立 `apps/core/shared/sdk` 独立机器报告和前端 Node 契约结果。
3. T2：启用分支采集，先建立可见基线，不用降低既有行覆盖门槛换取通过。
4. T3A 首批：只对 `data_center/account/decision_rhythm` 的高损失半径补行为测试。

首批提交完成后，2026-07-25 按原计划单独推进 T3B：
`alpha/policy/simulated_trading`。生产部署修复和其他治理主线不在 T3B 扩散。

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
| `apps` | 81.13% | 63.42% | line 80.0 / branch 62.8 |
| `core` | 69.47% | 51.33% | line 69.4 / branch 51.3 |
| `shared` | 69.07% | 50.29% | line 69.0 / branch 50.2 |
| SDK/MCP | 72.16% | 52.38% | line 72.1 / branch 52.3 |

架构层当前值：

| 层 | 行覆盖率 | 分支覆盖率 | 未覆盖行 |
|---|---:|---:|---:|
| Domain | 94.83% | 85.16% | 857 |
| Application | 80.18% | 61.35% | 7,994 |
| Infrastructure | 75.93% | 55.88% | 9,185 |
| Interface | 80.08% | 57.57% | 4,500 |
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
- Fast suite：`3,578 passed in 31.03s`，总耗时 `45.22s`，低于 120 秒预算。
- 固定高风险链路：`229 passed`。
- 最终 coverage ratchet 已通过。

## 当前未完成项

- 本批建立了真实 ratchet，但尚未达到计划最终目标：
  - `apps >=85%`；
  - `core/shared/sdk >=80%`；
  - 所有 P0 模块行覆盖率 `>=85%`；
  - 关键 Domain 分支覆盖率 `>=80%`。
- T3A 当前模块行覆盖率：
  - `data_center=77.85%`；
  - `account=81.23%`；
  - `decision_rhythm=83.51%`。
- T4、T5 和最终 T6 收口尚未开始；应按原计划在后续独立批次推进，不能在本批
  用扩大 omit 或降低阈值替代。
- Integration 修复后仅重跑了受影响的 24 项，完整 Integration 尚未二次全量重跑。
- PostgreSQL、Celery worker、live/optional runtime 和 Playwright RC 尚未在本地执行。
- AGENTS 指定的 `agomtradepro` conda 环境在本机不可用；本次证据来自
  Python 3.13.5 / Django 5.2.12。CI 的 Python 3.11 仍需远端验证。

## 阻断项

固定 SHA 的 Guardrail 仍有一个非本分支引入的失败：

- `apps/broker_execution/infrastructure/repositories.py` 从允许的 2,790 行增长到
  2,897 行；
- `apps/strategy/infrastructure/repositories.py` 为 1,225 行，未登记治理基线。

本批未通过抬高允许行数或扩大豁免隐藏该回退。另一 goal 的原工作区仍有未提交修改，
因此当前分支暂不合并；应先由对应主线完成结构整改或给出经审核的治理决策。

## 回滚点

本批不修改生产业务逻辑和数据库 schema。若 branch/multi-scope 采集影响 Nightly，
可单独回滚 coverage/CI 提交；测试数据契约修正可独立保留。
