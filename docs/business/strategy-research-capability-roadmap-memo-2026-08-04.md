# 策略研究能力后续开发备忘（2026-08-04）

> 状态：长期能力备忘，不是当前实施承诺
> 复核触发：情景治理 Quick Wins 完成、相关数据达到 Publication/PIT 门禁、或投资主任务发生变化时
> 适用版本：0.8.0 之后
> 来源边界：本备忘依据用户对四份策略会材料的摘要和当前仓库能力盘点编写，未读取原始 PDF。
> 关联实施计划：[情景治理与策略研究 Quick Wins 整改计划](../plans/scenario-governance-and-strategy-method-quick-wins-plan-2026-08-04.md)
> 2026-08-05 启动门复核：R1—R8 均为 `blocked`；已交付统一 fail-closed readiness 合约和分阶段计划，但未启动任何模型、数据回填或用户任务。
> 2026-08-05 开发续批：已实现 R1/R2 治理定义与 PIT 数据入口、R7 情景预测账本绑定、R8 research-only 输入合约及运行时 owner 取证；这些基础纵切不替代真实数据、样本外验证或 PromotionDecision，能力总门禁保持不变。
> 2026-08-05 无数据先行批次：已实现 R1 三情景经营预测与误差台账、R5 research-only 固收研究内核、R6 简单基准不足取证器，以及 R8 canonical portfolio snapshot/执行反馈台账；真实 Publication、外部对账、样本历史和晋级版本仍缺失，因此 R1—R8 总门禁不变。
> 2026-08-05 研究基础收口批次：进一步实现 R1 行业模板安全计算、R2 市场结构证据、R3 独立宏观因子研究 App、R4 宏观风险候选验证、R6 外部高级状态证据门禁、R7 校准/类比/路径研究和 R8 受约束确定性研究优化。所有结果保持 research-only；fixture、模型文件或迁移存在均不作为生产 ready 证据。
> 2026-08-05 Luna Max 交叉复核整改：三组独立只读复核未发现 P0，并提出的 13 项 P1 已全部关闭；整改覆盖 PIT 事实身份、双时间查询、coverage、固收输入封存、简单基准绑定、情景样本/路径身份、Portfolio snapshot owner 证据及优化风险贡献重算。该整改提升证据不可篡改性，不改变 R1—R8 的 `blocked` 结论。
> 2026-08-05 完整路线图审计：上述 13 项仅代表上一轮限定清单关闭，不代表 R1—R8 完成。新一轮按目标/最低验收逐项审计未发现 P0，但确认仍有多项无数据可开发 P1；本批新增 R5 组合风险预算/压力测试并加固 R4 report seal，完整队列见[完成度审计](../plans/strategy-research-capability-completion-audit-2026-08-05.md)。
> 2026-08-05 R1/R2 无数据续批：R1 已完成 Sector→Equity 持久证据桥接、通用 driver PIT 绑定、cash-flow/六阶段/template-run seal 及 legacy dual-read；R2 已完成版本化 expected-period calendar、series×period 完整 coverage 和整期全缺 fail-closed。该批当时尚未完成 R1 baseline/Promotion exact binding，已由 2026-08-06 续批关闭软件 P1；R2 真实 taxonomy/calendar/两个市场周期证据仍未完成，能力门禁保持 `blocked`。
> 2026-08-05 R7 reminder 续批：已完成 Research-owned append-only reminder ledger/internal outbox，修复 invalidation reminder 确定性时间锚，精确绑定 forecast/revision/policy 与逐期 conditional/transition evidence，并实现 due/ack/escalate/expiry。该流程只允许内部人工 pull/ACK，禁止外部发送、自动审批和执行；真实 outcome 历史、获批 sample policy、结果持久化与晋级仍未完成，R7 保持 `blocked`。
> 2026-08-05 R3 runner 续批：已完成 exact-PIT historical-mean/FMP、nested temporal-CV runner、可回读 canonical artifact bytes、dated current/forward ledger 与 append-only retirement lifecycle。每 fold 独立 selection，outer OOS 不参与选择，late revision/available-at/split/purge/embargo 均 fail closed。真实宏观 vintage、代理价格、benchmark/cost、regime/OOS trial 与 Research exact Promotion binding 尚未形成，R3 仍保持 `blocked`。
> 2026-08-06 R8 治理续批：已完成 13 类 typed 数值输入、当前配置基准、可投资 universe、A 股/基金/债券/商品约束、逐期 path drawdown、四候选可复算比较，以及 append-only result/Promotion/retirement/rollback lifecycle。输入组装和生命周期均从 canonical provider 精确回读，完整证据图使用 Decimal/UTC canonical hash；无法在 weight 层证明数量约束时稳定阻断。真实 R3/R4/R5 Promotion、Portfolio snapshot、broker reconciliation、成本/容量和市场规则校准仍未形成，因此该能力仅为 research-only 软件切片，R8 保持 `blocked`。
> 2026-08-06 R1 精确基线与晋级续批：已完成强制 owner approval 的 baseline spec 合同、forecast/baseline/actual manifest 精确封存、完整 period×metric 配对评估、预注册 trial，以及 Research-owned exact PromotionDecision、retirement/rollback 生命周期。Research 在运行时通过 Equity Application port 重读完整 artifact/template-run/sensitivity/trial seal，调用方不能用 decision id 或自报 hash 解锁；五张新表均为 append-only、schema-only、零 seed。真实 owner approval、QW-7 反馈、连续经营事实、财务/估值 Publication 和真实 trial 仍未形成，且未接 Valuation 消费，因此 R1 保持 `blocked`。
> 2026-08-06 R4 rolling 研究续批：已完成 typed walk-forward/embargo、formation-time Regime PIT assignment、rolling beta/CI/R²/残差/稳定性汇总，以及等权、资产风险平价、宏观因子风险平价三方法同窗 OOS 比较。Application 只接受 study identity，并通过 authoritative provider 重读 exact R3 Promotion attestation；协方差、OOS path、source projection、派生 summary 和完整 artifact 均逐值复算、全字段 seal，缺证据或时间穿越稳定 blocked。该批未新增 ORM、Promotion lifecycle、current/组合预览或执行接线；真实 R3 晋级、资产/因子输入和历史样本仍缺失，因此 R4 保持 `blocked`。
> 2026-08-06 R4 持久证据续批：已完成 Portfolio-owned append-only input receipt/result ledger、schema-only `0007` migration、canonical typed codec、factory replay、server-clock/UoW 写入保护与 exact PIT Application query。协方差 evidence 进一步封存 condition number、rank、expected/missing observation denominator 和 missing-value policy，并由版本化 condition/coverage 阈值稳定阻断；所有 bulk/direct mutation、caller self-attestation、非 canonical UTC payload、并发冲突和 raw tamper 均 fail closed。Research Promotion/retirement/rollback lifecycle 仍未实现，R4 继续保持 `blocked`。

本轮执行索引：

- [R1/R2 启动门整改计划](../plans/strategy-research-r1-r2-readiness-plan-2026-08-05.md)
- [R3/R4 启动门禁及分阶段实施计划](../plans/macro-factor-r3-r4-readiness-and-staged-delivery-2026-08-05.md)
- [R5—R8 启动门禁与分阶段实施计划](../plans/strategy-research-r5-r8-readiness-and-staged-delivery-2026-08-05.md)
- [R6 简单基准不足与状态模型分阶段计划](../plans/r6-simple-baseline-shortfall-and-state-model-staged-delivery-2026-08-05.md)
- [R1—R8 执行状态与复核入口](../plans/strategy-research-capability-roadmap-execution-2026-08-05.md)
- [R1—R8 完成度审计与剩余开发队列](../plans/strategy-research-capability-completion-audit-2026-08-05.md)

`blocked` 表示备忘定义的前置证据尚未齐备，不表示通过创建空模型、默认参数或演示页面即可解除。每项能力只有在 canonical owner 提供带时间、可追溯引用且完整的 verified evidence 后，才允许另建独立实施计划和分支。

## 1. 备忘目的

当前实施计划优先处理硬编码情景、版本治理、AI MCP 受控修改，以及少量能复用现有能力的 Quick Wins。本备忘单独保存开发成本更高、数据依赖更重或需要严格研究验证的能力，避免：

- 在同一批次同时扩张情景、量化、固收、公司研究和部署边界；
- 因已有“因子”“风险平价”“债券”等名称而误判能力已经完成；
- 为了快速展示而把主观映射、代理数据或默认阈值重新硬编码；
- 让探索性模型绕过 PIT、研究晋级、数据新鲜度和人工确认。

本备忘不是无限期 backlog。每项能力都给出启动条件、建议 owner 和最低验收标准，条件满足后应拆成独立 plan、分支和回归包。

## 2. 当前系统定位

AgomTradePro 当前主轴是：

```text
宏观/Regime/Policy/Pulse
        ↓
通用标的评分与 Qlib Alpha
        ↓
规则化资产配置与风险闸门
        ↓
人工确认、模拟执行、回测与归因
```

当前相对强项：

- 数据来源、freshness、failover 和 decision block；
- Regime/Policy/Pulse 状态与规则化配置；
- 通用财务、估值、因子和 Qlib Alpha；
- 信号证伪、PIT 回测、研究晋级；
- Beta/Risk Gate、执行审批和 Audit 归因。

当前研究深度缺口：

- 公司经营变量到盈利预测的因果链；
- 多类投资者资金流和市场结构解释；
- 正式的高频宏观因子复制、筛选与检验；
- 宏观因子风险贡献与组合优化；
- 久期、曲线、信用和流动性相对价值；
- 前瞻情景概率校准与历史类比验证。

## 3. 能力路线总览

| 编号 | 长期能力 | 主要参考方法 | 价值 | 成本/风险 | 建议顺序 |
|---|---|---|---|---|---|
| R1 | 行业经营驱动与盈利预测平台 | 大消费 | 高 | 高数据维护、中模型风险 | 第一梯队 |
| R2 | 市场结构与投资者资金流全景 | 权益市场 | 高 | 数据授权和口径风险 | 第一梯队 |
| R3 | 高频宏观因子复制与 nowcast | 高频宏观因子 | 很高 | 高统计、数据和研究风险 | 第二梯队 |
| R4 | 宏观敞口回归与宏观因子风险平价 | 高频宏观因子 | 很高 | 高模型和组合风险 | R3 之后 |
| R5 | 固定收益相对价值与久期引擎 | 宏观固收 | 高 | 高数据和资产建模成本 | 第二梯队 |
| R6 | 高级状态模型与政策反应函数 | 高频宏观/宏观固收 | 中—高 | 易过拟合、解释成本高 | 第三梯队 |
| R7 | 情景概率校准、历史类比与路径模拟 | 权益市场/宏观固收 | 高 | 依赖长期情景运行证据 | Quick Wins 后 |
| R8 | 多资产优化与真实执行约束统一 | 四类方法的组合层 | 很高 | 高耦合、需真实交易证据 | R4/R5 后 |

建议顺序不是按模型“高级程度”排序，而是按数据可用性、决策收益和可验证性排序。

## 4. R1：行业经营驱动与盈利预测平台

### 4.1 目标

从通用财务评分升级为可解释的经营模型：

```text
经营驱动 → 收入 → 成本/毛利率 → 费用 → 利润 → 现金流 → 估值
```

覆盖模板候选：

- 餐饮：门店数量、同店销售、客单价、翻台率；
- 零售/零食：门店数、单店收入、份额、毛利率、净利率；
- 啤酒：销量、吨价、产品结构；
- 教育：培训人数、学费、续费率；
- 服装：品牌、渠道、门店、单店收入、毛利率；
- 后续行业使用独立模板，不把所有公司塞进同一公式。

### 4.2 为什么后置

- 自动化需要公司公告、行业高频、价格、门店、渠道和成本数据；
- 不同行业的数据频率和业务定义差异很大；
- 盈利预测必须区分事实、研究员假设和模型推断；
- 错误的自动预测比缺少预测更危险。

### 4.3 建议边界

- `equity` 拥有公司经营模型和预测结果；
- `sector` 拥有行业模板与行业比较语义；
- `data_center` 拥有原始/标准化经营事实和来源证据；
- `valuation` 消费已批准预测，不自行生成经营假设；
- `research` 管理模型验证和晋级。

### 4.4 启动条件

1. Quick Win 经营驱动工作表已有真实使用反馈。
2. 至少一个行业具备连续、可审计的经营数据源。
3. 财务和估值事实通过 Publication/PIT 门禁。
4. 明确预测 horizon、误差指标和基准预测。

### 4.5 最低验收

- 能还原 base/bull/bear 的每个假设；
- 能按季度记录预测与实际偏差；
- 输出收入、利润、利润率和估值敏感性；
- 不能用未来公告或最新修订数据回填历史预测；
- 自动预测必须经过 research PromotionDecision 才能进入正式估值。

## 5. R2：市场结构与投资者资金流全景

### 5.1 目标

从现有成交额、融资余额、ETF 流和主力/散户流，扩展到：

- 产业资本；
- 外资；
- 居民资金；
- 融资盘；
- 险资；
- 公募/ETF；
- 回购、增减持和解禁；
- AI/非 AI、新旧经济、内外需等可版本化资产组。

### 5.2 为什么后置

- 数据口径、可得性和授权差异大；
- 资金流代理容易被误读为真实投资者行为；
- 资产组成员随时间变化，必须支持 PIT membership；
- 需要把“资金量”“持仓变化”“交易净流入”严格区分。

### 5.3 建议边界

- `data_center`：资金流事实、主体分类、资产组 membership 和 Publication；
- `sector`/`asset_analysis`：结构比较；
- `pulse`：只消费已发布的聚合状态，不保存第二份资金流真源；
- `audit`：检验资金流信号的实际解释力。

### 5.4 启动条件与验收

- 每类资金流有清晰定义、单位、频率、来源和修订方式；
- 至少覆盖两个市场周期并具有 PIT membership；
- 代理指标必须显式标记 proxy；
- 能区分总量变化、加速度、历史分位和跨主体差异；
- 无可靠数据时不输出“增量/存量/减量博弈”的确定结论。

## 6. R3：高频宏观因子复制与 Nowcast

### 6.1 目标

建立真正的宏观因子研究链，而不是复用股票横截面 FactorEngine：

1. 定义增长、通胀、利率、信用、流动性和汇率目标变量；
2. 建立可交易代理资产与高频数据 universe；
3. 构建 Factor Mimicking Portfolio；
4. 使用 Lasso + 交叉验证筛选变量；
5. 报告显著性、调整后 R²、BIC、稳定性和经济含义；
6. 形成“当前状态”和“未来若干月预期”两组日频因子；
7. 进行样本外、滚动和不同市场阶段验证。

### 6.2 为什么后置

- 需要稳定的历史 vintage、期货连续合约和宏观发布日期；
- Lasso 选择不等于经济有效，需要研究纪律和人工复核；
- 代理资产和目标变量之间存在结构变化；
- 无 PIT 数据会产生严重后视偏差。

### 6.3 建议模块

该能力具有独立业务实体、研究规则和数据结果，实施前应评估新增 `macro_factor` App，而不是继续扩大股票横截面的 `factor`。若不新增 App，也必须通过明确 Protocol 隔离两种因子语义。

### 6.4 启动条件

1. Data Center 的目标宏观序列、发布日期、修订和代理资产价格具备 PIT manifest。
2. Research Experiment Registry、multiple-test family 和 PromotionDecision 可用。
3. 明确训练、验证、样本外、walk-forward 和 embargo。
4. 有稳定 benchmark 和交易成本假设。

### 6.5 最低验收

- 每个因子保存目标定义、候选资产、入选资产、权重和版本；
- 报告样本内外 R²、IC、稳定性、换手和成本；
- Lasso 超参数通过嵌套或严格交叉验证选择；
- 结果能被相同 PIT manifest、代码版本和参数复算；
- 失效时有明确退役机制，不把旧模型继续发布为 current。

## 7. R4：宏观敞口回归与宏观因子风险平价

### 7.1 目标

- 估计资产、行业和组合对宏观因子的暴露；
- 报告 beta、置信区间、R²、残差和稳定性；
- 将资产风险分解为增长、通胀、利率、信用、流动性等宏观来源；
- 优化各宏观风险来源的贡献，而不是简单做资产等权或波动率倒数。

### 7.2 与当前能力的区别

当前 Rotation 的 `risk_parity` 是资产历史波动率倒数加权。未来实现不得沿用同名输出冒充宏观因子风险平价，应提供独立 `methodology`、`factor_covariance_version` 和风险贡献明细。

### 7.3 前置条件

- R3 宏观因子通过样本外验证；
- Portfolio 有规范的资产暴露和协方差输入；
- 交易成本、权重上下限、换手和流动性约束可用；
- 至少存在一个资产风险平价和等权基准。

### 7.4 最低验收

- 风险贡献之和与组合风险一致；
- 协方差矩阵异常时 fail closed 或进入明确降级；
- 报告滚动暴露和 regime 稳定性；
- 回测比较等权、资产风险平价、宏观因子风险平价；
- 不使用未来修订宏观数据。

## 8. R5：固定收益相对价值与久期引擎

### 8.1 目标

把“债券”从资产大类标签升级为可计算的策略能力：

- 国债/政策性金融债曲线；
- 久期、修正久期和凸性；
- carry 与 roll-down；
- 2Y—10Y、10Y—OMO、2Y—DR001 等利差；
- 信用利差、等级迁移和流动性溢价；
- 曲线陡峭/扁平交易；
- 期限、信用和流动性风险预算；
- 组合级利率与信用压力测试。

### 8.2 为什么后置

- 当前系统主要持有债券基金/ETF 和大类权重，不具备完整券级现金流；
- 收益率曲线、政策利率、信用估值和流动性数据需统一口径；
- 债券交易的计息、结算和流动性约束不同于股票；
- 简单文字“缩短久期”不足以支撑真实调整。

### 8.3 建议模块与边界

若进入券级研究，应新增独立 `fixed_income` App：

- Domain：Bond、CashFlow、Curve、Spread、Duration、RelativeValueSignal；
- Application：曲线构建、久期预算、相对价值和压力测试；
- Infrastructure：债券主数据、估值、成交和曲线适配；
- Interface：研究和组合预览。

Data Center 仍是事实真源，Strategy/Portfolio 只消费目标暴露和订单草案。

### 8.4 启动条件与验收

- 至少两条可靠曲线和一套信用估值数据通过 Publication；
- 债券主数据、现金流和交易日历完整；
- 久期/凸性与第三方或手工样本对账；
- 相对价值信号有历史分位、成本和流动性约束；
- 第一阶段只输出研究建议，真实执行另立计划。

## 9. R6：高级状态模型与政策反应函数

候选研究：

- Markov 状态切换；
- Hidden Markov Model；
- 政策反应函数；
- 动态贝叶斯状态概率；
- Regime 转移矩阵和持续期模型。

启动前必须证明简单 PMI/CPI/Pulse 规则的明确不足，并建立简单基准。模型状态需要经济解释、稳定标签和样本外转移准确率；不得为了“高级”替换可解释规则。

## 10. R7：情景概率校准、历史类比与路径模拟

在 Quick Wins 积累足够情景运行记录后，进一步建设：

- 主观概率与模型概率分开保存；
- Brier Score、校准曲线和分箱命中率；
- 历史相似阶段检索；
- 路径依赖和多期冲击；
- 情景之间的转移与条件概率；
- 情景假设被证伪后的自动复核提醒。

启动条件：至少积累一段完整预测—复核—兑现记录，且 Forecast Ledger 能按情景版本评分。没有真实结果记录前，不应训练所谓“情景概率模型”。

## 11. R8：多资产优化与真实执行约束统一

长期目标是把以下输入纳入同一组合构建问题：

- 预期收益或赔率；
- 宏观与资产风险暴露；
- 情景损失；
- 最大回撤和风险预算；
- 交易成本、换手、流动性和持仓上下限；
- A 股、基金、债券和商品的交易约束；
- 人工限制和账户资金需求。

该能力必须依赖 Portfolio canonical snapshot、Risk Center、R3/R4/R5 的可靠输入和真实执行反馈。不得先造一个无真实约束的优化器，再让执行层修补不可交易结果。

## 12. 全局研究纪律

所有长期能力共同遵守：

1. 数据、规则、模型解释、个人约束和人工判断分层。
2. 外部事实只通过 Data Center；current 决策只消费 Published 数据。
3. 回测和模型晋级必须引用 PIT manifest。
4. 探索结果与生产结果分开，缺少证据时标记 exploratory。
5. 不在 Domain 中硬编码指标目录、资产名单、阈值和情景。
6. 不把相关性包装成因果关系。
7. 不把规则分数包装成概率。
8. AI 可以提出假设、生成反方观点和创建草稿，不能绕过权限、确认和晋级门禁。
9. 每个模型必须有 benchmark、失效条件、监控、退役和回滚路径。
10. 新业务主任务默认进入 TUI，不扩张 Classic 页面。

## 13. 禁止的捷径

- 用当前成分股回填历史资产组；
- 用请求时间包装旧观测为“实时”；
- 用常量缺省值补齐缺失因子；
- 将波动率倒数称为宏观因子风险平价；
- 仅报告最佳参数而隐藏试验 family；
- 让 LLM 直接生成无法复算的盈利预测；
- 通过 Prompt 规定权限、确认或风险边界；
- 在 Application 或 Interface 直接读取其他 App ORM；
- 为快速接入新增一批 raw MCP tools；
- 数据不足时通过硬编码资产映射继续给出肯定结论。

## 14. 启动决策模板

任何一项从备忘进入实施计划前，必须回答：

| 问题 | 必需证据 |
|---|---|
| 当前用户主任务是什么？ | 一句话 primary task 和 outcome |
| 现有简单能力哪里不足？ | 真实案例、误差或决策缺口 |
| 数据是否可用？ | 来源、频率、PIT、Publication、覆盖率 |
| 最简单基准是什么？ | 规则/等权/历史均值等 |
| 如何避免后视偏差？ | as-of、manifest、样本切分 |
| 如何验证收益？ | 样本外指标、成本和风险 |
| 谁能激活？ | owner、RBAC、确认、PromotionDecision |
| 如何回滚？ | 配置、模型、读取和数据回滚点 |
| 哪些能力明确不做？ | 独立非目标清单 |

条件不完整时保持在备忘状态，不以“先做页面”代替业务与数据准备。

## 15. 复核节奏

- 情景治理 M1-M3 完成后：复核 R7 数据积累设计。
- Quick Wins M5A 完成后：根据真实使用决定 R1 或 R2 谁先启动。
- Data Center D0-D9 Publication/PIT 生产验收后：复核 R3、R5 数据前置。
- Macro Factor R3 样本外通过后：才允许启动 R4。
- 固收研究完成且有真实持仓需求后：再规划债券执行能力。
- 每次版本收口时更新本备忘状态，不复制动态模型数、数据行数或测试数。

## 16. 关联文档

- [情景治理与策略研究 Quick Wins 整改计划](../plans/scenario-governance-and-strategy-method-quick-wins-plan-2026-08-04.md)
- [人机协同决策分层设计](human-judgment-decision-layering.md)
- [集中风控中心](risk-center.md)
- [研究可信度与决策可复算体系整改计划](../plans/research-integrity-and-decision-reproducibility-2026-07-21.md)
- [Data Center 唯一真源架构重构计划](../plans/data-center-canonical-architecture-refactor-2026-08-02.md)
- [估值定价引擎](valuation-pricing-engine.md)
- [MCP 技术与开发标准](../mcp/mcp-technical-and-development-standard.md)
