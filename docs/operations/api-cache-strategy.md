# API 缓存策略文档

> **版本**: V1.0
> **更新日期**: 2026-03-04
> **负责模块**: M5 - 性能优化

## 概述

本文档描述 AgomSAAF 系统中高频 API 端点的缓存策略。目标是降低 Top 20 API 的 p95 延迟 >= 20%，缓存命中率 >= 50%。

## 架构

### 缓存组件

1. **`core/cache_utils.py`** - 缓存装饰器和工具
   - `cached_api` - API 视图缓存装饰器
   - `cached_function` - 函数缓存装饰器
   - `CacheKeyBuilder` - 缓存键生成器
   - `invalidate_pattern` - 模式匹配缓存失效

2. **Prometheus 指标**
   - `api_cache_hits_total` - 缓存命中计数
   - `api_cache_misses_total` - 缓存未命中计数
   - `api_cache_errors_total` - 缓存错误计数
   - `api_cache_latency_seconds` - 缓存操作延迟

### 缓存后端

| 环境 | 后端 | 配置 |
|------|------|------|
| 开发 | LocMemCache | `django.core.cache.backends.locmem.LocMemCache` |
| 生产 | Redis | `django.core.cache.backends.redis.RedisCache` |

## 高频端点缓存策略

### 1. 实时价格查询 (`/api/realtime/prices/`)

| 参数 | 值 |
|------|-----|
| Key Prefix | `realtime_prices` |
| TTL | 30 秒 |
| Vary On | `assets` (资产代码列表) |
| 适合缓存 | 是 |
| 理由 | 价格数据在短时间窗口内相对稳定 |

```python
@cached_api(key_prefix='realtime_prices', ttl_seconds=30, vary_on=['assets'])
def get(self, request, *args, **kwargs):
    ...
```

### 2. Regime 判定查询 (`/api/dashboard/v1/regime-quadrant/`)

| 参数 | 值 |
|------|-----|
| Key Prefix | `regime_quadrant` |
| TTL | 300 秒 (5 分钟) |
| Vary On | - |
| 适合缓存 | 是 |
| 理由 | Regime 状态在日内不会变化 |

```python
@cached_api(key_prefix='regime_quadrant', ttl_seconds=300)
def regime_quadrant_v1(request):
    ...
```

### 3. Dashboard 概览 (`/api/dashboard/v1/summary/`)

| 参数 | 值 |
|------|-----|
| Key Prefix | `dashboard_summary` |
| TTL | 180 秒 (3 分钟) |
| Vary On | - |
| Include User | 是 |
| 适合缓存 | 是 |
| 理由 | 聚合数据，短时间窗口内稳定 |

```python
@cached_api(key_prefix='dashboard_summary', ttl_seconds=180, include_user=True)
def dashboard_summary_v1(request):
    ...
```

### 4. 信号状态查询 (`/api/dashboard/v1/signal-status/`)

| 参数 | 值 |
|------|-----|
| Key Prefix | `signal_status` |
| TTL | 300 秒 (5 分钟) |
| Vary On | `limit` |
| Include User | 是 |
| 适合缓存 | 是 |
| 理由 | 信号列表变化频率低 |

```python
@cached_api(key_prefix='signal_status', ttl_seconds=300, vary_on=['limit'], include_user=True)
def signal_status_v1(request):
    ...
```

### 5. Alpha Provider 状态 (`/api/alpha/providers/status/`)

| 参数 | 值 |
|------|-----|
| Key Prefix | `alpha_provider_status` |
| TTL | 60 秒 |
| Vary On | - |
| 适合缓存 | 是 |
| 理由 | Provider 状态变化频率低，健康检查用 |

### 6. Alpha 股票池列表 (`/api/alpha/universes/`)

| 参数 | 值 |
|------|-----|
| Key Prefix | `alpha_universes` |
| TTL | 3600 秒 (1 小时) |
| Vary On | - |
| 适合缓存 | 是 |
| 理由 | 股票池配置基本不变 |

### 7. Alpha 健康检查 (`/api/alpha/health/`)

| 参数 | 值 |
|------|-----|
| Key Prefix | `alpha_health` |
| TTL | 30 秒 |
| Vary On | - |
| 适合缓存 | 是 |
| 理由 | 健康状态短时间稳定 |

## 缓存 TTL 预设

定义在 `core/cache_utils.py` 中的 `CACHE_TTL`：

```python
CACHE_TTL = {
    # 实时数据 (短 TTL)
    'realtime_price': 30,          # 30 秒
    'realtime_health': 60,         # 1 分钟

    # 近实时数据 (中 TTL)
    'regime_current': 300,         # 5 分钟
    'regime_history': 900,         # 15 分钟
    'signal_list': 300,            # 5 分钟
    'signal_detail': 600,          # 10 分钟

    # 参考数据 (长 TTL)
    'indicator_list': 3600,        # 1 小时
    'asset_info': 1800,            # 30 分钟
    'sector_list': 3600,           # 1 小时

    # 计算结果 (中长 TTL)
    'dashboard_summary': 180,      # 3 分钟
    'allocation_advice': 600,      # 10 分钟
    'backtest_result': 3600,       # 1 小时

    # 外部数据 (长 TTL 减少 API 调用)
    'macro_series': 900,           # 15 分钟
    'economic_calendar': 3600,     # 1 小时
}
```

## 缓存失效策略

### 主动失效

1. **Regime 缓存失效** - `/regime/clear-cache/`
   - 当新的宏观数据同步后触发
   - 清除所有 Regime 相关缓存

2. **信号状态失效** - 信号状态变更时
   - 创建/更新/删除信号时清除相关缓存
   - 使用模式匹配 `signal_status:*`

3. **定时失效**
   - 基于 TTL 自动过期
   - Redis 使用 EXPIRE 机制

### 缓存绕过

所有缓存的端点支持 `force_refresh=1` 查询参数来绕过缓存：

```python
GET /api/regime/?force_refresh=1
```

## 监控指标

### Prometheus 查询示例

```promql
# 缓存命中率
rate(api_cache_hits_total[5m]) / (rate(api_cache_hits_total[5m]) + rate(api_cache_misses_total[5m]))

# 各端点缓存命中率
sum by (endpoint) (rate(api_cache_hits_total[5m])) / sum by (endpoint) (rate(api_cache_hits_total[5m]) + rate(api_cache_misses_total[5m]))

# 缓存延迟 P95
histogram_quantile(0.95, rate(api_cache_latency_seconds_bucket[5m]))

# 缓存错误率
rate(api_cache_errors_total[5m]) / rate(api_cache_hits_total[5m])
```

### 告警规则建议

```yaml
- alert: LowCacheHitRate
  expr: |
    rate(api_cache_hits_total[5m]) / (rate(api_cache_hits_total[5m]) + rate(api_cache_misses_total[5m])) < 0.5
  for: 10m
  labels:
    severity: warning
  annotations:
    summary: "缓存命中率低于 50%"
    description: "端点 {{ $labels.endpoint }} 的缓存命中率为 {{ $value }}%"

- alert: HighCacheLatency
  expr: |
    histogram_quantile(0.95, rate(api_cache_latency_seconds_bucket[5m])) > 0.1
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "缓存延迟过高"
    description: "端点 {{ $labels.endpoint }} 的缓存 P95 延迟为 {{ $value }}s"

- alert: CacheErrorRate
  expr: |
    rate(api_cache_errors_total[5m]) > 0.1
  for: 5m
  labels:
    severity: critical
  annotations:
    summary: "缓存错误率过高"
    description: "端点 {{ $labels.endpoint }} 的错误率为 {{ $value }}/s"
```

## 使用指南

### 为新端点添加缓存

1. 导入缓存装饰器：
   ```python
   from core.cache_utils import cached_api, CACHE_TTL
   ```

2. 应用装饰器：
   ```python
   @cached_api(
       key_prefix='my_endpoint',
       ttl_seconds=CACHE_TTL['my_category'],
       vary_on=['param1', 'param2'],
       include_user=True,
   )
   def my_view(request):
       ...
   ```

3. 更新本文档，记录端点缓存策略

### 缓存键设计原则

- 使用描述性的前缀
- 包含影响响应的查询参数
- 用户相关数据包含用户 ID
- 避免键过长 (> 200 字符)

### 测试缓存功能

```python
# tests/unit/test_cache_utils.py
def test_cache_decorator():
    from core.cache_utils import cached_api

    @cached_api(key_prefix='test', ttl_seconds=60)
    def test_view(request):
        return {'data': 'value'}

    # 首次调用 - 缓存未命中
    response1 = test_view(mock_request)

    # 第二次调用 - 缓存命中
    response2 = test_view(mock_request)

    # 验证缓存指标
    assert cache_hits_total.labels(endpoint='test', key_prefix='test')._value._value > 0
```

## 性能目标

| 指标 | 目标值 | 当前值 | 状态 |
|------|--------|--------|------|
| Top 20 API p95 延迟下降 | >= 20% | TBD | 测量中 |
| 缓存命中率 | >= 50% | TBD | 测量中 |
| 缓存 P95 延迟 | < 50ms | TBD | 测量中 |

## 变更记录

| 日期 | 版本 | 变更内容 |
|------|------|----------|
| 2026-03-04 | V1.0 | 初始版本，定义缓存策略 |
