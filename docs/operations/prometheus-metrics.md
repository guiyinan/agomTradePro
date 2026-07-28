# Prometheus 指标体系

> 版本: 1.1
> 更新时间: 2026-07-27

## 概述

AgomTradePro 通过 `prometheus-client` 和 `django-prometheus` 实现了完整的 Prometheus 指标暴露能力，支持：

- **API 请求指标**：请求量、延迟、错误率
- **Celery 任务指标**：任务执行、重试、队列堆积
- **审计日志指标**：写入成功/失败计数
- **Web → TUI 迁移指标**：按受审任务对照 Classic/TUI 入口占比和真实执行错误率
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
curl http://localhost:8000/api/metrics/
```

说明：
- `/metrics/` 是 Prometheus 抓取主入口。
- `/api/metrics/` 是兼容运维脚本与外部探针的别名入口，返回同一份指标文本。

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
| `web_to_tui_migration_events_total` | Counter | surface, event_type, task_key, outcome | 兼容期入口、执行、缺参和确认事件 |

**标签说明**：
- `method`: HTTP 方法（GET/POST/PUT/DELETE）
- `endpoint`: API 端点路径（ID 参数会被替换为 `:id`）
- `status_code`: HTTP 状态码（200/400/500 等）
- `view_name`: DRF 视图类名
- `error_class`: 异常类名（仅错误时）

### Web → TUI 兼容期指标

`task_key` 只来自
`config/tui/migration/web_to_tui_telemetry.v1.json`，该文件由受审迁移矩阵确定性
生成，CI 会执行：

```bash
python scripts/build_web_to_tui_telemetry_catalog.py --check
```

标签说明：

- `surface`：`classic` 或 `tui`
- `event_type`：`entry`、`execution`、`form` 或 `confirmation`
- `task_key`：目标 action key；仅 screen 级任务使用 `screen:<screen_key>`
- `outcome`：`success`、`client_error`、`server_error`、`input_required` 或
  `confirmation_required`

TUI action 外层 HTTP 200 不作为成功依据；中间件读取 action response 内层真实状态。
缺少必填参数和写操作待确认属于正常交互，分别记录为 `form/input_required` 和
`confirmation/confirmation_required`，不进入执行错误率。目录外的 URL/action 不
记录，避免用户输入产生 Prometheus 高基数标签。Classic 页面发起的同源 `/api/`
请求通过受审页面 Referer 归入该页面的固定 task key；跨源或目录外 Referer 不记录。
迁移样本只记录已认证用户。匿名 Classic 登录跳转、匿名 TUI shell 请求和伪造 Referer 的
公共 API 请求均不进入 14 日 entry/request/error 分母，避免认证流量或扫描流量稀释真实任务
错误率；认证与对象授权仍由各 owner view/API 执行，遥测过滤不替代权限检查。

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

#### M5：14 日 Classic 入口占比

```promql
web_to_tui:legacy_entry_ratio_14d
```

只有 `web_to_tui:entry_samples_14d >= 20` 的任务可直接套用 5% 门槛；低于 20 次
必须走计划规定的低频 owner/reviewer 双签例外。

#### M5：14 日 TUI 与 Classic 任务请求错误率差

```promql
web_to_tui:task_request_error_ratio_14d{surface="tui"}
- on (task_key)
web_to_tui:task_request_error_ratio_14d{surface="classic"}
```

Classic 侧统计页面 entry 及其同源 API execution；TUI 侧统计真实 action execution，
不把 shell 打开或缺参/确认握手冒充任务结果。两侧各至少 20 个可比较 task request
样本时才触发自动回退告警；样本不足必须进入低频双签或继续观察，不能按 0 错误率
通过。结果不得高于 `0.005`。`monitoring/alerts.yml` 已提供对应 14 日 recording rules 和
`WebToTuiLegacyEntryRatioHigh`、`WebToTuiErrorRateRegression` 告警。

#### M5：生产遥测快照入证

观察窗口结束后，生产 Prometheus 查询结果必须先保存为仓库内、无凭证的
`web-to-tui-production-telemetry-snapshot.v1` JSON，再由生成器写入 cutover evidence：

```bash
python scripts/build_web_to_tui_production_telemetry.py \
  --snapshot <repo-relative-production-snapshot.json>
python scripts/build_web_to_tui_production_telemetry.py \
  --snapshot <repo-relative-production-snapshot.json> --write-evidence
```

快照必须包含 `candidate_version`、`candidate_commit`、`source_sha256`、`environment`、
`window_start`、`window_end`、`collected_at`、`collection` 和 `tasks`。`collection` 只能登记
不含用户名、密码、query 或 fragment 的 HTTPS Prometheus origin，并逐项保存生成器内置的
六条批准 PromQL；`tasks` 必须精确覆盖 catalog 的 101 个 task key，并提供 Classic/TUI
entry、task request 和 error 六类非负整数计数。工具会校验完整候选绑定、快照 SHA、低频
双签、5% Classic 占比、两侧最小请求样本和错误率回退门槛，任一不满足都不会写 evidence。

#### M5：机器化 cutover 判定

生产窗口证据统一写入
`config/tui/migration/web_to_tui_cutover_evidence.v1.json`。该文件必须与迁移矩阵
SHA 一致，并覆盖机器推导出的全部 migrated A/B route page 和全部 comparable task。
检查命令：

```bash
python scripts/check_web_to_tui_cutover_readiness.py
```

普通检查即使判定为 `DENY` 也以成功状态退出，便于兼容期持续验证证据结构；实际执行
Classic 清理、production registry 切换或计划归档前必须使用硬门：

```bash
python scripts/check_web_to_tui_cutover_readiness.py --require-allow
```

硬门同时校验：稳定版本不少于 14 天、逐 route task UAT、完整窗口 P0/P1 为 0、逐任务
旧入口比例、两侧 task request 错误率、低频 owner/reviewer 双签、回滚演练、生产
registry 备份和独立 cutover 审批。缺少样本使用 `null`/空列表表达，不得填 0 冒充已观测。

阻断缺陷门禁不再只检查观察结束时的 open 数。受审 issue-tracker 快照须通过：

```bash
python scripts/build_web_to_tui_defect_evidence.py \
  --snapshot <repo-relative-defect-snapshot.json> --require-clear
```

生成器分别登记窗口内新增和窗口内曾未关闭的 P0/P1；四项均为 0 才能通过，候选、commit、
矩阵 SHA、查询范围或快照摘要不匹配时 fail closed。

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
