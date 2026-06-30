# 账户级自动投顾 PRD

- 日期: 2026-06-25
- 状态: Implemented v1
- 范围: 持仓驱动的只读建议单，不接券商，不自动改持仓
- 后续增强: [personal-auto-advisor-roadmap-2026-06-30.md](personal-auto-advisor-roadmap-2026-06-30.md)

## 目标

自动投顾以 `account_id` 为唯一入口，为一个账户生成当天建议单。用户需要看到该账户的业务信息、当前持仓、风险摘要、建议订单数量以及每单怎么下；用户不需要理解持仓底层来自模拟盘表还是手工组合表。

## 用户问题

1. 这个账户今天是否行动: `ACT / REVIEW / WAIT / BLOCKED`
2. 当前账户有多少持仓、现金和风险暴露
3. 今天建议下多少单，哪些买入、加仓、减仓、清仓
4. 每单的数量、金额、价格区间、理由、风险提示和失效条件
5. 哪些阻断项导致不能执行，例如价格缺失、资金不足、风控冲突

## 范围

包含:

- `GET /api/decision/advisor/sheet/?account_id=<id>`
- Classic UI `/decision/workspace/` 顶部“今日自动投顾”区域
- TUI `command-center.auto-advisor` 屏幕与 `advisor.today_sheet` action
- Terminal 命令 `advisor_today`
- 只读 `order_intents`

不包含:

- 券商真实下单
- 自动修改账户持仓
- 跨账户合并现金、风险预算或持仓优化

## 决策原则

- 先读取账户现有持仓，再生成建议订单。
- 有持仓账户优先处理超配、亏损、退出/减仓推荐，再考虑新增买入。
- 无持仓账户不是错误，返回 `baseline=empty_positions` 和建仓建议。
- 推荐里的 `suggested_quantity=0` 不能直接展示为订单，必须用账户资金、目标权重和现价重新计算。
- 缺少有效价格时订单进入阻断状态，不计算虚假数量或金额。

## 建议订单字段

固定返回:

`order_intent_id`, `account_id`, `asset_code`, `asset_name`, `side`, `current_quantity`, `target_quantity`, `delta_quantity`, `estimated_price`, `estimated_amount`, `current_weight`, `target_weight`, `priority`, `price_band`, `reason`, `risk_notes`, `invalidation_rule`, `execution_hint`, `source_recommendation_id`, `blocking_status`.
