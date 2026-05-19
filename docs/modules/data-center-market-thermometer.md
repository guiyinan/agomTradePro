# Data Center 市场温度计

最后更新: 2026-05-19

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
- Terminal 命令: `market_temperature`
- AI capability: `terminal_command.market_temperature`

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
- `python manage.py import_investor_accounts --file <csv_path>`
