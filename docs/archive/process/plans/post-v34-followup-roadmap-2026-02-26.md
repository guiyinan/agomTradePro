# AgomTradePro V3.4 后续开发与完善路线图

> 版本: v1.0  
> 日期: 2026-02-26  
> 目标周期: 12 周

---

## 1. 背景与目标

当前系统已具备主流程能力，但仍存在影响“闭环可信度”的缺口，主要体现在：

1. 部分主链 API 仍为占位实现（501/TODO）。
2. 执行层存在“可配置但未实际执行”的断点。
3. 行情、绩效、审计存在占位数据或缺失字段。
4. 事件接口与生产门禁未完全收敛。

本路线图目标是将系统从“可演示”推进到“可持续运行、可审计、可发布”。

---

## 2. 范围与原则

### 2.1 范围

1. 资产分析统一 API 完整化。
2. 策略执行闭环打通。
3. 行情/绩效/审计可信度修复。
4. 事件 API 去占位与回测指标补齐。
5. RTM 与 CI 门禁闭环。

### 2.2 原则

1. 先修可信度，再做增强能力。
2. 主链路禁止 501 占位接口。
3. 所有功能补齐必须配套测试与验收口径。
4. 保持“决策辅助 + 人工确认执行”边界，不引入自动实盘下单。

---

## 3. 现状缺口清单（按优先级）

### P0（立即处理）

1. `POST /api/asset-analysis/multidim-screen/` 仍返回 501（`apps/asset_analysis/interface/views.py`）。
2. `strategy_execute` 未接策略执行引擎（`apps/strategy/interface/views.py`）。
3. Account 持仓创建仍用默认价格占位（`apps/account/application/use_cases.py`）。
4. 审计报告 `regime_actual` 仍为空写入（`apps/audit/application/use_cases.py`）。

### P1（第二优先）

1. 模拟盘绩效更新流程未落地（`apps/simulated_trading/application/auto_trading_engine.py`）。
2. 净值曲线/最大回撤算法仍有占位逻辑（`apps/simulated_trading/application/performance_calculator.py`）。
3. 通知功能未完整实现（`apps/simulated_trading/application/tasks.py`、`apps/signal/application/tasks.py` 等）。

### P2（第三优先）

1. Events API 在主路由中仍为 placeholder（`core/urls.py`）。
2. Backtest 若干指标（换手率、ICIR、旧权重等）仍 TODO（`apps/backtest/domain/*`）。
3. RTM 中仍有 Pending/NotStart 项（`docs/testing/requirements-traceability-matrix-2026-02.md`）。

---

## 4. 分阶段实施计划（12 周）

## Phase 1（第 1-4 周）：闭环可信度修复

### 4.1 交付项

1. 完成 `multidim-screen` 正式实现（等价接入现有 `screen/{asset_type}` 能力）。
2. `strategy_execute` 接入 `StrategyExecutor`，输出真实执行结果与日志关联。
3. 引入统一行情读取接口，清理 `100.0` 占位价。
4. 审计写入补齐 `regime_actual` 来源与计算。

### 4.2 代码改动点

1. `apps/asset_analysis/interface/views.py`
2. `apps/asset_analysis/application/use_cases.py`（必要时）
3. `apps/strategy/interface/views.py`
4. `apps/strategy/application/strategy_executor.py`（适配输出）
5. `apps/account/application/use_cases.py`
6. `apps/account/infrastructure/repositories.py`（行情适配）
7. `apps/audit/application/use_cases.py`

### 4.3 验收标准

1. `multidim-screen` 不再返回 501。
2. `/strategy/<id>/execute/` 返回真实执行统计（非固定 `0`）。
3. 新建持仓价格可追溯到行情源，不再硬编码。
4. 归因报告中 `regime_predicted/regime_actual` 均有值或明确错误码。

### 4.4 测试

1. `tests/integration/asset_analysis/test_multidim_screen_api.py`
2. `tests/integration/strategy/test_strategy_execute_flow.py`
3. `tests/integration/audit/test_attribution_actual_regime.py`
4. `tests/integration/account/test_position_price_from_marketdata.py`

---

## Phase 2（第 5-8 周）：执行自动化与绩效口径统一

### 5.1 交付项

1. 自动交易引擎完成绩效更新调用链。
2. 净值曲线按“现金 + 持仓市值”重算，最大回撤按时序计算。
3. 日更巡检结果可生成“待执行再平衡草案”。
4. 通知通道（邮件/站内）完成并支持失败重试。

### 5.2 代码改动点

1. `apps/simulated_trading/application/auto_trading_engine.py`
2. `apps/simulated_trading/application/performance_calculator.py`
3. `apps/simulated_trading/application/daily_inspection_service.py`
4. `apps/simulated_trading/application/tasks.py`
5. `apps/signal/application/tasks.py`（信号通知）

### 5.3 验收标准

1. 账户绩效指标可自动刷新且与净值曲线一致。
2. 净值曲线返回 `cash/market_value/net_value/drawdown_pct`。
3. 再平衡建议可追踪到建议来源和执行状态。
4. 通知失败有日志、重试、告警。

### 5.4 测试

1. `tests/integration/simulated_trading/test_performance_curve_accuracy.py`
2. `tests/integration/simulated_trading/test_rebalance_proposal_flow.py`
3. `tests/integration/simulated_trading/test_notification_delivery.py`

---

## Phase 3（第 9-12 周）：平台完整度与发布门禁

### 6.1 交付项

1. Events API 从 placeholder 迁移为真实服务接口。
2. Backtest 关键指标 TODO 补齐（换手率/ICIR/旧权重等）。
3. RTM Pending 项闭环，发布门禁自动化收敛。
4. 新增“主链路禁止 501”守护测试与 CI 检查。

### 6.2 代码改动点

1. `core/urls.py`
2. `apps/events/interface/views.py` 与 `apps/events/domain/services.py`
3. `apps/backtest/domain/services.py`
4. `apps/backtest/domain/alpha_backtest.py`
5. `apps/backtest/domain/stock_selection_backtest.py`
6. CI 配置与测试脚本

### 6.3 验收标准

1. `events/api/*` 不再返回 501 占位响应。
2. Backtest 结果关键指标完整且可验证。
3. RTM 中 P0/P1 项（除 PostDeploy）全部 Passed。
4. CI 失败条件包含“主路径 501”与“RTM 关键项未通过”。

### 6.4 测试

1. `tests/integration/events/test_events_api_contract.py`
2. `tests/integration/backtest/test_metrics_completeness.py`
3. `tests/guardrails/test_no_501_on_primary_paths.py`

---

## 7. API / 接口变更计划

1. `POST /api/asset-analysis/multidim-screen/`  
由占位响应改为正式筛选响应，字段对齐 `screen/{asset_type}`。

2. 策略执行返回结构增强  
新增字段：`execution_id`, `generated_signals`, `failed_rules`, `duration_ms`。

3. 审计报告字段规范化  
`regime_actual` 改为强约束字段，缺失时返回可识别错误而非静默空值。

4. 模拟盘绩效接口扩展  
补充净值曲线与回撤字段，确保前后端一致口径。

---

## 8. 项目管理与节奏

1. 每 2 周一个里程碑评审（功能 + 测试 + 文档）。
2. 每阶段结束输出：
- 功能完成列表
- 风险清单更新
- RTM 状态快照
- 可回归测试清单
3. 发布策略：
- Phase 1、2 先灰度
- Phase 3 合并 RC 门禁后再全量

---

## 9. 风险与缓解

1. 行情数据源不稳定  
缓解：多源 fallback + 缓存 + 熔断策略。

2. 绩效重算带来历史口径变动  
缓解：提供旧口径对照期与一次性迁移说明。

3. 事件 API 上线影响现有调用  
缓解：保留兼容路由 + 版本化响应。

4. 测试补齐工作量高  
缓解：优先覆盖 P0 主链路，按 RTM 风险级别推进。

---

## 10. 完成定义（DoD）

1. 主链路无占位接口（特别是 501）。
2. 关键业务值（价格、绩效、审计真值）不依赖硬编码占位。
3. 新增能力都有自动化测试与文档更新。
4. RTM 与 CI 门禁一致，发布决策可审计。

