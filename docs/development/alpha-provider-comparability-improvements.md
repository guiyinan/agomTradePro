# Alpha Provider 可比性改进总结

## 改进概述

针对 Alpha 模块 4 层降级机制可能导致的评分前后、横向不可比问题，实现了以下 5 个改进方案，确保数据可追溯性和可比性。

## 实施的改进

### 1. API 响应增强 ✅

**文件修改**：
- `apps/alpha/interface/serializers.py` - 已包含所有必要字段
- `apps/alpha/interface/views.py` - 返回完整元数据

**改进内容**：
- `AlphaResultSerializer` 包含 `source`、`status`、`staleness_days`、`latency_ms` 等元数据
- `StockScoreSerializer` 包含 `source`、`asof_date`、`intended_trade_date` 等审计字段
- API 响应明确标识数据来源，便于前端显示和追踪

**示例响应**：
```json
{
  "success": true,
  "source": "cache",
  "status": "available",
  "latency_ms": 150,
  "staleness_days": 1,
  "stocks": [
    {
      "code": "000001.SH",
      "score": 0.8,
      "rank": 1,
      "source": "cache",
      "asof_date": "2026-03-22",
      "intended_trade_date": "2026-03-22",
      ...
    }
  ]
}
```

### 1.1 ETF 降级真实数据回填 ✅

`ETFFallbackProvider` 现在在本地 `FundHoldingModel` 缺失时，会回退到 `akshare.fund_portfolio_hold_em` 拉取最近可用季度的真实 ETF 持仓，并将结果写回本地库。

这样处理后：

- `csi500` / `sse50` / `csi1000` 在 Qlib 与 cache 均不可用时，不再直接返回 `unavailable`
- 降级结果仍然基于真实持仓，而不是静态硬编码
- 远端 fallback 成功后会形成可复用的本地持仓缓存，后续请求优先命中数据库

### 1.2 Qlib 股票池展开与过期预检 ✅

Qlib 预测、训练、评估链路现在统一先将 `D.instruments()` 返回的股票池配置通过 `D.list_instruments(..., as_list=True)` 展开为真实成分股列表，再交给 `Alpha360`。

同时，`_execute_qlib_prediction()` 在入口处增加了本地数据覆盖预检。像 `bootstrap_alpha_cold_start` 这类直接调用预测函数的脚本，如果请求日期晚于本地 Qlib 数据最新交易日，不再抛出 `division by zero` 这类底层异常，而是返回可读原因，例如：

- `本地 Qlib 数据最新交易日为 2020-09-25，早于请求交易日 2026-04-06，请先同步 Qlib 数据`

这样处理后：

- 预测 / 训练 / 评估三条链使用同一套股票池解析逻辑
- 冷启动脚本与 Celery 任务的失败语义一致
- 运维侧可以直接区分“代码错误”和“本地 Qlib 数据未同步”两类问题

### 1.3 Qlib 自建诊断与 Recent 自建更新 ✅

新增 `python manage.py build_qlib_data --check-only`，用于统一诊断本地 Qlib 数据是否足够新鲜，以及当前是否具备自建更新前置条件。

同时，`python manage.py build_qlib_data` 已经不再只是诊断命令，而是会直接基于 Tushare 做“最近窗口”自建更新：

- 自动读取运行时 `provider_uri`
- 自动拉取 `csi300 / csi500 / sse50 / csi1000` 的最新成分股
- 增量写入 `calendars/day.txt`
- 增量写入 `instruments/*.txt`
- 增量写入 `features/<symbol>/*.day.bin`
- 保留显式 warning：如果当天日线尚未落地，会明确提示实际只更新到最近可用交易日

在本地公开数据仍旧停留在 `2020-09-25` 时，`--check-only` 会直接输出明确阻塞原因，例如：

- 本地或公开 Qlib 数据最新交易日过旧
- 当前是否已配置 `Tushare Token`
- 若已配置 token，可直接执行 `python manage.py build_qlib_data`

实测最近一次自建后，本地 `cn_data` 已从 `2020-09-25` 推进到 `2026-04-03`，并补齐了：

- `csi300 = 300`
- `csi500 = 500`
- `sse50 = 50`
- `csi1000 = 1000`

这样可以避免运维误以为是 `pyqlib` 本身异常，实际问题会被收敛成可执行的诊断与更新动作。

### 1.4 当天无日线时的显式交易日回退 ✅

Qlib 推理任务现在不再把“请求日期晚于本地最新日线，但仍在合理窗口内”的情况直接打成失败。

行为变更如下：

- 若请求日仍在最近可用交易日之后 10 天内，会自动回退到最新可用交易日执行推理
- 缓存仍写在原始 `intended_trade_date`
- `asof_date` 会记录真实推理日期
- `metrics_snapshot` / API metadata 会显式包含：
  - `requested_trade_date`
  - `effective_trade_date`
  - `trade_date_adjusted`
  - `trade_date_adjust_reason`

例如，请求 `2026-04-06` 而本地最新日线为 `2026-04-03` 时，返回会明确说明：

- `请求交易日 2026-04-06 尚无本地 Qlib 日线，已回退到最新可用交易日 2026-04-03。`

这样前端、API 和 MCP 都不会把这种情况误解为“静默过期”或“缓存脏数据”。

---

### 2. Provider 切换告警 ✅

**文件修改**：
- `apps/alpha/application/services.py`
  - 新增 `_create_fallback_alert()` 方法
  - 在 `get_scores_with_fallback()` 中检测降级并创建告警

**改进内容**：
- 检测 Provider 降级（从高优先级切换到低优先级）
- 自动创建 `AlphaAlertModel` 告警记录
- 告警类型：`model_degraded`
- 告警级别：`warning`

**告警信息**：
```python
AlphaAlertModel.objects.create(
    alert_type=AlphaAlertModel.ALERT_MODEL_DEGRADED,
    severity=AlphaAlertModel.SEVERITY_WARNING,
    title="Alpha Provider 降级",
    message="从 qlib 降级到 cache（原因：前序 Provider 不可用）",
    metadata={
        "current_provider": "cache",
        "attempted_providers": ["qlib", "cache"],
    }
)
```

---

### 3. 数据过滤工具 ✅

**文件修改**：
- `apps/alpha/interface/serializers.py`
  - `GetStockScoresRequestSerializer` 新增 `provider` 参数
- `apps/alpha/interface/views.py`
  - `get_stock_scores` 处理 `provider_filter` 参数
- `apps/alpha/application/services.py`
  - `get_scores_with_fallback()` 支持按 Provider 过滤
  - `get_stock_scores()` 传递 `provider_filter` 参数

**改进内容**：
- API 支持 `provider` 查询参数
- 强制使用指定 Provider（禁用自动降级）
- 支持 `qlib`、`cache`、`simple`、`etf` 四种选项

**API 使用示例**：
```bash
# 自动降级（默认）
GET /api/alpha/scores/?universe=csi300

# 强制使用 Cache
GET /api/alpha/scores/?universe=csi300&provider=cache

# 强制使用 Qlib
GET /api/alpha/scores/?universe=csi300&provider=qlib
```

---

### 4. 评分日志增强 ✅

**文件修改**：
- `apps/alpha/application/services.py`
  - `get_scores_with_fallback()` 增强日志记录

**改进内容**：
- 请求开始日志：`[AlphaRequest]` 标识
- Provider 尝试日志：`[AlphaProvider]` 标识
- 降级日志：`[AlphaFallback]` 标识
- 成功日志：`[AlphaSuccess]` 标识
- 失败日志：`[AlphaFailed]` 标识
- 告警日志：`[AlphaAlert]` 标识

**日志示例**：
```
[AlphaRequest] universe=csi300, date=2026-03-22, top_n=30, provider_filter=None
[AlphaProvider] 尝试 Provider: qlib (priority=1, 1/3)
[AlphaProvider] Provider qlib 返回失败: Qlib 不可用
[AlphaProvider] 尝试 Provider: cache (priority=10, 2/3)
[AlphaFallback] 从 qlib 降级到 cache (尝试了 1 个 Provider)
[AlphaSuccess] 成功从 cache 获取 30 只股票评分 (latency=45ms, staleness=1天)
[AlphaAlert] 创建降级告警: 从 qlib 降级到 cache（原因：前序 Provider 不可用）
```

---

### 5. 配置选项（固定 Provider）✅

**文件修改**：
- `apps/account/infrastructure/models.py`
  - `SystemSettingsModel` 新增 `alpha_fixed_provider` 字段
  - 新增 `get_runtime_alpha_fixed_provider()` 类方法
- `apps/alpha/application/services.py`
  - `get_scores_with_fallback()` 检查系统配置

**数据库迁移**：
- `apps/account/migrations/0021_add_alpha_fixed_provider.py`

**改进内容**：
- 系统配置支持固定使用指定 Provider
- 配置选项：自动降级（默认）/ 仅使用 Qlib / 仅使用缓存 / 仅使用 Simple / 仅使用 ETF
- API 请求的 `provider` 参数优先于系统配置

**配置示例**：
```python
# 系统配置（SystemSettingsModel）
settings = SystemSettingsModel.get_settings()
settings.alpha_fixed_provider = "qlib"  # 强制使用 Qlib
settings.save()

# 查询配置
fixed_provider = SystemSettingsModel.get_runtime_alpha_fixed_provider()
```

---

## 使用指南

### 对于前端开发

**显示评分来源**：
```javascript
// API 响应包含 source 字段
const response = await fetch('/api/alpha/scores/');
const data = await response.json();

// 显示来源标识
const sourceLabel = {
  'qlib': 'Qlib 模型',
  'cache': '缓存数据',
  'simple': '简单因子',
  'etf': 'ETF 降级',
}[data.source];

console.log(`评分来源: ${sourceLabel}`);
console.log(`数据状态: ${data.status === 'available' ? '可用' : '降级'}`);
if (data.staleness_days > 0) {
  console.log(`数据陈旧: ${data.staleness_days} 天`);
}
```

### 对于数据分析

**按 Provider 过滤查询**：
```python
# 使用 Python SDK
from sdk.agomtradepro import AgomTradeProClient

client = AgomTradeProClient()

# 只看 Qlib 评分
qlib_scores = client.alpha.get_scores(
    universe="csi300",
    provider="qlib"  # 强制使用 Qlib
)

# 只看缓存评分
cache_scores = client.alpha.get_scores(
    universe="csi300",
    provider="cache"  # 强制使用缓存
)
```

### 对于运维监控

**查看告警**：
```bash
# 查看最近告警
python manage.py shell

from apps.alpha.infrastructure.models import AlphaAlertModel

# 未解决的降级告警
alerts = AlphaAlertModel.objects.filter(
    alert_type=AlphaAlertModel.ALERT_MODEL_DEGRADED,
    is_resolved=False
)

for alert in alerts:
    print(f"[{alert.severity.upper()}] {alert.title}")
    print(f"消息: {alert.message}")
    print(f"元数据: {alert.metadata}")
    print()
```

---

## 风险缓解

### 前后不可比问题

**原因**：不同 Provider 的评分逻辑不同

**解决方案**：
1. ✅ 使用 `provider_filter` 参数固定使用单一 Provider
2. ✅ 配置 `alpha_fixed_provider` 全局固定 Provider
3. ✅ 在 API 响应中明确标识评分来源

### 横向不可比问题

**原因**：同一时刻不同资产可能来自不同 Provider

**解决方案**：
1. ✅ 系统单次查询保证所有股票来自同一 Provider
2. ✅ 使用 `provider_filter` 确保来源一致

### 数据污染问题

**原因**：不同来源的评分混合存储

**解决方案**：
1. ✅ 数据库 `provider_source` 字段明确标识来源
2. ✅ 查询时可按 `provider_source` 过滤
3. ✅ 完整的审计字段（`model_id`、`model_artifact_hash` 等）

---

## 测试覆盖

**新增测试**：`tests/unit/test_alpha_comparability.py`

**测试用例**：
- ✅ `test_provider_filter_parameter` - 测试 provider_filter 参数
- ✅ `test_fallback_alert_creation` - 测试降级告警创建
- ✅ `test_fixed_provider_config` - 测试固定 Provider 配置
- ✅ `test_detailed_logging` - 测试详细日志记录
- ✅ `test_api_response_metadata` - 测试 API 响应元数据

**测试结果**：
```
tests/unit/test_alpha_comparability.py::TestAlphaComparabilityImprovements::test_provider_filter_parameter PASSED
tests/unit/test_alpha_comparability.py::TestAlphaComparabilityImprovements::test_fallback_alert_creation PASSED
tests/unit/test_alpha_comparability.py::TestAlphaComparabilityImprovements::test_fixed_provider_config PASSED
tests/unit/test_alpha_comparability.py::TestAlphaComparabilityImprovements::test_detailed_logging PASSED
tests/unit/test_alpha_comparability.py::TestAlphaComparabilityImprovements::test_api_response_metadata PASSED
```

---

## 向后兼容性

所有改进均向后兼容：
- ✅ 现有 API 调用无需修改
- ✅ 默认行为保持不变（自动降级）
- ✅ 新增参数均为可选
- ✅ 所有现有测试通过

---

## 后续建议

### 短期（P1）
1. ✅ 前端显示评分来源
2. ✅ Dashboard 显示告警列表
3. ✅ 配置界面支持固定 Provider 设置

### 中期（P2）
1. 评分数据可视化：按 Provider 分组显示历史评分趋势
2. 评分对比工具：同一资产在不同 Provider 下的评分对比
3. 回测支持：指定使用特定 Provider 进行回测

### 长期（P3）
1. 评分标准化：将不同 Provider 的评分映射到统一范围
2. 评分质量评估：为每个评分添加质量评分指标
3. 自动化报表：定期生成 Provider 使用情况报告
