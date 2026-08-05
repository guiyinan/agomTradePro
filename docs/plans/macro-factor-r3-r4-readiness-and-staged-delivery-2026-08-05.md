# R3/R4 宏观因子与宏观风险平价启动门禁及分阶段实施计划

> 状态：**Blocked / readiness-only**
> 建立日期：2026-08-05
> 适用分支：`dev/refactor-scenario-governance-quick-wins`
> 来源：[策略研究能力后续开发备忘](../business/strategy-research-capability-roadmap-memo-2026-08-04.md) R3、R4
> 本阶段目标：固定启动证据与阻断理由；不实现 Lasso、Nowcast、宏观敞口回归或宏观因子风险平价。

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

`research` 仅拥有“是否允许启动研究能力”的门禁和 PromotionDecision。它不拥有市场事实、宏观因子定义或组合优化结果。

### 3.2 R3 启动后新增 `macro_factor` App

R3 数据门禁通过后，新增完整四层 `apps/macro_factor/`，建议归属：

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

- 注册完整 `macro_factor` App 和模型版本实体；
- 先实现历史均值/简单回归/固定 universe 等基准；
- 固定目标定义、候选 universe、频率对齐、缺失值规则、成本和退役条件；
- 注册 Experiment 和完整 trial family；不得先挑最佳结果再补登记。

### M3：R3 模型研究与样本外晋级

- 嵌套或严格 CV 选择 Lasso 超参数；
- 保存入选资产、权重、adjusted R²/BIC/IC/稳定性/换手/成本；
- walk-forward、embargo、regime 分段和样本外验证；
- PromotionDecision 未 approved 时只能 exploratory，不能发布 current。

### M4：R4 Portfolio canonical inputs

- 不可变资产收益协方差快照及 PSD/条件数/缺失值证据；
- 资产×宏观因子 exposure version 与置信区间；
- 成本、上下限、换手、流动性和人工限制统一版本；
- 等权和资产风险平价基准可复算。

### M5：R4 研究和晋级

- 风险贡献恒等式和数值容差；
- 协方差异常 fail closed；
- 比较等权、资产风险平价、宏观因子风险平价；
- 报告滚动 beta、R²、残差、稳定性、成本和真实可交易性；
- 仅 approved 版本可进入组合预览，真实执行另立计划。

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
