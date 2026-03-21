# 估值修复生产联调指南

## 目标

这份指南用于把“估值修复跟踪 + 估值数据可信链”联调到生产环境。

适用范围：

- 已完成代码部署
- Django migration 已执行
- Celery worker / beat 可正常运行
- 生产环境准备接入 `AKShare` 主源与 `Tushare` 备源

这份文档是操作指南，不替代实施计划。设计和约束以 [valuation-repair-tracking-plan.md](/D:/githv/agomTradePro/docs/plans/valuation-repair-tracking-plan.md) 为准。

## 联调目标

生产联调通过后，系统应满足：

1. 本地 `equity_valuation` 能写入估值数据和可信元数据
2. 每日同步链可以完成 `sync -> validate -> gate -> repair scan`
3. `scan` 只会在质量门禁通过时刷新快照
4. API / SDK / MCP 能看到最新 freshness 和 quality 状态
5. 页面和列表能反映“数据日期”和“是否 stale”

## 前置检查

联调前先确认：

1. 部署代码已包含 commit `d40ddef`
2. 已执行 `python manage.py migrate --noinput`
3. Celery worker 已启动
4. Celery beat 已启动
5. 生产环境可访问 AKShare
6. 已配置 `TUSHARE_TOKEN`
7. `StockInfoModel.is_active=True` 的股票基础信息已存在

建议先执行：

```bash
python manage.py check
python manage.py showmigrations equity
```

期望：

- `check` 无报错
- `equity` 下 `0004`、`0005`、`0006` 都已应用

## 环境配置

至少确认这些配置项：

```bash
TUSHARE_TOKEN=your_token
DJANGO_SETTINGS_MODULE=core.settings.production
```

说明：

- `AKShare` 为主源，不需要额外 token
- `Tushare` 是备源，没有 `TUSHARE_TOKEN` 时无法做真实备源联调
- 若生产通过 systemd、Docker Compose 或 `.env` 管理变量，需保证 worker 和 web 进程都能读取相同配置

## 数据库检查

联调前确认以下表已存在：

- `equity_valuation`
- `equity_valuation_repair_tracking`
- `equity_valuation_quality_snapshot`

建议检查字段是否齐全：

```sql
SELECT column_name
FROM information_schema.columns
WHERE table_name = 'equity_valuation';
```

至少应包含：

- `source_provider`
- `source_updated_at`
- `fetched_at`
- `pe_type`
- `is_valid`
- `quality_flag`
- `quality_notes`
- `raw_payload_hash`

## 联调顺序

严格按下面顺序执行，不要先跑 `scan`。

### 第 1 步：手动同步 1 天数据

先用单只股票做小样本验证：

```bash
python manage.py sync_equity_valuation --stock-code 000001.SZ --days-back 10
```

再做全量最近 1 天同步：

```bash
python manage.py sync_equity_valuation --days-back 1
```

期望结果：

- 命令返回 `synced_count > 0`
- 如主源失败且备源成功，`fallback_used_count > 0`
- 不应出现整批 `error_count` 异常飙升

数据库抽查：

```sql
SELECT stock_code, trade_date, source_provider, pe_type, is_valid, quality_flag
FROM equity_valuation
WHERE stock_code = '000001.SZ'
ORDER BY trade_date DESC
LIMIT 10;
```

验收点：

- `source_provider` 为 `akshare` 或 `tushare`
- `quality_flag` 有明确值，不为空
- `fetched_at` 已写入

### 第 2 步：生成质量快照

```bash
python manage.py validate_equity_valuation_quality
```

或指定日期：

```bash
python manage.py validate_equity_valuation_quality --date 2026-03-10
```

期望结果：

- 生成一条 `equity_valuation_quality_snapshot`
- 返回 `coverage_ratio`
- 返回 `valid_ratio`
- 返回 `is_gate_passed`

数据库抽查：

```sql
SELECT as_of_date, coverage_ratio, valid_ratio, is_gate_passed, gate_reason
FROM equity_valuation_quality_snapshot
ORDER BY as_of_date DESC
LIMIT 5;
```

验收点：

- 质量快照日期和同步日期一致
- gate 失败时有 `gate_reason`
- `invalid_pb_count` 不应大于 0；若大于 0，本轮联调不通过

### 第 3 步：检查 freshness

```bash
curl http://127.0.0.1:8000/api/equity/valuation-data/freshness/
```

或通过 SDK / MCP 查询。

验收点：

- `latest_trade_date` 正确
- `lag_days` 合理
- `status` 为 `fresh` 或 `warning`
- 不应直接进入 `critical`

### 第 4 步：质量通过后再跑 repair scan

先确认最近 quality snapshot 是 `is_gate_passed=true`。

然后执行：

```bash
curl -X POST http://127.0.0.1:8000/api/equity/valuation-repair/scan/ \
  -H "Content-Type: application/json" \
  -d "{\"universe\":\"all_active\",\"lookback_days\":756}"
```

验收点：

- gate 通过时返回 `success=true`
- gate 未通过时返回业务错误，不刷新快照
- `saved_count` 大于等于 0，且 phase 统计存在

数据库抽查：

```sql
SELECT stock_code, current_phase, signal, as_of_date, source_universe
FROM equity_valuation_repair_tracking
ORDER BY updated_at DESC
LIMIT 20;
```

### 第 5 步：联调页面、SDK 和 MCP

页面：

- 打开 `/equity/valuation-repair/`
- 检查列表是否能展示
- 点击单只股票，确认详情和图表可加载

SDK 示例：

```python
from agomtradepro import AgomTradeProClient

client = AgomTradeProClient(base_url="http://127.0.0.1:8000/api")

print(client.equity.get_valuation_data_quality_latest())
print(client.equity.get_valuation_data_freshness())
print(client.equity.list_valuation_repairs(phase="repairing", limit=10))
```

MCP 推荐调用顺序：

```python
sync_valuation_data(days_back=1)
validate_valuation_data()
get_valuation_data_quality_latest()
get_valuation_data_freshness()
scan_valuation_repairs(universe="all_active")
list_valuation_repairs(phase="repairing", limit=20)
get_valuation_repair_status(stock_code="000001.SZ", lookback_days=756)
```

验收点：

- SDK / MCP 返回字段与 API 一致
- `status/history` 中能看到 `data_quality_flag`
- `data_source_provider`
- `data_as_of_date`

## 定时任务联调

生产建议使用：

```bash
python manage.py setup_equity_valuation_sync --hour 18 --minute 30
```

期望创建或更新这些任务：

- `equity-valuation-daily-sync`
- `equity-valuation-quality-validate`
- `equity-valuation-freshness-check`

说明：

- `equity-valuation-daily-sync` 当前应执行编排任务 `sync_validate_scan_equity_valuation_task`
- 日常链路应由这条任务完成 `sync -> validate -> gate -> scan`

建议在 Django Admin 或数据库中确认 `django_celery_beat_periodictask` 已创建对应记录。

## 联调验收标准

生产联调最低通过标准：

1. 手动同步 1 天成功
2. 手动质量校验成功
3. freshness 状态正常
4. gate 通过时 `scan` 能刷新快照
5. gate 不通过时 `scan` 被阻断
6. 页面、SDK、MCP 至少各完成 1 次成功读取
7. 抽样 10 只股票人工核对 PE/PB/PB 分位是否合理

建议扩大到发布前验收：

1. 连续 5 个交易日同步成功
2. 最近 5 个交易日无 `invalid_pb`
3. 最近 5 个交易日 `coverage_ratio >= 0.95`
4. 最近 5 个交易日 `valid_ratio >= 0.90`
5. fallback 使用次数可解释

## 常见故障排查

### 1. `scan` 返回 quality gate not passed

排查顺序：

1. 执行 `validate_equity_valuation_quality`
2. 查看最近 quality snapshot
3. 检查 `gate_reason`
4. 先修复底层估值数据，再重跑 `scan`

### 2. `fallback_used_count` 很高

说明：

- AKShare 主源稳定性可能有问题
- 或主源字段缺失较多

处理：

1. 抽样对比 AKShare 与 Tushare 返回
2. 检查网络和代理
3. 检查 token 和 provider 限流

### 3. freshness 进入 `critical`

处理：

1. 先确认当天是否交易日
2. 检查定时任务是否执行
3. 检查 worker / beat 是否正常
4. 手动执行一次 `sync_equity_valuation --days-back 1`

### 4. quality snapshot 存在但页面没有数据

排查：

1. 确认 `scan` 是否执行
2. 确认 gate 是否通过
3. 检查 `equity_valuation_repair_tracking` 是否有 active 快照
4. 检查页面请求的 `valuation-repair-list` 响应

## 回滚口径

如果生产联调失败，按下面顺序回滚：

1. 停止新的定时同步任务
2. 不删除 `equity_valuation` 原始数据
3. 暂停 `scan`，避免继续刷新 repair 快照
4. 页面和 SDK 只读展示最近一次已通过 gate 的快照

不建议：

- 直接删除 `equity_valuation_quality_snapshot`
- 直接清空 `equity_valuation_repair_tracking`
- 在未定位根因前反复全量回填

## 上线后首周观察项

上线后至少连续观察 5 个交易日：

- 每日同步成功率
- fallback 使用次数
- freshness 状态
- coverage_ratio
- valid_ratio
- jump_alert_count
- source_deviation_count
- repair scan 成功次数
- 被 gate 阻断次数

如果这些指标稳定，再考虑把“候选池辅助信号”使用范围扩大。
