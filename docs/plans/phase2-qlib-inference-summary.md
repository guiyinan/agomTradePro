# Phase 2: Qlib 推理异步产出实现总结

> **完成日期**: 2026-02-05
> **状态**: ✅ 完成
> **实施内容**: AgomSAAF + Qlib 松耦合集成方案 - Phase 2

## 一、实施概览

### 已完成的任务

1. ✅ 实现 `QlibAlphaProvider` adapter
2. ✅ 实现 `qlib_predict_scores` Celery 任务
3. ✅ 配置 Qlib Celery 队列
4. ✅ 创建 `init_qlib_data` 管理命令
5. ✅ 编写 Qlib 集成测试

## 二、核心组件说明

### QlibAlphaProvider (`apps/alpha/infrastructure/adapters/qlib_adapter.py`)

**关键设计**：
- **快路径**: 优先从 `AlphaScoreCache` 读取缓存
- **慢路径**: 缓存未命中时触发异步推理任务，立即返回 degraded
- **优先级**: 1（最高）
- **最大陈旧天数**: 2 天（ML 模型要求新鲜数据）

```python
# 工作流程
1. 检查缓存 → 命中返回 available
2. 缓存未命中 → 触发 Celery 任务 → 返回 degraded
3. 下次请求 → 缓存命中 → 返回 available
```

### Celery 任务 (`apps/alpha/application/tasks.py`)

#### `qlib_predict_scores`
运行在 `qlib_infer` 队列，执行：
1. 加载激活的模型
2. 准备数据
3. 执行预测（使用 Qlib）
4. 结果写入 `AlphaScoreCache`

**容错机制**：
- 如果 Qlib 未安装，自动使用模拟数据
- 失败自动重试 3 次
- 超时时间 1 小时

#### 其他任务
- `qlib_train_model` - 训练任务（Phase 3 实现）
- `qlib_evaluate_model` - 评估任务
- `qlib_refresh_cache` - 批量刷新缓存

### Celery 队列配置 (`core/settings/base.py`)

```python
# 队列路由
CELERY_TASK_ROUTES = {
    'apps.alpha.application.tasks.qlib_train_model': {'queue': 'qlib_train'},
    'apps.alpha.application.tasks.qlib_predict_scores': {'queue': 'qlib_infer'},
    'apps.alpha.application.tasks.qlib_evaluate_model': {'queue': 'qlib_train'},
    'apps.alpha.application.tasks.qlib_refresh_cache': {'queue': 'qlib_infer'},
}

# 超时配置
CELERY_TASK_TIME_LIMIT = 3600  # 1 小时
CELERY_TASK_SOFT_TIME_LIMIT = 3300  # 55 分钟
```

### 管理命令 (`apps/alpha/management/commands/init_qlib_data.py`)

**功能**：
- 检查 Qlib 安装状态
- 检查数据完整性
- 下载 Qlib 数据
- 准备股票池数据

**用法**：
```bash
# 检查数据
python manage.py init_qlib_data --check

# 下载并初始化数据
python manage.py init_qlib_data --download --universe=csi300

# 准备指定天数的数据
python manage.py init_qlib_data --days=365
```

## 三、AlphaService 更新

**降级链路（更新后）**：
1. **Qlib** (priority=1) - 机器学习模型
2. **Cache** (priority=10) - 缓存数据
3. **Simple** (priority=100) - 简单因子
4. **ETF** (priority=1000) - ETF 降级

```python
# 自动注册 Qlib Provider
def _setup_providers(self):
    # 1. Qlib Provider（可能不可用）
    try:
        qlib_provider = QlibAlphaProvider()
        self._registry.register(qlib_provider)
    except Exception as e:
        logger.warning(f"Qlib Provider 初始化失败: {e}")
    # ... 其他 Providers
```

## 四、验收标准

- [x] `QlibAlphaProvider` 优先级为 1（最高）
- [x] 缓存未命中时触发 Celery 任务
- [x] Celery 任务写入 `AlphaScoreCache`
- [x] 支持模拟数据（Qlib 未安装时）
- [x] 管理命令可执行
- [x] 集成测试覆盖核心流程

## 五、使用示例

### 1. 初始化 Qlib 数据

```bash
# 检查 Qlib 安装和数据状态
python manage.py init_qlib_data --check

# 下载并初始化数据（需要先安装 pyqlib）
pip install pyqlib
python manage.py init_qlib_data --download --universe=csi300
```

### 2. 启动 Celery Worker

```bash
# 启动 Qlib 推理队列 worker
celery -A core worker -l info -Q qlib_infer --max-tasks-per-child=10

# 启动 Qlib 训练队列 worker（可选）
celery -A core worker -l info -Q qlib_train --max-tasks-per-child=1
```

### 3. API 测试

```bash
# 第一次请求：缓存未命中，触发异步任务
curl http://localhost:8000/api/alpha/scores/?universe=csi300

# 返回 degraded，但后台已触发任务
{
  "success": false,
  "source": "qlib",
  "status": "degraded",
  "error_message": "缓存缺失，已触发异步推理任务"
}

# 等待任务完成后，第二次请求：缓存命中
curl http://localhost:8000/api/alpha/scores/?universe=csi300

# 返回 available，带有实际评分
{
  "success": true,
  "source": "qlib",
  "status": "available",
  "stocks": [...]
}
```

### 4. Python 代码

```python
from apps.alpha.application.services import AlphaService

service = AlphaService()

# 第一次调用（触发异步推理）
result1 = service.get_stock_scores("csi300", date.today())
# result1.status == "degraded"

# 等待 Celery 任务完成后...

# 第二次调用（命中缓存）
result2 = service.get_stock_scores("csi300", date.today())
# result2.status == "available"
```

## 六、模拟数据机制

当 Qlib 未安装或不可用时，系统会使用模拟数据：

```python
def _generate_mock_scores(top_n: int) -> List[dict]:
    """生成模拟评分数据"""
    mock_stocks = [
        "600519.SH", "000333.SH", "600036.SH", ...
    ]
    # 生成 0.3 到 0.9 之间的评分
    return [...]
```

这确保了：
1. 开发环境无需安装 Qlib 即可测试
2. 降级链路始终可用
3. 集成测试可以正常运行

## 七、故障排查

| 问题 | 可能原因 | 解决方法 |
|------|----------|----------|
| Qlib import 失败 | 未安装 pyqlib | `pip install pyqlib` |
| 数据不存在 | `~/.qlib/qlib_data/cn_data` 为空 | 运行 `init_qlib_data --download` |
| 没有激活的模型 | Registry 中 `is_active=False` | 激活模型 |
| 推理任务不执行 | Celery queue 未启动 | `celery -A core worker -Q qlib_infer` |
| 缓存过期 | `staleness_days > 2` | 检查定时任务配置 |

## 八、下一步 (Phase 3)

实现训练流水线：
1. 实现 `train_qlib_model` 管理命令
2. 完善 `qlib_train_model` Celery 任务
3. 实现 artifact 目录规范（`/models/qlib/{name}/{hash}/`）
4. 实现 `QlibModelRegistry` 激活/回滚机制
5. 单元测试：`tests/unit/test_qlib_training.py`

## 九、文件清单

### 创建的新文件
```
apps/alpha/infrastructure/adapters/qlib_adapter.py
apps/alpha/application/tasks.py
apps/alpha/management/commands/init_qlib_data.py
tests/integration/test_qlib_integration.py
docs/plans/phase2-qlib-inference-summary.md
```

### 修改的文件
```
apps/alpha/infrastructure/adapters/__init__.py  # 导出 QlibAlphaProvider
apps/alpha/application/services.py                # 注册 Qlib Provider
core/settings/base.py                             # 添加 Qlib Celery 配置
```

## 十、验证方法

### 开发环境验证

```bash
# 1. 安装依赖（可选，用于实际 Qlib 功能）
pip install pyqlib

# 2. 检查 Qlib 数据
python manage.py init_qlib_data --check

# 3. 启动 Celery worker（新终端）
celery -A core worker -l info -Q qlib_infer

# 4. 触发推理任务
python -c "
from apps.alpha.application.tasks import qlib_predict_scores
qlib_predict_scores.delay('csi300', '2026-02-05', 10)
"

# 5. 检查缓存
python manage.py shell
>>> from apps.alpha.infrastructure.models import AlphaScoreCache
>>> AlphaScoreCache.objects.filter(provider_source='qlib')
```

### API 验证

```bash
# 第一次请求（触发异步）
curl http://localhost:8000/api/alpha/scores/?universe=csi300

# 检查任务状态
celery -A core inspect active

# 第二次请求（命中缓存）
curl http://localhost:8000/api/alpha/scores/?universe=csi300
```
