# 决策工作台实施计划：收敛为“账户级调仓计划 -> 审批执行”，审计移出主流程

## Summary

本次实施分两部分同步完成：

- 先改文档，把工作台主链路明确为：`系统级分析 -> 推荐筛选 -> 账户级调仓计划 -> 审批执行`
- 再按文档落地代码，把当前 Step 6 的 `审计复盘` 从漏斗中移除，改成执行后的独立入口

已锁定的业务决策：

- 主流程仍保留 6 步
- Step 5 改为 `交易计划`
- Step 6 改为 `审批执行`
- 工作台产物是“账户级调仓单”，不是单条 recommendation
- `SELL` 在 v1 语义固定为“减仓/清仓”，不支持做空
- 证伪/止损/复核条件属于交易计划必填项，审批前必须补齐

## 文档先行

先更新这两份现有文档，不新建平行规范：

- `docs/api/decision-workspace-v2.md`
- `docs/development/decision-unified-workflow.md`

文档改动要求：

- 把“工作台闭环”从 `系统推荐 -> 推荐解释 -> 用户动作 -> 执行审批` 改为 `系统推荐 -> 用户采纳 -> 交易计划 -> 审批执行 -> 审计入口`
- 明确 `UnifiedRecommendation` 是推荐层对象，不是最终执行单
- 新增 `PortfolioTransitionPlan` 章节，定义计划级字段、订单级字段、风控/证伪字段
- 明确 `审计复盘` 为执行后的独立模块入口，不再属于工作台必经步骤
- 明确兼容策略：`/api/decision/execute/preview/` 进入 plan-scoped 模式，旧 recommendation-scoped 入参保留 1 个版本作为兼容

## 实施变更

### 1. 漏斗与页面结构

调整工作台壳和 step partial：

- `core/templates/decision/workspace.html`
- `core/views_decision_funnel.py`
- `core/api_views_decision_funnel.py`
- `core/application/decision_context.py`

具体实施：

- stepper 标签改为 `环境评估 / 方向选择 / 板块偏好 / 推优筛选 / 交易计划 / 审批执行`
- 页面副标题去掉“最终审计复盘闭环”
- `funnel_step5_view` 改为渲染新 partial `decision/steps/plan.html`
- `funnel_step6_view` 改为渲染当前 `decision/steps/execute.html`，职责收敛为审批与执行
- 当前 `decision/steps/audit.html` 保留，但不再由工作台 Step 6 加载，只作为执行后的跳转入口承载页
- Step 4 增加 recommendation 选择能力，并提供“生成交易计划”入口
- Step 5 展示 `当前持仓 -> 目标持仓 -> delta 指令`，支持编辑止损/证伪/复核条件
- Step 6 只显示审批请求、风险检查、执行预览、执行结果和“查看审计复盘”链接

### 2. 领域与持久化模型

在 `apps/decision_rhythm/domain/entities.py` 和 `apps/decision_rhythm/infrastructure/models.py` 中新增计划层对象：

- `PortfolioTransitionPlan`
- `TransitionOrder`
- `TransitionPlanStatus`

v1 持久化方案固定为“计划表 + JSON 快照”，不拆 order 子表：

- `PortfolioTransitionPlanModel`
- `current_positions_snapshot`：JSON
- `target_positions_snapshot`：JSON
- `orders`：JSON
- `risk_contract`：JSON
- `summary`：JSON

计划状态固定为：

- `DRAFT`
- `READY_FOR_APPROVAL`
- `APPROVAL_PENDING`
- `APPROVED`
- `REJECTED`
- `EXECUTED`
- `FAILED`
- `CANCELLED`

订单生成规则固定为：

- 只消费当前账户 `user_action=ADOPTED` 且 `status!=CONFLICT` 的 recommendation
- `BUY` recommendation 生成加仓或新开仓目标
- `SELL` recommendation 只生成 `REDUCE` 或 `EXIT`，不允许负仓位
- 无持仓的 `SELL` 直接过滤，并记录原因 `no_position_to_sell`
- 同证券 BUY/SELL 冲突仍留在 conflict 队列，Step 5 不生成计划
- `target_qty` 永远不小于 0

证伪默认填充规则固定为：

- 若 `source_signal_ids` 可解析出上游 signal 的 `invalidation_rule_json`，直接带入 order
- 否则生成 `requires_user_confirmation=true` 的 draft risk item
- 任一非 `HOLD` order 缺少完整 `invalidation_rule` 或 `stop_loss_price` 时，计划不得进入审批

### 3. API 收敛方案

在 `apps/decision_rhythm/interface/api_views.py` 和 `apps/decision_rhythm/interface/urls.py` 增加计划层接口：

- `POST /api/decision/workspace/plans/generate/`
- `GET /api/decision/workspace/plans/<str:plan_id>/`
- `POST /api/decision/workspace/plans/<str:plan_id>/update/`

请求/响应固定要求：

- `generate` 输入：`account_id`、`recommendation_ids` 可选；为空时默认取当前账户所有 `ADOPTED`
- `generate` 输出：完整 `PortfolioTransitionPlan`
- `update` 仅允许改 `orders[*].stop_loss_price`、`orders[*].invalidation_rule`、`orders[*].review_by`、`risk_contract`

执行接口兼容改造：

- `POST /api/decision/execute/preview/` 主入参改为 `plan_id`
- 兼容保留 `recommendation_id` 1 个版本；收到旧入参时，后端先生成单标的临时计划，再走同一 preview 逻辑
- `approve/reject` 继续使用 `approval_request_id`，但 `ExecutionApprovalRequest` 和模型必须新增 `plan_id`
- `ExecutionApprovalRequest` 的审批对象从单 recommendation 升级为整份计划快照

## Test Plan

必须补齐以下测试：

- 文档契约测试：OpenAPI/文档示例中出现 `plans/generate`、`plan_id`、`交易计划`
- 模板回归：工作台 stepper 不再显示 `审计复盘`，Step 5/6 标签和内容正确
- Domain 单测：基于当前持仓生成 `BUY / REDUCE / EXIT / HOLD` delta 指令
- Domain 单测：无持仓 SELL、冲突 recommendation、缺少证伪规则、缺少止损价时的阻断行为
- API 测试：`plans/generate`、`plans/update`、`execute/preview(plan_id)`、旧 `recommendation_id` 兼容路径
- E2E：账户切换 -> 采纳推荐 -> 生成计划 -> 补齐证伪 -> 提交审批 -> 执行 -> 跳转审计入口
- 回归：现有 recommendation 列表、conflicts、approve/reject 主链仍可工作

## Assumptions And Defaults

- v1 不支持做空，`SELL` 仅表示减仓或清仓
- v1 计划层使用 JSON 快照建模，不做细粒度 order ORM 拆表
- `UnifiedRecommendation` 保留，状态语义不再承载“最终执行单”心智
- `audit.html` 和审计 use case 继续保留，但从 funnel 中脱钩
- 文档更新与代码实现在同一轮提交中完成，文档作为单一叙事源
