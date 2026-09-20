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

2026-09-19 修正：历史 DTO 和落库显式保留复权口径，成交量统一为股/份、成交额为元；同日不同复权数据不能被合并，同步只替换同口径旧数据。旧库已错标数据需单独核验修复，详见 [VPS 停更复盘](../reviews/vps-alpha-auto-refresh-2026-09-19.md)。

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

## 历史单位修复

`repair_legacy_price_units --plan <reviewed.json>` 默认只核验。`--apply --audit-dir <directory>` 对明确来源、资产类别、成交额是否存在和抓取时间上限的旧记录应用清单；每组记录数必须与审计一致，写前归档旧行并加行锁，修复后写 schema 版本和 revision，重跑不会重复缩放。保留行情日期与原 fetched_at，不修改评分缓存时间。生产修复清单见 `docs/reviews/vps-alpha-price-repair-2026-09-19.json`。已被旧解析器截断的不足一手部分无法从库内恢复，后续重新采集可恢复原始精度。

原始参考补录可显式调用 `TencentGateway.get_historical_prices(..., price_adjustment=PriceAdjustment.NONE)`；该模式只接受响应的 `day`，不能用 `qfqday` 替代。默认请求仍为前复权。2026-09-19 的生产修复后，当前 CSI300 300 个成分股补入 79,696 条缺失的未复权参考，保留独立 ingestion run；6 个来源末日滞后的标的单独记录，不将其日期推进。

### 已验证的全天停牌

2026-09-19 后续排查确认 601059.SH、601238.SH、601995.SH 的尾部行情缺失有逐日全天停牌证据。模型中台将此情况与无法验证的数据滞后区分，Qlib 仅排除当前停牌标的，发布 suspended_codes 和警告，不补造停牌行情、不推进停牌标的的 instrument 末日；通用及组合推理均限制目标日可用成分。

### 腾讯历史成交量按配置转换

腾讯同一日线接口存在板块单位差异，禁止统一乘 100。规则真源为 Config Center 键 data_center.tencent.history_volume_multipliers（JSON 字符串，形如 {"*":100,"688.SH":1,"689.SH":1}）。星号是显式默认规则，其他键为代码前缀.交易所，最长前缀优先。规则缺失或非法时失败关闭。该配置不改变实时报价接口的既有语义。

初始化或修订先运行 dry-run，再加 --apply：

```bash
python manage.py configure_tencent_history_units --rules docs/reviews/tencent-history-volume-rules-2026-09-19.json --environment production --actor operator --reason "Verified source volume units"
```

--apply 仅补丁该配置键并保留其他 active profile 值，定义也可在已有 Config Center Admin 中管理。2026-09-19 首轮 294,879 条腾讯科创板旧记录与 5,304 条新 raw 参考被过量缩放，已以独立事务/旧值归档修正为 legacy-units-20260919-star-v3；首次单位修复 JSON 留作操作审计，不再代表最终科创板倍数。

Qlib 增量复权须以同一天的既有 factor 和原始 adj_factor 配对，使用最近重叠日计算分母；连续刷新不得累乘公司行动。异常旧 factor 或 float32 溢出发布 MODEL_MARKET_LOCAL_FEATURE_INVALID，先备份隔离再重建。显式组合范围缺少目标日特征成分时发布 MODEL_MARKET_SCOPE_INCOMPLETE，任务不得裁剪范围或重用旧缓存冒充本次成功。
