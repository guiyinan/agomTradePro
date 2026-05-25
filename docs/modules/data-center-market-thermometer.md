# Data Center 市场温度计

最后更新: 2026-05-21

## 概述

市场温度计归属 `apps/data_center`，负责统一接入市场热度输入、标准化存储、温度聚合、阈值配置、用户阈值覆盖与快照查询。

第一期输入范围:

- 开户数 `CN_A_NEW_INVESTOR_ACCOUNTS`
- 全市场成交额 `CN_A_TOTAL_TURNOVER`
- 全市场融资余额 `CN_A_MARGIN_BALANCE`
- ETF 资金净流入 `CN_A_ETF_NET_FLOW`
- 市场新闻热度 `CN_A_MARKET_NEWS_COUNT`
- 市场新闻情绪 `CN_A_MARKET_NEWS_SENTIMENT`

内部聚合辅助指标:

- 市场新闻正向占比 `CN_A_MARKET_NEWS_POSITIVE_RATIO`

## 架构归属

- Domain:
  - 温度计配置、用户覆盖、快照、组件评分实体
  - 分段阈值、freshness、增速/分位评分规则
- Application:
  - `SyncMarketThermometerInputsUseCase`
  - `CalculateMarketThermometerUseCase`
  - `ManageMarketThermometerConfigUseCase`
  - `ManageMarketThermometerUserOverrideUseCase`
  - `ImportInvestorAccountsUseCase`
- Infrastructure:
  - `MarketThermometerConfigModel`
  - `MarketThermometerUserOverrideModel`
  - `MarketThermometerSnapshotModel`
  - provider adapter / CSV 导入 / NewsFact 日聚合
- Interface:
  - API、HTML 页面、management command

## API

- `GET /api/data-center/market-thermometer/current/`
- `GET /api/data-center/market-thermometer/history/?days=90`
- `GET|PUT|PATCH /api/data-center/market-thermometer/config/`
- `GET|PUT|PATCH|DELETE /api/data-center/market-thermometer/me/`
- `POST /api/data-center/market-thermometer/calculate/`
- `POST /api/data-center/market-thermometer/sync-inputs/`
- `POST /api/data-center/market-thermometer/import/investor-accounts/`

## 页面与命令

- 页面: `/data-center/market-thermometer/`
- Dashboard 卡片: 首页新增市场温度计卡片与 overheat/extreme attention 提示
- Macro 页面: `/macro/data/` 顶部同步展示市场温度计卡片，方便宏观事实浏览与市场热度同屏观察
- Terminal 命令: `market_temperature`
- AI capability: `terminal_command.market_temperature`

## 推荐链路集成

市场温度计现在已经进入账户 sizing 与 Dashboard Alpha 推荐链路，具体规则如下：

- Recommendation multiplier = `regime_factor * pulse_factor * market_temperature_factor * drawdown_factor`
- `market_temperature_factor` 不复用温度计阈值本身，而是由 `account.MacroSizingConfigModel` 单独配置，便于把“分段判定”和“仓位缩放”拆开管理
- 默认缩放规则：
  - `cold = 1.00`
  - `warm = 1.00`
  - `hot = 0.90`
  - `overheat = 0.75`
  - `extreme = 0.35`
- 默认 `extreme` 还会触发 `block_new_position_on_extreme=True`，对“当前无持仓的新建仓建议”直接阻断
- 如果温度计 payload 标记为 `must_not_use_for_decision=True`，推荐链路会降级为中性，不使用温度因子缩仓，也不会触发 extreme 阻断

## 可调参数

以下字段位于 `apps/account/infrastructure/models.py::MacroSizingConfigModel`，可单独调整：

- `market_temperature_cold_factor`
- `market_temperature_warm_factor`
- `market_temperature_hot_factor`
- `market_temperature_overheat_factor`
- `market_temperature_extreme_factor`
- `block_new_position_on_extreme`

这意味着：

- `data_center` 负责“温度怎么算、band 怎么判”
- `account` 负责“不同 band 对仓位和是否允许开新仓有什么影响”

两层权责分离，避免把交易动作权重硬编码回温度计模块。

## SDK / MCP

这组权重现在已经打通到 API、SDK 和 MCP：

- HTTP API:
  - `GET /api/account/macro-sizing-config/`
  - `PATCH /api/account/macro-sizing-config/`
  - `PUT /api/account/macro-sizing-config/`
- Python SDK:
  - `client.account.get_macro_sizing_config()`
  - `client.account.update_macro_sizing_config(payload, partial=True)`
- MCP tools:
  - `get_macro_sizing_config`
  - `update_macro_sizing_config`

权限边界：

- 读取：任意已认证用户可读当前生效配置
- 更新：仅 `staff/superuser` 可通过 API / SDK / MCP 创建新版本并切换生效配置

## 默认规则

- 短窗 `5`
- 中窗 `20`
- 长窗 `252`
- 月频长窗 `24`
- 日频 stale `3` 个交易日
- 月频 stale `45` 天
- 最少有效组件数 `4`

默认阈值:

- `cold < 35`
- `35 <= warm < 60`
- `60 <= hot < 75`
- `75 <= overheat < 85`
- `>= 85 extreme`

## 运维入口

- `python manage.py sync_market_thermometer_inputs`
- `python manage.py calculate_market_thermometer`

## 调度与故障语义

- Celery Beat 现在默认启用 `apps.data_center.application.tasks.refresh_market_thermometer_task`
- 调度窗口: 交易日 `17:20 / 18:20 / 19:20` 自动重试，统一刷新最近收盘后的温度计快照
- 任务流程: 先执行 `sync_market_thermometer_inputs`，再执行 `calculate_market_thermometer`
- 当快照 `valid_component_count == 0` 且 `must_not_use_for_decision == True` 时，Dashboard 首页不再把结果展示为 `0.0`，而是明确标识为“数据缺失”
- `python manage.py import_investor_accounts --file <csv_path>`
