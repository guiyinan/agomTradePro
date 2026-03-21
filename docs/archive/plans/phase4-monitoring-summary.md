# Phase 4: 评估闭环 + 监控实现总结

> **完成日期**: 2026-02-05
> **状态**: ✅ 完成
> **实施内容**: AgomTradePro + Qlib 松耦合集成方案 - Phase 4

## 一、实施概览

### 已完成的任务

1. ✅ 实现评估指标基础设施 (`shared/infrastructure/model_evaluation.py`)
2. ✅ 实现监控指标系统 (`shared/infrastructure/metrics.py`)
3. ✅ 实现告警配置和通知 (`apps/alpha/infrastructure/alerts.py`)
4. ✅ 实现监控 Celery 任务 (`apps/alpha/application/monitoring_tasks.py`)
5. ✅ 更新 AlphaService 集成监控 (`apps/alpha/application/services.py`)
6. ✅ 配置 Celery Beat 定时任务 (`core/settings/base.py`)
7. ✅ 编写 Phase 4 集成测试

## 二、核心组件说明

### 评估基础设施 (`shared/infrastructure/model_evaluation.py`)

**功能**：
- IC/ICIR 计算（相关系数和信息比率）
- Rank IC 计算（排序相关系数）
- 滚动 IC 计算（时间窗口）
- 分组 IC 计算（按行业分组）
- 性能指标计算（夏普比率、最大回撤、换手率、覆盖率）

**主要类**：
- `IC_Calculator`: IC 系列指标计算器
  - `calculate_ic()`: Pearson 相关系数
  - `calculate_rank_ic()`: Spearman 相关系数
  - `calculate_icir()`: IC 的信息比率（mean/std）
  - `calculate_group_ic()`: 分组 IC
  - `calculate_rolling_ic()`: 滚动窗口 IC

- `PerformanceCalculator`: 性能指标计算器
  - `calculate_sharpe_ratio()`: 风险调整收益
  - `calculate_max_drawdown()`: 最大回撤
  - `calculate_turnover()`: 换手率
  - `calculate_coverage()`: 覆盖率

- `ModelEvaluator`: 综合评估器
  - `evaluate_predictions()`: 评估预测结果
  - 返回 `ModelMetrics` 数据类

**数据结构**：
```python
@dataclass(frozen=True)
class ModelMetrics:
    ic: Optional[float] = None           # IC 值
    icir: Optional[float] = None         # ICIR 值
    rank_ic: Optional[float] = None      # Rank IC
    sharpe: Optional[float] = None       # 夏普比率
    turnover: Optional[float] = None     # 换手率
    coverage: Optional[float] = None     # 覆盖率
    annual_return: Optional[float] = None      # 年化收益
    annual_volatility: Optional[float] = None  # 年化波动率
    max_drawdown: Optional[float] = None      # 最大回撤
```

### 监控指标系统 (`shared/infrastructure/metrics.py`)

**功能**：
- Prometheus 风格指标定义
- 指标注册和管理（单例模式）
- 支持多种指标类型（Counter, Gauge, Histogram）
- JSON Lines 格式导出（日志友好）

**核心类**：
- `MetricsRegistry`: 指标注册表
  - `define_metric()`: 定义指标
  - `set_gauge()`: 设置仪表盘值
  - `inc_counter()`: 增加计数器
  - `observe_histogram()`: 观测直方图
  - `to_prometheus()`: 导出 Prometheus 格式
  - `to_json_lines()`: 导出 JSON Lines 格式

- `AlphaMetrics`: Alpha 专用指标收集器
  - `PROVIDER_SUCCESS_RATE`: Provider 成功率
  - `PROVIDER_LATENCY_MS`: Provider 延迟
  - `PROVIDER_STALENESS_DAYS`: 数据陈旧度
  - `COVERAGE_RATIO`: 覆盖率
  - `IC_DRIFT`: IC 漂移
  - `RANK_IC_ROLLING`: 滚动 Rank IC
  - `INFER_QUEUE_LAG`: 推理队列积压
  - `TRAIN_QUEUE_LAG`: 训练队列积压
  - `CACHE_HIT_RATE`: 缓存命中率

**使用示例**：
```python
from shared.infrastructure.metrics import get_alpha_metrics

metrics = get_alpha_metrics()

# 记录 Provider 调用
metrics.record_provider_call(
    provider_name="qlib",
    success=True,
    latency_ms=150.5,
    staleness_days=1
)

# 记录覆盖率
metrics.record_coverage(scored_count=280, universe_count=300)

# 获取指标
output = metrics.get_all_metrics()  # Prometheus 格式
```

### 告警配置和通知 (`apps/alpha/infrastructure/alerts.py`)

**功能**：
- 预定义告警规则
- 告警评估和持续期检查
- 告警通知器（日志、邮件、Webhook）
- 动态阈值配置

**核心类**：
- `AlertRule`: 告警规则定义
  - 支持条件：gt, lt, eq, ne
  - 持续时间检查
  - 严重级别：info, warning, critical

- `AlphaAlertConfig`: Alpha 告警配置
  - `PROVIDER_UNAVAILABLE`: Provider 成功率过低
  - `HIGH_LATENCY`: Provider 延迟过高
  - `STALE_DATA`: 数据陈旧
  - `LOW_COVERAGE`: 覆盖率过低
  - `IC_DRIFT`: IC 值漂移
  - `QUEUE_BACKLOG`: 队列积压

- `AlphaAlertManager`: 告警管理器
  - `evaluate_with_notification()`: 评估并发送通知
  - `get_alert_summary()`: 获取告警摘要

- `AlertNotifier`: 告警通知器
  - 支持多处理器
  - 默认：日志处理器

**告示规则示例**：
```python
PROVIDER_UNAVAILABLE = AlertRule(
    name="provider_unavailable",
    metric_name="alpha_provider_success_rate",
    condition="lt",
    threshold=0.5,
    severity="critical",
    duration_seconds=60,
    message_template="Alpha Provider 成功率过低: {value:.2%} < {threshold:.2%}"
)
```

### 监控 Celery 任务 (`apps/alpha/application/monitoring_tasks.py`)

**任务列表**：
1. `evaluate_alerts` - 评估告警规则（每分钟）
2. `update_provider_metrics` - 更新 Provider 指标（每 5 分钟）
3. `calculate_ic_drift` - 计算 IC 漂移（每周）
4. `check_queue_lag` - 检查队列积压（每分钟）
5. `generate_daily_report` - 生成每日报告（每天）
6. `cleanup_old_metrics` - 清理旧数据（每周）

**Celery Beat 配置**：
```python
CELERY_BEAT_SCHEDULE = {
    "alpha-evaluate-alerts": {
        "task": "apps.alpha.application.monitoring_tasks.evaluate_alerts",
        "schedule": crontab(minute="*/1"),
    },
    "alpha-update-provider-metrics": {
        "task": "apps.alpha.application.monitoring_tasks.update_provider_metrics",
        "schedule": crontab(minute="*/5"),
    },
    # ... 更多任务
}
```

## 三、监控指标定义

### 核心指标

| 指标名称 | 类型 | 描述 | 告警阈值 |
|---------|------|------|----------|
| `alpha_provider_success_rate` | Gauge | Provider 成功率 | < 50% (critical) |
| `alpha_provider_latency_ms` | Histogram | Provider 延迟 | > 5000ms (warning) |
| `alpha_provider_staleness_days` | Gauge | 数据陈旧度 | > 3 天 (warning) |
| `alpha_coverage_ratio` | Gauge | 覆盖率 | < 70% (warning) |
| `alpha_ic_drift` | Gauge | IC 漂移 | < -0.03 (warning) |
| `alpha_rank_ic_rolling` | Gauge | 滚动 Rank IC | < 0.02 (warning) |
| `qlib_infer_queue_lag` | Gauge | 推理队列积压 | > 100 (warning) |
| `qlib_train_queue_lag` | Gauge | 训练队列积压 | > 10 (warning) |
| `alpha_cache_hit_rate` | Gauge | 缓存命中率 | < 30% (info) |
| `alpha_score_request_count` | Counter | 评分请求总数 | N/A |
| `qlib_model_activation_count` | Counter | 模型激活次数 | N/A |
| `qlib_model_rollback_count` | Counter | 模型回滚次数 | N/A |

## 四、AlphaService 监控集成

### 自动指标记录

`AlphaService.get_scores_with_fallback()` 现在会自动记录：

1. **Provider 调用指标**
   - 成功/失败状态
   - 延迟时间（毫秒）
   - 数据陈旧度

2. **覆盖率指标**
   - 评分股票数量
   - 股票池总数

3. **缓存命中率**
   - Cache Provider 命中记录

### 集成示例

```python
# AlphaService 内部自动记录
from apps.alpha.application.services import AlphaService

service = AlphaService()
result = service.get_stock_scores("csi300")

# 指标已自动记录：
# - alpha_provider_success_rate{provider="..."}
# - alpha_provider_latency_ms{provider="..."}
# - alpha_coverage_ratio
# - alpha_cache_hit_rate (如果是 cache provider)
```

## 五、Prometheus 集成

### 导出格式

```bash
# 获取所有指标（Prometheus 格式）
curl http://localhost:8000/api/alpha/metrics/prometheus

# 响应示例：
# HELP alpha_provider_success_rate Alpha Provider 成功率（0-1）
alpha_provider_success_rate{provider="qlib"} 0.95 1707123456789
alpha_provider_success_rate{provider="cache"} 1.00 1707123456789

# HELP alpha_provider_latency_ms Alpha Provider 延迟（毫秒）
alpha_provider_latency_ms_bucket{provider="qlib",le="100"} 0
alpha_provider_latency_ms_bucket{provider="qlib",le="500"} 150
alpha_provider_latency_ms_bucket{provider="qlib",le="1000"} 280
alpha_provider_latency_ms_bucket{provider="qlib",le="+Inf"} 300
alpha_provider_latency_ms_sum{provider="qlib"} 125000
alpha_provider_latency_ms_count{provider="qlib"} 300
```

### Prometheus 配置

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'agomtradepro_alpha'
    scrape_interval: 1m
    static_configs:
      - targets: ['localhost:8000']
    metrics_path: '/api/alpha/metrics/prometheus'
```

## 六、Grafana 仪表盘

### 推荐面板

1. **Provider 健康状态**
   - 成功率（时间序列图）
   - 延迟（热力图）
   - 陈旧度（单值）

2. **Alpha 信号质量**
   - 覆盖率（仪表盘）
   - IC 漂移（时间序列图）
   - Rank IC（时间序列图）

3. **系统状态**
   - 队列积压（条形图）
   - 缓存命中率（单值）
   - 请求速率（时间序列图）

## 七、验收标准

- [x] IC/ICIR 计算正确
- [x] 监控指标自动记录
- [x] 告警规则可配置
- [x] Celery 任务正常执行
- [x] Prometheus 格式导出
- [x] 集成测试覆盖核心流程

## 八、使用示例

### 查看监控指标

```python
from shared.infrastructure.metrics import get_alpha_metrics

metrics = get_alpha_metrics()

# Prometheus 格式
prometheus_output = metrics.get_all_metrics()
print(prometheus_output)

# JSON 格式
json_output = metrics.get_metrics_json()
print(json_output)

# 记录到日志
metrics.log_metrics()
```

### 手动触发告警评估

```python
from apps.alpha.infrastructure.alerts import get_alpha_alert_manager

manager = get_alpha_alert_manager()

# 评估并发送通知
notifications = manager.evaluate_with_notification()

# 查看摘要
summary = manager.get_alert_summary()
print(summary)
```

### 调用监控任务

```python
from apps.alpha.application.monitoring_tasks import (
    evaluate_alerts,
    update_provider_metrics,
    generate_daily_report,
)

# 评估告警
alert_result = evaluate_alerts()

# 更新指标
metrics_result = update_provider_metrics()

# 生成报告
report = generate_daily_report()
```

## 九、故障排查

| 问题 | 可能原因 | 解决方法 |
|------|----------|----------|
| 指标未记录 | AlphaMetrics 未初始化 | 调用 `get_alpha_metrics()` |
| 告警未触发 | 持续时间不足 | 检查 `duration_seconds` 配置 |
| 任务不执行 | Celery Beat 未启动 | `celery -A core beat -l info` |
| 队列积压 | Worker 数量不足 | 增加 `--concurrency` |
| IC 计算错误 | 数据不足 | 检查缓存记录数量 |

## 十、下一步 (Phase 5)

实现宏观集成 + 全链路联调：
1. 与 Signal 模块对接
2. 与 Backtest 模块对接
3. 与 Rotation 模块对接
4. 与 Hedge 模块对接
5. 端到端测试
6. 压力测试

## 十一、文件清单

### 创建的新文件
```
shared/infrastructure/
├── model_evaluation.py     # 评估基础设施
└── metrics.py              # 监控指标系统

apps/alpha/infrastructure/
└── alerts.py               # 告警配置

apps/alpha/application/
└── monitoring_tasks.py     # 监控 Celery 任务

tests/integration/
└── test_alpha_monitoring.py  # Phase 4 集成测试

docs/plans/
└── phase4-monitoring-summary.md  # 本文档
```

### 修改的文件
```
apps/alpha/application/services.py  # 集成监控指标
core/settings/base.py               # 添加 Celery Beat 配置
```

## 十二、验证方法

### 开发环境验证

```bash
# 1. 启动 Celery Beat
celery -A core beat -l info

# 2. 启动 Celery Worker
celery -A core worker -l info

# 3. 测试监控任务
python manage.py shell
>>> from apps.alpha.application.monitoring_tasks import update_provider_metrics
>>> update_provider_metrics()

# 4. 查看指标
>>> from shared.infrastructure.metrics import get_alpha_metrics
>>> metrics = get_alpha_metrics()
>>> print(metrics.get_all_metrics())

# 5. 测试告警
>>> from apps.alpha.infrastructure.alerts import get_alpha_alert_manager
>>> manager = get_alpha_alert_manager()
>>> print(manager.get_alert_summary())
```

### 指标验证

```bash
# 通过 API 获取指标
curl http://localhost:8000/api/alpha/metrics/prometheus

# 检查日志中的指标记录
tail -f logs/alpha.log | grep "Alpha 模块指标摘要"
```

### 告警验证

```python
# 模拟触发告警
from shared.infrastructure.metrics import get_alpha_metrics

metrics = get_alpha_metrics()
metrics.registry.set_gauge(
    "alpha_provider_success_rate",
    0.3,  # 低于临界值 0.5
    labels={"provider": "test"}
)

# 评估告警
from apps.alpha.application.monitoring_tasks import evaluate_alerts
result = evaluate_alerts()
print(result)
```

---

**Phase 4 完成**：评估闭环和监控系统已完全实现，为 Phase 5 的全链路集成奠定了基础。
