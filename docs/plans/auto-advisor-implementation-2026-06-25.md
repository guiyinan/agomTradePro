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
6. 按 `asset_code` 做组合级裁决，同标的重复建议合并来源，同标的方向冲突记录 `recommendation_conflicts`。
7. 先为现有持仓生成 `EXIT / REDUCE / ADD / HOLD`。
8. 再用剩余现金和推荐生成新增 `BUY`。
9. 读取 `risk_center` 有效个人风险配置并生成稳定 `risk_policy.version`。
10. 读取 `data_center` 决策数据健康 payload。
11. 对每条订单意图执行 Decision Rhythm execution guard，检查价格、Beta Gate、配额、冷却期和来源信号证伪状态。
12. 对每条订单意图执行 risk_center 前置风控闸门，写入 `risk_gate_status`、`risk_gate`。
13. 读取 `data_center` 资产行业/细分行业元数据，结合推荐策略 bucket 计算当前和拟执行后的组合暴露。
14. 对新增买入/加仓执行行业、细分行业和策略暴露上限检查，超限写入 `risk_gate.exposure_guard` 并阻断为 `BLOCKED_EXPOSURE_LIMIT`。
15. 读取已有 recommendation-to-execution links，按来源推荐生成 `tracking` 复盘入口。
16. 读取 `data_center` 收盘价历史，按推荐锚点价计算 7/20/60 日 raw return 和 directional return。
17. 按已成熟表现窗口生成表现型错误归因初版，例如 `MODEL_MISJUDGMENT`、`EXECUTION_TOO_EARLY`。
18. 按半自动执行规则生成 `confirmation` 和只读 `execution_plan`，真实账户固定 `broker_execution_enabled=false`。
19. Dashboard 自动投顾主控台 API 复用 advisor sheet，输出今日是否可交易、宏观象限、组合风险、今日建议、必须处理的预警、数据 freshness 和执行确认状态。
20. Dashboard 自然语言查询 API 复用 advisor sheet，确定性回答最大风险、减仓原因、证伪持仓、下跌冲击损失和未执行建议表现。
21. `tracking.performance.error_attribution.deep_attribution` 输出 Regime、Policy 和人工 override 维度的深层归因证据，并比较推荐时上下文与成熟表现窗口对应日期的事后 Regime/Policy 标签。
22. Dashboard 个人周报 API 复用 advisor sheet，输出组合快照、最大风险暴露、系统建议与实际操作差异、未执行建议表现、已证伪建议和下周观察清单。
23. 输出配置偏离、订单意图、统一决策卡片、阻断项、暴露摘要、追踪状态、执行计划、风险摘要和下一步动作。

## 第一版规则

- 浮亏超过 10%: 生成 `EXIT` 复核意图。
- 单一持仓权重超过 25%: 生成 `REDUCE`，目标权重 20%。
- 推荐 `SELL/EXIT`: 生成 `EXIT`。
- 推荐 `REDUCE`: 生成 `REDUCE`。
- 已持有且有 `BUY` 推荐: 转为 `ADD`。
- 空仓账户: 按推荐目标权重生成 starter `BUY`。
- 缺价格: `BLOCKED_PRICE_MISSING`。
- 缺价格的订单不派生目标数量、差额数量或估算金额，避免展示虚假订单。
- 缺现金: `BLOCKED_NO_CASH`。
- 风控失败: `BLOCKED_RISK_GATE`。
- 行业/策略暴露超限: `BLOCKED_EXPOSURE_LIMIT`。
- 风险配置不可用时，新增买入/加仓默认保守阻断为 `BLOCKED_RISK_POLICY_UNAVAILABLE`。
- 执行前检查失败: `BLOCKED_EXECUTION_GUARD`，包括 Beta Gate 未通过、配额不足、冷却期未结束、来源信号已证伪。
- 数据健康不可用于决策时，建议单降级为 `REVIEW`，不返回强行动结论。
- 同一 `asset_code` 多条推荐会归并为一个最终订单意图；方向冲突时建议单降级为 `REVIEW` 并输出冲突原因。

## 路线图第一阶段增强

- 建议单顶层返回 `risk_policy`，包含命中的个人风险配置版本。
- 建议单顶层返回 `data_health`，复用 data_center 决策数据 readiness payload。
- 每条 `order_intent` 返回 `risk_gate_status`、`risk_gate`、`data_asof` 和 `decision_card`。
- `decision_cards` 作为 Dashboard、Terminal、API 共用的统一建议卡片数组。
- 每条 `order_intent` 和 `decision_card` 返回 `tracking`，展示来源推荐的用户动作、执行链接、是否已执行、7/20/60 日表现和表现型错误归因。

## 路线图第二阶段增强

- Advisor sheet 内置组合级裁决顺序：数据健康、硬风控、现有持仓退出/减仓、新增买入。
- 同一标的每日最多输出一个最终 `order_intent`。
- 重复同向建议合并 `source_recommendation_ids`、`source_signal_ids`、`source_candidate_ids`。
- 方向冲突建议输出 `recommendation_conflicts` 和每单 `conflict_resolution`，并降级为 `REVIEW`。
- `risk_gate.execution_guard` 记录价格、Beta Gate、配额、冷却期和 signal invalidation 检查。
- `risk_gate.exposure_guard` 记录行业、细分行业和策略 bucket 暴露检查；建议单顶层返回 `exposure_summary`。
- `tracking` 复用已有 execution link，记录建议是否已被采纳、是否已有手工/模拟执行记录，并按 7/20/60 日窗口追踪推荐后表现。
- `tracking.performance.error_attribution` 基于已成熟表现窗口输出初版错误归因；深层 Regime/Policy/人工 override 归因仍需后续审计证据补齐。

## 路线图第三阶段增强

- `confirmation` 记录二次确认要求，覆盖单笔金额阈值、亏损/大额卖出、连续加仓、当日多单、数据健康 warning、高波动资产和真实账户隔离。
- `execution_plan` 只生成交易计划，不触发券商真实下单；真实账户固定为 `real_confirm_only`。
- Terminal `advisor_today` 输出执行计划确认状态和每单确认状态。
- `/api/dashboard/auto-advisor-console/` 返回首页主控台摘要，聚合今日结论、宏观象限、组合风险、今日建议、数据 freshness、必须处理的预警和执行确认状态。
- Dashboard 首页已嵌入“今日自动投顾主控台”面板，支持账户切换后异步刷新主控台摘要。
- `/api/dashboard/auto-advisor-query/` 返回个人自动投顾问答结果，首版使用 deterministic intent matching，不依赖 LLM。
- `/api/dashboard/auto-advisor-weekly-report/` 返回个人周报首版，组合变化区块优先读取模拟账户日净值历史输出 `HISTORICAL` 周变化；历史不足时降级为当前快照并标记 `CURRENT_SNAPSHOT_ONLY`。
- Celery 任务 `dashboard.generate_auto_advisor_weekly_reports` 每周生成个人自动投顾周报；默认 beat 记录由 `setup_auto_advisor_weekly_report` 创建，`init_scheduler_defaults` 会统一初始化。

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
