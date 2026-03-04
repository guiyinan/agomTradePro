# 外包落实计划：估值定价引擎与执行审批闭环（2026-03-02）

## 1. 背景与目标

当前系统已具备“环境判断 -> 生成建议 -> 提交决策 -> 执行”的主链路，但在“低买高卖”核心盈利逻辑上仍存在关键缺口：

1. 建议侧只有“买/卖”方向，缺少可执行的价格建议与数量建议。
2. 执行侧虽然已有确认入口，但审批信息不完整，无法形成标准交易审批单。
3. 策略建议、执行申请、审批记录、审计复盘之间尚未形成统一的数据主键与闭环可追踪关系。

本计划目标：

1. 建立可落地的“估值定价 + 仓位建议 + 风控约束”决策产物。
2. 建立“提交决策 -> 执行审批 -> 执行结果 -> 事后审计”的端到端闭环。
3. 统一系统内价格/仓位/regime/信号引用口径，避免跨页面和跨模块不一致。
4. 形成可验收、可回归、可灰度上线的外包交付包。

## 2. 范围与非范围

### 2.1 范围（必须交付）

1. 估值定价引擎（A股先行）：
   1. 生成 fair value、buy zone、sell zone、stop-loss、take-profit。
   2. 输出 entry price range、target price range、size suggestion。
2. 决策建议结构升级：
   1. 从仅“方向建议”升级为“方向 + 价格区间 + 数量 + 风险预算 + 理由”。
3. 执行审批工作流升级：
   1. 点击“去执行”弹出审批模态窗口（详情 + 评论 + 批准/拒绝）。
   2. 审批通过后生成标准执行单并落库。
4. 数据模型与链路统一：
   1. 统一 security_code 归并与资产级聚合规则。
   2. 统一 regime 来源链路（全系统同一计算口径）。
5. 文档、测试、回归、上线脚本同步交付。

### 2.2 非范围（本期不做）

1. 高频交易执行引擎。
2. 盘口微观结构预测。
3. 多市场（美股/港股）全面适配（仅保留扩展接口）。

## 3. 业务规则（强约束）

### 3.1 交易建议输出规范

每条建议必须包含：

1. `security_code`
2. `side`（BUY/SELL/HOLD）
3. `confidence`（0-1）
4. `valuation_method`（如 DCF/PE-band/EV-EBITDA/Dividend）
5. `fair_value`
6. `entry_price_low`、`entry_price_high`
7. `target_price_low`、`target_price_high`
8. `stop_loss_price`
9. `position_size_pct`（组合权重建议）
10. `max_capital`（最大可用资金）
11. `reason_codes`（可枚举）
12. `human_readable_rationale`

### 3.2 买卖约束

1. BUY 只能在 `market_price <= entry_price_high` 时可批准。
2. SELL 只能在 `market_price >= target_price_low` 或触发风控条件时可批准。
3. 任何审批前必须通过 quota/cooldown/风控闸门。
4. 同一账户同一证券同一周期只允许一个 `PENDING` 执行单。
5. 所有金额、数量必须可追溯至建议快照版本。

### 3.3 账户维度归并规则

1. 工作台“待决策/可执行”按“账户 + 证券代码 + side”聚合展示，不允许重复散列项。
2. 多策略命中同一证券时，按优先级规则合并为一条主建议并保留来源明细。
3. 执行单永远对应聚合后主建议，不直接对应原始碎片信号。

## 4. 技术改造任务分解

### 4.1 后端 Domain/Application

1. 新增 `ValuationSnapshot` 聚合根：
   1. 保存 fair value、区间、估值方法、输入参数、版本号、生成时间。
2. 扩展 `InvestmentRecommendation`：
   1. 新增价格区间、止盈止损、仓位建议、估值引用字段。
3. 新增 `ExecutionApprovalRequest`：
   1. 状态流转：`DRAFT -> PENDING -> APPROVED/REJECTED -> EXECUTED/FAILED`。
4. 新增统一服务 `RecommendationConsolidationService`：
   1. 按账户+证券归并建议。
   2. 处理重复证券根因，不依赖前端去重。
5. 统一 `RegimeResolver`：
   1. 全模块仅允许调用统一 resolver。
   2. 旧版 regime 计算链路注释并保留迁移说明。

### 4.2 API 层

新增/改造接口（REST）：

1. `POST /api/valuation/recalculate/`
2. `GET /api/valuation/snapshot/{id}/`
3. `GET /api/decision/workspace/aggregated/`
4. `POST /api/decision/execute/preview/`
5. `POST /api/decision/execute/approve/`
6. `POST /api/decision/execute/reject/`
7. `GET /api/decision/execute/{request_id}/`

返回结构必须包含：

1. `request_id`、`recommendation_id`、`valuation_snapshot_id`
2. `price_range`、`suggested_qty`、`risk_checks`
3. `regime_source`（链路追踪字段）

### 4.3 前端（决策工作台/首页）

1. “提交决策”按钮：
   1. 提交后进入确定态，支持状态刷新，不出现长期 loading。
2. “去执行”按钮：
   1. 打开审批模态窗口，不直接确认即执行。
3. 审批模态窗口必须展示：
   1. 证券、方向、建议价格区间、建议数量、资金占用、止损止盈、闸门结果、评论框。
4. 支持操作：
   1. `批准执行`
   2. `拒绝并备注`
   3. `取消`
5. 工作台列表改为聚合展示，默认按风险优先级排序。

### 4.4 数据迁移

1. 新增字段 migration + backfill 脚本。
2. 历史 recommendation 生成 valuation 占位快照（标记 `legacy=true`）。
3. 历史重复执行单做归并映射表，保证旧链接可跳转。

## 5. 交付物清单（外包必须提交）

1. 代码：
   1. 后端改造 PR（Domain/Application/API）。
   2. 前端改造 PR（workspace + 首页入口 + 模态）。
2. 数据：
   1. migration 脚本。
   2. backfill 脚本。
3. 测试：
   1. 单元测试。
   2. 集成测试。
   3. E2E 冒烟测试（含审批模态流程）。
4. 文档：
   1. API 文档更新。
   2. 模块设计文档更新。
   3. 运维回滚说明。
5. 验收证据：
   1. 测试报告（通过率）。
   2. 关键页面截图/录屏。
   3. 回归清单打勾版。

## 6. 验收标准（必须全部通过）

### 6.1 功能验收

1. 任一 BUY/SELL 建议均可看到价格区间与数量建议。
2. 点击“去执行”必须进入模态审批，不允许直接执行。
3. 审批动作可记录评论并持久化查询。
4. 同账户同证券重复建议被后端归并为单条。
5. 决策工作台 regime 与 regime 页面完全一致（同一时间点）。

### 6.2 数据一致性验收

1. recommendation -> valuation_snapshot -> execution_request 全链路可追踪。
2. 历史数据迁移后不出现空价格区间导致的 UI 崩溃。
3. quota/alerts 历史字段告警降为 0（或纳入白名单并有说明）。

### 6.3 质量验收

1. 新增代码单测覆盖率 >= 80%。
2. 关键 API P95 延迟不高于改造前 +20%。
3. 无 P0/P1 缺陷遗留。

## 7. 计划排期（建议）

1. 第 1 周：
   1. 需求冻结 + 数据模型设计 + API 合同评审。
2. 第 2 周：
   1. 后端估值快照与建议结构改造。
3. 第 3 周：
   1. 工作台聚合与执行审批模态联调。
4. 第 4 周：
   1. 历史数据迁移 + 全量回归 + UAT + 上线准备。

## 8. 风险与控制

1. 风险：历史脏数据导致审批失败。
   1. 控制：迁移前执行数据体检脚本，输出问题清单并先修复。
2. 风险：前后端字段不同步导致 UI 异常。
   1. 控制：OpenAPI 合同锁版本，CI 做 schema diff。
3. 风险：建议合并逻辑影响策略收益解释性。
   1. 控制：保留 source_recommendation_ids 明细并可回放。

## 9. 外包执行要求

1. 禁止先做 UI 假数据联调后补后端，必须先锁定 API 契约。
2. 每个里程碑提交可运行分支与测试证据，不接受仅代码片段。
3. 每周固定一次验收会，未过项进入下周阻断清单。
4. 未经批准不得改动核心风控阈值与审批状态机。

## 10. 完成定义（DoD）

满足以下全部条件即视为完成：

1. 主流程“建议 -> 审批 -> 执行 -> 审计”端到端可用。
2. 建议包含价格建议与仓位建议，并被执行模块消费。
3. 工作台与 regime 页面口径一致。
4. 文档、测试、回滚方案齐备。
5. 验收报告签字通过。

