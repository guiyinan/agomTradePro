# 报告一：EVID global deny 与 ASH-08 人工调仓计划

核查方式：只读代码与治理文件；未请求生产、未运行业务写入。结论限于核查时工作区源码，尚不能替代 ASH-08 实现后的端到端验证。

## 结论

**现有代码没有一个对所有计划生成统一返回 deny 的 EVID 开关；生成、上游决策数据和提交执行分别受约束。** Canonical Portfolio 的计划生成方法直接计算并保存计划，没有调用 Broker 执行闸；提交执行则无条件拒绝。ASH-08 尚未实现，不能据此声称新用户流程已经可用。

因此：EVID-03 延期不必阻止一个有界、可读的人工调仓建议；但若 ASH-08 沿用当前受阻断的决策输入或把展示结果直接当作可执行授权，仍会被挡住。不能只改 UI 标签解除这些门。

## 证据与适用边界

| 核查点 | 实际行为 | 对当前目标的影响 |
| --- | --- | --- |
| `apps/portfolio/application/use_cases.py:26-57` | BuildTransitionPlanUseCase 组装计划后保存，无 Broker Evidence 调用 | 存在可复用的计划生成基础；保存计划不是只读操作，仍须显式授权、幂等和审计 |
| 同文件 `:70-84` | SubmitApprovedPlanUseCase 即使 APPROVED 且未过期，仍抛出 Evidence 未集成错误 | 自动执行不应成为 M1 的退出门 |
| `apps/broker_execution/application/evidence_gate.py:19-36` | create/approve/lease/submitting 全部硬阻断，integrated 固定 false | 维持无自动下单的 Owner 范围 |
| `core/middleware/decision_gate.py:12-24,33-69` | Decision Runtime 对 equity、valuation、regime、chat 等前缀在阻断时返回 503；没有直接列入 `/api/portfolio/transition-plans/` | 计划接口本身没有被这个中间件统一拦截，但其上游数据和 Agent 入口可能被阻断 |
| `apps/research/domain/evidence_contracts.py:525-538,706-716` | DISPLAY_ONLY/ADVISORY 都派生 must_not_use_for_decision=true；有 blocker 时强制 DISPLAY_ONLY | ADVISORY 不是交易资格；不能把已有阻断结果改标成决策可用 |
| `apps/portfolio/interface/api_views.py:26-41,93-134` | 旧生成接口仍接收调用方价格、持仓和目标 | 能返回一个计划不证明输入是真实当前 owner 数据；ASH-08 须完成可信装配 |
| ADR-0007 与 `governance/decision_write_surfaces.json` | 生成/保存/审批等仓位影响入口已纳管 | 新语义必须同步现有契约与冻结清单，不能借新名称新增旁路 |
| `governance/evidence_output_surfaces.json` 的 Portfolio/TransitionPlan 项 | 部分现存输出明确登记为 `not_evidence_integrated_legacy_ungated` | 这是已登记缺口，不是允许绕过 Evidence 的批准；不能用“旧接口能返回”作为 ASH-08 的验收证据 |

## 最小方案：人工决策建议投影（提案，未实施）

1. 复用 Portfolio TransitionPlan，由现有 owner Application 读取一个已授权模拟账户的现金、持仓、T+1 可卖量、目标、价格、规则及来源时间；冻结版本/hash/失效时间。生成动作显式确认，普通 GET 不隐式重算、写库或排任务。
2. 用户首屏固定标记“人工决策建议”“请在券商端自行判断并下单”，显示当前/可卖/目标股数、建议差额、估算费用、现金和不满足的条件。可卖量、单位、来源或时点无法确认时，显示不完整/阻断与原因，不能补成可执行数量。
3. 顶层发布用途 `manual_decision_support`，并保留真实 Evidence permission、各源 blockers、must_not_execute=true、execution_authorized=false。只有满足既有资格的输出才可使用既有 ADVISORY；原 envelope 有 blocker 时仍为 DISPLAY_ONLY，不把 boolean 改成 false。此用途字段只是人类工作流说明，不是新的授权等级。
4. 不产生可交给 Broker 的执行 token/receipt，不调用 submit、lease 或自动下单。人工成交由既有显式导入入口记账，保留真实费用与未知结果；导入不是补签历史决策资格。
5. TUI 只接既有 `/tui/` 任务流程；若旧 Agent/决策 API 因全局门返回 503，应增加有界的人工计划 owner facade/投影契约，而非关闭 Decision Runtime。最终路径必须由契约与用户流程实测决定，本报告不建议直接加入 URL 白名单。

## 接受标准与回滚

后续至少证明：global runtime blocked 时仍可读取合格事实并输出明确受限的人工建议；无数据时不伪造；跨账户拒绝；GET 零业务写入；过期失效；普通/管理员、手机/桌面主任务；生成不会触发 Broker、Celery 自动交易或隐式导入；真实成交导入计数与数据库一致。必须对现有 serializer、API/SDK/MCP 和 TUI 全链路核查标记。

回滚仅停用新增人工建议入口并回退自有代码/配置；保留计划快照、已导入成交、历史 Evidence 与审计。EVID-01/02 的真实 authority 另按决策 A 办理；它们不是给自动交易解闸。
