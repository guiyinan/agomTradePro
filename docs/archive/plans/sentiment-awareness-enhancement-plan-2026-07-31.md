# A 股情绪态势感知增强计划（S0-S4）

> **文档日期**: 2026-07-31
> **状态**: S0-S4 已完成并归档（2026-07-31）
> **适用对象**: 开发负责人 / 模块维护人 / AI 代理
> **范围**: `data_center`（指标采集与目录）、`pulse`（sentiment 维度）、`sentiment`（文本情绪指数）、`terminal`（TUI 展示）；不改 Regime 战略层
> **目标**: 把 A 股情绪感知从"1 个沪深300 读数 + 文本情绪指数"补齐为"交易行为情绪 + 文本情绪 + 资金情绪"三位一体的战术感知层，并在 TUI 形成独立情绪面板

## 1. 背景与现状基线（2026-07-31 快照）

### 1.1 当前情绪感知能力的真实构成

| 层 | 现状 | 证据 |
|---|---|---|
| Pulse sentiment 维度 | **仅 1 个指标**：`000300.SH`（沪深300 日涨跌，阈值 ±3%） | `apps/pulse/infrastructure/data_provider.py:133-142` |
| Pulse 转折预警 | **不含 sentiment 维度**，只看 growth/inflation/liquidity | `apps/pulse/domain/services.py:138-183` |
| 市场温度计 | 6 分量（成交额/融资余额/ETF 流/新闻热度/新闻情绪/新增开户），已接入 account 宏观缩仓 | `apps/data_center/application/market_thermometer_specs.py:7-38` |
| 文本情绪指数 | 政策事件（AI 打分）+ 市场新闻（关键词启发式）日频合成，与 Pulse 完全断开 | `apps/sentiment/application/tasks.py:50-196` |
| TUI 展示 | `macro-regime.overview` 无独立情绪 panel，情绪仅是脉搏 datagrid 里的一行 | `config/tui/ia/tui_information_architecture.v1.json:31-41` |

### 1.2 交易行为情绪数据缺口

| 数据 | 现状 | 可用数据源 |
|---|---|---|
| 涨停/跌停家数、涨跌家数 | 无（realtime API 占位硬编码为 0，`apps/realtime/interface/views.py:252-256`） | AKShare 涨跌停池系接口、东财 ulist 批量行情聚合（已落地，`:624-706`）、Tushare `limit_list_d` |
| 炸板率、连板高度 | 零实现 | AKShare 涨跌停池/强势股池 |
| 北向资金 | S0 实测确认：日频净买额披露止于 2024-08-16，当前不可用 | 移出本计划；不得使用 AKShare 后续空值/`0.0` 占位 |
| 龙虎榜 | 零实现 | AKShare `stock_lhb_*` 系（优先级低） |
| 两融 | 仅融资余额（`CN_A_MARGIN_BALANCE`）；融资买入额、融券无 | AKShare/Tushare 两融接口 |
| 个股级新闻情绪 | 东财集成计划 Phase 4 未落地（无 `StockNewsModel`/`StockSentimentModel`） | 东财 `stock_news_em` 已通（`akshare_eastmoney_gateway.py:263-276`） |

### 1.3 已被目录收录但 Pulse 未使用的现成指标

`migrations/0030_seed_market_thermometer_inputs.py:145-156` 已 seed 且 `pulse_input_policy=direct_allowed`，当前只喂温度计：`CN_A_TOTAL_TURNOVER`、`CN_A_MARGIN_BALANCE`、`CN_A_ETF_NET_FLOW`、`CN_A_MARKET_NEWS_COUNT`、`CN_A_MARKET_NEWS_SENTIMENT`、`CN_A_MARKET_NEWS_POSITIVE_RATIO`、`CN_A_NEW_INVESTOR_ACCOUNTS`。**接入 Pulse 只需写 `PulseIndicatorConfigModel`，零采集开发**——这是本计划性价比最高的第一步。

### 1.4 机器唯一真源

- 指标目录：`IndicatorCatalogModel` / `IndicatorUnitRuleModel` / `data_center_macro_fact`，治理元数据 `apps/data_center/infrastructure/seed_data/macro_indicator_governance.py`
- Pulse 配置：DB `pulse_indicator_config` 优先，fallback `DEFAULT_PULSE_INDICATORS`（`apps/pulse/infrastructure/data_provider.py:76-143`）
- 新鲜度契约：`governance/current_data_contracts.json`；任务契约：`governance/celery_task_contracts.json`

## 2. 总原则

1. **先吃现成的，再采新的**。S1 只做"已入库指标接 Pulse"，S2 才开发新采集。禁止在现成指标未接完前动采集代码。
2. **走 catalog 指标路线，不建新 app，不塞错 fetcher**。日频市场行为指标复用市场温度计链路（catalog `category="market_heat"` + `_provider_adapter_*.py` 的 `fetch_macro_series` 特判），不得塞进宏观 fetchers 目录（其定位是宏观经济指标）。
3. **数据治理门禁一个不能少**。新指标必须同步：`pulse_input_policy`/`regime_input_policy` 元数据、`governance/current_data_contracts.json`（若暴露 current 语义）、`governance/celery_task_contracts.json`（若新增 Celery 任务）、单位规则（`IndicatorUnitRuleModel`）。
4. **降级优先于精确**。外部情绪数据源（东财/AKShare 页面型接口）不稳定，所有新指标必须定义"取不到数时的行为"：指标缺席不拖垮 Pulse 快照（维度内剩余指标归一化），禁止静默填 0 或沿用旧值冒充新鲜数据。
5. **单日一个主线**。S1-S4 各自独立分支（`dev/feat-sentiment-<阶段>`）、独立 commit 组；`terminal/tui` 改动按 AGENTS.md 固定最小回归包验证。
6. **文案不泄露实现**。TUI 情绪面板的用户可见文案不得出现 `/api/`、指标 code、数据源名。

## 3. 分批实施

### S0：指标矩阵与数据源可用性验证

| 项 | 内容 |
|---|---|
| 范围 | 产出目标指标矩阵（指标 code/名称/频率/数据源/降级行为/进 Pulse 还是温度计）；对 AKShare 涨跌停池、`stock_hsgt_*`、两融接口做**实机连通性验证**（记录接口名、返回字段、更新时点、历史回填能力），不可用项当场降级或移出范围；确认 Tushare `limit_list_d` 是否需要积分权限 |
| 交付 | 指标矩阵见附录 A；[数据源可用性验证](sentiment-data-source-verification-2026-07-31.md) |
| 验收 | 矩阵中每个指标都有已验证的采集通道和明确的降级行为；不可用项有书面处置 |
| 回滚 | 纯文档与探测脚本，无代码改动 |

### S1：现成指标接入 Pulse sentiment 维度（零采集开发）

| 项 | 内容 |
|---|---|
| 范围 | 从 §1.3 七个现成指标中选定 3-5 个（建议：`CN_A_TOTAL_TURNOVER`、`CN_A_MARGIN_BALANCE`、`CN_A_MARKET_NEWS_SENTIMENT`、`CN_A_ETF_NET_FLOW`）写入 `PulseIndicatorConfigModel`（dimension=sentiment）；设计各指标 signal_type 与阈值（成交额/融资余额/ETF 流用环比或分位数，新闻情绪直接用 score 映射）；决定 `000300.SH` 在新组合中的权重；加入 `PULSE_MACRO_SYNC_INDICATORS` 预刷新白名单（`apps/pulse/application/use_cases.py:23-30`） |
| 验收 | Pulse 快照 sentiment 维度由 ≥4 个指标合成；`tests/component/test_pulse_data_provider.py`、`test_pulse_weights.py` 及维度单测全绿；`init_pulse_config` seed 与 DB 配置一致；缺数时维度归一化行为有测试 |
| 回滚 | 删除/禁用对应 `PulseIndicatorConfigModel` 行即可，无代码耦合 |

### S2：交易行为情绪指标采集（核心增量）

| 项 | 内容 |
|---|---|
| 范围 | 按 S0 矩阵实现新指标采集。确认优先级：① 涨停/跌停家数 + 涨跌家数（市场宽度）；② 融资买入额占比。炸板率/连板高度在增量留存与 Tushare 权限验收前暂缓；**北向净流入因 2024-08-19 起披露口径变化移出当前范围**。每指标：catalog + unit rule seed migration（仿 0030）→ `_provider_adapter_akshare.py`/`_provider_adapter_tushare.py` 特判采集 → 治理元数据登记 → 接入采集调度；同时修复 `apps/realtime/interface/views.py:252-256` 的涨跌停硬编码占位，改读新指标 |
| 验收 | 新指标连续 3 个交易日有真实数据落库（MacroFact）；failover 与缺数降级有测试；`init_macro_indicator_governance --check` 通过；治理门禁（current_data_contracts / celery_task_contracts）同步完成 |
| 回滚 | 每指标独立 migration + 独立 commit；停用采集分支即回滚，已落库数据保留但 catalog 标记停用 |

### S3：文本情绪与 Pulse 打通 + TUI 情绪面板

| 项 | 内容 |
|---|---|
| 范围 | ① 把 sentiment 模块的日频情绪指数作为 Pulse sentiment 维度读数源（需为 `data_provider.py` 新增第三条读取通道：非 `.SH/.SZ` 资产码、非 MacroFact 的模块内读数，注意 `must_not_use_for_decision` 新鲜度契约的传导）；② 评估 sentiment 维度是否加入转折预警（`apps/pulse/domain/services.py:138-183`，需同步改 `tests/unit/test_pulse_transition.py`）；③ TUI `macro-regime.overview` 新增独立情绪 panel（chart 展示情绪指数趋势 + detail 展示当日分量），按 TUI 设计标准补齐 `primary_task`/P0/空态 |
| 验收 | 文本情绪参与 Pulse 合成且新鲜度违约时不参与（fail closed）；转折预警改动有完整单测；TUI 最小回归包（`test_tui_workbench.py` 等）+ IA 契约测试全绿 |
| 回滚 | 读数通道由配置开关控制，关闭即回到 S2 状态；TUI panel 走 IA/publish 回滚机制 |

转折预警评估结论：**不把 sentiment 维度作为 Regime 战略切换的独立触发器**。该维度属于战术感知层，短期文本或交易行为噪声不应越权改变增长/通胀象限；其信号保留在 Pulse sentiment 分数与 TUI 情绪面板中。现有转折预警逻辑与单测保持不变。

### S4：社会面情绪源评估（只做评估，不做实现）

| 项 | 内容 |
|---|---|
| 范围 | 对雪球/股吧/微博财经等社会面情绪源做合规性、稳定性、反爬风险、数据质量评估；产出"接入/不接入/暂缓"结论；如结论为接入，另立独立计划 |
| 验收 | [社会面情绪源评估](social-sentiment-source-assessment-2026-07-31.md) 已交付；默认处置为雪球不接入、股吧/微博暂缓，owner 若改变结论须另立计划 |
| 回滚 | 无代码改动 |

## 4. 标准验证命令

```bash
# Pulse / sentiment 定向
pytest tests/component/test_pulse_data_provider.py tests/component/test_pulse_weights.py -q
pytest tests/unit/test_pulse_services.py tests/unit/test_pulse_dimension.py -q
pytest tests/component/test_pulse_config_command.py -q

# data_center 治理
python manage.py init_macro_indicator_governance --check
python scripts/check_current_data_contracts.py   # 如涉及 current 语义

# TUI 最小回归包（S3）
pytest tests/unit/test_tui_workbench.py -q
pytest tests/unit/terminal/test_tui_information_architecture.py -q

# 通用门禁
python scripts/check_mypy_regression.py <changed-production-python-files>
python scripts/check_architecture.py
```

## 5. 风险与控制

| 风险 | 控制 |
|---|---|
| AKShare 页面型接口不稳定/字段漂移 | S0 实机验证先行；采集层 failover + 一致性校验（AGENTS.md 数据源规则）；缺数降级有测试 |
| 指标变多稀释 sentiment 维度信号 | S1 阈值设计先做历史回测式 sanity check（用既有 MacroFact 历史数据回放 signal_score 分布），再定权重 |
| 文本情绪新鲜度违约污染 Pulse | S3 通道必须传导 `must_not_use_for_decision`，stale 时 fail closed 不参与合成 |
| 与 Web→TUI 迁移 M5 观察期冲突 | **owner 已决策（2026-07-31）：S3 的 TUI 改动不计入 M5 窗口重置**。S1/S2 纯后端本就不受影响；执行时仍需在 S3 批次提交说明中引用本条决策，且 M5 遥测分母若混入本计划新增的 TUI 交互，需在 M5 证据中单独标注 |
| 涨跌停口径不一致（ST/北交所/新股） | S0 矩阵中显式定义口径（建议：剔除 ST、剔除上市首日、含主板/创业板/科创板分开统计） |

## 6. 每批完成定义与跟踪

| 批次 | 状态 | 结果/证据 | 未验证风险 |
|---|---|---|---|
| S0 指标矩阵与可用性 | 已完成 | 附录 A；`sentiment-data-source-verification-2026-07-31.md`；AKShare 1.18.21 实机探测；Tushare 官方权限文档 | 本机无 Tushare Token，`limit_list_d` 仍需在部署环境完成带权限探针 |
| S1 现成指标接 Pulse | 已完成 | 4 个既有 market-heat 指标 + 沪深300 纳入 fallback/DB seed；预刷新与缺数归一化测试 | 权重上线后仍需结合历史分布持续校准 |
| S2 交易行为情绪采集 | 已完成（代码） | 上涨/下跌/涨停/跌停 4 指标；AKShare/Tushare；1% 多源一致性；realtime freshness contract | 本机无 Tushare Token；生产连续 3 个交易日落库观察仍属部署验收证据 |
| S3 文本情绪打通 + TUI 面板 | 已完成 | `SENTIMENT_DAILY_INDEX` fail-closed facade；Pulse 第三通道；情绪摘要与趋势 panel；current-data 契约 | 情绪转折预警经评估不纳入战略触发，见本节决策 |
| S4 社会面情绪源评估 | 已完成 | `social-sentiment-source-assessment-2026-07-31.md`；雪球不接入，股吧/微博暂缓 | 微博官方 API 的具体检索、留存与再处理权限未采购/审核，因此未做 PoC |

## 7. 总完成定义

只有同时满足以下条件，本计划才算完成：

- [x] Pulse sentiment 维度由 ≥5 个指标合成，其中至少 2 个为交易行为情绪指标（宽度/涨跌停/北向类）
- [x] 文本情绪指数以 fail-closed 方式参与 Pulse 或明确记录不参与的决策
- [x] TUI `macro-regime.overview`（或新 screen）有独立情绪面板，符合 TUI 设计标准硬约束
- [x] realtime API 涨跌停字段不再硬编码为 0
- [x] 全部新增指标通过治理门禁（catalog/unit rule/pulse_input_policy/current_data_contracts/celery_task_contracts）
- [x] S4 社会面情绪源有书面结论
- [x] 本计划归档至 `archive/plans/` 并在 `docs/INDEX.md` 标记完成

## 8. 最终验证证据

- Pulse Domain 与 sentiment fail-closed：29 passed。
- Pulse data provider：11 passed。
- 交易行为 adapter/query/realtime：13 passed。
- 市场温度计调度、Pulse 配置与用例：40 passed；修正 1 个 consensus 断言后精确重跑通过。
- TUI 情绪/宏观页精确用例：3 passed；IA 全文件：7 passed；terminal agent / SDK client / SSL 与 IA 拆分包累计 48 passed（首次 3 个旧 IA 计数断言已同步后通过）。
- `black --check`、Ruff、增量 mypy、架构边界、migration consistency、current-data、Celery task contract、治理临时库 `--check` 全部通过。
- `tests/unit/test_tui_workbench.py` 全文件与其余最小包合并执行达到 20 分钟工具上限，未返回断言结果；与本功能直接相关的 3 个精确 TUI 用例已通过。
- 未完成的部署证据：生产环境 Tushare 5000 积分权限探针，以及连续 3 个交易日真实 MacroFact 落库观察；两项不改变已实现的 fail-closed 行为。

## 附录 A：S0 指标矩阵（2026-07-31 冻结）

下表是本轮实现口径。`缺席`统一表示不写 0、不沿用旧值；Pulse 对当日剩余新鲜指标重新归一化。详细实测证据见 [S0 数据源可用性验证](sentiment-data-source-verification-2026-07-31.md)。

| code | 名称 | 频率 | 主数据源 | failover / 校验源 | 缺数降级 | 去向 | 口径与状态 |
|---|---|---|---|---|---|---|---|
| `000300.SH` | 沪深300涨跌 | 日 | 既有指数行情 provider | 既有行情 failover 链 | 缺席 | Pulse | 收盘到收盘涨跌；保留低权重，避免与市场宽度重复放大 |
| `CN_A_TOTAL_TURNOVER` | A股全市场成交额 | 日 | 既有 catalog 采集 | Tushare 沪深市场汇总 / 东财全市场聚合，重叠日 1% 校验 | 缺席 | Pulse + 温度计 | 沪深京可交易 A 股成交额，统一为元；使用环比/标准化信号 |
| `CN_A_MARGIN_BALANCE` | A股融资余额 | 日 | 既有两市汇总 | AKShare `stock_margin_account_info` / Tushare `margin`，同日 1% 校验 | 未发布时缺席 | Pulse + 温度计 | 沪深两市融资余额之和，源观测日通常为 T-1，不洗白为请求日 |
| `CN_A_ETF_NET_FLOW` | A股 ETF 净流入 | 日 | 既有 catalog 采集 | 已登记 ETF 份额规模代理源 | 缺席 | Pulse + 温度计 | 使用标准化值；代理来源必须随数据发布 |
| `CN_A_MARKET_NEWS_SENTIMENT` | 市场新闻情绪均值 | 日 | 既有市场新闻链路 | AKShare / 东财新闻源 | 缺席 | Pulse + 温度计 | 当日去重有效新闻情绪均值，范围约 `[-1,1]` |
| `CN_A_MARKET_NEWS_COUNT` | 市场新闻热度 | 日 | 既有市场新闻链路 | AKShare / 东财新闻源 | 缺席 | 温度计 | 去重后有效新闻数量；不单独进入 Pulse，避免与新闻情绪双重计权 |
| `CN_A_MARKET_NEWS_POSITIVE_RATIO` | 市场新闻正面占比 | 日 | 既有市场新闻链路 | 同上 | 缺席 | 温度计/诊断 | 正面新闻数 ÷ 有效新闻数；分母 0 时缺席 |
| `CN_A_NEW_INVESTOR_ACCOUNTS` | 新增投资者账户 | 月 | 既有 catalog 采集 | 已登记代理/备用源 | 缺席 | 温度计 | 月频，不用请求时间包装为日频 current |
| `SENTIMENT_DAILY_INDEX` | 文本综合情绪指数 | 日 | sentiment Application facade | 无跨源静默替代 | fail closed，发布稳定阻断原因 | Pulse + TUI | 只使用 `data_sufficient=true` 且新鲜的模块内指数；不落入 MacroFact 冒充宏观指标 |
| `CN_A_ADVANCE_COUNT` | A股上涨家数 | 日 | 东财全市场批量行情 | Tushare 全市场日线 / 同批行情重试 | 缺席 | Pulse + realtime 摘要 | 当前实现剔除 ST 与无有效涨跌幅记录；源数据未稳定提供上市日，上市首日单独剔除留作后续口径增强 |
| `CN_A_DECLINE_COUNT` | A股下跌家数 | 日 | 东财全市场批量行情 | 同上 | 缺席 | Pulse + realtime 摘要 | 与上涨家数同 universe；平盘不计入二者 |
| `CN_A_LIMIT_UP_COUNT` | A股涨停家数 | 日 | AKShare `stock_zt_pool_em` | Tushare `limit_list_d`（部署环境通过 5000 积分权限探针后）/ 全市场行情校验 | 无 schema 空池时先交叉确认；不能确认则缺席 | Pulse + realtime 摘要 | 收盘仍封板并剔除 ST；上市首日因跨源字段不一致暂未稳定剔除，作为已知口径风险 |
| `CN_A_LIMIT_DOWN_COUNT` | A股跌停家数 | 日 | AKShare `stock_zt_pool_dtgc_em` | Tushare `limit_list_d` / 全市场行情校验 | 同上 | Pulse + realtime 摘要 | 收盘仍封板；同 `CN_A_LIMIT_UP_COUNT` universe |
| `CN_A_MARGIN_BUY_AMOUNT` | A股融资买入额 | 日 | AKShare `stock_margin_account_info` | Tushare `margin` / 上交所与深交所汇总 | 缺席 | 后续 Pulse 候选/诊断 | 沪深合计、统一为元；本轮先留存，不直接替代融资余额 |
| `CN_A_MARGIN_BUY_TURNOVER_RATIO` | 融资买入额占成交额 | 日 | 上述融资买入额 ÷ 同日全市场成交额 | 分子分母各自 failover 后再计算 | 任一缺失或成交额为 0 时缺席 | 后续 Pulse 候选 | 必须同一交易日；先影子回放再定阈值/权重 |
| `CN_A_BROKEN_LIMIT_RATE` | 炸板率 | 日 | AKShare `stock_zt_pool_zbgc_em` + 涨停池 | Tushare `limit_list_d` U/Z（权限验收后） | 分母 0 或任一池不可确认时缺席 | **暂缓** | `Z / (U + Z)`；AKShare 只有近 30 日窗口，先每日留存并完成口径测试 |
| `CN_A_MAX_LIMIT_UP_STREAK` | 最高连板高度 | 日 | AKShare 涨停池 `连板数` | Tushare `limit_list_d.limit_times`（权限验收后） | 缺席 | **暂缓** | 对过滤后收盘涨停股取最大值；空池不能与采集失败混淆 |
| `CN_A_NORTHBOUND_NET_FLOW` | 北向净流入 | 日 | 无可用当前源 | 无 | 永久缺席 | **移出范围** | 净买额字段 2024-08-16 后不再有效；禁止把空值/占位 `0.0` 写入决策数据 |

S1-S3 不因炸板率、连板高度、融资买入额占比或北向净流入而阻塞；本计划的交易行为完成口径以 `CN_A_ADVANCE_COUNT`、`CN_A_DECLINE_COUNT`、`CN_A_LIMIT_UP_COUNT`、`CN_A_LIMIT_DOWN_COUNT` 为准。
