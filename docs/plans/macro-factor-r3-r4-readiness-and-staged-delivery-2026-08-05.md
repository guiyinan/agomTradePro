# R3/R4 宏观因子与宏观风险平价启动门禁及分阶段实施计划

> 状态：**R3 concrete research fitting 与 R4 候选风险验证已实现；真实 PIT、owner policy、晋级版本和 canonical 组合输入仍 Blocked**
> 建立日期：2026-08-05
> 适用分支：`dev/refactor-scenario-governance-quick-wins`
> 来源：[策略研究能力后续开发备忘](../business/strategy-research-capability-roadmap-memo-2026-08-04.md) R3、R4
> 本阶段边界：允许 Infrastructure 在已验证的 PIT design 上执行 research-only Lasso/nested temporal-CV；不从空库造训练数据，不发布 current，不把拟合结果或 R4 候选称为已晋级宏观因子/风险平价。

> 2026-08-09 concrete fitting 续批：新增 sklearn 标准化/Lasso 与 OLS refit Infrastructure adapter。每个 inner fold 独立选择预登记 alpha，outer OOS 不进入选择或 final fit；标准化参数、intercept、系数、权重、显著性、BIC、调整 R²、benchmark/cost/version/hash 均进入 canonical artifact。Application 仍先验证 exact PIT manifest/dataset/spec，composition 缺任一 owner/config/repository 时显式 blocked 且零写入。合成 PIT 测试只证明算法与防泄漏合同，不替代真实宏观 vintage、代理资产、连续期货、成本、Regime/OOS trial 或 Promotion。

> 2026-08-09 inference chronology 续批：PIT design rows 继续只服务训练、选择与历史 OOS 评估；dated publication 改为要求独立、无 label/value 的 manifest-selected inference row。Authoritative manifest full seal 封存 calendar owner 与 exact period member；版本化 freshness policy 对 manifest/inference age 设置封存上限，validity 不得越过任一 expiry。Inference proxy facts、target-calendar period、manifest cutoff 与 request hash 精确绑定，FORWARD period 必须晚于 knowledge/production cutoff，CURRENT period 不得晚于 cutoff；concrete runner 的 final fit 只预测该行，external runner 使用独立重建副本，返回后按未传出的基线现场重验。Trusted Application clock、provider/malformed-object 边界和逐 fact cutoff 均 fail closed。真实 inference Publication/calendar owner、PIT 数据、trial 与 Promotion 未形成，门禁不变。

## 1. 启动决策

R3 与 R4 当前均不允许进入模型实现：

- R3：`blocked`。Data Center 有通用 PIT 双时间模型和 ManifestBound reader，但没有生产路径把宏观 vintage 和代理资产价格写入 `PITFactVersionModel`；连续期货合约规则、宏观因子专用 benchmark 和成本假设也没有可引用的激活版本。
- R4：`blocked`。除继承 R3 阻断外，Portfolio 尚未提供版本化资产收益协方差、宏观暴露矩阵和优化输入快照；当前交易规划约束不能等同于宏观风险预算输入。
- 现有 `factor` 明确是股票横截面评分：其实体、仓储和接口都围绕 `stock_code`、截面 percentile/z-score 与股票组合。不得把该模块改名或复用为宏观时间序列因子引擎。

本次只新增 `research` 所拥有的启动门禁合同：

- Domain：固定 R3/R4 必需证据、canonical owner、状态和稳定 blocker code；
- Application：通过 Protocol 收集 owner-attested evidence，缺一项即 fail closed；
- 不新增半成品 `macro_factor` Django App，不注册模型、URL、任务、MCP 或 TUI；
- readiness evidence 未接入 canonical provider 前不会发布“ready”。

## 2. 仓库能力审计

### 2.1 Data Center PIT/vintage

| 检查项 | 当前证据 | 结论 |
|---|---|---|
| 双时间事实 | `apps/data_center/domain/pit.py` 定义 effective/available/ingested/revision；`0039_pit_fact_versions_and_manifests.py` 建表 | 通用结构存在 |
| 不可变 Manifest | `PITManifestRepository` 冻结 version ID/hash；`ManifestBoundPITDataView` 拒绝未来时点、篡改和清单外版本 | 通用结构存在 |
| 宏观 vintage 生产写入 | 生产代码没有 `PITFactVersionModel` 的 create/bulk-create/upsert 写入路径；现有行只在测试构造 | **阻断** |
| 代理资产价格 PIT 写入 | 同上；Price Publication 不能自动替代 PIT fact version/manifest | **阻断** |
| 发布日历 | 宏观事实有 `published_at`，但没有宏观因子 universe 所需的完整发布日历版本证据 | **阻断** |
| 连续期货 | 未发现连续合约 roll policy、合约链版本或 PIT 连续价格证据 | **阻断** |

Publication 证明“某批数据可被决策读取”，PIT Manifest 证明“历史某时点实际可知的确切版本”。R3 必须同时满足两者，不能用当前 Published 行回填历史训练样本。

2026-08-05 的 local/dev 数据库只用于开发环境盘点：`PITFactVersion=0`、`PITManifest=0`。这进一步证明当前本地环境不能产出 R3 训练清单，但该行数不代表生产库状态，也不作为长期治理基线。

### 2.2 Research 研究治理

| 检查项 | 当前证据 | 结论 |
|---|---|---|
| Experiment Registry | `ResearchExperiment`、`ExperimentTrial` 与受控 UseCase/API 已存在 | 平台能力可用 |
| Multiple-test family | `MultipleTestFamily` 固定 planned trial count；Promotion 计算 q-value/deflated Sharpe | 平台能力可用 |
| PromotionDecision | 完成试验、PIT manifest、backtest trust、family 完整性均进入 immutable decision | 平台能力可用 |
| Split/embargo | Trial 合同保存 train/validation/OOS/walk-forward/embargo | 合同可用；R3 尚无专用 split policy 版本 |
| R3 晋级证据 | 没有 macro-factor experiment、trial、样本外结果或 approved PromotionDecision | **阻断 R4** |

通用研究注册表可复用，但它不是 R3 已验证的证据。未来每个超参数候选必须属于预先声明的 family，失败试验也必须保留。

同次 local/dev 盘点为 `approved PromotionDecision=0`；Forecast Ledger 相关表也为 `ForecastLedgerEntry=0`、`ForecastOutcome=0`。这些只说明本地尚无可引用的晋级/预测兑现证据，不外推为生产数据结论。

### 2.3 Portfolio 协方差、成本与约束

| 检查项 | 当前证据 | 结论 |
|---|---|---|
| Canonical snapshot | `PortfolioSnapshot` 保存持仓和现金；transition plan 绑定 snapshot ID | 持仓快照能力存在 |
| 交易成本 | Portfolio Planning Policy 有 versioned fee/slippage；Account 有更细交易成本配置 | 能力分散，尚无 R3/R4 canonical cost input |
| 执行约束 | Portfolio 有单资产上限、成交量参与、现金、涨跌停、T+1 等规划约束 | 执行规划可用 |
| 换手约束 | Rotation 有 `max_turnover`，但不是 Portfolio canonical optimization contract | **阻断** |
| 协方差输入 | Portfolio 没有版本化资产收益协方差、估计窗口、缺失值/PSD 证据 | **阻断** |
| 宏观暴露 | 没有资产×宏观因子暴露矩阵、置信区间、稳定性或版本引用 | **阻断** |
| 基准 | Rotation 的 volatility-inverse `risk_parity` 不能作为宏观因子风险平价 | **阻断** |

R4 不得直接复用 Rotation 的资产波动率倒数结果，也不得将散落在 Account/Portfolio/Rotation 的参数拼成未版本化优化输入。

## 3. 代码边界与未来 owner

### 3.1 当前阶段

`research` 仅拥有“是否允许启动研究能力”的门禁和 PromotionDecision。它不拥有市场事实、宏观因子定义或组合优化结果。`macro_factor` 现已拥有 research-only 外部证据验证，但没有权力自行签发 PromotionDecision。

### 3.2 已新增的 `macro_factor` research-only App

已新增完整四层 `apps/macro_factor/`，当前归属与边界如下：

- Domain：`MacroTargetDefinition`、`ProxyUniverseVersion`、`FactorModelSpecification`、`MimickingPortfolioVersion`、`NowcastObservation`、失效和退役规则；
- Application：训练计划、walk-forward 编排、复算、监控、退役；只依赖 Data Center PIT Protocol 和 Research UseCase；
- Infrastructure：模型执行适配器、不可变版本仓储；不得成为第二份价格/宏观事实真源；
- Interface：研究结果和证据读取，激活仍必须引用 Research `PromotionDecision`；新主任务进入 TUI。

现有 `apps/factor/` 继续拥有股票横截面财务/估值/动量等 exposure 与选股组合。两者不得共享含混的 `FactorExposure`、`FactorEngine` 或数据库表。

### 3.3 R4 责任边界

- `macro_factor`：资产对宏观因子的回归暴露、置信区间、因子协方差和研究结果；
- `portfolio`：canonical holdings、资产收益协方差输入、成本/换手/流动性/权重约束快照和目标组合；
- `research`：等权、资产风险平价、宏观因子风险平价的同族试验、multiple-test 和 PromotionDecision；
- `data_center`：全部 PIT 事实及 manifest；
- `risk_center`：只消费晋级后的暴露/风险贡献，不生成第二套模型。

## 4. Readiness contract

合同版本：`research-capability-readiness.v1`。

### R3 必需证据

1. Data Center 宏观目标 vintage PIT；
2. Data Center 代理资产价格 PIT；
3. 版本化宏观发布日历；
4. 版本化连续期货 roll policy；
5. Experiment Registry；
6. Multiple-test family；
7. PromotionDecision；
8. train/validation/OOS/walk-forward/embargo policy；
9. 宏观因子 benchmark 版本；
10. 组合 owner 提供的成本模型版本。

### R4 必需证据

1. R3 approved PromotionDecision 和不可变 factor version；
2. Portfolio canonical asset exposure universe；
3. Portfolio versioned covariance input；
4. canonical cost model；
5. weight bounds；
6. turnover constraint；
7. liquidity constraint；
8. equal-weight benchmark；
9. asset-risk-parity benchmark。

verified 证据必须来自合同指定 owner、包含非空引用、timezone-aware `observed_at` 和明确的 `valid_until`。缺失、未验证、过期、重复、未来时间或 owner 错配均不得得到 ready；评估时超过 `valid_until` 的 verified evidence 自动转为 `stale`。

## 5. 分阶段主线

### M0：Readiness-only（本阶段）

- [x] 审计 PIT、Research Registry、factor 与 Portfolio 边界；
- [x] 新增 R3/R4 Domain/Application readiness contract；
- [x] 缺失证据自动形成稳定 blocker，不推断成功；
- [x] 单元测试覆盖全绿、缺失、未验证、owner 错配、未来时间和 R3→R4 依赖；
- [ ] canonical evidence providers：待各 owner 建立真实证据后实施。

### M1：Data Center PIT 生产闭环

- 宏观 fact/revision → append-only PIT fact version；
- 代理现货/ETF/期货价格 → append-only PIT fact version；
- 发布日历和连续合约 roll policy 版本化；
- 覆盖率、缺失、estimated/unknown 门禁及生产数据验收；
- PostgreSQL 上验证重跑幂等、修订不污染旧 manifest。

完成条件：至少一个目标变量和一组代理资产可以从相同 manifest、代码版本和参数复算；当前没有该证据。

### M2：R3 研究合同与最简单基准

- [x] 注册完整 `macro_factor` App、不可变外部研究结果和 append-only repository；
- [x] 固定 current/forward output role、目标、候选/入选资产、split/embargo、BIC/显著性/经济含义、成本和退役合同；
- [x] 实现逐 outer fold 的 historical-mean 与预注册 fixed-universe FMP 基准，使用与外部 final fit 一致的 train+validation 窗口；
- [x] 固化 selection 前完整 trial family、exact artifact/regime report 绑定与确定性 family hash；真实 Research owner trial 仍须由 canonical provider 提供，不得先挑最佳结果再补登记。

### M3：R3 模型研究与样本外晋级

- [x] 实现 nested temporal-CV plan 与 typed external runner envelope；每个 outer fold 独立保存 inner scores/alpha/coefficients/weights，显式 final fold 才绑定最终模型；
- [x] 保存可回读 canonical artifact bytes、dated current/forward outputs、PIT fact/manifest、benchmark/FMP/cost/split/code/dependency/parameter identity；
- [x] 实现 walk-forward、purge/embargo、available-at/revision 防泄漏门禁和 append-only retirement hash chain；
- [x] 实现 exact OOS prediction 全覆盖的 regime 分段复算、trial/Promotion artifact 绑定和 monitoring 读取合同；真实 Regime/OOS/Promotion owner evidence 仍待形成；
- [x] exact output 读取只接受 artifact/output ID+hash 和统一 PIT cutoff；PromotionDecision 未 approved、已过期、退役或监控不完整时稳定阻断，成功投影仍不发布 current。

2026-08-05 R3 runner 续批：上述无数据可开发的软件合同已实现。Input row 逐项绑定 Data Center fact version/content hash/effective/available time，并精确核对 manifest selected versions；TemporalSplitSpec 与每个 inner/outer window 和 row identity 一致。Artifact 原始 bytes/media/length/producer、逐 fold selection、baseline/FMP、dated outputs 和 retirement owner attestation 均可回读复算，`macro_factor.0002_reproducible_run_ledger` 只建立空 append-only schema，不 seed、不回填 0001。所有结果仍固定 `research_only / must_not_use_for_decision / must_not_execute`；真实 vintage、代理价格、benchmark/cost、OOS trial 和 Research exact Promotion binding 尚未形成，因此 R3 保持 `blocked`。

2026-08-07 R3 governed read 续批：新增 Domain/Application exact contract，从 canonical external artifact bytes 重放完整 OOS prediction identity，以 Regime owner 的 actual/assignment 双时间证据现场重算分段 MSE/MAE/R²；Research trial family 必须在最早 outer-fold selection 前预注册，并逐项绑定 artifact/source/external/PIT/dataset/split/plan/regime hash，family 与 Promotion authorization 均使用确定性内容哈希。读取命令只收 exact artifact/output identity 与 `as_of`，依次动态重读 Regime report、trial、PromotionDecision、既有 append-only lifecycle 和 retirement-policy owner 的原始 monitoring facts；监控规则按阈值/连续窗口现场复算，缺项、篡改、到期、退役或触发失效规则均 fail closed，且不得自动退役。成功结果只是 production-facing 的 research read projection，固定 `publishes_current=false / decision_authorized=false / execution_authorized=false / must_not_use_for_decision / must_not_execute`。本批无 ORM/migration、无 concrete Regime/Research/monitoring provider、无 API/TUI/Celery/current/组合/执行接线；fixture 只证明软件合同，真实宏观 vintage、代理资产、Regime assignment、OOS trial、owner authorization 和 approved PromotionDecision 仍缺，因此 R3 继续 `blocked`。

### M4：R4 Portfolio canonical inputs

- [x] 实现 exposure/covariance/constraint 候选合同、PSD 检查、风险贡献恒等式和版本化成本预算；
- [x] 不可变资产收益协方差 evidence、PIT/source/estimation-window seal、PSD、condition number、rank、expected/missing denominator 与 missing-coverage policy；
- [x] 资产×宏观因子 exposure version、置信区间及 Macro Factor owner projection；
- [x] 成本、上下限、换手、流动性和人工限制统一版本；
- [x] 等权和资产风险平价基准可复算。

### M5：R4 研究和晋级

- [x] 风险贡献恒等式和数值容差；
- [x] 协方差异常 fail closed；
- [x] 比较等权、资产风险平价、宏观因子风险平价；
- [x] 报告 rolling beta、CI、R²、残差、稳定性、gross return、drawdown、turnover 和 cost；真实可交易性仍待 canonical input；
- 仅 approved 版本可进入组合预览，真实执行另立计划。

现有 R4 代码只评估 caller/provider 提供的候选并保持 `research_only / must_not_execute`；没有真实 exposure/covariance row，也没有 R3 approved version，因此 M4/M5 退出条件均未满足。

2026-08-05 交叉复核后，R8 优化输入必须完整绑定 R4 exposure、covariance、snapshot 和宏观风险预算；求解后的宏观风险贡献由 solver weights 重新计算并进入输出 seal，不接受调用方沿用旧权重预填的贡献。该收紧只防止证据错配，不代表 R4 已有真实 canonical inputs。

2026-08-05 完成度审计整改进一步将 R4 exposure/covariance 的 `valid_until` 边界收紧为到期时刻立即 stale，并让 candidate report hash 覆盖 input hash、资格状态、factor/residual/total variance、完整 contribution vector 及 blocker detail。

2026-08-06 rolling 续批完成 typed walk-forward/embargo、formation-time Regime PIT assignment、rolling exposure/Regime summary 与同窗三基准 OOS 比较。ID-only Application 必须从 authoritative provider 重读 exact R3 Promotion attestation；三候选共享全部 formation/OOS inputs，selection/validation、covariance estimation window、available-at、expiry 和 return knowledge cutoff 均 fail closed。服务端重算所有候选与路径数值，artifact factory 再把 exposure、Regime/method summary 逐值绑定回 source projection/window metrics。该批没有 ORM、R4 Promotion/lifecycle、组合预览或执行接线；真实 R3 approved artifact、canonical inputs、历史样本、conditioning/missing-coverage 与 append-only lifecycle 仍未形成，R4 保持 `blocked`。

2026-08-06 persistence/query 续批新增 Portfolio-owned append-only receipt/result ledger 与 schema-only `0007`。持久化入口只收 identity/provenance，通过 exact study/R3 provider 重读后由 server-clock Repository 写入；typed restore 会重新运行 R4 service/output integrity 并核对完整 subhash ledger。协方差 condition/rank/coverage denominator 与版本化阈值已进入 study/payload/hash；exact query 只按 record id/hash/as-of 返回 PIT-valid owner evidence。所有 bulk/direct mutation、错误 UoW/clock、raw tamper、非 canonical UTC 与并发冲突 fail closed。Research R4 policy/trial/decision、Promotion/retirement/rollback lifecycle、组合预览和下游 active consumption 仍未形成，R4 保持 `blocked`。

2026-08-06 Promotion Phase A 已完成 Research Domain/Application 软件合同：stable semantic scope 与 exact evidence seal 分离，Policy 必须在最早 selection 前预注册，Decision 在同一 atomic/UoW 内动态重读 exact policy/Portfolio/current-R3 并派生 gates/outcome/validity。Lifecycle 使用 scope-local stack，A→B→C 只能逐层 C→B→A；PROMOTE/ROLLBACK/active 重验当前 evidence，RETIRE 可按 decision-time 历史 PIT 清理失效 top。当前没有五表 append-only repository/migration、concrete owner provider/composition、组合预览或下游 active input，Phase A 测试不能替代真实 Promotion，R4 继续 `blocked`。

2026-08-06 Promotion Phase B 已完成五表 append-only persistence、schema-only `0004`、strict typed restore、server-clock policy registration、private UoW/insert claim、concrete repository/providers/composition 与持久 PIT replay。Portfolio 只通过 Application exact query 注入；decision/lifecycle receipt 与 child 同事务，first-miss race 只重放完整一致 winner，stream fork、异证据、raw tamper 和所有 ORM mutation shortcut fail closed。Phase A + codec `38 passed`、component `13 passed`、migration `4 passed`，Luna Max 最终复核 P0/P1 为 0。仍未接组合预览或下游 active consumer；真实 R3 Promotion、canonical input、owner authorization 与 OOS trial 缺失，R4 继续 `blocked`。

## 6. 明确非目标

- 本阶段不添加 sklearn/statsmodels/cvxpy 依赖；
- 不提供空壳 Lasso、随机权重、固定 beta 或示例优化结果；
- 不在 Domain 硬编码目标指标、代理资产、窗口、阈值或成本；
- 不将当前成分、当前修订宏观值回填历史；
- 不新增 Classic Web 页面、raw MCP tool 或可激活模型的写 API；
- 不将 volatility-inverse allocation 命名为 macro factor risk parity。

## 7. 验证与进入下一阶段的证据

本阶段验证命令：

```bash
pytest tests/unit/research/test_capability_readiness.py -q
ruff check apps/research/domain/capability_readiness.py apps/research/application/capability_readiness.py tests/unit/research/test_capability_readiness.py
python scripts/check_mypy_regression.py apps/research/domain/capability_readiness.py apps/research/application/capability_readiness.py
python scripts/check_architecture_layers.py
```

进入 M1/M2 前，实施 PR 必须附：

- 真实 dataset key、来源、频率、覆盖窗口、available/revision 语义；
- PIT writer、manifest 和回放测试；
- 连续合约与发布日历版本；
- benchmark/cost/split policy 版本；
- PostgreSQL 验证和缺失/修订/篡改负向证据。

进入 M4/M5 前还必须附：

- R3 approved PromotionDecision；
- factor version/hash 与可复算 trial；
- Portfolio covariance/exposure/constraint snapshot；
- 等权和资产风险平价基准；
- 协方差异常、成本冲击、约束不可行的 fail-closed 测试。
