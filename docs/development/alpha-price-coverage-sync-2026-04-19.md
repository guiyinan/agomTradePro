# Alpha Price Coverage Sync

## 背景

- Alpha cache 当前混有两类资产代码：
  - 标准 Tushare 代码，如 `000001.SZ`
  - 历史脏格式，如 `"(Timestamp(...), 'SH600048')"`
- 本地 `data_center_price_bar` 覆盖资产过少，导致 Alpha 评估拿不到真实收益。

## 本次改动

- 新增 Alpha cache 代码解析器：
  - `apps/alpha/infrastructure/cache_code_parser.py`
- `cache_evaluation` 改为先规范化缓存代码，再查本地价格库：
  - `apps/alpha/infrastructure/cache_evaluation.py`
- 新增价格覆盖同步服务与管理命令：
  - `apps/data_center/infrastructure/alpha_price_coverage_sync.py`
  - `python manage.py sync_alpha_price_coverage`
- 同步服务改为多源回填：
  - `TushareGateway`
  - `AKShareEastMoneyGateway`
- `TushareGateway` 与 `AKShareEastMoneyGateway` 内部均新增腾讯历史价 fallback
- 当某只股票成功获取到新 bar 时，会先替换同日期范围内旧的同步源 bar，避免错误旧值残留。

## 同步策略

- 从 `AlphaScoreCacheModel.scores` 提取并规范化资产代码
- 通过 `AssetMasterBackfillService` 回填 `data_center_asset_master`
- 依次尝试 `Tushare -> AKShare` 拉取历史价格并写入 `data_center_price_bar`
- 若主源失败，会在 gateway 内部自动降级到腾讯历史价
- 默认日期范围：
  - 起点为最早 Alpha cache `intended_trade_date`
  - 终点为执行当天

## 2026-04-19 实测结果

- 执行命令：
  - `python manage.py sync_alpha_price_coverage`
- 实际同步结果：
  - `requested_count=42`
  - `synced_count=42`
  - `total_bars=588`
- 同步后本地覆盖：
  - `data_center_asset_master` 中 42 只 Alpha cache 股票全部存在
  - `data_center_price_bar` 中 42 只 Alpha cache 股票全部存在
  - 新写入 bar 主要来源为 `tushare`
