# 0.8.0 发布后两周稳定化实施清单

> **文档日期**: 2026-07-08
> **执行窗口**: 2026-07-08 ~ 2026-07-22
> **适用对象**: 实施团队 / 运维团队 / 测试负责人
> **目标**: 将 AgomTradePro 从“`0.8.0` 已正式切版”推进到“运行闭环稳定、证据链完整、关键热区回归可控”

---

## 1. 背景判断

当前仓库状态说明项目已进入 `0.8.0` 发布后的稳定化阶段，而不是大规模新功能阶段。

判断依据：

- [docs/VERSION.md](../VERSION.md) 已将 `0.8.0` 定义为正式发布版本线。
- [docs/governance/SYSTEM_BASELINE.md](../governance/SYSTEM_BASELINE.md) 已将正式生产口径收敛到 `PostgreSQL + Redis + Celery + persisted evidence`。
- 最近提交以 `fix / chore / docs / test` 为主，主战场集中在 `task_monitor`、`terminal/TUI`、`data_center`、VPS 运行链路和 readiness 证据链。
- [docs/testing/personal-investment-readiness-2026-06-30.md](../testing/personal-investment-readiness-2026-06-30.md) 中最新已落库的连续运行记录显示：在 `2026-07-03` scheduler evidence 之后，状态仍为 `accepted_days=4`、`remaining_days=16`、`status=in_progress`。这说明“功能存在”不等于“正式运行闭环已完成”。

因此，未来两周工作重点应为：

1. 完成运行与验收闭环
2. 压缩高频变更热区的回归风险
3. 清理少量剩余结构债
4. 补齐正式发布锚点与交付材料

---

## 2. 执行原则

本窗口内默认遵循以下原则：

1. **停止新增非必要功能面**。除阻断稳定性的修复外，不新增大型功能。
2. **先证据、后叙事**。任何“已稳定”“已可用”结论必须附带命令输出、证据文件或回归记录。
3. **先生产链路、后局部优化**。优先级高于 UI 微调、低价值重构和非关键体验优化。
4. **先黑盒回归、后结构优化**。高风险热区先证明不坏，再拆文件。
5. **所有修复都必须落文档**。至少同步到对应测试/运维/实施文档。

---

## 3. 总体优先级

| 优先级 | 模块/主题 | 判断 | 本窗口目标 |
|------|------|------|------|
| `P0` | `task_monitor` / readiness / VPS runtime | 最大缺口 | 完成连续运行验收链，跑通稳定 scheduler-clean 证明 |
| `P1` | `alpha` / `data_center` / `risk_center` 联动 | 决策主链风险区 | 稳住 Qlib、新鲜度、决策数据守门和风控联动 |
| `P1` | `terminal` / `agent_runtime` / TUI operator | 高频变更区 | 补黑盒回归，减少 operator/TUI 回退 |
| `P2` | TUI 大文件与残余结构债 | 非阻断，但应压缩 | 清掉至少一项 temporary allowance 或形成明确拆分结果 |
| `P2` | 发布锚点与稳定化总结 | 交付缺口 | 补正式 tag、补稳定化报告、形成对外可转发材料 |

---

## 4. 两周 Top 10 任务

### 4.1 P0 任务

| ID | 优先级 | 任务 | 负责人角色 | 关键模块 | 推荐命令 / 检查 | 验收标准 | 主要风险 |
|------|------|------|------|------|------|------|------|
| `S1` | `P0` | 跑完 readiness 连续证据窗口 | 运维负责人 | `task_monitor` | `python manage.py show_personal_readiness_status --json --strict-monitor --require-local-scheduler-runtime` | 连续窗口推进，formal evidence 连续、可读、无手工破坏链 | 调度任务安全但未实际派发；证据断档 |
| `S2` | `P0` | 跑通 VPS scheduler-clean 验收 | 运维负责人 | `task_monitor` / VPS | `powershell -ExecutionPolicy Bypass -File scripts/check-personal-readiness-monitor.ps1 -SummaryOnly` | 至少一个完整交易周内 worker/beat/evidence/runtime 持续稳定 | 端口漂移、volume 未持久化、worker/beat collateral restart |
| `S3` | `P0` | 固化 health / DB / metrics 巡检链 | 运维 + 测试 | `task_monitor` / system health | `python manage.py healthcheck --json` | health、database、metrics 口径一致，异常可复现、可定位 | endpoint 回退、兼容探针与页面不一致 |
| `S4` | `P0` | 输出最新 readiness 状态快照文档 | 文档/测试负责人 | docs / `task_monitor` | 汇总上述命令与 evidence 文件 | 明确写出截至某日 accepted/remaining、阻塞项、下一动作 | 团队继续凭口头状态推进 |

### 4.2 P1 任务

| ID | 优先级 | 任务 | 负责人角色 | 关键模块 | 推荐命令 / 检查 | 验收标准 | 主要风险 |
|------|------|------|------|------|------|------|------|
| `S5` | `P1` | 做一轮 Alpha 生产态回归 | 测试负责人 | `alpha` / `dashboard` | `python scripts/run_alpha_ops_regression.py` | Qlib freshness、workspace consistency、scope/actionable 守门稳定 | 研究态结果误当生产建议；缓存/作用域漂移 |
| `S6` | `P1` | 做一轮 Data Center 决策链回归 | 测试负责人 | `data_center` | `pytest tests\\unit\\data_center -q` | market thermometer、decision readiness、provider failover 无回退 | blocked snapshot 被误持久化；latest usable fallback 失效 |
| `S7` | `P1` | 做一轮 Risk Center 联动回归 | 测试 + 业务 | `risk_center` / `strategy` / `simulated_trading` | 重点跑 pre-trade / post-investment / daily report 链路 | 风控在真实执行链中不中断、不绕过、不静默失败 | 策略执行链绕过集中风控；日报证据不完整 |
| `S8` | `P1` | 做一轮 TUI operator 黑盒回归 | 测试负责人 | `terminal` / `agent_runtime` | 重点覆盖 `/tui/`、operator home、governance、overview、default action | 默认入口、operator API、导航流无明显回退 | TUI 改动快，局部修复引入新回退 |

### 4.3 P2 任务

| ID | 优先级 | 任务 | 负责人角色 | 关键模块 | 推荐命令 / 检查 | 验收标准 | 主要风险 |
|------|------|------|------|------|------|------|------|
| `S9` | `P2` | 继续拆 TUI 剩余大文件 | 开发负责人 | `terminal` | 以 `tui_workbench_result_models.py` 为目标 | large-file allowance 至少下降一轮，行为不变 | 为拆而拆，回归不足导致 operator 流程破坏 |
| `S10` | `P2` | 补发布锚点与稳定化总结 | 仓库负责人 | Git / docs | `git tag --list`、补 release 文档 | 补正式 tag，形成一份可转发稳定化结论 | 外部对版本状态理解模糊，无法快速追溯 |

---

## 5. 建议排期

### 第 1 周：`2026-07-08` ~ `2026-07-14`

目标：先稳运行链路。

1. 优先执行 `S1`、`S2`、`S3`
2. 每个交易日收盘后记录一次 readiness 状态
3. 若 scheduler / worker / beat / evidence 任一环不稳定，暂停非必要优化
4. 并行准备 `S5`、`S6` 的回归脚本与基线数据

### 第 2 周：`2026-07-15` ~ `2026-07-22`

目标：回归高风险热区并压结构债。

1. 完成 `S5`、`S6`、`S7`、`S8`
2. 若第 1 周运行链路已稳定，再执行 `S9`
3. 收尾 `S10`，形成对外可转发结果材料

---

## 6. 每日执行节奏

建议实施团队按以下节奏推进：

### 开盘前

- 检查前一日 evidence 是否已落盘
- 检查 beat / worker / queue / health 状态
- 记录当前阻塞项

### 收盘后

- 运行 readiness 状态检查
- 检查 quote pre-refresh 与 daily evidence 是否由 scheduler 正常触发
- 若异常，先修调度与运行时，不优先做手工 backfill

### 日终

- 更新当日执行记录
- 记录“今日是否推进 accepted_days”
- 记录“下一步动作是什么”

---

## 7. 不建议本窗口做的事

以下事项默认不进入这两周窗口，除非直接阻断稳定性：

- 新增大型业务模块
- 大规模视觉重做
- 与稳定性无关的 TUI 美化
- 非关键性能微优化
- 无测试支撑的大规模重构
- 将 readiness 手工补跑当成常规流程

---

## 8. 交付物要求

实施团队在本窗口结束前，至少应交付以下材料：

1. 一份最新 readiness 状态快照
2. 一份 VPS scheduler-clean 连续运行记录
3. 一份 Alpha/Data Center/Risk Center/TUI 的集中回归记录
4. 一份结构债处理结果说明
5. 一份稳定化总结文档
6. 如条件成熟，补正式 `0.8.0` Git tag

---

## 9. 本文档引用

- [docs/VERSION.md](../VERSION.md)
- [docs/governance/SYSTEM_BASELINE.md](../governance/SYSTEM_BASELINE.md)
- [docs/governance/MODULE_CLASSIFICATION.md](../governance/MODULE_CLASSIFICATION.md)
- [docs/testing/personal-investment-readiness-2026-06-30.md](../testing/personal-investment-readiness-2026-06-30.md)
- [docs/testing/0.8.0-release-regression-report-2026-07-05.md](../testing/0.8.0-release-regression-report-2026-07-05.md)
- [docs/business/risk-center.md](../business/risk-center.md)
- [docs/operations/runbook.md](../operations/runbook.md)

---

## 10. 一句话结论

未来两周的目标不是“继续做更多功能”，而是把 `0.8.0` 真正推到“运行闭环稳定、证据完整、关键链路可回归”的状态。

## 2026-08-15：归档与残余门禁转移

本两周计划已过期，不再作为独立执行主线；它保留为历史排期和验收来源。尚未完成的
生产证据不得因归档而被标记为通过，统一转入当前工作流：`S1-S4`、`S6` 归入
`data-production-reliability`，`S5` 归入 `strategy-research-production`，`S7` 归入
`evidence-hard-gate`，`S8-S10` 归入 `web-to-tui-m5`。正式 tag、readiness 连续窗口、
角色化 TUI UAT、观察期和生产签字仍以各自当前计划为准。
