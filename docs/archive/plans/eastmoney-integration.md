# 东方财富数据源集成计划

> **创建时间**: 2026-03-09
> **最近修订**: 2026-03-09 (Phase 1-3 全部完成)
> **状态**: 全部实施完成（含 SDK/MCP/API 文档）
> **涉及模块**: `apps/realtime`, `apps/equity`, `apps/sentiment`

---

## Context

当前系统的股票数据来源主要是：

- `Tushare Pro`：基本面、历史行情
- `AKShare`：宏观、部分实时数据

现有覆盖不足主要体现在：

- **资金流向**：缺少稳定的股票级主力资金/超大单/北向等数据
- **个股新闻情绪**：现有情绪能力偏市场级，缺少股票级输入源
- **实时行情补强**：现有 `CompositePriceDataProvider` 已有多源回退，但没有更细的站点级能力隔离
- **技术指标补充**：缺少量比、换手率、KDJ、BOLL 等扩展字段

东方财富这类数据虽然可通过 `AKShare` 访问，但本质上仍然依赖第三方站点接口/页面结构。无论入口是：

- 直接 HTTP 请求
- `AKShare` 的上游封装
- 后续替换成别的抓取实现

都属于**易变外部采集源**，不能直接把站点字段和业务模块耦死。

---

## 目标

1. 为系统补充 A 股的实时行情、资金流向、股票新闻、扩展技术指标。
2. 对东方财富站点变化保持弹性，做到**采集实现可替换**。
3. 与现有 `realtime / equity / sentiment` 业务层解耦，业务层只依赖稳定的领域 DTO / Protocol。
4. 允许未来把东方财富替换成其他来源，而不需要大改评分、接口、任务编排。

**市场范围**：第一阶段仅 A 股，港股/美股后续扩展。

---

## 核心原则

### 1. 不把 “东方财富” 直接当成业务层概念

业务层不感知：

- `AKShare` 方法名
- 东方财富原始字段名
- 站点 URL / 页面结构 / 参数规则

业务层只感知：

- `QuoteSnapshot`
- `CapitalFlowSnapshot`
- `StockNewsItem`
- `TechnicalSnapshot`

### 2. 把采集实现放进独立 Source Gateway

新增一个独立的数据源接入层，负责：

- 站点请求
- `AKShare` 调用
- 字段映射
- 容错重试
- 限流和降级
- 原始响应落盘/缓存

建议目录：

```text
apps/market_data/
  domain/
    entities.py
    protocols.py
    enums.py
  infrastructure/
    gateways/
      eastmoney_gateway.py
      akshare_eastmoney_gateway.py
    parsers/
      eastmoney_quote_parser.py
      eastmoney_capital_flow_parser.py
      eastmoney_news_parser.py
    registries/
      source_registry.py
    repositories/
      raw_payload_repository.py
      market_data_cache_repository.py
```

如果当前不想新增 app，也至少要抽出统一目录，例如：

```text
shared/market_data/
```

重点不是目录名，而是**把站点耦合从 `apps/realtime`、`apps/equity`、`apps/sentiment` 里拿出来**。

### 3. Adapter 分两层，不直接把 AKShare 当领域接口

推荐拆成两层：

- `Gateway`：负责“怎么拿到数据”
- `Parser/Mapper`：负责“怎么把外部字段变成内部标准模型”

例如：

```text
EastMoneySiteGateway      -> 直接请求站点/API
AKShareEastMoneyGateway   -> 通过 akshare 调用东方财富封装
EastMoneyQuoteParser      -> 标准化为 QuoteSnapshot
```

这样后续如果 `AKShare` 失效，可以只替换 `Gateway`，不用改 `Parser` 和业务逻辑。

### 4. 按能力注册，不按站点写死

不要在业务代码里出现这种判断：

```python
if source == "eastmoney":
    ...
```

应改为能力导向：

- `REALTIME_QUOTE`
- `CAPITAL_FLOW`
- `STOCK_NEWS`
- `TECHNICAL_FACTORS`

由 `SourceRegistry` 决定每种能力当前用哪个 provider：

```python
REALTIME_QUOTE: [eastmoney, akshare_general, tushare]
CAPITAL_FLOW: [eastmoney]
STOCK_NEWS: [eastmoney]
TECHNICAL_FACTORS: [eastmoney, tushare]
```

### 5. 原始数据和标准化数据分开

对这种“类爬虫”来源，建议保留两层数据：

- **raw payload**：原始响应，便于站点变更后排查
- **normalized snapshot**：标准化后的内部模型，供业务使用

这样线上一旦字段变了，可以先比对 raw 数据，不需要直接进业务逻辑里排查。

---

## 推荐架构

### 能力抽象

新增统一协议：

```python
class MarketDataProviderProtocol(Protocol):
    def supports(self, capability: DataCapability) -> bool: ...
    def get_quote_snapshots(self, stock_codes: list[str]) -> list[QuoteSnapshot]: ...
    def get_capital_flows(self, stock_code: str, period: str) -> list[CapitalFlowSnapshot]: ...
    def get_stock_news(self, stock_code: str, limit: int = 20) -> list[StockNewsItem]: ...
    def get_technical_snapshot(self, stock_code: str) -> TechnicalSnapshot | None: ...
```

其中 `DataCapability` 建议定义为枚举：

```python
REALTIME_QUOTE
CAPITAL_FLOW
STOCK_NEWS
TECHNICAL_FACTORS
```

### Source Registry

统一由注册表分发 provider：

```python
class SourceRegistry:
    def get_provider(self, capability: DataCapability) -> MarketDataProviderProtocol: ...
    def get_providers(self, capability: DataCapability) -> list[MarketDataProviderProtocol]: ...
```

注册表负责：

- 优先级
- 健康检查
- 熔断状态
- feature flag
- failover

### 标准领域对象

建议在统一模块定义以下实体：

```python
@dataclass(frozen=True)
class QuoteSnapshot:
    stock_code: str
    price: Decimal
    change: Optional[Decimal]
    change_pct: Optional[float]
    volume: Optional[int]
    amount: Optional[Decimal]
    turnover_rate: Optional[float]
    volume_ratio: Optional[float]
    source: str
    fetched_at: datetime


@dataclass(frozen=True)
class CapitalFlowSnapshot:
    stock_code: str
    trade_date: date
    main_net_inflow: float
    main_net_ratio: float
    super_large_net_inflow: float
    large_net_inflow: float
    medium_net_inflow: float
    small_net_inflow: float
    source: str
    fetched_at: datetime


@dataclass(frozen=True)
class StockNewsItem:
    stock_code: str
    news_id: str
    title: str
    content: str
    published_at: datetime
    url: Optional[str]
    source: str
    fetched_at: datetime


@dataclass(frozen=True)
class TechnicalSnapshot:
    stock_code: str
    trade_date: date
    close: Decimal
    ma5: Optional[Decimal]
    ma20: Optional[Decimal]
    ma60: Optional[Decimal]
    macd: Optional[float]
    macd_signal: Optional[float]
    macd_hist: Optional[float]
    rsi: Optional[float]
    kdj_k: Optional[float]
    kdj_d: Optional[float]
    kdj_j: Optional[float]
    boll_upper: Optional[float]
    boll_mid: Optional[float]
    boll_lower: Optional[float]
    turnover_rate: Optional[float]
    volume_ratio: Optional[float]
    source: str
```

---

## 与现有系统的解耦方式

### apps/realtime

现状：

- 已有 `PriceDataProviderProtocol`
- 已有 `CompositePriceDataProvider`

改造建议：

- 不直接新增 `EastMoneyPriceDataProvider` 绑定到 `ak.stock_zh_a_spot_em()`
- 改为新增一个桥接 provider，例如 `MarketDataBridgePriceProvider`
- 这个 bridge 从 `SourceRegistry` 获取 `REALTIME_QUOTE` provider，再转换成现有 `RealtimePrice`

示意：

```python
class MarketDataBridgePriceProvider(PriceDataProviderProtocol):
    def __init__(self, registry: SourceRegistry):
        self.registry = registry

    def get_realtime_prices_batch(self, asset_codes):
        provider = self.registry.get_provider(DataCapability.REALTIME_QUOTE)
        snapshots = provider.get_quote_snapshots(asset_codes)
        return [self._to_realtime_price(item) for item in snapshots]
```

这样 `apps/realtime` 只依赖桥接层，不依赖东方财富、AKShare 或页面字段。

### apps/equity

建议不要在 `apps/equity/infrastructure/adapters/eastmoney_adapter.py` 里直接写站点逻辑。

更合理的方式是：

- `apps/equity` 只保留 `Repository` 和 `UseCase`
- 外部数据由统一 `market_data` 层提供
- `equity` 只消费标准化后的 `CapitalFlowSnapshot` 和 `TechnicalSnapshot`

也就是：

- 资金流同步 use case 调用 `market_data` provider
- repository 负责把标准对象落到 `StockCapitalFlowModel`
- scorer 只依赖领域对象，不依赖外部源

### apps/sentiment

不要让 `SentimentAnalyzer` 直接知道 `AKShare` 或东方财富。

建议拆分为两步：

1. `StockNewsIngestionService` 负责拉取并标准化新闻
2. `StockSentimentAnalyzer` 只负责对标准化新闻文本做 AI 分析

这样站点变更只影响新闻采集层，不影响 AI 分析层。

---

## 分阶段实施方案

### Phase 0: 预验证

目标：确认数据可取、字段大致稳定、调用成本可接受。

验证内容：

- `AKShare` 入口是否稳定可用
- 单次批量行情接口耗时
- 资金流字段是否固定
- 新闻接口是否包含正文/摘要/发布时间
- 是否存在频率限制、验证码、空数据窗口

这一步只做 PoC，不进入正式业务集成。

### Phase 1: 建统一数据源接入层

新增内容：

- `DataCapability` 枚举
- `MarketDataProviderProtocol`
- `SourceRegistry`
- `AKShareEastMoneyGateway`
- 对应 parser / mapper
- raw payload 持久化或缓存能力

这一步先不改业务模块接口，只把“可采集能力”建立起来。

### Phase 2: 接入 realtime

在现有 `CompositePriceDataProvider` 前面插入桥接 provider：

```python
providers = [
    MarketDataBridgePriceProvider(registry),
    AKSharePriceDataProvider(),
    TusharePriceDataProvider(),
]
```

说明：

- 第一优先级仍然可以来自东方财富能力
- 但 `realtime` 不直接依赖东方财富实现
- failover 仍沿用现有组合模式

### Phase 3: 接入 equity 资金流和扩展技术指标

新增：

- `StockCapitalFlow` 领域对象
- `StockCapitalFlowModel`
- `CapitalFlowScorer`
- `SyncCapitalFlowUseCase`

改造：

- 技术指标扩展字段进入 `TechnicalIndicators`
- 同步任务只消费 `TechnicalSnapshot`

这里应特别注意：

- `capital_flow_score` 建议先写入 `custom_scores`
- 是否纳入总分，建议通过配置开关控制，不要第一版写死

### Phase 4: 接入 sentiment 股票新闻

新增：

- `StockSentimentIndex`
- `StockNewsIngestionService`
- `AnalyzeStockNewsSentimentUseCase`

流程：

1. 从 `market_data` provider 拉股票新闻
2. 标准化并去重
3. 命中缓存则复用已有分析结果
4. 未命中才调用 AI
5. 聚合为股票级情绪指数

### Phase 5: 权重和开关配置化

新增配置建议：

- `MARKET_DATA_REALTIME_PROVIDER=eastmoney`
- `MARKET_DATA_CAPITAL_FLOW_PROVIDER=eastmoney`
- `MARKET_DATA_STOCK_NEWS_PROVIDER=eastmoney`
- `MARKET_DATA_ENABLE_RAW_PAYLOAD=true`
- `MARKET_DATA_FAILOPEN=true`

评分相关也建议配置化：

- `capital_flow_weight`
- `stock_sentiment_weight`
- `technical_extension_enabled`

不要把这些直接硬编码在服务里。

---

## 数据模型建议

### 1. 资金流表

可新增：

```python
class StockCapitalFlowModel(models.Model):
    stock_code = models.CharField(max_length=10, db_index=True)
    trade_date = models.DateField(db_index=True)
    main_net_inflow = models.FloatField()
    main_net_ratio = models.FloatField()
    super_large_net_inflow = models.FloatField(null=True, blank=True)
    large_net_inflow = models.FloatField(null=True, blank=True)
    medium_net_inflow = models.FloatField(null=True, blank=True)
    small_net_inflow = models.FloatField(null=True, blank=True)
    source = models.CharField(max_length=50, default="eastmoney")
    raw_version = models.CharField(max_length=50, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
```

建议补充：

- `raw_version` 或 `schema_version`
- 便于后续排查字段映射变更

### 2. 新闻情绪表

除了 `StockSentimentModel`，建议新增原始新闻表，而不是只存聚合结果：

```python
class StockNewsModel(models.Model):
    stock_code = models.CharField(max_length=10, db_index=True)
    news_id = models.CharField(max_length=100, unique=True)
    title = models.CharField(max_length=500)
    content = models.TextField(blank=True)
    published_at = models.DateTimeField(db_index=True)
    url = models.URLField(blank=True)
    source = models.CharField(max_length=50, default="eastmoney")
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
```

原因：

- 便于去重
- 便于重跑情绪分析
- 便于切换模型时重新计算

### 3. 原始 payload 存储

可以是表，也可以是缓存/文件。

建议最少保留：

- 请求类型
- 股票代码
- 请求时间
- provider 名称
- 原始 payload
- 解析状态
- 错误信息

---

## 对原方案的具体修正

### 修正 1：不要把 “AKShare 已封装，所以不是爬虫问题” 作为前提

原方案默认：

- `AKShare` 封装了东方财富
- 所以可以直接按普通 API 集成

这个前提不稳。

更准确的表述应是：

- 第一版可优先复用 `AKShare`
- 但系统架构必须把它视为**易变上游**
- 需要预留 direct gateway / fallback gateway / parser 重配能力

### 修正 2：不要把 EastMoney adapter 分散落在多个 app

原方案里：

- `apps/equity/infrastructure/adapters/eastmoney_adapter.py`
- `apps/sentiment/infrastructure/adapters/eastmoney_news_adapter.py`
- `apps/realtime/infrastructure/repositories.py` 中再加 provider

这样会产生三个问题：

- 站点字段映射重复
- 限流/重试/错误处理重复
- 站点变更时改动面过大

应改为：

- 统一采集层一处接站点
- 各业务 app 通过 protocol/bridge 使用

### 修正 3：评分权重不要一次性写死

当前 `apps/equity/application/services.py` 里综合评分已写死固定权重。

如果新增：

- `capital_flow_score`
- `stock_sentiment_score`

不建议直接改成另一套硬编码，而应：

- 先进入 `custom_scores`
- 再通过配置化权重决定是否纳入综合分

### 修正 4：新闻接口要考虑“无正文、重复、营销稿、时间错位”

股票新闻不是拿到就能做情绪分析。

需要在 ingestion 层加：

- 去重规则：`news_id` / `title + published_at`
- 时间窗口过滤：例如只取近 1-3 天
- 内容清洗：去广告、免责声明、模板尾巴
- 数据充足性标记：避免 0 条新闻被误判成中性

### 修正 5：技术指标的来源要拆分

建议：

- `turnover_rate`、`volume_ratio` 走实时 quote snapshot
- `KDJ`、`BOLL` 走历史日线计算

不要都塞进一个 `fetch_technical()` 里混着抓，后续不好排障。

---

## 韧性设计

这是这类方案最容易漏掉的部分。

### 1. Fail Open

东方财富能力失败时：

- `realtime` 回退到现有 `AKSharePriceDataProvider` / `TusharePriceDataProvider`
- `equity` 的资金流和扩展技术指标允许部分缺失
- `sentiment` 新闻缺失时返回“数据不足”，不要伪造中性值

### 2. 限流与节流

建议加：

- 单 capability 并发限制
- 股票批量分片
- TTL 缓存
- 指数退避重试

### 3. 健康检查与熔断

为每个 provider 记录：

- 最近成功时间
- 连续失败次数
- 熔断到期时间

避免每次请求都去撞一个坏掉的站点。

### 4. 观测性

至少记录：

- provider 名称
- capability
- 股票代码/批次大小
- 请求耗时
- 成功率
- 解析失败原因

---

## 建议修改后的实施清单

### 新增

- `apps/market_data/domain/protocols.py`
- `apps/market_data/domain/entities.py`
- `apps/market_data/domain/enums.py`
- `apps/market_data/infrastructure/registries/source_registry.py`
- `apps/market_data/infrastructure/gateways/akshare_eastmoney_gateway.py`
- `apps/market_data/infrastructure/parsers/eastmoney_quote_parser.py`
- `apps/market_data/infrastructure/parsers/eastmoney_capital_flow_parser.py`
- `apps/market_data/infrastructure/parsers/eastmoney_news_parser.py`
- `apps/market_data/infrastructure/repositories/raw_payload_repository.py`
- `apps/equity/infrastructure/models.py` 中新增 `StockCapitalFlowModel`
- `apps/sentiment/infrastructure/models.py` 中新增 `StockNewsModel`、`StockSentimentModel`

### 修改

- `apps/realtime/infrastructure/repositories.py`
- `apps/realtime/application/price_polling_service.py`
- `apps/equity/domain/entities.py`
- `apps/equity/domain/services.py`
- `apps/equity/application/use_cases.py`
- `apps/equity/application/services.py`
- `apps/equity/infrastructure/repositories.py`
- `apps/sentiment/domain/entities.py`
- `apps/sentiment/application/services.py`
- `apps/sentiment/interface/api_urls.py`

### 不建议新增

- `apps/equity/infrastructure/adapters/eastmoney_adapter.py`
- `apps/sentiment/infrastructure/adapters/eastmoney_news_adapter.py`

原因：

- 会把站点耦合散落进业务 app

---

## 验证方案

### 1. Provider 验证

验证维度：

- 能否成功拉到数据
- 字段是否齐全
- 空值比例
- 批量接口耗时
- 连续调用稳定性

建议验证用例：

```python
provider = registry.get_provider(DataCapability.CAPITAL_FLOW)
flows = provider.get_capital_flows("000001.SZ", period="5d")
assert flows
assert flows[0].stock_code == "000001.SZ"
```

### 2. Parser 契约测试

重点测：

- 字段缺失
- 数值格式异常
- 空响应
- 重复新闻
- 时间字段格式变化

### 3. Failover 测试

需要覆盖：

- 东方财富 provider 失败
- registry 自动切换下一 provider
- `realtime` 仍能返回结果
- `equity/sentiment` 返回“部分缺失/数据不足”而非 500

### 4. 集成验证

建议关注：

- `custom_scores` 中是否新增 `capital_flow`、`stock_sentiment`
- 总分是否仅在开关开启后纳入
- 新闻少于阈值时是否返回 `data_sufficient = False`

---

## 结论

这个方案可以做，但前提是不要把它当成“普通第三方 API 接入”。

更稳的做法是：

- 把东方财富视为**易变采集源**
- 先抽统一 `market_data` 能力层
- 让 `realtime / equity / sentiment` 只依赖稳定协议和标准 DTO
- 把站点相关风险收敛到一个 gateway/parser/registry 边界内

这样后面即使东方财富站点改版、`AKShare` 参数变更、某个字段消失，最多也是改一层接入逻辑，不会把现有系统其他数据源和业务模块一起带崩。
