# R6 简单基准不足证据与高级状态模型分阶段计划（2026-08-05）

> 状态：S0/S2、qualification evidence/persistence/lifecycle 与 monitoring Phase A 纯合同已实现；真实 S1、monitoring 持久化/owner 接线、真实监控事实和 approved Promotion 仍 `blocked`
> 来源：[策略研究能力后续开发备忘](../business/strategy-research-capability-roadmap-memo-2026-08-04.md) R6
> 边界：不在仓库内训练 Markov/HMM/贝叶斯/政策反应模型；只验证外部 artifact、状态概率/转移/OOS/政策目标证据，且永不替换现有 Regime/Pulse。

## 1. 当前决策

现有 PMI/CPI/Regime/Pulse 是 R6 必须比较的简单基准。只有真实 PIT 样本证明该基准在预先批准的指标上存在明确不足，才允许提出高级状态模型研究计划。

当前没有可引用的基准误差、决策损失或样本外转移证据，因此 `simple_baseline_shortfall_proven` 仍为 `missing`。新增 evaluator 只是建立取证方法，不将“可计算”误报为“已证明”。

## 2. S0 已完成

代码入口：

- Domain：`apps/research/domain/state_model_baseline.py`
- Application：`apps/research/application/state_model_baseline.py`
- Tests：`tests/unit/research/test_state_model_baseline.py`

已实现：

1. `BaselineEvaluationSpecification` 固定 baseline/version、PIT manifest、样本窗口、最小样本量、指标、单位、方向和阈值。
2. 所有指标与阈值由 Research 治理版本注入，代码没有默认误差阈值。
3. `BaselineEvaluationEvidence` 保存不可变 evaluation ID、窗口、样本量、metrics、evidence refs、`evaluated_at` 和 `valid_until`。
4. 缺指标、单位漂移、样本不足、证据过期、非 verified 状态或 identity/PIT manifest 不一致均 fail closed。
5. 所有 criterion 都证明 shortfall 后才返回 `PROVEN`；指标未跨阈值返回 `NOT_PROVEN`，不得为了使用高级模型而改写结论。

## 3. S1 真实基准评估

Owner：`research` + `regime` + `data_center`。

启动条件：

- Data Center 提供冻结的 Regime/Pulse 输入 PIT manifest；
- Research 批准 evaluation specification、窗口、样本量和 metric definitions；
- 指标至少覆盖转折漏报/误报、状态持续期误差和可归因的决策损失；
- observation time、release time 和 revision time 不被当前请求时间覆盖。

交付：

- 运行简单基准并冻结每次 evaluation evidence；
- 保存误差案例、状态转移和决策影响引用；
- 由 `EvaluateSimpleBaselineShortfallUseCase` 输出 `PROVEN / NOT_PROVEN / BLOCKED`；
- 只有 `PROVEN` 才允许新建高级模型 Experiment family。

## 4. S2 高级模型研究

S1 通过后另建计划与分支：

- 预注册 Markov/HMM 或政策反应函数假设、候选 family、split 和 embargo；
- 明确稳定 label alignment、经济命名和 label-switching 处理；
- 与简单基准比较样本外转移准确率、持续期、决策损失、复杂度和稳定性；
- 模型状态只能标记 exploratory，经过 Research PromotionDecision 后才能成为候选输入；
- 未证明增量价值时保留简单规则，不以模型复杂度作为晋级理由。

2026-08-05 开发先行状态：已实现 `advanced_state_model` Domain/Application 证据门禁。它要求 S0 report 为 `PROVEN`、PIT manifest 完整且未过期、input version/hash 一致、经济标签稳定无 drift、概率/转移行归一、持续期样本充足、OOS 指标超过注入阈值并同时优于简单基准、policy target 与 PIT 输入匹配、外部 artifact 有独立 hash attestation。任一条件失败返回稳定 blocker；通过也仅是 `research_only`，并强制 `must_not_replace_regime=true`。本地 fixture 不构成 S1 真实证据或模型晋级。

交叉复核整改后，S0 report 额外封存 baseline key/version、PIT manifest、窗口、原始指标、证据引用/时间/状态及 canonical SHA-256；高级候选不得自报基准指标，只能绑定 report hash 并读取该报告的真实指标。因而“比较器可用”仍不能替代 S1 的真实不足证据。

2026-08-07 qualification 续批进一步实现：content-addressed comparative study 与 OOS 前预注册 family/split/embargo；transition accuracy、log loss、calibration、duration、decision loss、complexity、label stability 七指标同窗比较；政策反应系数的 target/lag/sign/CI/p-value/magnitude 与回归诊断。Application 命令只接受 study ID/time，并精确重读 candidate、baseline、S2 attestation、derived metric bundle、preregistration 和 policy。S2 attestation 必须用完整 PIT manifest、独立 artifact attestation 与 threshold payload 重放原 gate，不能包装裸 `ACCEPTED`；成功也只表示可送人工 Promotion review，不生成 decision 或替换 Regime。真实 S1/PIT/OOS 证据、持久化、monitoring/retirement/Promotion 仍未完成。

2026-08-07 qualification persistence/lifecycle 续批：新增 schema-only `research.0008` assessment、lifecycle authorization、lifecycle event 三本 append-only ledger；ID-only exact PIT 注册/读取/审计分页与 PROMOTE/RETIRE 终态生命周期均在 shared-UoW 内动态重读 assessment 和 owner authorization。该能力仍固定 `research_only`，不替换 Regime、不产生决策或执行；新增 persistence/lifecycle 回归 `14 passed`。真实 S1/PIT/OOS、stable label、owner authorization、monitoring 原始事实和 approved Promotion 仍缺，因此 R6 继续 `blocked`。

2026-08-09 monitoring Phase A：新增纯 Domain/Application 监控合同。版本化 policy 必须显式注入 transition accuracy、log loss、calibration error、duration MAE、decision loss、label stability 及政策反应 adjusted R²、残差自相关、异方差、参数稳定性和 condition number 的全部单位、方向、阈值与连续 breach 次数；不存在代码默认。11 类 raw metric 按数学语义拒绝越界值（比例/p-value `[0,1]`，loss/error/MAE 非负，adjusted R² 不得大于 1，condition number 不得小于 1）。Policy 另精确绑定 owner-recorded period calendar manifest 的 owner/ID/version/content hash；manifest 封存全部 canonical start/end/period ID 成员并现场重算 seal。Raw observation 封存 `period_start/period_end`，要求 `start < end` 且 `observed_at` 落在半开窗口内；评估除拒绝重复/重叠窗口外，还要求每个窗口逐值命中 exact manifest member，因此自行派生两个相邻 1µs 窗口也会 blocked。Application 命令只接受 qualification ref、policy ID/version、expected policy hash 与 as-of，通过 Protocol 精确重读 active qualification、policy、period calendar 和 raw facts 后现场复算；calendar 缺失、同 ID/version 替换、未来记录或私有篡改均 fail closed。Domain 重算全部 content seal，并把 policy 约束的 source owner、PIT manifest ID/hash、period calendar 与 evidence namespace 逐项绑定；metrics 作为语义集合按 metric key canonical 封存。输出仅为 `healthy / breached / retirement_review_required / blocked`，连续 breach 或 label drift 只能请求人工退役复核，固定禁止自动 RETIRE、Regime replacement、current、decision 和 execution。Phase A targeted unit 回归 `46 passed`。

2026-08-09 monitoring Phase B：Research `0011` 已建立 observation/assessment 两张 schema-only append-only ledger，无 seed/backfill。ID-only registration 在同一 UoW 精确重读 active qualification、policy、完整连续 period calendar 与 raw facts并现场复算；owner `recorded_at` 与 server-clock `ledger_recorded_at` 分离，后者进入 row-header seal与 PIT/cursor replay。Strict codec、first-winner/fork/rollback、future cutoff、raw header/clock tamper及常规 ORM/Collector mutation均 fail closed；Domain/Application/codec/repository 合并 targeted `81 passed`，最终 malformed owner hash 补强后相关组合 `73 passed`，独立复核 P0/P1/P2 为 0。

2026-08-09 activation Phase A：新增与 qualification lifecycle 分离的纯 Domain/Application activation stream。ACTIVATE 必须动态重读 exact qualification、健康且新鲜的 monitoring、approved Promotion 和 owner authorization；Authorization 封存 exact previous-event hash，签发/记录时点严格晚于当前 head。Existing winner 只有在完整 canonical prefix 重放、前驱和授权全部一致时才可幂等返回；RETIRE 清空当前栈，ROLLBACK 只能回到 `stack[-2]`。构造后 UoW identity 漂移、orphan/fork/future winner、projection 自证和 owner 异常均 fail closed。该阶段无 ORM/migration/composition/consumer，固定禁止替换 Regime、发布 current、产生决策或执行。

下一项无数据工作是 activation Phase B append-only persistence、strict codec、server-clock/shared-UoW、exact PIT/audit、canonical owner adapters，以及数据库权限/签名纵深。Phase B 还应显式验证全 stream 事件时钟单调并补可离线复验的 projection seal；在真实 monitoring facts、owner authorization 与 approved Promotion 缺失时不得接入 consumer。

## 5. 非目标

- 不从当前 Regime 分数反推“模型概率”；
- 不用全量修订后数据回填历史状态；
- 不在 Domain 中硬编码状态数、阈值或经济标签；
- 不用单个最佳窗口替代预注册 experiment family；
- 不新增 Classic 页面、raw MCP tool 或生产状态模型任务。

## 6. 回归与回滚

```powershell
pytest tests/unit/research/test_state_model_baseline.py -q
pytest tests/unit/research/test_advanced_state_model.py tests/unit/research/test_advanced_state_model_edges.py tests/component/research/test_advanced_state_model.py -q
python scripts/check_mypy_regression.py apps/research/domain/state_model_baseline.py apps/research/application/state_model_baseline.py
python scripts/verify_architecture.py
```

Monitoring Phase A 仅新增纯 Domain/Application 合约和测试，无 ORM、迁移、训练任务或运行时接线。既有 qualification persistence/lifecycle 仍只保存内部研究档案；本批回滚不会修改现有 Regime、Policy、Pulse 或决策结果。
