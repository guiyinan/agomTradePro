# 性能调优指南

> 版本: 1.0
> 更新时间: 2026-03-04

## 概述

本文档介绍 AgomSAAF 的性能监控和调优方法，包括：
- 慢查询检测和分析
- 数据库查询优化
- API 缓存策略
- Prometheus 监控指标

## 慢查询分析

### 启用查询分析器

在 `.env` 文件中配置：

```bash
# 启用查询性能分析
QUERY_PROFILER_ENABLED=True
# 慢查询阈值（毫秒）
SLOW_QUERY_THRESHOLD_MS=100
```

### 查看慢查询日志

日志会记录以下信息：

```json
{
  "event": "slow_query",
  "sql": "SELECT * FROM regime_regimestate WHERE ...",
  "sql_hash": 1234567890,
  "duration_ms": 150.5,
  "threshold_ms": 100,
  "operation": "SELECT",
  "trace_id": "abc123def",
  "request_path": "/api/regime/states/",
  "request_method": "GET"
}
```

### 分析慢查询日志

使用分析脚本生成报告：

```bash
# 基本分析
python scripts/analyze_slow_queries.py logs/django.log

# 只显示 Top 10
python scripts/analyze_slow_queries.py logs/django.log --top 10

# 按操作类型过滤
python scripts/analyze_slow_queries.py logs/django.log --operation SELECT

# 指定时间范围
python scripts/analyze_slow_queries.py logs/django.log --start "2026-03-01" --end "2026-03-02"

# 输出 JSON 格式
python scripts/analyze_slow_queries.py logs/django.log --json
```

### 报告示例

```
============================================================
           Slow Query Analysis Report
============================================================

📊 Overall Statistics:
   Total slow queries:     1,234
   Total slow query time:  45,678.9 ms
   Requests affected:      456
   Avg per request:        100.2 ms

🔍 By Operation Type:
   SELECT  :  1,100 ( 89.1%)
   UPDATE  :    100 (  8.1%)
   INSERT  :     30 (  2.4%)
   DELETE  :      4 (  0.3%)

🐌 Top 20 Slowest Query Patterns:
------------------------------------------------------------

   #1. SELECT * FROM regime_regimestate WHERE asof_date = ? ORDER BY ?
       Count:   500
       Total:   15000.0 ms
       Average: 30.0 ms
       Max:     150.0 ms
```

## 常见查询优化模式

### N+1 查询问题

**检测**：日志中会记录 `n_plus_one_warning`

```json
{
  "event": "n_plus_one_warning",
  "pattern": "SELECT * FROM signal_investmentsignal WHERE asset_id = ?",
  "count": 100,
  "total_time_ms": 5000
}
```

**解决方案**：使用 `select_related` 或 `prefetch_related`

```python
# ❌ N+1 查询
signals = InvestmentSignal.objects.filter(asset_code='000001.SH')
for signal in signals:
    print(signal.asset.name)  # 每次都查询 asset

# ✅ 使用 select_related
signals = InvestmentSignal.objects.select_related('asset').filter(asset_code='000001.SH')
for signal in signals:
    print(signal.asset.name)  # 不再额外查询
```

### 缺少索引

**检测**：分析脚本显示相同模式的查询次数很高但平均时间很长

**解决方案**：添加数据库索引

```python
class InvestmentSignal(models.Model):
    asset_code = models.CharField(max_length=20, db_index=True)  # 添加索引
    created_at = models.DateTimeField(db_index=True)
    signal_type = models.CharField(max_length=50)

    class Meta:
        indexes = [
            models.Index(fields=['asset_code', '-created_at']),  # 复合索引
            models.Index(fields=['signal_type', 'created_at']),
        ]
```

### 大结果集查询

**检测**：单次查询时间超过 500ms

**解决方案**：
1. 使用分页
2. 只选择需要的字段（`only()`/`defer()`）
3. 使用 `iterator()` 处理大结果集

```python
# ✅ 只选择需要的字段
signals = InvestmentSignal.objects.only(
    'asset_code', 'signal_type', 'created_at'
).filter(asset_code='000001.SH')

# ✅ 大结果集使用 iterator
for signal in InvestmentSignal.objects.iterator(chunk_size=100):
    process(signal)
```

## 数据库连接配置

### 连接池配置

生产环境建议使用 pgBouncer 或类似连接池工具：

```ini
# pgbouncer.ini
[databases]
agomsaaf = host=localhost port=5432 dbname=agomsaaf

[pgbouncer]
pool_mode = transaction
max_client_conn = 100
default_pool_size = 25
```

### Django 配置

```python
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'agomsaaf',
        'USER': 'postgres',
        'PASSWORD': '***',
        'HOST': 'localhost',
        'PORT': '5432',
        'CONN_MAX_AGE': 600,  # 连接复用 10 分钟
        'OPTIONS': {
            'connect_timeout': 10,
            'options': '-c statement_timeout=30000',  # 30 秒查询超时
        }
    }
}
```

## Prometheus 指标

### 查询延迟监控

```
# 数据库查询延迟分布（按操作类型）
histogram_quantile(0.95, sum(rate(db_query_latency_seconds_bucket[5m])) by (le, operation))

# 慢查询率
sum(rate(db_query_latency_seconds_bucket{le="0.1"}[5m])) by (operation) /
sum(rate(db_query_latency_seconds_count[5m])) by (operation)
```

### API 延迟监控

```
# P95 API 延迟
histogram_quantile(0.95, sum(rate(api_request_latency_seconds_bucket[5m])) by (le, endpoint))

# API 错误率
sum(rate(api_error_total[5m])) / sum(rate(api_request_total[5m])) * 100
```

## 缓存策略

### Redis 缓存配置

```python
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.redis.RedisCache',
        'LOCATION': 'redis://127.0.0.1:6379/1',
        'TIMEOUT': 900,  # 默认 15 分钟
        'KEY_PREFIX': 'agomsaaf',
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
            'SOCKET_CONNECT_TIMEOUT': 5,
            'SOCKET_TIMEOUT': 5,
            'CONNECTION_POOL_KWARGS': {'max_connections': 50}
        }
    }
}
```

### 缓存使用示例

```python
from django.core.cache import cache
from core.cache import cache_result

# 使用装饰器缓存
@cache_result(timeout=300, key_prefix='regime:current')
def get_current_regime():
    return RegimeState.objects.latest('asof_date')

# 手动缓存
def get_regime_states():
    cache_key = 'regime:states:all'
    states = cache.get(cache_key)

    if states is None:
        states = list(RegimeState.objects.all())
        cache.set(cache_key, states, timeout=300)

    return states
```

## 性能测试

### 使用 django-silk

开发环境可以启用 django-silk 进行性能分析：

```bash
pip install django-silk
```

```python
# settings.py
INSTALLED_APPS = [
    ...
    'silk',
]

MIDDLEWARE = [
    ...
    'silk.middleware.SilkyMiddleware',
]
```

访问 `/silk/` 查看请求分析。

### 基准测试

```bash
# 使用 pytest-benchmark
pytest tests/benchmark/test_api_performance.py --benchmark-only
```

## 故障排查

### 慢查询突然增多

1. **检查数据库锁**
   ```sql
   SELECT * FROM pg_stat_activity WHERE state != 'idle';
   ```

2. **检查索引是否被使用**
   ```sql
   EXPLAIN ANALYZE SELECT ...;
   ```

3. **检查表大小**
   ```sql
   SELECT schemaname, tablename,
          pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
   FROM pg_tables
   ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;
   ```

### 内存使用过高

1. **检查查询缓存**
   ```python
   from django.db import connection
   print(f"Queries: {len(connection.queries)}")
   ```

2. **使用 Django Debug Toolbar**
   ```bash
   pip install django-debug-toolbar
   ```

## 参考资料

- [Django 数据库优化](https://docs.djangoproject.com/en/4.2/topics/db/optimization/)
- [PostgreSQL 性能调优](https://www.postgresql.org/docs/current/performance-tips.html)
- [Prometheus 查询指南](https://prometheus.io/docs/prometheus/latest/querying/basics/)
