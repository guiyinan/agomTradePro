# R6 简单基准不足证据与高级状态模型分阶段计划（2026-08-05）

> 状态：S0 证据评估合约已实现；高级状态模型仍 `blocked`
> 来源：[策略研究能力后续开发备忘](../business/strategy-research-capability-roadmap-memo-2026-08-04.md) R6
> 边界：本阶段不实现 Markov/HMM、政策反应函数或状态概率，不替换现有 Regime/Pulse。

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

## 5. 非目标

- 不从当前 Regime 分数反推“模型概率”；
- 不用全量修订后数据回填历史状态；
- 不在 Domain 中硬编码状态数、阈值或经济标签；
- 不用单个最佳窗口替代预注册 experiment family；
- 不新增 Classic 页面、raw MCP tool 或生产状态模型任务。

## 6. 回归与回滚

```powershell
pytest tests/unit/research/test_state_model_baseline.py -q
python scripts/check_mypy_regression.py apps/research/domain/state_model_baseline.py apps/research/application/state_model_baseline.py
python scripts/verify_architecture.py
```

S0 仅新增纯 Domain/Application 合约和测试，无 ORM、迁移或运行时接线。回滚不会修改现有 Regime、Policy、Pulse 或决策结果。
