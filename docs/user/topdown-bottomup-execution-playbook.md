# 环境-标的-执行-审计一体化操作手册

> 版本: 1.0  
> 适用对象: 投资经理、交易员、策略研究员  
> 更新日期: 2026-02-26

---

## 1. 目标与边界

本手册用于指导用户在 AgomSAAF 中形成闭环流程：

1. 自上而下分析环境（Macro/Regime/Policy）
2. 自下而上分析标的（Asset Analysis + Equity/Fund）
3. 在执行层按风控框架推进（Beta Gate + Decision Rhythm + Strategy + Account）
4. 对仓位进行约束与再平衡
5. 做事后审计并反馈到下一轮参数调整

系统定位是决策辅助，不是自动交易终端。下单执行与最终责任在用户。

---

## 2. 一张图看全流程

1. 环境判断: `/macro/` -> `/regime/dashboard/` -> `/policy/dashboard/`
2. 标的筛选: `/asset-analysis/screen/` + `/equity/screen/`/`/fund/screen/`
3. 执行闸门: `/beta-gate/config/` + `/beta-gate/test/` + `/decision/workspace/`
4. 仓位与风险: `/strategy/` + `/simulated-trading/my-accounts/` + `/api/account/...`
5. 再平衡: 回测频率 + 模拟盘巡检建议
6. 审计复盘: `/audit/reports/` + `/audit/indicator-performance/`

---

## 3. 第1阶段: 自上而下分析环境

### 3.1 页面入口

1. 宏观数据: `/macro/`
2. Regime 仪表盘: `/regime/dashboard/`
3. 政策仪表盘: `/policy/dashboard/`

### 3.2 API 入口

1. `GET /api/macro/...`
2. `GET /api/regime/current/`
3. `GET /api/regime/history/`
4. `GET /api/policy/...`

### 3.3 输出要求

每次决策前至少落地 3 个结论：

1. 当前主导 Regime + 置信度
2. 当前 Policy 档位
3. 当前环境下允许/不宜重仓的资产类别

---

## 4. 第2阶段: 自下而上分析标的

### 4.1 页面入口

1. 统一筛选页: `/asset-analysis/screen/`
2. 股票筛选: `/equity/screen/`
3. 基金筛选: `/fund/screen/`

### 4.2 推荐 API 主链

1. `POST /api/asset-analysis/screen/{asset_type}/`
2. `GET /api/asset-analysis/pool-summary/`

### 4.3 重要说明（避免走错接口）

`POST /api/asset-analysis/multidim-screen/` 当前为开发中占位，返回 501；生产使用请走 `screen/{asset_type}` 链路。

### 4.4 输出要求

每次筛选后至少产出：

1. 可投资池（investable）
2. 观察池（watch）
3. 候选池（candidate）
4. 每个标的的总分、风险等级、所属池

---

## 5. 第3阶段: 执行前风控框架

### 5.1 Beta Gate（硬闸门）

1. 配置页: `/beta-gate/config/`
2. 测试页: `/beta-gate/test/`
3. 核心约束: 风险画像、Regime 约束、Policy 约束、组合约束

在提交执行前，先用测试工具验证目标资产是否可见、被拦截原因是什么。

### 5.2 Decision Workspace（统一看板）

入口: `/decision/workspace/`

该页面聚合：

1. 当前 Regime/Policy
2. 可操作 Alpha 候选
3. 配额使用状态（Decision Rhythm）
4. 待处理决策请求与系统告警

### 5.3 Decision Rhythm（频率与配额）

1. 配额页: `/decision-rhythm/quota/`
2. 配置页: `/decision-rhythm/config/`
3. API: `/api/decision-rhythm/...`

提交决策前先检查：剩余额度、冷却期、是否触发频率约束。

---

## 6. 第4阶段: 仓位约束与执行

### 6.1 策略级硬约束（Strategy）

策略模型中直接定义：

1. `max_position_pct`（单资产上限）
2. `max_total_position_pct`（总仓位上限）
3. `stop_loss_pct`（止损约束）

页面入口: `/strategy/`

### 6.2 规则级仓位计算（Position Management Rule）

数据库驱动规则，避免硬编码，支持：

1. 买卖条件表达式
2. 买卖建议价
3. 止损止盈价
4. 建议仓位表达式

API：

1. `POST /api/strategy/api/position-rules/{id}/evaluate/`
2. `POST /api/strategy/api/strategies/{id}/evaluate_position_management/`

### 6.3 账户层风险评估（Account）

系统会从持仓计算：

1. `total_exposure`（总敞口）
2. `concentration_ratio`（集中度）
3. `geographic_diversification`（分散度）
4. `risk_level`（low/medium/high）

执行动作前要求：

1. 不突破策略上限
2. 不触发高风险集中度
3. 止损参数有明确定义

---

## 7. 第5阶段: 再平衡

### 7.1 回测中的再平衡

入口: `/backtest/`  
参数: `rebalance_frequency`（如 monthly/quarterly）

用于验证不同再平衡频率下的收益、回撤、交易成本表现。

### 7.2 模拟盘中的再平衡建议

入口:

1. 页面: `/simulated-trading/my-accounts/{account_id}/inspection-notify/`
2. API: `POST /simulated-trading/api/accounts/{account_id}/inspections/run/`

巡检结果会给出权重偏离与建议动作（buy/sell/hold）及建议数量。

### 7.3 执行口径

当前体系以“规则驱动建议 + 人工确认执行”为主，不应宣称为全自动实盘调仓。

---

## 8. 第6阶段: 审计与复盘闭环

### 8.1 页面与 API

1. 页面: `/audit/reports/`、`/audit/indicator-performance/`、`/audit/threshold-validation/`
2. API: `POST /api/audit/reports/generate/`、`GET /api/audit/summary/`

### 8.2 归因维度

重点跟踪：

1. Regime 择时贡献（regime_timing）
2. 选股/选基贡献（asset_selection）
3. 交互项（interaction）
4. 交易成本影响

### 8.3 复盘输出模板（每月）

1. 环境判断偏差: 哪些月份 Regime/Policy 识别偏差最大
2. 执行偏差: 哪些交易未按风控框架执行
3. 结果归因: 收益与损失来自哪里
4. 参数调整: 下月阈值/仓位上限/配额策略如何调整

---

## 9. 每日/每周/月操作节奏

### 每日（5-10 分钟）

1. 刷新环境状态（Regime/Policy）
2. 查看候选池与告警
3. 检查配额和冷却期
4. 如有持仓，跑一次巡检

### 每周（30 分钟）

1. 回顾本周执行是否越过仓位约束
2. 检查集中度和敞口变化
3. 复核 Beta Gate 配置是否仍匹配环境

### 每月（60-90 分钟）

1. 生成审计报告
2. 形成参数调整清单
3. 回测新参数并评估是否上线

---

## 10. 常见失败场景与处理

1. 资产被 Beta Gate 拦截  
处理: 在 `/beta-gate/test/` 查看原因，优先调整资产池，不绕过闸门。

2. 有候选但无法执行  
处理: 检查 `/decision-rhythm/quota/` 配额与冷却期。

3. 仓位建议过大  
处理: 先看策略 `max_position_pct` 与账户风险等级，再调 `position_size_expr`。

4. 再平衡建议频繁触发  
处理: 调整巡检中的 `metadata.rebalance.drift_threshold`，降低噪声调仓。

5. 审计显示择时贡献持续为负  
处理: 回看 Regime 置信度阈值与样本窗口，先回测再上线。

---

## 11. 附录: 关键路径速查

### 页面

1. `/decision/workspace/`
2. `/regime/dashboard/`
3. `/asset-analysis/screen/`
4. `/beta-gate/config/`
5. `/decision-rhythm/quota/`
6. `/strategy/`
7. `/simulated-trading/my-accounts/`
8. `/audit/reports/`

### API（示例）

1. `GET /api/regime/current/`
2. `POST /api/asset-analysis/screen/equity/`
3. `POST /api/strategy/api/position-rules/{id}/evaluate/`
4. `POST /simulated-trading/api/accounts/{id}/inspections/run/`
5. `POST /api/audit/reports/generate/`
