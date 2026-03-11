# 估值修复生产可信化改造与实施计划 v3

## Summary

本计划将现有“估值修复跟踪”从“功能可用”提升为“生产可验证、可追责、可监控、可逐步放行”的状态，目标用途限定为：

- 生产中的候选池辅助信号
- 不直接作为自动交易触发器
- 上线前必须通过严格门槛验收

本方案基于当前仓库实际情况制定：

- 估值修复功能已存在，核心算法、API、快照表、SDK/MCP 已有实现
- 当前估值修复直接读取本地 `equity_valuation` 表，不直接请求第三方数据源
- 仓库原先没有现成的“股票估值日同步”生产链，本期已在 `apps/equity` 内补齐最小可用实现
- 项目已有可复用的模式：
  - `django-celery-beat` 配置定时任务
  - Celery task 执行同步
  - provider health 接口
  - freshness check 与告警链

本次改造范围选择：

- 做“生产可信链”
- 交易用途限定为“候选池辅助”
- 上游数据源采用 `AKShare 主、Tushare 备`
- 首次历史回填窗口为 3 年
- 生产放行采用“严格门槛”

## Goals

本计划完成后，系统必须满足：

1. `equity_valuation` 中的估值数据具备来源、抓取时间、质量状态、口径信息，可审计。
2. 存在正式的股票估值同步链路，支持日常增量同步和 3 年历史回填。
3. 存在同步后质量校验链路，能识别覆盖率不足、空值/非法值、单日异常跳变、主备源显著偏差。
4. 估值修复只消费“通过质量门槛”的本地估值数据。
5. 存在 freshness / provider health / sync failure / data quality 告警。
6. 存在上线门槛和回滚门槛，避免未验证数据直接影响候选池排序。

非目标：

- 不把估值修复直接接入自动下单
- 不做多源全量事件溯源仓库
- 不在本期扩展到 CSI300/CSI500 universe 数据治理
- 不做分钟级或盘中估值同步

## Important API And Interface Changes

### Database schema changes

修改 `ValuationModel`，补齐可信数据字段：

- `source_provider`
- `source_updated_at`
- `fetched_at`
- `pe_type`
- `is_valid`
- `quality_flag`
- `quality_notes`
- `raw_payload_hash`

新增 `ValuationDataQualitySnapshotModel`，用于记录：

- `as_of_date`
- `expected_stock_count`
- `synced_stock_count`
- `valid_stock_count`
- `coverage_ratio`
- `valid_ratio`
- `missing_pb_count`
- `invalid_pb_count`
- `missing_pe_count`
- `jump_alert_count`
- `source_deviation_count`
- `primary_source`
- `fallback_used_count`
- `is_gate_passed`
- `gate_reason`

### Application additions

新增：

- `apps/equity/application/use_cases_valuation_sync.py`

当前已实现：

1. `SyncEquityValuationUseCase`
2. `BackfillEquityValuationUseCase`
1. `ValidateEquityValuationQualityUseCase`
2. `GetEquityValuationFreshnessUseCase`
3. `GetLatestEquityValuationQualityUseCase`

### Repair dependency changes

`ScanValuationRepairsUseCase` 默认只在最近一个质量 gate 通过的估值日期上运行；如果没有通过 gate 的质量快照，则返回：

```json
{
  "success": false,
  "error": "valuation data quality gate not passed"
}
```

### API additions

新增：

- `POST /api/equity/valuation-data/sync/`
- `POST /api/equity/valuation-data/validate/`
- `GET /api/equity/valuation-data/freshness/`
- `GET /api/equity/valuation-data/quality-latest/`

单股估值修复接口补充返回：

- `data_quality_flag`
- `data_source_provider`
- `data_as_of_date`

## Data Source And Quality Rules

### Upstream source strategy

- 主源：`AKShare`
- 备源：`Tushare`

当前代码已实现：

- AKShare 主源抓取：`total_mv / pe_ttm / pb`
- Tushare 备源抓取接口骨架：`daily_basic`
- 本地落库、质量标记、质量快照和 repair 门禁

当前限制：

- 若未配置 `TUSHARE_TOKEN`，备源不会启用
- AKShare 当前主抓口径以 `pe_ttm` 为主，因此会出现 `quality_flag="missing_pe"` 且 `pe_type="ttm"`

### Quality rules

对每个 `stock_code + trade_date`：

1. `pb is None` -> `missing_pb`, `is_valid=False`
2. `pb <= 0` -> `invalid_pb`, `is_valid=False`
3. `pe is None` -> `missing_pe`, `is_valid=True`
4. 与前一交易日相比：
   - `pb` 跳变绝对比例 > 60% -> `jump_alert`
   - `pe` 跳变绝对比例 > 80% -> `jump_alert`

### Gate rules

某交易日 `is_gate_passed=True` 的条件：

- `coverage_ratio >= 0.95`
- `valid_ratio >= 0.90`
- `invalid_pb_count == 0`
- `jump_alert_count / synced_stock_count <= 0.03`
- `source_deviation_count / synced_stock_count <= 0.05`

若任一条件失败：

- gate 不通过
- 不刷新 repair 快照
- 发送告警
- 保留上一交易日有效快照用于只读展示

## Implementation Sequence

### Milestone 1: 数据模型可信化

目标：

- 补齐估值底表可审计字段
- 保持现有 repair 功能不被破坏

必测项：

1. 老记录迁移后默认值正确
2. 新字段可正常写入/读取
3. `(stock_code, trade_date)` 唯一性不变
4. 新索引存在
5. 旧 repair API 仍可读历史数据

### Milestone 2: 质量校验与门禁

目标：

- 同步后自动形成质量快照和 gate 结果

必测项：

1. 覆盖率不足
2. `pb<=0`
3. `pe missing`
4. 异常跳变
5. freshness 超阈值
6. gate passed / failed 两种路径

### Milestone 3: Repair 与可信链整合

目标：

- 让估值修复只消费合格数据，并把质量信息透出给前端/SDK/MCP

必测项：

1. gate passed 时 `scan` 正常
2. gate failed 时 `scan` 返回业务错误
3. `status/history` 响应包含质量字段
4. 页面能展示 stale / gate fail 提示

### Milestone 4: 上游估值同步链

目标：

- 建立 AKShare 主、Tushare 备的日同步和回填能力

必测项：

1. AKShare 成功路径
2. AKShare 失败 -> Tushare 成功
3. 双源都失败
4. 回填分批逻辑
5. 重复同步不产生重复行

### Milestone 5: 上线前严格验收

上线门槛：

1. 3 年回填完成
2. 最近 20 个交易日覆盖率 >= 95%
3. 最近 20 个交易日 valid ratio >= 90%
4. 无 `invalid_pb`
5. repair API、quality API 自动化测试全部通过
6. 候选池辅助试运行至少 2 周

## File Plan

### New files

- `apps/equity/application/use_cases_valuation_sync.py`
- `apps/equity/application/tasks_valuation_sync.py`
- `apps/equity/infrastructure/valuation_source_gateways.py`
- `apps/equity/management/commands/sync_equity_valuation.py`
- `apps/equity/management/commands/backfill_equity_valuation.py`
- `apps/equity/management/commands/validate_equity_valuation_quality.py`
- `apps/equity/management/commands/setup_equity_valuation_sync.py`
- `tests/unit/equity/test_valuation_sync.py`
- `tests/unit/equity/test_valuation_sync_tasks.py`
- `tests/unit/equity/test_valuation_quality_gate.py`

### Modified files

- `apps/equity/domain/entities.py`
- `apps/equity/infrastructure/models.py`
- `apps/equity/infrastructure/repositories.py`
- `apps/equity/application/use_cases_valuation_repair.py`
- `apps/equity/interface/serializers.py`
- `apps/equity/interface/views.py`
- `sdk/agomsaaf/modules/equity.py`
- `sdk/agomsaaf_mcp/tools/equity_tools.py`
- `docs/plans/valuation-repair-tracking-plan.md`

## Test Cases And Scenarios

### Unit tests

- 质量快照统计准确
- gate 通过/失败边界
- freshness 状态分类
- repair scan 门禁

### API / integration tests

- `POST valuation-data/sync/`
- `POST valuation-data/validate/`
- `GET valuation-data/freshness/`
- `GET valuation-data/quality-latest/`
- gate fail 阻断 `scan`
- repair `status/history` 返回质量元数据

### SDK / MCP tests

- SDK `sync_valuation_data`
- SDK `validate_valuation_data`
- SDK `get_valuation_data_freshness`
- SDK `get_valuation_data_quality_latest`
- MCP 同名工具参数透传和返回结构一致

## MCP Usage Examples

以下示例面向 MCP 客户端调用顺序，目标是先治理数据，再读估值修复结果。

### 1. 每日同步后校验

先同步最近 1 天估值数据：

```python
sync_valuation_data(
    days_back=1,
    primary_source="akshare",
    fallback_source="tushare",
)
```

再生成当日质量快照：

```python
validate_valuation_data(
    primary_source="akshare",
)
```

### 2. 查询质量门禁和新鲜度

查看最近一次 quality gate：

```python
get_valuation_data_quality_latest()
```

期望关注这些字段：

- `as_of_date`
- `coverage_ratio`
- `valid_ratio`
- `is_gate_passed`
- `gate_reason`
- `fallback_used_count`

查看数据是否过期：

```python
get_valuation_data_freshness()
```

期望关注这些字段：

- `latest_trade_date`
- `lag_days`
- `status`
- `is_stale`

### 3. 只有 gate 通过时才刷新估值修复快照

```python
scan_valuation_repairs(
    universe="all_active",
    lookback_days=756,
)
```

如果质量门禁未通过，预期返回业务错误而不是刷新快照。

### 4. 查询候选列表

```python
list_valuation_repairs(
    universe="all_active",
    phase="repairing",
    limit=20,
)
```

适合页面列表、研究看板、候选池巡检。

### 5. 查询单只股票修复状态

```python
get_valuation_repair_status(
    stock_code="000001.SZ",
    lookback_days=756,
)
```

重点读取：

- `phase`
- `signal`
- `composite_percentile`
- `repair_progress`
- `data_quality_flag`
- `data_source_provider`
- `data_as_of_date`

### 6. 推荐的 MCP 日常调用顺序

```python
sync_valuation_data(days_back=1)
validate_valuation_data()
get_valuation_data_quality_latest()
get_valuation_data_freshness()
scan_valuation_repairs(universe="all_active")
list_valuation_repairs(phase="repairing", limit=20)
```

说明：

- `sync_valuation_data` 和 `validate_valuation_data` 属于数据治理工具
- `scan_valuation_repairs` 只应在 `is_gate_passed=True` 后执行
- 估值修复结果当前只适合作为候选池辅助信号，不应直接驱动自动交易

## 配置参数管理

估值修复策略参数已支持在线调整，无需修改代码。

### 配置优先级

1. 缓存（5 分钟 TTL）
2. 数据库激活配置
3. Django Settings
4. 代码默认值

### MCP 配置工具

```python
# 获取当前激活配置
get_valuation_repair_config()

# 列出历史版本
list_valuation_repair_configs(limit=20)

# 创建新配置
create_valuation_repair_config(
    change_reason=”调高目标百分位”,
    target_percentile=0.55,
)

# 激活配置
activate_valuation_repair_config(config_id=2)

# 回滚到指定版本
rollback_valuation_repair_config(config_id=1)
```

### Web UI

访问 `/equity/valuation-repair/config/` 进行可视化配置管理。

### 详细文档

参见 [估值修复策略参数配置](../business/valuation-repair-config.md)。

## Assumptions And Defaults

- 当前仓库允许继续在 `apps/equity` 内扩展，不新建独立 app
- 估值修复当前默认仍使用 `pe` 而非 `pe_ttm`
- 本期主源固定为 `AKShare`，备源固定为 `Tushare`
- 本期已实现最小可用 provider 同步器，但生产级 Tushare 备源联调依赖实际 token 配置
- gate 未通过时阻断 `scan`，但不阻断单股 `status/history`
- 交易用途固定为”候选池辅助”
- 策略参数可通过 Web UI 或 API 在线调整，无需重启服务
