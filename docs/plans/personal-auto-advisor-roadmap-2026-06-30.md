# 个人自动投顾路线图

- 日期: 2026-06-30
- 状态: Implemented v1
- 范围: 仅个人自用, 不对公众开放, 不收费, 不接券商自动下单
- 定位: 个人自动化投研 + 风控决策助手 + 半自动执行系统

## 0. 当前落地进度

- 2026-06-30: 第一阶段已开始落地到 `decision_rhythm` advisor sheet。
- 已输出 `risk_policy.version`，用于说明命中的个人风险配置版本。
- 已接入 `data_center` 决策数据健康 payload，数据不可用于决策时建议单降级为 `REVIEW`。
- 已为每条 `order_intent` 增加 `risk_gate_status`、`risk_gate`、`data_asof` 和统一 `decision_card`。
- 已在 Terminal 和 Classic Decision Workspace 展示风控闸门与数据 freshness 摘要。
- 已在 advisor sheet 增加组合级裁决和同标的冲突消解：同一 `asset_code` 最多输出一个最终建议，重复同向建议合并来源，方向冲突输出 `recommendation_conflicts` 并降级为 `REVIEW`。
- 已接入 Decision Rhythm execution guard：价格校验、Beta Gate、配额、冷却期和来源信号证伪失败都会阻断可执行订单。
- 已接入行业/细分行业/策略 bucket 暴露检查：新增买入/加仓导致 projected exposure 超过风险配置上限时阻断为 `BLOCKED_EXPOSURE_LIMIT`，减仓/清仓不受该阻断影响。
- 已接入建议执行链接追踪：`order_intent.tracking` 和 `decision_card.tracking` 可展示来源推荐是否已采纳、是否已有手工/模拟成交链接。
- 已接入建议 7/20/60 日表现追踪：按推荐锚点价与 `data_center` 收盘价历史输出 raw return 和 directional return。
- 已接入表现型错误归因初版：当成熟窗口 directional return 为负时输出 `MODEL_MISJUDGMENT`、`EXECUTION_TOO_EARLY` 等机器可读归因。
- 已接入半自动确认流：`confirmation` 和 `execution_plan` 标记二次确认原因，真实账户固定只生成计划、确认和记录，不自动下单。
- 已接入首页自动投顾主控台：`/api/dashboard/auto-advisor-console/` 聚合今日是否可交易、宏观象限、组合风险、今日建议、必须处理的预警、数据 freshness 和执行确认状态，并已嵌入 Dashboard 首页。
- 已接入自然语言查询首版：`/api/dashboard/auto-advisor-query/` 基于 advisor sheet 确定性回答最大风险、减仓原因、证伪持仓、下跌冲击损失和未执行建议表现，不依赖 LLM。
- 已接入深层归因证据：`tracking.performance.error_attribution.deep_attribution` 输出 Regime 上下文、Policy 上下文和人工 override 结果分类。
- 已接入个人周报首版：`/api/dashboard/auto-advisor-weekly-report/` 输出组合快照、最大风险暴露、系统建议与实际操作差异、未执行建议表现、已证伪建议和下周观察清单。
- 已接入投资日记持久化：weekly report 返回 `investment_diary`，Celery 周报任务会持久化 weekly report、投资日记快照、dashboard 通知和 audit operation log。
- 已接入事后 Regime/Policy 标签对比：deep attribution 会比较推荐时上下文和成熟表现窗口对应日期的 Regime/Policy，输出 `REGIME_JUDGMENT_ERROR`、`POLICY_MISJUDGMENT` 等分类。
- 已接入个人周报每周自动生成：Celery 任务 `dashboard.generate_auto_advisor_weekly_reports` 默认由 `setup_auto_advisor_weekly_report` 创建每周五 17:30 beat 记录，并纳入 `init_scheduler_defaults`。
- 已接入 CLI 自然语言查询：Terminal 命令 `advisor_query account_id=<id> question=<问题>` 复用 Dashboard auto-advisor query API，输出紧凑答案和关键证据。

## 1. 目标定位

本路线图不按公开自动投顾产品设计, 不覆盖公众客户适当性、营销披露、投顾收费和对外服务合规流程。

系统目标是帮助个人投资者每天回答:

1. 当前组合最大的风险是什么。
2. 今天是否应该行动。
3. 如果行动, 应该买入、减仓、清仓、等待还是复核。
4. 每个建议依赖哪些数据、规则和证伪条件。
5. 如果建议错了, 预期损失和退出条件是什么。

第一原则:

- 少犯大错优先于追求最高收益。
- 组合级风险优先于单票信号。
- 数据新鲜度优先于复杂模型输出。
- 真实交易必须保留人工确认。
- 每条建议必须可解释、可追踪、可复盘。

## 2. 优先级总览

| 优先级 | 主题 | 目标 | 建议模块 |
| --- | --- | --- | --- |
| P0 | 安全护栏 | 防止脏数据、过度集中、超额交易和失控执行 | `risk_center`, `account`, `data_center`, `decision_rhythm` |
| P1 | 建议质量 | 让建议从局部信号升级为组合级决策 | `decision_rhythm`, `alpha`, `rotation`, `policy`, `regime` |
| P2 | 半自动执行 | 生成交易计划, 但真实执行前必须确认 | `simulated_trading`, `account`, `terminal`, `dashboard` |
| P3 | 复盘闭环 | 跟踪建议表现, 形成个人投资反馈循环 | `audit`, `share`, `task_monitor` |
| P4 | 体验效率 | 首页聚合和自然语言查询 | `dashboard`, `terminal`, `agent_runtime` |

## 3. P0: 安全护栏

### 3.1 个人风险配置中心

目标: 建立统一的个人投资约束, 作为所有建议和交易计划的硬前置条件。

建议配置项:

- 单资产最大仓位。
- 单行业最大仓位。
- 单策略最大仓位。
- 最小现金比例。
- 最大账户回撤阈值。
- 单日最大调仓比例。
- 单周最大调仓比例。
- 禁买清单。
- 观察清单。
- 强制持有清单。
- 高波动资产最大暴露。

落地建议:

- 优先复用 `risk_center` 的前置风控能力。
- 如果现有配置分散在 `account`、`risk_center`、`decision_rhythm`, 需要增加一个只读汇总 query service。
- 所有 advisor sheet 和 decision workspace 输出必须携带命中的风险配置版本。

验收标准:

- 任意建议都能说明使用了哪一版个人风险配置。
- 超过硬约束的建议必须返回 `BLOCKED` 或 `REVIEW`, 不能返回直接行动。
- 配置缺失时, 系统默认保守, 不生成强买入建议。

### 3.2 建议前置风控闸门

目标: 所有买入、卖出、减仓、调仓建议在展示前必须经过统一检查。

检查项:

- 是否超过单资产仓位上限。
- 是否超过行业或主题暴露上限。
- 是否低于最低现金比例。
- 是否和当前 Regime/Policy 明显冲突。
- 是否和已有持仓高度相关。
- 是否触发冷却期。
- 是否近期刚被证伪。
- 是否缺关键价格、估值、宏观或持仓数据。

落地建议:

- 统一入口优先放在 `decision_rhythm` 的 advisor sheet 生成链路。
- 风控实现优先调用 `risk_center.application.trade_guard` 或对应 query/use case。
- 风控结果必须进入建议卡片和审计日志。

验收标准:

- 每条建议有 `risk_gate_status`。
- 每个阻断项有机器可读 code 和人类可读说明。
- 风控失败不会生成可执行订单意图。

### 3.3 数据新鲜度与缺失告警

目标: 避免旧数据或缺失数据产生看似正常的建议。

核心数据:

- 最新价格。
- 组合持仓。
- Alpha 缓存。
- 宏观指标。
- Regime 状态。
- Policy 状态。
- 估值数据。
- 行业/轮动数据。

落地建议:

- 在 `data_center` 增加统一数据健康 payload。
- 在 dashboard 首页显示数据新鲜度。
- advisor sheet 生成前读取数据健康状态。

验收标准:

- 数据过期时, 建议降级为 `WAIT` 或 `REVIEW`。
- 每条建议展示关键数据的 `asof_date`。
- 价格缺失不得计算虚假数量或金额。

## 4. P1: 建议质量

### 4.1 统一决策卡片

目标: 所有建议用统一结构输出, 方便人工判断和后续复盘。

建议字段:

- `action`: `BUY`, `ADD`, `REDUCE`, `EXIT`, `HOLD`, `WAIT`, `REVIEW`
- `confidence`
- `current_weight`
- `target_weight`
- `delta_weight`
- `estimated_amount`
- `primary_reasons`
- `counter_reasons`
- `invalidation_logic`
- `valid_until`
- `data_asof`
- `risk_notes`
- `blocking_status`
- `expected_loss_if_wrong`

验收标准:

- Dashboard、Terminal、API 输出字段一致。
- 每条建议至少有一个理由和一个证伪条件。
- 没有证伪条件的建议不得进入强执行状态。

### 4.2 组合级裁决器

目标: 避免 alpha、rotation、policy、regime、risk_center 各自给出局部正确但组合冲突的建议。

裁决顺序建议:

1. 数据健康。
2. 硬风控。
3. 当前组合风险。
4. Regime/Policy 方向。
5. 持仓退出/减仓。
6. 新增买入。
7. 执行节奏。

验收标准:

- 冲突建议必须被归并为一个最终动作。
- 最终动作能追溯到被采纳和被否决的信号。
- 组合超配修复优先于新增买入。

### 4.3 建议去重与冲突消解

目标: 避免同一资产在不同模块中重复出现, 或同一资产同时出现买入和卖出建议。

验收标准:

- 同一 `asset_code` 每日最多一个最终建议。
- 同一建议可附带多个来源信号。
- 冲突必须输出 conflict reason。

## 5. P2: 半自动执行

### 5.1 只生成交易计划

原则: 真实账户默认只生成交易计划, 不自动下单。

交易计划包括:

- 标的。
- 动作。
- 建议数量。
- 建议金额。
- 价格区间。
- 优先级。
- 执行前检查项。
- 失效时间。

### 5.2 二次确认规则

以下情况必须人工确认:

- 单笔金额超过阈值。
- 卖出大额盈利或亏损持仓。
- 买入高波动资产。
- 连续加仓同一资产。
- 当天已有多次交易。
- 任一数据健康项为 warning。

### 5.3 真实账户与模拟账户隔离

原则:

- 模拟账户可自动跑计划和回放。
- 真实账户只允许建议、确认和记录。
- 真实交易执行状态必须和建议状态分离。

## 6. P3: 复盘闭环

### 6.1 建议结果追踪

每条建议至少追踪:

- 建议时价格。
- 执行价格。
- 7 日表现。
- 20 日表现。
- 60 日表现。
- 是否触发证伪。
- 是否人工 override。
- override 后结果。

### 6.2 错误归因

错误归因分类:

- 数据错误。
- 模型误判。
- Regime 判断错误。
- Policy 判断错误。
- 执行过早。
- 执行过晚。
- 仓位过重。
- 人工 override 错误。

首版已在 advisor sheet tracking 中输出 `deep_attribution`:

- `regime`: 推荐时 Regime、置信度、事后 Regime 标签和上下文缺失/偏弱/判断错误分类。
- `policy`: 推荐时 Policy 档位、事后 Policy 标签和上下文缺失/误判分类。
- `manual_override`: 根据 `user_action` 与成熟表现窗口判断未采纳建议是否构成人工 override 错误或保护本金。

### 6.3 个人投资周报

每周自动输出:

- 本周组合变化。
- 最大风险暴露。
- 系统建议与实际操作差异。
- 未执行建议的后续表现。
- 已证伪建议。
- 下周重点观察。

首版已落地为只读 weekly report API、投资日记区块和每周自动生成任务，复用 advisor sheet。Celery 周报任务会持久化 weekly report payload、`investment_diary`、dashboard 通知和 audit operation log；实时 API 调用仍只生成 payload。`portfolio_change` 优先读取模拟账户日净值历史输出 `HISTORICAL` 周变化；历史不足时降级为当前快照并标记 `CURRENT_SNAPSHOT_ONLY`。`investment_diary` 输出周复盘 entry、反思标签、经验教训、人工备注提示和原始证据。默认调度任务为 `dashboard-auto-advisor-weekly-report`，执行 `dashboard.generate_auto_advisor_weekly_reports`，每周五 17:30 生成全部活跃账户周报；也可用 `setup_auto_advisor_weekly_report --user-id <id> --account-ids <ids>` 缩小范围。

## 7. P4: 体验效率

### 7.1 主控台

首页优先展示:

- 今日是否可交易。
- 当前宏观象限。
- 当前组合风险。
- 今日建议。
- 必须处理的预警。
- 数据是否新鲜。

### 7.2 自然语言查询

优先支持的问题:

- 我现在最大风险是什么。
- 今天为什么建议减仓。
- 哪些持仓已经证伪。
- 如果明天跌 3%, 组合损失多少。
- 哪些建议我上次没执行, 结果如何。

首版已落地为确定性 query service 和 Dashboard API，不调用 LLM，直接复用 advisor sheet 的 `risk_summary`、`decision_cards`、`order_intents`、`tracking`、`data_health` 和账户市值字段。

## 8. 推荐实施顺序

第一阶段:

1. 个人风险配置中心。
2. 数据新鲜度/缺失告警。
3. 统一决策卡片。

第二阶段:

4. 建议前置风控闸门。
5. 组合级建议裁决器。
6. 建议去重与冲突消解。

第三阶段:

7. 建议追踪与复盘。
8. 半自动交易确认流。
9. 主控台简化。

第四阶段:

10. 投资日记/周报。（首版已完成，Celery 周报任务持久化日记快照、通知和审计记录）
11. 自然语言查询。（首版已完成，Dashboard API 和 Terminal `advisor_query` 已接入；后续可接入 agent_runtime 做多轮追问）

## 9. 非目标

本阶段明确不做:

- 面向公众开放。
- 投顾收费。
- 券商自动下单。
- 代客理财。
- 多客户适当性体系。
- 营销话术和收益承诺。

## 10. 与现有文档关系

- `auto-advisor-prd-2026-06-25.md`: 已实现的账户级建议单 PRD。
- `auto-advisor-implementation-2026-06-25.md`: 已实现链路的技术说明。
- 本文档: 面向个人自用场景的后续增强优先级。
