# 账户级自动投顾实施文档

- 日期: 2026-06-25
- 状态: Implemented v1

## 后端链路

入口: `GenerateAdvisorDecisionSheetUseCase(account_id, user)`

流程:

1. `AccountHoldingSnapshotProvider` 校验账户归属。
2. 读取 simulated position snapshots。
3. 若账户绑定手工组合，同步读取 portfolio positions。
4. 按标的代码合并为统一持仓快照。
5. 读取 Decision Workspace 的 `UnifiedRecommendationDTO`。
6. 先为现有持仓生成 `EXIT / REDUCE / ADD / HOLD`。
7. 再用剩余现金和推荐生成新增 `BUY`。
8. 输出配置偏离、订单意图、阻断项、风险摘要和下一步动作。

## 第一版规则

- 浮亏超过 10%: 生成 `EXIT` 复核意图。
- 单一持仓权重超过 25%: 生成 `REDUCE`，目标权重 20%。
- 推荐 `SELL/EXIT`: 生成 `EXIT`。
- 推荐 `REDUCE`: 生成 `REDUCE`。
- 已持有且有 `BUY` 推荐: 转为 `ADD`。
- 空仓账户: 按推荐目标权重生成 starter `BUY`。
- 缺价格: `BLOCKED_PRICE_MISSING`。
- 缺现金: `BLOCKED_NO_CASH`。

## UI 集成

Classic UI:

- `/decision/workspace/` 顶部新增“今日自动投顾”面板。
- 复用页面账户 selector。
- 切换账户时同步刷新账户快照、推荐列表和 advisor sheet。
- 展示结论、订单数量、前 6 条订单、价格区间、理由、风险提示和执行提示。

TUI:

- Runtime metadata 注入 `command-center.auto-advisor`。
- Action `advisor.today_sheet` 读取 `/api/decision/advisor/sheet/`。
- 必填字段 `account_id`。

Terminal:

- migration seed `advisor_today`。
- 默认输出账户摘要、结论、订单计数、前 5 条订单、阻断项和下一步命令。
- `verbose=true` 时保留完整 JSON 输出。

## 测试矩阵

- 有持仓账户: 减仓、清仓、新增买入，且超配/退出优先。
- 空仓账户: 返回 `empty_positions` 和建仓订单。
- `suggested_quantity=0`: 重新计算数量。
- 价格缺失: 阻断且不生成虚假数量。
- API: `account_id` 必填、权限错误映射、返回字段契约。
- UI/TUI: 模板面板和 metadata action 存在。
