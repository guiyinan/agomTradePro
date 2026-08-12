# AgomTradePro 数据中台统一收口完整计划

## Summary
- 新建独立业务模块 `apps/data_center/`，作为系统唯一的数据接入与分发中心，统一承接外部数据源配置、运行时路由、标准化、持久化、同步任务、查询接口。
- 最终目标是全域收口：宏观、股票/ETF/指数价格、基金净值、财务、估值、板块成分、新闻、资金流全部迁入 `data_center`，业务模块只消费中台，不再直接连外部源。
- 采用“目标一次性收口、实施分阶段落地”的方式：同一重构项目内完成架构定型与消费者切换，但按基础设施、标准事实表、消费者迁移、旧链路删除四段执行，避免全量大改失控。
- 因系统尚未正式上线，本计划默认允许破坏旧入口和旧内部实现；但为了排障和数据源漂移治理，保留 `raw + standard` 双层存储，不采用“只存标准层”。
- 完成后，`apps/data_center/infrastructure/` 之外禁止任何模块直接 import `tushare`、`akshare`、XtQuant/QMT、旧 adapter、旧 registry。

## Current Progress
- `Phase 1` 已完成：`ProviderConfig` / `DataProviderSettings` 已迁入 `apps/data_center`，配置页与运行状态页已切通。
- `Phase 2` 已完成：主数据表、事实表、`IndicatorCatalog` seed、统一代码归一和基础查询链路已落地。
- `Phase 3-5` 已完成：统一 provider adapter、sync/query use cases、HTTP API 和主要业务消费侧均已切换到 `apps/data_center`。
- `Phase 6` 已完成：
  - 旧 macro datasource 路由与旧 market-data 路由已移除。
  - SDK / MCP / 配置中心 / 文档入口已统一对齐到 `data_center`。
  - 仓库内 `apps/data_center/infrastructure/` 之外已无直接 `tushare / akshare / xtquant` import。
  - 旧 `market_data` registry 运行链、cross-validator、bridge provider、legacy use cases 已从主代码和测试路径清理。

## Target Architecture
- `apps/data_center/domain/`
  - 定义统一实体与值对象：`ProviderConfig`、`ProviderCapability`、`ProviderHealth`、`ProviderPriority`、`AssetMaster`、`AssetAlias`、`IndicatorCatalog`、`MacroFact`、`PriceBar`、`QuoteSnapshot`、`FundNavFact`、`FinancialFact`、`ValuationFact`、`SectorMembershipFact`、`NewsFact`、`CapitalFlowFact`。
  - 定义统一规则：代码归一、单位归一、发布时间/新鲜度判定、数据质量状态、failover 选择规则。
  - 定义统一协议：`ProviderProtocol`、`RegistryProtocol`、`MasterDataRepositoryProtocol`、各事实表 `RepositoryProtocol`、各 `QueryServiceProtocol`。
- `apps/data_center/application/`
  - `ManageProviderConfigUseCase`、`TestProviderConnectionUseCase`、`GetProviderStatusUseCase`。
  - `SyncMacroUseCase`、`SyncPriceUseCase`、`SyncFundNavUseCase`、`SyncFinancialUseCase`、`SyncValuationUseCase`、`SyncSectorMembershipUseCase`、`SyncNewsUseCase`、`SyncCapitalFlowUseCase`。
  - `QueryMacroSeriesUseCase`、`QueryLatestQuoteUseCase`、`QueryPriceHistoryUseCase`、`QueryFundNavUseCase`、`QueryFinancialsUseCase`、`QueryValuationsUseCase`、`QuerySectorConstituentsUseCase`、`QueryNewsUseCase`、`QueryCapitalFlowsUseCase`、`ResolveAssetUseCase`。
  - Celery 任务全部汇总到 `data_center/application/tasks.py`，由中台统一调度同步。
- `apps/data_center/infrastructure/`
  - 外部源 adapter：Tushare、AKShare、EastMoney、QMT、FRED。
  - 统一跨域 registry：扩展现有 `market_data` registry 思路，不再只支持行情能力，而是支持 macro/price/fund/financial/valuation/sector/news/capital-flow 八类能力。
  - ORM models、repositories、provider factory、health state persistence、connection tester、raw payload audit。
- `apps/data_center/interface/`
  - 页面入口：`/data-center/`、`/data-center/providers/`、`/data-center/catalog/`、`/data-center/monitor/`。
  - API 入口：`/api/data-center/*`，由 serializers 做输入/输出校验，不承载业务逻辑。

## Core Data Model And Public Interfaces
- Provider 配置模型
  - 从现有 `macro` 配置迁入中台：`source_type`、`priority`、`is_active`、`api_key`、`api_secret`、`http_url`、`api_endpoint`、`extra_config`、`default_source`、`enable_failover`、`failover_tolerance`。
  - `source_type` 至少支持：`tushare`、`akshare`、`eastmoney`、`qmt`、`fred`。
  - `extra_config` 统一承载 provider 特定参数，如 QMT `client_path/data_dir/dividend_type`。
- 主数据模型
  - `AssetMasterModel`：统一股票、ETF、指数、基金代码和资产类型。
  - `AssetAliasModel`：同一资产的多市场代码/外部源代码映射。
  - `IndicatorCatalogModel`：统一宏观指标代码、频率、单位、发布时间规则、是否货币类。
- 标准事实表
  - `MacroFactModel`：标准字段 `indicator_code/value/unit/original_unit/reporting_period/period_type/published_at/source/revision_number/quality_status/fetched_at`。
  - `PriceBarModel`：标准字段 `asset_code/trade_date/open/high/low/close/volume/amount/source/adjustment/schema_version/fetched_at`。
  - `QuoteSnapshotModel`：标准字段 `asset_code/price/pre_close/open/high/low/change/change_pct/volume/amount/turnover_rate/source/observed_at/fetched_at`。
  - `FundNavFactModel`、`FinancialFactModel`、`ValuationFactModel`、`SectorMembershipFactModel`、`NewsFactModel`、`CapitalFlowFactModel` 均采用统一的 `source/schema_version/quality_status/fetched_at` 审计字段。
- Raw 审计表
  - 按数据域记录 `provider_name/request_type/request_params/payload/parse_status/error_message/schema_version/fetched_at`。
  - 不作为业务查询入口，只用于排障、字段漂移跟踪、集成调试。
- 对外 API 定稿
  - `/api/data-center/providers/`
  - `/api/data-center/providers/{id}/test/`
  - `/api/data-center/providers/status/`
  - `/api/data-center/assets/resolve/`
  - `/api/data-center/macro/series/`
  - `/api/data-center/prices/quotes/`
  - `/api/data-center/prices/history/`
  - `/api/data-center/funds/nav/`
  - `/api/data-center/financials/`
  - `/api/data-center/valuations/`
  - `/api/data-center/sectors/constituents/`
  - `/api/data-center/news/`
  - `/api/data-center/capital-flows/`
- 公共服务接口
  - `UnifiedPriceService` 迁入 `data_center`，成为唯一价格入口。
  - 新增 `UnifiedMacroService`、`UnifiedFundDataService`、`UnifiedFinancialDataService`、`UnifiedReferenceDataService`。
  - 旧模块对外若需要保留 facade，内部实现必须完全委托给 `data_center`。

## Migration And Cutover Plan
### Phase 1: 中台骨架与配置中心落地
- 创建 `apps/data_center` 四层目录、App 注册、路由、基础测试骨架。
- 迁移 `DataSourceConfig`、`DataProviderSettings`、provider inventory、连接测试页面/API 到 `data_center`。
- 把现有 `market_data` registry、health、priority、failover、circuit breaker 迁入 `data_center`。
- 保证 Tushare `http_url`、QMT `extra_config`、默认数据源和 failover 容差在新模型中语义不变。
- 完成 Config Center、导航、设置中心的入口改名与跳转。

### Phase 2: 主数据与标准事实表建立
- 落主数据表与标准事实表迁移。
- 实现统一代码归一规则：
  - 股票/ETF/指数/基金代码只在中台维护一份转换逻辑。
  - Tushare、AKShare、QMT、EastMoney 的代码映射不允许散落在业务模块。
- 实现统一单位规则：
  - 宏观货币类统一存“元”。
  - 比例/利率统一 `%`。
  - 时间字段统一 timezone-aware。
- 实现 raw payload 审计仓储与标准化写入流水。

### Phase 3: 外部源 adapter 全量迁入
- 迁入并统一封装：
  - Tushare：宏观、日线、基金、财务、估值、板块。
  - AKShare：宏观、行情备用、基金、新闻/部分公开数据。
  - EastMoney：实时行情、资金流、新闻。
  - QMT：本地终端行情与历史价。
  - FRED：宏观国际指标。
- 每个 adapter 仅返回标准化 DTO，不直接暴露 pandas/原始字段给上层。
- 连接测试改为“调用 adapter 标准解析路径”，不能只验证 HTTP 可达，避免出现“连接成功但取数解析失败”的假阳性。

### Phase 4: 八大数据域同步与查询完成
- 宏观：统一替代 `macro` 当前采集链。
- 价格：统一替代 `market_data/equity/realtime/backtest/simulated_trading` 中所有价格入口。
- 基金净值：统一替代 `fund` 当前外部源接入。
- 财务/估值：统一替代 `equity` 当前财务和估值 gateway。
- 板块成分：统一替代 `sector` 当前外部源 adapter。
- 新闻/资金流：统一替代 `market_data` 当前新闻与资金流实现。
- 为每个域提供 `Sync*`、`Query*`、标准事实表仓储和 provider failover 策略。

### Phase 5: 业务模块消费者一次性切换
- `regime`：只通过 `data_center` 读取宏观事实与指标序列。
- `equity`：只通过 `data_center` 获取历史价格、财务、估值。
- `fund`：只通过 `data_center` 获取基金净值与基础主数据。
- `backtest`：只通过 `data_center` 获取价格历史。
- `realtime`：只通过 `data_center` 获取实时与准实时行情。
- `simulated_trading`：只通过 `data_center` 的统一价格服务。
- `sector`、`factor`、`hedge`、`dashboard`、`terminal` 涉及数据接入的部分全部切换。
- 每切完一个模块，同步删除该模块中的旧 adapter/use case/import，不保留平行链路。

### Phase 6: 旧链路删除与仓库收口
- 删除旧 macro datasource 入口和旧 `market_data` 配置/状态入口。
- 删除旧 registry、旧 adapter、旧 datasource connection tester、旧 provider inventory 重复实现。
- 更新 `core/urls.py`、前端导航、模板、JS、SDK/MCP 名称映射和所有文档。
- 加入静态合规测试：除 `apps/data_center/infrastructure/` 外，任何模块 import 外部源 SDK 直接失败。

## Testing And Acceptance
- 单元测试
  - 代码归一、单位归一、发布时间计算、staleness 判定。
  - registry 的优先级、failover、熔断、恢复、健康状态。
  - 各 adapter 字段映射，特别是 Tushare/AKShare 真实返回列名变体。
- 集成测试
  - provider 配置 CRUD、连接测试、provider status。
  - 主数据解析与事实表写入。
  - 八类数据域的同步与查询链路。
  - 每个新 API 端点的状态码、Content-Type、错误体契约。
- 运行态测试
  - 本地 8000 服务验证 `/data-center/providers/` 页面、连接测试、状态展示。
  - 真实 Tushare 链路验证：
    - SHIBOR 宏观数据
    - `000001.SZ` 历史价/最新价
    - 至少一条基金净值
    - 至少一条财务或估值数据
- 回归测试
  - `regime / equity / fund / backtest / realtime / simulated_trading` 改造后主路径必须通过。
  - 旧路由、旧文档、旧前端引用必须全部清理。
- 验收标准
  - 仓库内外部数据接入只有 `apps/data_center` 一处。
  - 页面/API/SDK/MCP 都以 `data_center` 为唯一入口。
  - 真实 Tushare 与至少一个备用源可在本地运行态通过连接测试和真实取数测试。
  - 任一业务模块删除其旧 adapter 后功能仍完整。

## Assumptions And Defaults
- 最终模块名固定为 `apps/data_center`。
- 系统尚未上线，因此默认允许破坏旧入口和旧兼容层，不做长期双轨。
- 仍保留 `raw + standard` 双层存储，这是默认选择，不再另作取舍。
- `data_center` 只负责上游数据事实和统一查询，不承接 Regime、策略、回测等业务决策逻辑。
- 所有修改需同步更新 `docs/INDEX.md`、`docs/development/quick-reference.md`、配置中心矩阵、系统规格、相关架构文档，确保文档不再引用旧架构。
