# 生产事故复盘：Realtime 市场概况把旧快照当成当前行情

> 日期：2026-07-30
>
> 影响面：VPS Terminal / MCP 市场概况与依赖 Realtime provider 的读取
>
> 性质：决策数据完整性缺陷

## 结论

这是可以在开发阶段避免的低级语义错误。系统把“数据库中最新的一行”误当成“仍然新鲜的当前数据”，又在历史日线降级路径中把请求时刻写成行情时间。进程、Redis、Celery 和 HTTP 健康检查全部正常，但业务数据已经过期，因此传统可用性监控没有发现问题。

## 用户可见影响

VPS Terminal 在 2026-07-30 回答“目前市场情绪怎么样”时，读取并展示了 2026-04-06 的三大指数快照。旧值可能进入 AI 市场判断上下文。复盘范围内没有据此确认任何实际交易执行；但只要旧行情能进入建议链路，本身就属于必须失败关闭的数据完整性问题。

## 技术故障链

1. `MarketSummaryView` 请求上证、深证、创业板三个代码。
2. Redis 五分钟缓存未命中后进入 `CompositePriceDataProvider`。
3. 第一层 `DataCenterPriceDataProvider` 从 PostgreSQL 取到 2026-04-06 的最新持久化快照。
4. 组合 provider 只判断结果是否非空，没有判断源观测时间是否过期，因此停止 failover。
5. AKShare/EastMoney/Tencent 后续数据源没有机会执行。
6. API 只用 `available_count > 0` 判成功，没有发布完整性/决策阻断契约。
7. Terminal Agent 看见指数值后继续生成“当前市场”结论。

同类旁路并不只存在于 Realtime。全仓审计还发现：UnifiedPriceService 可接受任意年龄的日线收盘和基金净值；Regime/情绪/对冲/轮动把“持久化最新”直接交给决策层；估值可绕过统一价格服务复用旧 fallback；汇率隐式换算、Equity 分时校验和 Decision Rhythm 特征可读取旧缓存；SDK 还会把缺失的 Regime 观测日替换成当天。这些缺陷共享同一根因：排序语义、缓存命中和请求时间被错误地当作数据有效性证明。

## 五问分析

### 1. 为什么展示旧行情？

因为 provider 把非空的 latest row 当成有效 realtime 结果。

### 2. 为什么旧结果没有触发备用源？

因为 failover 契约只有 success/missing，没有 stale 状态。

### 3. 为什么 API/Agent 没有拒绝？

因为市场概况响应没有 `market_data_as_of`、`is_reliable`、`must_not_use_for_decision` 的硬契约。

### 4. 为什么测试没有发现？

原测试只断言价格、来源和“缺失时回退”，固定日期样本没有与当前时钟比较，也没有“第一数据源返回旧值、第二数据源返回新值”的场景。

### 5. 为什么生产监控没有发现？

监控只证明任务运行、容器健康和接口可达，没有比较业务观测时间与请求时间。26,000 多次成功调度并不等于行情被刷新。

## 失效的工程防线

| 防线 | 原状态 | 缺陷 |
|---|---|---|
| Domain | 只有价格值对象 | 没有 freshness 判定和 aware 时间边界 |
| Provider | 非空即成功 | stale 会截断 failover |
| Adapter | 日线可包装成 realtime | 使用 `timezone.now()` 洗白 bar 日期 |
| API | `available_count > 0` | 不区分完整、部分、过期和不可决策 |
| Tests | happy path 为主 | 缺 stale→fresh provider 顺序与时间边界 |
| Ops | 进程/任务状态 | 未检查业务观测时间 |

## 已实施整改

- `RealtimePrice.is_fresh()` 统一拒绝过期、未来和 naive 时间；
- Redis 命中和 provider 返回都执行 freshness 校验；
- Composite 遇到 stale 继续 failover；
- 历史日线保留实际交易日收盘时间；
- 市场概况发布完整性、观测时间与决策阻断契约；
- MCP 工具说明要求遵守 `must_not_use_for_decision`；
- `UnifiedPriceService` 复用 Data Center `QueryLatestQuoteUseCase`，不再自创“最新即实时”的旁路；
- Account/模拟盘全链保留源 `observed_at`，不再用请求时间生成元数据；
- 新增 `governance/current_data_contracts.json`、AST 门禁和 CI 步骤。
- 将 Regime、Sentiment、Valuation、FX、Hedge、Rotation、Equity Intraday、Decision Rhythm 等同类数据面纳入同一失败关闭契约；
- 价格轮询在写缓存、更新持仓和触发告警之前先过滤 stale/future/naive 观测，避免旧数据产生副作用；
- 日线收盘与基金净值按最近完成交易日判鲜，持久化旧值不再截断备用数据源；
- Regime 保留 PMI/CPI 的真实源日期，SDK/MCP/Terminal 不再补造观测时间；
- 关键特征任一不可决策时，统一推荐强制 `HOLD`、置信度归零并持久化阻断证据；
- current-data 治理清单由最初 6 个数据面扩展为 18 个，CI 同时扫描应用、SDK 和 MCP 的时间戳洗白模式。

## 防复发测试矩阵

| 场景 | 必须结果 |
|---|---|
| 缓存新鲜 | 直接使用并保留源观测时间 |
| 缓存过期 | 忽略缓存并请求 provider |
| 第一 provider 过期、第二 provider 新鲜 | 继续 failover，采用第二来源 |
| 全部 provider 过期/缺失 | 返回不可用或决策阻断，不展示旧值 |
| 部分指数缺失 | `is_partial=true` 且 `must_not_use_for_decision=true` |
| 历史日线降级 | 标记 close fallback，保留交易日期，不伪装 realtime |
| future/naive 时间 | 失败关闭 |
| Pulse/Regime 不可靠 | 禁止输出确定性联合行动建议 |
| stale Regime/Sentiment/Flow 特征 | 下游推荐强制 HOLD，不得用中性默认值继续计算 |
| stale 汇率隐式换算 | 阻断换算和组合币种配置；显式历史查询仍允许 |
| stale 估值 fallback | 重新通过统一价格服务验证；无法验证则不输出估值 |
| stale 对冲/轮动快照 | 保留诊断值，但明确发布不可决策契约 |

## 后续验收原则

以后不能再用“Celery 在跑”“接口 200”“数据库有记录”作为当前数据可用的证据。验收必须同时回答：值是什么、源观测时间是什么、是否在允许窗口、是否发生降级、能否用于决策。任何一项缺失，当前数据面不得标记为生产就绪。
