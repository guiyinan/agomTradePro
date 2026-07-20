# Data Center 市场温度计

最后更新: 2026-07-20

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

当前快照与 AI capability 的结构化结果稳定包含 `score`、`band`、`effective_band`、`change_5d`、`change_20d`、`observed_at`、`threshold_source`、`overheating_risk` 和 `avoid_chasing`。其中 `overheating_risk` 在 `overheat/extreme` 为真，`avoid_chasing` 在 `hot/overheat/extreme` 为真；Terminal 文本摘要也展示数据时间和这两个风险结论。

## ETF 资金净流入同步口径

`CN_A_ETF_NET_FLOW` 通过数据中台同步，不由页面或 Dashboard 直接请求外部接口。它是市场温度计使用的 canonical 输入，底层拆成两个原子口径：

- `CN_A_ETF_NET_FLOW_MAIN`: ETF 主力净流入，来自 AKShare / EastMoney ETF spot 的 `f62` 聚合。
- `CN_A_ETF_SIZE_FLOW`: ETF 规模变化代理，来自 Tushare 协议兼容源的 `etf_share_size.total_size` 日差。

- Infrastructure provider 只负责取数：
  - AKShare `fund_etf_spot_em`
  - EastMoney `clist/get` 直连回退，读取 `f62` 主力净流入和 `f297` 数据日期
- Tushare 协议兼容源通过 `trade_cal` 找最近交易日，再用 `etf_share_size` 汇总沪深 ETF 总规模，计算当日规模变化
- Tushare ETF 规模代理按短日期区间分别批量拉取 SSE/SZSE，再按交易日聚合；任一交易所当日数据缺失时整日 fail closed，禁止把单市场规模误当全市场。
- Application `SyncMarketThermometerInputsUseCase` 会采集所有 active market providers，不再首个成功即停止。
- 对 `CN_A_ETF_NET_FLOW_MAIN` 多个同口径渠道返回同一日期数据时，按 1% 容差做一致性校验。
- 校验通过后只写入一条 `source=data_center_consensus` 的 canonical fact，`extra.candidates` 保留各渠道原始候选值。
- 只有单一渠道返回时允许写入，但 `extra.verification_status=single_source`，用于后续审计区分。
- 多渠道偏差超过 1% 时不静默切换，不写入 consensus，只记录 `mismatch` 审计结果。
- 如果主力净流入口径不可用，会降级使用 `CN_A_ETF_SIZE_FLOW`，写入 canonical `CN_A_ETF_NET_FLOW` 时标记 `extra.verification_status=fallback_proxy` 与 `extra.proxy_indicator=CN_A_ETF_SIZE_FLOW`。

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
- `python manage.py calculate_market_thermometer --skip-sync`
- `python manage.py calculate_market_thermometer --allow-blocked-write`
- `python manage.py import_investor_accounts --file <csv_path>`
- `python manage.py import_investor_accounts <csv_path>`
- `python manage.py import_investor_accounts --print-template`
- `python manage.py import_investor_accounts --file <csv_path> --dry-run`
- `python manage.py import_investor_accounts --file <csv_path> --dry-run --json`
- `python manage.py import_investor_accounts --file <csv_path> --dry-run --json --fail-on-warning`
- `python manage.py import_investor_accounts --file <csv_path> --value-unit 万户 --dry-run --json`

未传 `--as-of-date` 时，`sync_market_thermometer_inputs` 与 `calculate_market_thermometer` 会复用 Celery 任务的 as-of-date 解析规则：

- 交易日 `16:00` 前默认处理上一业务日，避免盘中写入尚未闭合的当日快照。
- 周末默认处理上一业务日。
- 显式传入 `--as-of-date YYYY-MM-DD` 时按指定日期执行，用于补跑历史日期。

`calculate_market_thermometer` 的手工命令默认先同步输入再计算。若计算结果标记为 `must_not_use_for_decision=True`，命令默认只输出计算结果并附带 `persisted=False` / `blocked_write_skipped=True`，不写入快照表。只有在确认需要保留 blocked 快照作为操作证据时，才使用 `--allow-blocked-write` 显式写入。`--skip-sync` 仅用于诊断，不建议作为常规刷新入口。

## 数据源覆盖

- 开户数 `CN_A_NEW_INVESTOR_ACCOUNTS` 现在由 `SyncMarketThermometerInputsUseCase` 通过 AKShare/EastMoney-backed `stock_account_statistics_em` 自动同步。
- AKShare 原始 `新增投资者-数量` 为“万户”口径，入库前统一转换为 canonical `户`，并在 `MacroFact.extra.original_unit` 保留 `万户` 供审计。
- 当 AKShare 的投资者表未覆盖近月时，系统会自动回退到上交所月报投资者页 `https://www.sse.com.cn/aboutus/publication/monthly/investor/` 的 `COMMON_SSE_TZZ_M_ALL_ACCT_C` 账户新开户状况表。该 fallback 同样按“万户”转 canonical `户`，并在 `MacroFact.extra` 写入 `proxy=sse_monthly_all_account_openings`、`source_url`、`source_sql_id`、`sse_query_month` 和原始 `raw_total_account_openings`。
- CSV 导入仍作为人工兜底入口，适用于远端数据源不可用、SSE fallback 不可达或需要补历史月份的情况；命令同时支持 `--file <csv_path>` 和位置参数路径，也可用 `--print-template` 输出最小模板。
- 导入正式写库前，先运行 `python manage.py import_investor_accounts --file <csv_path> --dry-run --json`，确认 `parsed_count`、`first_period`、`last_period` 和 `unit` 符合预期后再去掉 `--dry-run`。需要脚本化核验时使用 `--dry-run --json --fail-on-warning`，保留结构化输出并在存在 warning 时返回非零。
- 管理端 API `POST /api/data-center/market-thermometer/import/investor-accounts/` 与 CLI 使用同一套 use case，支持 `csv_text` / 文件上传、`dry_run`、`value_unit` 和 `fail_on_warning`；dry-run 有 warning 且 `fail_on_warning=true` 时返回 HTTP 400，不写入数据。
- dry-run 结果若出现 `warnings[].code=suspicious_low_account_count`，说明数值看起来低于 canonical `户` 口径，常见原因是 CSV 使用了 `万户`；此时不要直接导入，改用 `--value-unit 万户` 让命令自动换算并在 `extra.original_unit` / `extra.raw_value` 留痕。
- CSV 接受日期列 `reporting_period` / `date` / `month`，数值列 `value` / `accounts` / `new_accounts`；默认数值单位是 canonical `户`，若源文件是 `万户` 必须显式传 `--value-unit 万户`。

```csv
reporting_period,value
2026-05-31,12345
```

## 调度与故障语义

- Celery Beat 现在默认启用 `apps.data_center.application.tasks.refresh_market_thermometer_task`
- 调度窗口: 交易日 `17:20 / 18:20` 自动重试，统一刷新最近收盘后的温度计快照
- 任务流程: 先执行 `sync_market_thermometer_inputs`，再执行 `calculate_market_thermometer`
- 正式 Celery 调度保留 `must_not_use_for_decision=True` 快照写入语义，用于审计真实调度失败；该行为不同于手工命令的默认 blocked 写入保护
- `sync_market_thermometer_inputs` 现在对单个 provider 调用施加超时保护；超时或临时网络错误会记录到 raw audit，并继续尝试下一个可用源，而不是整条链路卡死
- 日频 freshness 统一按工作日年龄计算，周末不消耗 stale 预算；月频仍按自然日计算。该规则同时用于市场温度计、Pulse 日频输入和决策可靠性价格检查。
- 成交额的 provider timeout 以“交易日历 + 最近 5 个交易日全市场聚合”的生产耗时为基准设置；ETF 规模代理改成沪深两次区间批量请求，避免逐日逐市场调用天然越过 timeout。
- AKShare 新增开户的原始“万户”通过精确单位规则转换为 canonical“户”；规则缺失或单位不匹配仍 fail closed。
- `etf_net_flow` 的 verified sync 现在也会应用组件级超时 override，不再误用全局默认 `4s`
- 当本地环境因 `WinError 10013` 等权限限制直接阻断外网套接字时，ETF 的 EastMoney 直连 fallback 会快速失败并降级，不再在多轮重试里卡成超时
- 同样的本地权限拒绝语义现在也覆盖了 turnover / Tencent 历史行情 / 市场新闻链路：检测到 `WinError 10013` 时会跳过多轮重试和跨源空转，直接进入降级结果
- 当最新快照 `valid_component_count == 0` 且 `must_not_use_for_decision == True` 时，Dashboard 首页会回退展示最近一个仍有可用分数的历史快照，同时保留“仅供参考 / 数据链断开”的提示，避免把断链结果误显示为当天 `0.0`
