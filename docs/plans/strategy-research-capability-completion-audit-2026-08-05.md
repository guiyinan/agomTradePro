# 策略研究能力 R1—R8 完成度审计（2026-08-05）

> 状态：**路线图未完成；无 P0，仍有可在真实数据到位前开发的 P1**
> 审计基线：`dev/refactor-scenario-governance-quick-wins` / `6958b33c`
> 权威目标：[策略研究能力后续开发备忘](../business/strategy-research-capability-roadmap-memo-2026-08-04.md)

## 1. 审计结论

上一批完成了 readiness、research-only 合同和 13 项限定交叉复核整改，但不能据此推断完整路线图已经实现。本次由三组 Luna Max 分别审计 R1—R3、R4—R6、R7—R8，并按备忘中的目标、启动条件、最低验收和全局研究纪律逐项核对。

- 未发现当前代码可越过 research-only/readiness 直接影响生产决策或执行的 P0。
- 真实数据、Publication、PIT 样本、历史 outcome、外部对账和 PromotionDecision 仍是外部阻断。
- 同时确认多项纯软件能力仍可在无真实数据时开发，因此不得再使用“R1—R8 无数据基础全部完成”的口径。
- 本批优先完成 R5 组合风险预算/压力测试，并修复 R4 到期边界及报告 seal；其余项目进入下列实施队列。

## 2. 逐能力剩余开发项

| 能力 | 已有可靠基础 | 仍可无数据开发的主要 P1 | 必须等待的真实证据 |
|---|---|---|---|
| R1 | Sector typed AST/DAG、三情景、PIT fact、Equity 误差台账 | Sector→Equity bridge；cash-flow/六阶段/template-run identity 封存；通用经营 driver 事实绑定；baseline spec；Promotion artifact 精确绑定 | QW-7 反馈、连续行业 KPI、财务/估值 Publication、真实 trial |
| R2 | actor/series 双时间、proxy/measure semantics、PIT membership、描述性证据 | canonical expected-period/calendar schedule；series×period 完整 coverage；整期全缺门禁 | 获批 taxonomy、授权、两个市场周期、Production Publication、Audit 解释力 |
| R3 | 独立 App、PIT scope、外部结果 envelope、研究隔离 | 可复算 baseline/FMP/nested temporal-CV runner；dated current/forward ledger；artifact hash；append-only retirement lifecycle | 宏观 vintage、代理资产/连续期货、真实 cost/benchmark、OOS trial、Promotion |
| R4 | beta/CI/R²/残差、PSD、风险贡献、成本/流动性门禁 | 独立 R3 Promotion/PIT attestation；滚动/regime exposure；三基准同窗回测；完整持久证据 | R3 晋级版本、真实 exposure/covariance/constraint snapshot 和历史样本 |
| R5 | 单券定价、久期/凸性、carry/roll-down、曲线/信用利差 | 历史分位、等级迁移、流动性溢价、曲线组合及容量门禁；组合结果持久化/晋级闭环 | 两条曲线、信用估值、Bond Master/CashFlow/Calendar Publication、外部对账 |
| R6 | 简单基准不足 report、高级 artifact evidence gate | duration/决策损失/复杂度/稳定性比较；政策反应系数和诊断；监控/退役/Promotion 闭环 | 真实 shortfall、PIT 输入、预注册 family、OOS 证据 |
| R7 | 概率分栏、Brier/分箱、PIT 类比、路径证据、review intent | append-only reminder ledger/outbox；due/ack/escalate/expiry；逐期条件概率/转移绑定；结果持久化和 lifecycle | 完整预测—复核—兑现历史、获批 sample policy、PIT 路径样本 |
| R8 | canonical snapshot、execution feedback、统一输入、PSD/可行性、research solver | 13 类数值 payload 与 owner hash 精确绑定；现有配置基准；可投资 universe；四市场 typed constraints；真实 path drawdown；持久化/Promotion/lifecycle | broker reconciliation、R3/R4/R5 晋级、真实成本/容量/市场约束校准 |

## 3. 本批完成项

### 3.1 R4 证据封存整改

- `valid_until` 到期边界由 `>` 收紧为 `>=`，到期时刻立即 stale。
- `MacroRiskCandidateReport` 保存 input hash，并对资格状态、factor/residual/total variance、turnover、完整 contribution vector、blocker code/detail、研究边界和时间重新计算 canonical SHA-256。
- 篡改 eligibility 或 contribution 后，report 构造立即拒绝。

### 3.2 R5 组合风险预算与压力测试

新增纯 Domain/Application 纵切：

- Portfolio-owned snapshot owner/hash/as-of 绑定；
- 估值/流动性证据归 `data_center`，久期/凸性和信用敏感度归 `fixed_income`；
- 完整 PIT manifest、Publication identity、币种、as-of、freshness 和 exact-expiry 门禁；
- 可复算 budget policy hash，bundle 精确绑定 policy hash；
- DV01、CS01、convexity、可变现比例、流动性成本及逐持仓恒等式；
- 显式 parallel/key-rate/steepener/flattening/credit widening shock；
- 一阶利率、凸性、信用和总压力 P&L 贡献恒等式；
- 所有预算和证据问题发布稳定 blocker；
- 完整 input/output SHA-256，固定 `research_only / must_not_use_for_decision / must_not_execute`。

本纵切不新增 ORM、迁移、URL、任务或生产写入，也不解除 R5 readiness。

## 4. 后续实施顺序

1. R1 Sector→Equity bridge、cash flow/template/run seal 和通用 driver 事实绑定。
2. R2 expected-period/calendar coverage，关闭“整期全缺不可见”。
3. R7 review reminder ledger/outbox，仅提醒人工复核。
4. R3 可复算 runner、dated outputs 和 retirement lifecycle。
5. R8 typed input binding、current baseline、universe 与四市场约束。
6. R1 baseline/Promotion、R4 rolling backtest、R5 relative-value 扩展、R6/R7/R8 lifecycle。

每项按独立 commit 组推进；真实证据未齐时保持 blocked，不使用 fixture、模型文件或迁移存在作为 ready 证明。

## 5. 验证边界

当前新增纵切最低回归：

```powershell
pytest tests/unit/portfolio/test_macro_factor_risk.py -q
pytest tests/unit/fixed_income/test_portfolio_risk.py tests/unit/fixed_income/test_portfolio_risk_use_case.py -q
python scripts/check_mypy_regression.py apps/portfolio/domain/macro_factor_risk.py apps/fixed_income/domain/portfolio_risk.py apps/fixed_income/application/portfolio_risk.py
python scripts/verify_architecture.py
```

本批实际验证：fixed-income 全部 unit/component 加 R4 macro-risk 共 `49 passed`；新增 3 个生产文件增量 mypy 为 0 regression；Ruff、Black、Django system check、架构扫描（2148 files / 0 violations）、业务配置硬编码门禁和 43 个 current-data surface 均通过。

完成路线图仍需为上表每项取得代码、迁移/台账、研究证据、运行时行为和 Promotion/回滚的直接证明；“测试全绿”只证明已覆盖合同，不替代真实数据和样本外结果。
