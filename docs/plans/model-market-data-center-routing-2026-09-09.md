# 模型行情经数据中台取数（本地改造，2026-09-09）

## 目标与边界

Alpha/Qlib 只表达股票范围、日期窗口以及所需字段；数据中台负责选择提供方、外部调用、标准化、来源一致性、新鲜度检查和 canonical 原始行情存储。业务模块不再取得 SDK 后自行编排 Tushare → AKShare。

这是 [数据中台 canonical 架构整改](data-center-canonical-architecture-refactor-2026-08-02.md) 的历史行情子阶段。本次仅修改本地代码，不包含 VPS 发布、生产配置切换、历史错误数据修复或新模型训练。此前 VPS 额度故障的事实仍见 [故障复盘](../reviews/vps-alpha-stale-score-2026-09-09.md)。

## 已迁移链路

| 消费者 | 新入口 | 保留职责 |
| --- | --- | --- |
| Alpha Qlib 数据构建 | `get_model_market_data_port()` | 股票池业务选择、Qlib 特征缩放、bin/instrument 文件生成 |
| `build_qlib_data` 维护命令 | `DataCenterQlibBuilder` | 参数校验、诊断与输出；不再检查 Tushare Token |
| Equity 指数收益率 | 同一中台端口的 `index_history` | 收盘价到收益率的计算 |
| Equity 股票日线与技术指标 | 同一中台端口的 `stock_history` | 业务实体转换和指标计算 |

`TushareQlibBuilder` 暂保留为类名兼容别名，已经不负责 Tushare 取数；新增调用应使用 `DataCenterQlibBuilder`。单元测试直接注入 `ModelMarketDataPort`，提供方 SDK 假对象只能注入中台适配器。

## 取数与数据正确性

1. 路由来源是已有 `ProviderRegistry` 的 `HISTORICAL_PRICE` 能力、启用状态与优先级；`default_source`、`enable_failover`、`failover_tolerance` 从配置中心运行时配置读取。配置缺失必须阻断，不制造可用配置。
2. `ModelDailyBar` 是类型明确的标准观测：股票价格不复权、CNY；指数价格为点位；成交量为股，成交额为 CNY；保留提供方名称、源交易日与同源复权因子。查询时间不能替代交易日。中台统一为股；Qlib 写入端显式保留既有模型的股票股/指数手约定，避免向旧 bin 追加不同量纲；若统一模型端指数单位，必须另行全量重建与训练验证。
3. Tushare 的 daily/adj_factor 必须配对。SDK 参数、重试、额度识别及字段解析全部移入中台。日额度耗尽后当前服务实例停用该路由，尝试获准备用源；没有可用备用源则阻断。
4. AKShare 使用原始 OHLC 和后复权 OHLC 配对，检查同日 OHLC 是否可以用同一乘法因子解释；缺失、非正价格、非乘法复权均不接受。禁止将 qfq OHLC 当作未复权价格再复权。因子绝对尺度可以不同，跨源重叠期的相对因子变化必须一致。
5. 候选历史数据末日早于所请求窗口的交易日历末日时继续 failover；没有更新来源则 `MODEL_MARKET_STALE`。这意味着停牌/退市标的不会被自动视为“当前可评分”；尚无停牌证据契约时，包含此类标的的构建可能阻断，需先按业务规则配置可用股票池。
6. 切源必须有同日期原始 OHLC/成交量参考：优先使用失败源返回的有效旧观测，否则使用中台 canonical 未复权历史；无重叠证据为 `MODEL_MARKET_UNVERIFIED_FAILOVER`，超过配置容差为 `MODEL_MARKET_SOURCE_CONFLICT`。不得仅因备用源返回非空就接受。主源被 registry 熔断过滤后也保留备用源校验要求；配置更换主源时同样对旧来源事实检查一致性。旧库若曾把 qfq 错标为 none，可能产生冲突，不能通过放宽阈值绕过。
7. 合格原始行情由中台写入 canonical PriceBar。中台尚没有独立的复权因子事实表；因子随本次类型化输入返回，不能把仅有 OHLC 的旧库当作完整的离线 Qlib 数据集。
8. 交易日历来自提供方，不推算工作日。AKShare 的当前指数成分表不能冒充历史快照，因此该适配器明确不提供历史指数成员；由中台尝试其他获准来源。
9. Qlib 写文件之前先完成指数行情取数，避免指数取数失败时已经推进日历。文件写入本身的崩溃原子性仍是既有独立问题。
10. Alpha 任务将 `MODEL_MARKET_*` 及额度错误发布为 `outcome=blocked`、`stored=0`、`must_not_use_for_decision=true`，不执行预测或评分缓存写入；稳定阻断原因保留给任务监控。

## 同类入口盘点与后续阶段

下面是不同数据契约，不能机械替换为股票日线端口；本阶段没有宣称仓库全部 SDK 逃逸已清零。

| 剩余入口 | 所需后续工作 |
| --- | --- |
| `alpha/infrastructure/adapters/etf_adapter.py` | ETF 持仓的披露期、权重与发布时间契约，接中台持仓事实端口 |
| `fund/infrastructure/adapters/tushare_fund_adapter.py` | 基金基础信息、净值和持仓分别迁移已有中台能力 |
| `realtime/infrastructure/repositories.py` | 逐笔/快照源时间、交易时段、新鲜度与报价一致性 |
| `equity/infrastructure/intraday_repository.py` | 分钟级周期、时区与交易时段契约 |
| `sector/infrastructure/adapters/akshare_sector_adapter.py` | 行业分类版本与成员生效区间契约 |

上述入口不在本次历史行情调用链内；后续按各自契约独立迁移，避免引入业务 App 级循环依赖。全仓 SDK 逃逸盘点测试将上述五个文件列为只减不增的存量边界。新增类似调用不得继续暴露 `get_tushare_client` / `get_akshare_module` 给业务层。

## 验收与回滚

验收范围：中台路由的成功、禁用 failover、旧源续试、额度停止、无重叠阻断、价格/复权冲突、AKShare 单位转换；Qlib bin 构建、参数边界、并发上限；Equity 消费中台日线；Alpha 阻断时无预测/写入。边界测试禁止已迁移消费者重新获取 SDK 或调用 vendor-specific 历史行情端口。

本地验证结果：

- 核心回归：94 passed，覆盖中台模型行情、Qlib 构建、Equity 仓储与 API。此前 API 测试仍把缓存写入归给业务模块，现改成通过真实中台存储组装验证。
- Alpha 任务与 Provider 适配器回归：59 passed，覆盖中台错误阻断、零评分写入及现有提供方行为。
- 中台专项：15 passed，包括全仓 SDK 逃逸存量边界、熔断后的校验、配置换源校验、单位与复权冲突。
- 首轮命令/构建/仓储回归：60 passed，包含维护命令参数校验及取消供应商 Token 门槛。
- 15 个生产 Python 文件增量 mypy：0 errors；全量 mypy debt ceiling：0 errors；未提高基线。
- Celery task contracts：91 tasks；current-data contracts：55 surfaces；Black/isort/Ruff 与 diff whitespace 检查通过。

尚未验证：VPS 全市场构建性能、真实多源全窗口复权一致性、生产中台配置与历史参考覆盖。生产启用前必须验证这些项目，不能把本地假源测试当作生产评分恢复证据。

回滚单位：本阶段的新中台模型行情契约/适配器及消费者切换整体回滚；不要回滚此前 VPS 额度与陈旧评分阻断修复，不修改用户其他未提交内容。按用户要求将本阶段提交归并到 `dev/next-development`；不包含生产发布。

## 提供方字段依据

- [Tushare 日线](https://tushare.pro/document/1?doc_id=27)：成交量为手、成交额为千元。
- [Tushare 指数日线](https://tushare.pro/document/1?doc_id=95)：点位、成交量手、成交额千元。
- [AKShare 股票历史行情](https://akshare.akfamily.xyz/data/stock/stock.html)：不复权/qfq/hfq 的区别。
- [AKShare 已知数据问题](https://akshare.akfamily.xyz/data_tips.html)：后复权可能存在非正价格，应拒绝而非静默填补。
