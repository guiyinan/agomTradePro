# 研究可信度与决策复算 M0 责任及迁移盘点

## 责任矩阵

| 证据/动作 | Canonical owner | Canonical 写入口 | 兼容状态 |
|---|---|---|---|
| 双时间事实与数据清单 | `data_center` | `BuildPITManifestUseCase` | 原事实表保留；可信读取仅走 manifest-bound view |
| 回测执行结果 | `backtest` | `RunBacktestUseCase` | 旧结果标记 `legacy_unverified`；探索运行不得晋级 |
| 决策输入包 | `decision_rhythm` | `BuildDecisionInputSnapshotUseCase` | 状态表继续由各模块拥有，决策只引用冻结包 |
| 状态变更事件 | `events` | event append service | 扩展聚合版本索引，不强制一次性全面事件溯源 |
| 目标组合 | `strategy` | `BuildTargetPortfolioUseCase` | strategy 不生成 canonical 可执行计划 |
| 差额、约束、订单草案 | `portfolio` | transition-plan facade/API | 原表不搬迁，Django state owner 转交 portfolio |
| 组合规划阈值 | `portfolio` | 唯一激活的 `PortfolioPlanningPolicyModel` 版本 | API 只读激活版本，客户端不得提交覆盖值 |
| 模拟成交 | `simulated_trading` | approved-plan handoff | `RebalanceProposal` 在切换期仍为兼容执行投影 |
| 实验与晋级结论 | `research` | experiment/trial/promotion APIs | 必须绑定真实 PIT manifest 与 completed backtest |
| 预测逐次证伪 | `signal` | forecast ledger use cases | 旧 signal 继续存在但视为 `legacy_unscored` |
| 预测聚合评分 | `audit` | forecast scoreboard query | 样本不足只展示数量，不参与排名 |
| Prompt 版本和评测 | `prompt` | evaluation/promotion APIs | feature flag 开启后禁止绕过评测激活 |
| Agent 执行证据 | `agent_runtime` | execution repository | 记录 prompt/model/schema/eval/snapshot/cost |

## 表与 API 迁移映射

| 原对象 | 目标 | 数据迁移策略 |
|---|---|---|
| `decision_portfolio_transition_plan` | `portfolio.PortfolioTransitionPlanModel` | `SeparateDatabaseAndState`，复用原表并 additive 增加证据字段 |
| `order_intent` | `portfolio.OrderIntentModel` | `SeparateDatabaseAndState`，strategy 保留兼容 re-export |
| `simulated_trading_rebalance_proposal` | execution projection | 本版本不搬历史数据；canonical planner flag 默认关闭 |
| backtest 既有记录 | `trust_status=legacy_unverified` | 不伪造 manifest、commit 或 trial 证据 |
| 既有 signal | `legacy_unscored` | 不反向推造概率、基准和预测期限 |
| 既有 prompt | 兼容模板记录 | 新版本进入 eval 状态机；active 内容不得原地改写 |

新增 canonical API：`/api/data-center/pit-manifests/`、`/api/decision-rhythm/input-snapshots/`、`/api/portfolio/transition-plans/`、`/api/research/experiments/`、`/api/research/trials/`、`/api/signal/forecast-ledger/`、`/api/audit/forecast-scoreboard/`、`/api/prompts/evaluations/` 与 Prompt 版本激活入口。

## 切换和回滚

五个 feature flag 默认关闭。先写证据并影子比较，再逐项启用门禁。所有 schema 变更为 additive 或 state-only；回滚时关闭 flag 并回退应用代码即可，PIT、快照、试验、评测和事件证据不得删除或覆盖。
