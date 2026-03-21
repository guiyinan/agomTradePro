# Prometheus 指标体系

> 版本: 1.0
> 更新时间: 2026-03-04

## 概述

AgomTradePro 通过 `prometheus-client` 和 `django-prometheus` 实现了完整的 Prometheus 指标暴露能力，支持：

- **API 请求指标**：请求量、延迟、错误率
- **Celery 任务指标**：任务执行、重试、队列堆积
- **审计日志指标**：写入成功/失败计数
- **Django 基础指标**：数据库连接、缓存等（由 django-prometheus 自动收集）

## 快速开始

### 1. 安装依赖

```bash
pip install django-prometheus>=2.3.1
```

依赖已添加到 `requirements-prod.txt`。

### 2. 访问指标端点

```bash
curl http://localhost:8000/metrics/
```

返回示例：
```
# HELP api_request_total Total API requests
# TYPE api_request_total counter
api_request_total{method="GET",endpoint="/api/regime/",status_code="200",view_name="RegimeViewSet"} 123.0

# HELP api_request_latency_seconds API request latency in seconds
# TYPE api_request_latency_seconds histogram
api_request_latency_seconds_bucket{method="GET",endpoint="/api/regime/",view_name="RegimeViewSet",le="0.1"} 100.0
api_request_latency_seconds_sum{method="GET",endpoint="/api/regime/",view_name="RegimeViewSet"} 12.5
```

### 3. 配置 Prometheus 抓取

在 `prometheus.yml` 中添加：

```yaml
scrape_configs:
  - job_name: 'agomtradepro'
    scrape_interval: 15s
    static_configs:
      - targets: ['localhost:8000']
    metrics_path: '/metrics/'
```

## 指标定义

### API 请求指标

| 指标名 | 类型 | 标签 | 描述 |
|--------|------|------|------|
| `api_request_total` | Counter | method, endpoint, status_code, view_name | API 请求总数 |
| `api_request_latency_seconds` | Histogram | method, endpoint, view_name | API 请求延迟（秒） |
| `api_error_total` | Counter | method, endpoint, error_class, status_code | API 错误请求总数（4xx/5xx） |

**标签说明**：
- `method`: HTTP 方法（GET/POST/PUT/DELETE）
- `endpoint`: API 端点路径（ID 参数会被替换为 `:id`）
- `status_code`: HTTP 状态码（200/400/500 等）
- `view_name`: DRF 视图类名
- `error_class`: 异常类名（仅错误时）

### Celery 任务指标

| 指标名 | 类型 | 标签 | 描述 |
|--------|------|------|------|
| `celery_task_total` | Counter | task_name, status | Celery 任务执行总数 |
| `celery_task_duration_seconds` | Histogram | task_name | Celery 任务执行时间（秒） |
| `celery_task_retry_total` | Counter | task_name, reason | Celery 任务重试次数 |
| `celery_queue_length` | Gauge | queue_name | Celery 队列积压量 |
| `celery_active_workers` | Gauge | worker_name | 活跃工作线程数 |

**标签说明**：
- `task_name`: 任务函数名
- `status`: 任务状态（success/failure/retry/timeout）
- `reason`: 重试原因（异常类名）

### 审计日志指标

| 指标名 | 类型 | 标签 | 描述 |
|--------|------|------|------|
| `audit_write_total` | Counter | module, source, status | 审计日志写入总数 |
| `audit_write_latency_seconds` | Histogram | module, source | 审计日志写入延迟（秒） |

**标签说明**：
- `module`: 模块名称（regime/signal/backtest 等）
- `source`: 数据来源（api/mcp/sdk）
- `status`: 写入状态（success/failure）

### Django 基础指标（自动收集）

由 `django-prometheus` 自动收集：

- `django_model_inserts_total`: 模型插入次数
- `django_model_updates_total`: 模型更新次数
- `django_model_deletes_total`: 模型删除次数
- `django_cache_get_total`: 缓存获取次数
- `django_db_connections_total`: 数据库连接数

## 代码使用

### 记录自定义指标

```python
from core.metrics import record_api_request, record_celery_task, record_audit_write

# 记录 API 请求
record_api_request(
    method='GET',
    endpoint='/api/regime/',
    status_code=200,
    duration_seconds=0.123,
    view_name='RegimeViewSet'
)

# 记录 Celery 任务
record_celery_task(
    task_name='sync_macro_data',
    status='success',
    duration_seconds=5.6
)

# 记录审计写入
record_audit_write(
    module='regime',
    status='success',
    source='api',
    latency_seconds=0.05
)
```

### 使用装饰器

```python
from core.metrics import track_api_request, track_celery_task

# API 视图装饰器
class MyViewSet(viewsets.ModelViewSet):
    @track_api_request
    def list(self, request, *args, **kwargs):
        ...

# Celery 任务装饰器
@shared_task
@track_celery_task
def my_task(arg1, arg2):
    ...
```

### 审计模块专用指标

```python
from apps.audit.infrastructure.metrics import (
    record_audit_write_success,
    record_audit_write_failure
)

# 记录审计写入成功
record_audit_write_success(
    module="regime",
    action="analyze",
    source="mcp",
    latency_seconds=0.1
)

# 记录审计写入失败
record_audit_write_failure(
    module="regime",
    error_type="database",
    source="api",
    latency_seconds=0.5
)
```

## Grafana 仪表盘

### 推荐查询

#### API 错误率

```promql
sum(rate(api_error_total[5m])) / sum(rate(api_request_total[5m])) * 100
```

#### API P95 延迟

```promql
histogram_quantile(0.95, sum(rate(api_request_latency_seconds_bucket[5m])) by (le, endpoint))
```

#### Celery 任务成功率

```promql
sum(rate(celery_task_total{status="success"}[5m])) / sum(rate(celery_task_total[5m])) * 100
```

#### 审计写入失败率

```promql
sum(rate(audit_write_total{status="failure"}[5m])) / sum(rate(audit_write_total[5m])) * 100
```

## 架构说明

```
┌─────────────────────────────────────────────────────────────┐
│                         Django 应用                          │
│                                                              │
│  ┌─────────────┐    ┌──────────────┐    ┌──────────────┐   │
│  │   API 请求  │───>│ Prometheus   │───>│  指标存储    │   │
│  │   中间件    │    │   指标记录    │    │  (内存)      │   │
│  └─────────────┘    └──────────────┘    └──────────────┘   │
│         ▲                                      │             │
│         │                                      ▼             │
│  ┌─────────────┐    ┌──────────────┐    ┌──────────────┐   │
│  │ Celery 信号 │───>│  指标聚合     │───>│ /metrics/    │   │
│  │   处理器    │    │              │    │   端点       │   │
│  └─────────────┘    └──────────────┘    └──────────────┘   │
│                                                              │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │   Prometheus     │
                    │   定期抓取       │
                    └──────────────────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │     Grafana      │
                    │   可视化展示     │
                    └──────────────────┘
```

## 文件结构

```
core/
├── metrics.py              # 统一的指标定义和记录函数
├── celery_metrics.py       # Celery 信号处理器
├── middleware/
│   └── prometheus.py      # API 请求指标中间件
└── urls.py                # /metrics/ 端点

apps/audit/
└── infrastructure/
    └── metrics.py         # 审计模块专用指标

tests/
└── integration/
    └── test_prometheus_metrics.py  # 指标集成测试
```

## 注意事项

1. **性能影响**：指标记录操作失败不会影响业务逻辑，但会记录警告日志

2. **标签基数**：避免使用高基数标签（如用户 ID），会导致指标数量爆炸

3. **端点保护**：生产环境建议对 `/metrics/` 端点添加认证或 IP 白名单

4. **数据类型**：
   - Counter：单调递增的计数器
   - Gauge：可增可减的数值
   - Histogram：记录分布的直方图

## 故障排查

### 指标未显示

1. 检查 `django-prometheus` 是否在 `INSTALLED_APPS` 中
2. 确认中间件顺序正确
3. 查看日志是否有指标记录失败警告

### Celery 任务指标缺失

1. 确认 `core/celery_metrics.py` 被导入
2. 检查 Celery worker 是否正常启动
3. 验证信号处理器是否正常工作

## 参考资料

- [Prometheus Python Client 文档](https://prometheus.github.io/client_python/)
- [Django Prometheus 文档](https://github.com/korfuri/django-prometheus)
- [Prometheus 查询语言 (PromQL)](https://prometheus.io/docs/prometheus/latest/querying/basics/)
