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
| R1 | Sector typed AST/DAG、三情景、PIT fact、Equity 误差台账与持久 bridge、cash-flow/六阶段/template-run seal、owner-approval-enforced baseline spec、完整配对 trial、Research exact Promotion/retirement/rollback | 当前 R1 无数据软件切片经 Luna Max 复核已无 P0/P1；Valuation 消费须等待真实证据并另建阶段 | QW-7 反馈、连续行业 KPI、财务/估值 Publication、真实 owner approval、trial 与 approved decision |
| R2 | actor/series 双时间、proxy/measure semantics、PIT membership、描述性证据、版本化 expected-period calendar、series×period 完整 coverage、整期全缺门禁 | 运行时 taxonomy/calendar Publication 接线与研究晋级闭环 | 获批 taxonomy、授权、两个市场周期、Production Publication、Audit 解释力 |
| R3 | 独立 App、exact PIT fact/manifest、historical-mean/FMP、nested temporal-CV runner、canonical artifact bytes、dated current/forward ledger、append-only retirement lifecycle | regime 分段、trial/Promotion exact artifact binding、监控与生产读取投影 | 宏观 vintage、代理资产/连续期货、真实 cost/benchmark、OOS trial、Promotion |
| R4 | beta/CI/R²/残差、PSD、风险贡献、成本/流动性门禁 | 独立 R3 Promotion/PIT attestation；滚动/regime exposure；三基准同窗回测；完整持久证据 | R3 晋级版本、真实 exposure/covariance/constraint snapshot 和历史样本 |
| R5 | 单券定价、久期/凸性、carry/roll-down、曲线/信用利差 | 历史分位、等级迁移、流动性溢价、曲线组合及容量门禁；组合结果持久化/晋级闭环 | 两条曲线、信用估值、Bond Master/CashFlow/Calendar Publication、外部对账 |
| R6 | 简单基准不足 report、高级 artifact evidence gate | duration/决策损失/复杂度/稳定性比较；政策反应系数和诊断；监控/退役/Promotion 闭环 | 真实 shortfall、PIT 输入、预注册 family、OOS 证据 |
| R7 | 概率分栏、Brier/分箱、PIT 类比、typed 逐期路径证据、append-only reminder ledger/internal outbox、due/ack/escalate/expiry | calibration/path 结果持久化、retirement/Promotion lifecycle 与审计分页 | 完整预测—复核—兑现历史、获批 sample policy、PIT 路径样本 |
| R8 | canonical snapshot、execution feedback、13 类 typed 输入、current baseline、可投资 universe、四市场约束、path drawdown、四候选比较、append-only result/Promotion/retirement/rollback lifecycle | 本轮无数据软件清单经 Luna Max 复核已无 P0/P1；进入 transition plan/生产消费前仍须基于真实证据另建阶段 | broker reconciliation、R3/R4/R5 晋级、真实 Portfolio snapshot、成本/容量/市场约束校准 |

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

### 3.3 R1 Sector→Equity 持久证据桥接

- Bridge 只接受 `run_key/run_version` 与 Equity-owned typed sensitivity evidence，从 Sector append-only evidence 读取、校验 hash 并 typed restore；调用方不能提交自称可信的 run result。
- Equity v2 预测封存任意治理 `metric_code` 的完整 PIT identity、template/run identity、cash flow、三情景六阶段结果及 sensitivity source artifact hash。
- `0012` 精确区分 0010/0011 legacy hash recipe，保留原 content hash、估值和 promotion 字段；旧行不补造 template/run、cash flow 或 stage，unverified legacy 只读且不可消费。
- v2 当前强制 research-only。旧的 decision-id-only checker 不能解锁估值消费；Promotion artifact exact binding 仍是后续独立 P1。
- Equity/Sector concrete base manager、并发首次写、run identity 幂等/冲突、事务全回滚及季度 actual evaluation 均已有直接组件证据。

### 3.4 R2 预期期间与完整 coverage

- Data Center 新增无 seed、append-only 的版本化 `MarketStructurePeriodCalendar`，request 精确绑定 code/version，日历 payload 与 hash 一并进入研究证据。
- Application 按 request series × calendar periods 生成完整 coverage，不再由已有 observation 反推期间；某整期所有 series 都缺可靠数据时发布稳定 blocker 并 fail closed。
- 日历 identity/frequency/as-of/active/expiry、coverage 缺格或重复、raw hash tamper、并发注册和 `_base_manager` 旁路均被拒绝。
- `0061` 只建 schema，不回填日历、不创建业务 seed，并保持旧 evidence payload/hash 字节不变。

### 3.5 R7 人工复核 reminder ledger/internal outbox

- 修复 review intent 的确定性缺陷：schedule 固定锚定 invalidation time，identity 同时封存 forecast observation、scenario revision/set、policy version/content hash；重复研究评估不再产生同 ID 异 payload。
- Research 新增 immutable reminder header 与 hash-chained lifecycle event，状态由 `scheduled / due / escalated / acknowledged / expired` 事件推导；exact due/escalation/expiry 边界和 terminal transition 均 fail closed。
- Conditional/transition evidence 显式携带 period index，并从 typed `ScenarioPathStudyEvidence` 派生完整 horizon binding；调用方不能提交任意 claimed hash，也不能跨 path、scenario set 或 period 替换。
- Application 只提供 internal pull queue、deterministic reconcile 与 owner-authorized human ACK；Domain/DB 固定 `must_not_execute / must_not_use_for_decision / no auto approval / no external dispatch`，未新增 Celery、邮件、短信、webhook 或执行链。
- `research.0002` 只新建空 ledger/outbox 表，不 seed、不回填旧 reminder，并保持 0001 既有研究记录不变；default/base/related manager mutation、并发 winner replay、同 key 异 evidence、事务回滚和 raw tamper 均有组件证据。

### 3.6 R3 可复算 runner、dated outputs 与 retirement lifecycle

- PIT design rows 逐项封存 target/proxy fact version、content hash、effective/available time，并核对 typed manifest selected versions；晚修订、未来不可知值和跨 manifest 替换均拒绝。
- Nested temporal-CV plan 精确绑定 governed split windows、purge/embargo、label availability 和 inner/outer row identity；outer OOS 全局唯一且不进入 selection。每个 outer fold 独立选择 alpha/资产，只有显式 final fold 绑定最终 result。
- Historical-mean 与 fixed-universe FMP 基准按 fold 重算；historical mean 与外部 final fit 使用同一 train+validation 窗口，避免人为弱化基准。
- External envelope 封存 per-fold inner scores、selected alpha、coefficients/weights、final-fit lineage、OOS prediction 和 canonical artifact bytes；bytes/media/length/producer 可从 DB 回读并重新解析、SHA 校验。
- Dated output 精确区分 current horizon 0 与 forward horizon > 0，保存 as-of/target period/produced/valid-until/value/unit；到期时刻立即 stale，latest 不等于 current。
- Run artifact、outputs 与 lifecycle event 使用三张 append-only 表；retirement 通过 owner-attested hash chain 派生，不修改 0001 source result。`macro_factor.0002` 为 schema-only、零 seed，完整保留 legacy payload/hash/status/timestamp。

### 3.7 R8 governed optimization input、结果与生命周期

- 13 类数值 payload 分别绑定 canonical owner、payload hash、PIT/knowledge time、有效期和 source artifact；R3/R4/R5 Promotion 必须由 exact provider 在运行时重读，调用方不能提交自称已批准的对象。
- Portfolio current baseline 使用版本化 conservation tolerance；可投资 universe 的 `can_buy / can_sell / retain_if_held` 被合成硬边界，held-only/no-buy 资产不能增仓。
- A 股、基金、债券和商品规则均为带 `available_at` 的 typed constraint。weight-only 求解无法证明手数、T+1、结算、应计利息或保证金约束时，候选稳定返回 `constraint_not_yet_enforced`，不会产出可执行权重。
- Path drawdown 只接受 knowledge cutoff 之前的完整逐期资产/现金路径；current、等权、资产风险平价和 local-search 四候选必须完整、守恒、可重算，selected candidate 必须是真实合格 argmin。
- 完整 problem/result/lifecycle 证据图统一使用 canonical Decimal 与 UTC 时间；scale 或等价时区表示不改变 hash。
- `portfolio.0006` 只创建 append-only input/result/lifecycle 台账，不 seed、不回填。Promotion 事件必须从 Research provider 精确回读，retirement/rollback 必须从 Portfolio owner authorization provider 精确回读；Repository 只持久化，不承担授权。
- 本纵切未注册 API/TUI/Celery/订单或 transition plan 写入口，所有输出固定 `research_only / must_not_use_for_decision / must_not_execute`。

### 3.8 R1 精确预测基线、trial 与晋级生命周期

- Equity 定义强制 owner approval 的 baseline spec 合同，精确绑定 subject、industry、scenario、purpose、horizon、calendar 和 metric set；预测与 baseline 在每个 period×metric 上完整配对，actual 使用独立 PIT manifest，不允许以评估时可见事实改写预测起点。
- Baseline artifact、trial result、forecast/template-run/sensitivity seal 与 owner receipt 均使用 canonical hash；trial 预注册样本、误差指标、失效条件和比较口径，缺行、重复行、单位不一致、未来知识或 owner 不一致均 fail closed。
- Research 使用 R1 专用 typed Promotion policy/decision，不复用通用 Sharpe/FDR/DSR 语义；approved/rejected 都保存完整审计结果，生命周期按 canonical scope 隔离并支持 promoted、retired、rolled_back。
- Research Infrastructure 只依赖 Equity Application query port，在决策、查询 active promotion 与回滚时重读 canonical Equity ledger；decision id、自报 hash、伪造 receipt、非尾回滚、过期 policy/trial 和跨 scope 替换均不能放行。
- Equity 四张、Research 五张 append-only ledger 均通过 schema-only、零 seed 迁移建立；未注册 Valuation consumer、API/TUI/Celery 或生产读取面。

## 4. 后续实施顺序

1. R4 rolling backtest、regime exposure 与三基准同窗比较；R5 relative-value 扩展；R6 lifecycle。
2. R3 regime 分段、trial/Promotion exact binding 与监控读取投影。
3. R7 calibration/path 结果持久化与 retirement/Promotion lifecycle。

R1 与 R8 本轮无数据软件清单已关闭。R1 只有取得真实 QW-7、Publication、连续 KPI、真实 trial 与 approved decision 后，才另建 Valuation 消费阶段；R8 只有取得真实 R3/R4/R5 Promotion、Portfolio snapshot、broker reconciliation 和约束校准后，才另建 transition plan/生产消费阶段。两者都不在 fixture 上提前接线。

每项按独立 commit 组推进；真实证据未齐时保持 blocked，不使用 fixture、模型文件或迁移存在作为 ready 证明。

## 5. 验证边界

当前新增纵切最低回归：

```powershell
pytest tests/unit/portfolio/test_macro_factor_risk.py -q
pytest tests/unit/fixed_income/test_portfolio_risk.py tests/unit/fixed_income/test_portfolio_risk_use_case.py -q
python scripts/check_mypy_regression.py apps/portfolio/domain/macro_factor_risk.py apps/fixed_income/domain/portfolio_risk.py apps/fixed_income/application/portfolio_risk.py
python scripts/verify_architecture.py
```

本批此前验证 fixed-income 与 R4 macro-risk 共 `49 passed`。本次 R1/R2 续批由实现与只读复核 Luna Max 交叉验收：R1 unit `15 passed`、component `10 passed`、migration `3 passed`；R2 unit `18 passed`、component `6 passed`、migration `2 passed`。主代理另行联合复跑 unit `27 passed`、component `13 passed`。14 个变更生产文件增量 mypy 为 0 regression；Ruff、Black、isort、Django system check、三 App migration drift、架构扫描（2150 files / 0 violations）、业务配置硬编码门禁和 43 个 current-data surface 均通过。

R7 reminder 续批经 Luna Max 实现与只读复核关闭全部 P0/P1；主代理独立复跑 unit `18 passed`、component `11 passed`、migration `2 passed`。8 个变更生产文件增量 mypy 为 0 regression；Ruff、Black、isort、Research migration drift、Django system check、架构扫描（2155 files / 0 violations）、44 个 current-data surface、业务配置、governance consistency 和 Celery task contract 均通过。

R3 runner 续批经 Luna Max 实现与多轮泄漏/持久化复核关闭全部 P0/P1；主代理独立复跑 unit `32 passed`、component `11 passed`，实现 agent migration `1 passed`。16 个生产文件增量 mypy 为 0 regression；Ruff、Black、isort、Macro Factor migration drift、Django system check、架构扫描（2168 files / 0 violations）、45 个 current-data surface、业务配置和 governance consistency 均通过。

R8 governed optimization 续批经 Luna Max 实现、两轮独立只读复核和定点整改后无 P0/P1；主代理独立复跑 unit `21 passed`、component `11 passed`、migration `2 passed`。19 个生产文件增量 mypy 为 0 regression；Ruff、Black、isort、Portfolio migration drift、Django system check、架构扫描（2182 files / 0 violations）、45 个 current-data surface、业务配置、governance consistency 和 Celery contracts 均通过。测试只证明 software contract，不替代真实 Promotion、snapshot、broker reconciliation 或约束校准。

R1 精确基线与晋级续批经 Luna Max 实现、独立只读复核和定点整改后无 P0/P1：Domain/Application `80 passed`；Equity unit/component `99 passed`、migration `2 passed`；Research unit/component/migration `48 / 24 / 3 passed`。相关生产文件增量 mypy 为 0 regression，Ruff、Black、isort、Equity/Research migration drift、Django system check、架构边界、业务配置与 governance consistency 均通过。测试只证明 baseline/trial/Promotion/lifecycle 软件合同，不替代真实 Publication、经营事实、样本外结果或 Valuation 授权。

完成路线图仍需为上表每项取得代码、迁移/台账、研究证据、运行时行为和 Promotion/回滚的直接证明；“测试全绿”只证明已覆盖合同，不替代真实数据和样本外结果。
