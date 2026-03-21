# 估值修复策略参数配置

> **最后更新**: 2026-03-11
> **版本**: V1.0
> **用途**: 在线调整估值修复检测参数，支持版本管理和回滚

## 概述

估值修复配置系统允许在线调整策略参数，无需修改代码即可优化检测逻辑。配置采用数据库持久化 + 版本管理，支持：

- **在线调参**: 通过 Web UI 或 API 修改参数
- **版本管理**: 保留历史配置版本，支持回滚
- **激活机制**: 同一时间只有一个配置生效
- **缓存优化**: 5 分钟缓存，减少数据库查询

## 配置参数说明

### 历史数据要求

| 参数 | 默认值 | 范围 | 说明 |
|-----|-------|------|------|
| `min_history_points` | 120 | ≥ 60 | 最小历史样本数，低于此值不进行修复检测 |
| `default_lookback_days` | 756 | ≥ 252 | 默认回看交易日数（约 3 年） |

### 修复确认参数

| 参数 | 默认值 | 范围 | 说明 |
|-----|-------|------|------|
| `confirm_window` | 20 | ≥ 5 | 修复确认窗口（交易日），反弹需持续此天数 |
| `min_rebound` | 0.05 | 0.01 - 0.5 | 最小反弹幅度（百分位），低于此值不算修复开始 |

### 停滞检测参数

| 参数 | 默认值 | 范围 | 说明 |
|-----|-------|------|------|
| `stall_window` | 40 | ≥ 10 | 停滞检测窗口（交易日） |
| `stall_min_progress` | 0.02 | 0.01 - 0.1 | 停滞最小进展阈值，窗口期内进展低于此值判定为停滞 |

### 阶段判定阈值

| 参数 | 默认值 | 范围 | 说明 |
|-----|-------|------|------|
| `target_percentile` | 0.50 | 0.30 - 0.70 | 目标百分位，修复完成的目标位置 |
| `undervalued_threshold` | 0.20 | 0.05 - 0.40 | 低估阈值，低于此值判定为低估 |
| `near_target_threshold` | 0.45 | 0.30 - 0.60 | 接近目标阈值，高于此值判定为接近目标 |
| `overvalued_threshold` | 0.80 | 0.60 - 0.95 | 高估阈值，高于此值判定为高估 |

**阶段判定逻辑**：
```
composite_percentile <= undervalued_threshold → UNDERVALUED
composite_percentile >= target_percentile → NEAR_TARGET / COMPLETED
composite_percentile >= overvalued_threshold → OVERVALUED
```

### 复合百分位权重

| 参数 | 默认值 | 范围 | 说明 |
|-----|-------|------|------|
| `pe_weight` | 0.6 | 0 - 1 | PE 权重 |
| `pb_weight` | 0.4 | 0 - 1 | PB 权重 |

**约束**: `pe_weight + pb_weight = 1.0`

复合百分位计算：
```python
composite_percentile = pe_percentile * pe_weight + pb_percentile * pb_weight
```

### 置信度计算参数

| 参数 | 默认值 | 范围 | 说明 |
|-----|-------|------|------|
| `confidence_base` | 0.4 | 0.1 - 0.8 | 基础置信度 |
| `confidence_sample_threshold` | 252 | ≥ 120 | 样本数阈值，超过此值获得奖励 |
| `confidence_sample_bonus` | 0.2 | 0 - 0.5 | 样本数奖励 |
| `confidence_blend_bonus` | 0.15 | 0 - 0.3 | PE+PB 双源可用奖励 |
| `confidence_repair_start_bonus` | 0.15 | 0 - 0.3 | 修复起点确认奖励 |
| `confidence_not_stalled_bonus` | 0.1 | 0 - 0.2 | 非停滞状态奖励 |

**置信度计算**：
```python
confidence = confidence_base
if sample_count >= confidence_sample_threshold:
    confidence += confidence_sample_bonus
if has_pe and has_pb:
    confidence += confidence_blend_bonus
if phase == REPAIR_STARTED or phase == REPAIRING:
    confidence += confidence_repair_start_bonus
if not is_stalled:
    confidence += confidence_not_stalled_bonus
```

### 其他阈值

| 参数 | 默认值 | 范围 | 说明 |
|-----|-------|------|------|
| `repairing_threshold` | 0.10 | 0.05 - 0.30 | REPAIRING 阶段阈值（相对起点） |
| `eta_max_days` | 999 | 100 - 9999 | ETA 最大天数，超过此值显示为 "> 999" |

## API 端点

### 获取当前激活配置

```http
GET /api/equity/config/valuation-repair/active/
```

**响应**:
```json
{
  "success": true,
  "data": {
    "id": 1,
    "version": 1,
    "is_active": true,
    "min_history_points": 120,
    "default_lookback_days": 756,
    "target_percentile": 0.50,
    ...
  }
}
```

### 列出所有配置版本

```http
GET /api/equity/config/valuation-repair/
```

**响应**:
```json
{
  "results": [
    {
      "id": 2,
      "version": 2,
      "is_active": true,
      "change_reason": "调高目标百分位",
      "effective_from": "2026-03-11",
      "created_at": "2026-03-11T10:00:00Z"
    },
    {
      "id": 1,
      "version": 1,
      "is_active": false,
      "change_reason": "初始配置",
      "effective_from": "2026-01-01",
      "created_at": "2026-01-01T00:00:00Z"
    }
  ]
}
```

### 创建新配置

```http
POST /api/equity/config/valuation-repair/
Content-Type: application/json

{
  "change_reason": "调高目标百分位至 55%",
  "target_percentile": 0.55
}
```

**响应**: 返回创建的配置（草稿状态，需激活）

### 激活配置

```http
POST /api/equity/config/valuation-repair/{id}/activate/
```

**响应**:
```json
{
  "success": true,
  "message": "配置 v2 已激活"
}
```

### 回滚到指定版本

```http
POST /api/equity/config/valuation-repair/{id}/rollback/
```

**响应**:
```json
{
  "success": true,
  "message": "已回滚到配置 v1"
}
```

### 清除缓存

```http
POST /api/equity/config/valuation-repair/clear-cache/
```

**用途**: 修改配置后立即生效（跳过 5 分钟缓存）

## SDK 使用

```python
from agomtradepro import AgomTradeProClient

client = AgomTradeProClient()

# 获取当前配置
config = client.equity.get_valuation_repair_config()
print(f"目标百分位: {config['target_percentile']}")

# 列出历史版本
configs = client.equity.list_valuation_repair_configs(limit=10)

# 创建新配置
new_config = client.equity.create_valuation_repair_config(
    change_reason="调高目标百分位",
    target_percentile=0.55,
)

# 激活配置
client.equity.activate_valuation_repair_config(new_config['id'])

# 回滚
client.equity.rollback_valuation_repair_config(old_config_id)
```

## MCP 工具

### get_valuation_repair_config

获取当前激活的估值修复策略参数配置。

### list_valuation_repair_configs

列出所有估值修复配置版本。

### create_valuation_repair_config

创建新的估值修复配置（草稿状态）。

### activate_valuation_repair_config

激活指定的估值修复配置。

### rollback_valuation_repair_config

回滚到指定的估值修复配置版本。

## Web UI

访问路径: `/equity/valuation-repair/config/`

功能：
1. **当前激活配置**: 展示当前生效的配置参数
2. **创建新配置**: 表单编辑，自动验证参数范围
3. **历史版本**: 列表展示所有版本，支持激活和加载到表单

## 配置优先级

配置加载优先级（由高到低）：

1. **缓存**: 5 分钟 TTL，减少数据库查询
2. **数据库激活配置**: 持久化的激活配置
3. **Django Settings**: 环境变量覆盖
4. **默认值**: 代码中的默认配置

```python
# apps/equity/application/config.py
def get_valuation_repair_config(use_cache: bool = True) -> ValuationRepairConfig:
    if use_cache:
        cached = cache.get(CACHE_KEY)
        if cached:
            return cached

    db_config = ValuationRepairConfigModel.get_active_config()
    if db_config:
        return db_config.to_domain_config()

    # 回退到默认值
    return DEFAULT_VALUATION_REPAIR_CONFIG
```

## 最佳实践

### 参数调整建议

1. **目标百分位 (`target_percentile`)**:
   - 保守策略: 0.45（提前止盈）
   - 激进策略: 0.55（追求更高收益）

2. **低估阈值 (`undervalued_threshold`)**:
   - 严格筛选: 0.15（只选极度低估）
   - 宽松筛选: 0.25（更多候选股）

3. **停滞窗口 (`stall_window`)**:
   - 短线策略: 20 天
   - 长线策略: 60 天

### 变更流程

1. 在 Web UI 或通过 API 创建新配置
2. 验证参数合理性
3. 激活配置
4. 监控效果，必要时回滚

### 回滚时机

- 检测到大量误判
- 候选池质量下降
- 系统告警增加

## 相关文档

- [估值修复跟踪计划](../plans/valuation-repair-tracking-plan.md)
- [股票估值判断逻辑](equity-valuation-logic.md)
- [估值修复生产上线指南](../plans/valuation-repair-production-rollout-guide.md)
