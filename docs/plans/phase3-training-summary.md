# Phase 3: 训练流水线实现总结

> **完成日期**: 2026-02-05
> **状态**: ✅ 完成
> **实施内容**: AgomSAAF + Qlib 松耦合集成方案 - Phase 3

## 一、实施概览

### 已完成的任务

1. ✅ 实现 `train_qlib_model` 管理命令
2. ✅ 实现 `qlib_train_model` Celery 任务
3. ✅ 实现模型激活/回滚管理命令
4. ✅ 编写 Qlib 训练单元测试

## 二、核心组件说明

### 训练管理命令 (`apps/alpha/management/commands/train_qlib_model.py`)

**功能**：
- 同步/异步训练模式
- 自动保存模型 artifact
- 写入模型注册表
- 支持训练完成后自动激活

**用法**：
```bash
# 同步训练
python manage.py train_qlib_model \
    --name mlp_csi300 \
    --type LGBModel \
    --universe csi300 \
    --activate

# 异步训练（后台执行）
python manage.py train_qlib_model \
    --name mlp_csi300 \
    --async

# 查看任务状态
celery -A core inspect active | grep train
```

### 激活/回滚命令

#### `activate_model.py`
```bash
# 激活指定模型
python manage.py activate_model abc123...

# 强制激活（替换当前激活的模型）
python manage.py activate_model abc123... --force
```

#### `rollback_model.py`
```bash
# 回滚到上一个版本
python manage.py rollback_model --model-name mlp_csi300 --prev

# 回滚到指定版本
python manage.py rollback_model --model-name mlp_csi300 --to def456...
```

#### `list_models.py`
```bash
# 列出所有模型
python manage.py list_models

# 只显示激活的模型
python manage.py list_models --active

# 按名称过滤
python manage.py list_models --model-name mlp
```

### Celery 训练任务 (`apps/alpha/application/tasks.py`)

#### `qlib_train_model`
运行在 `qlib_train` 队列，执行：
1. 准备数据
2. 训练模型（使用 Qlib API 或模拟）
3. 评估指标（IC/ICIR/RankIC）
4. 保存 artifact 到 `/models/qlib/{name}/{hash}/`
5. 写入 `QlibModelRegistry`

**Artifact 目录结构**：
```
/models/qlib/
└── mlp_csi300/
    └── abc123def456...
        ├── model.pkl           # 模型文件
        ├── config.json         # 训练配置
        ├── metrics.json        # 评估指标
        ├── feature_schema.json # 特征定义
        └── data_version.txt    # 数据版本
```

## 三、模型注册表功能

### QlibModelRegistry 模型

**字段**：
- `artifact_hash` - 主键，SHA256 哈希
- `model_name` - 模型名称
- `model_type` - LGBModel/LSTMModel/MLPModel
- `universe` - 股票池
- `train_config` - 训练配置（JSON）
- `ic`, `icir`, `rank_ic` - 评估指标
- `is_active` - 是否激活
- `activated_at`, `activated_by` - 激活审计

**方法**：
- `activate(activated_by)` - 激活模型（自动取消其他激活状态）
- `deactivate()` - 取消激活

## 四、训练流程

### 完整训练流程

```
1. 准备数据
   ├── 指定训练日期范围
   ├── 获取股票池列表
   └── 计算特征

2. 训练模型
   ├── 初始化 Qlib
   ├── 训练（LGBModel/LSTM/MLP）
   └── 保存模型对象

3. 评估模型
   ├── 计算 IC/ICIR
   ├── 计算 RankIC
   └── 生成评估报告

4. 保存 Artifact
   ├── 生成 artifact hash
   ├── 保存模型文件
   ├── 保存配置/指标
   └── 创建目录结构

5. 写入 Registry
   ├── 创建注册记录
   ├── 设置 is_active=False
   └── 可选：自动激活
```

### 模拟训练模式

当 Qlib 未安装时，系统使用模拟模式：
- 创建 `MockModel` 对象
- 生成模拟指标（IC=0.05, ICIR=0.8）
- 保存到相同目录结构

## 五、验收标准

- [x] `train_qlib_model` 命令可执行
- [x] 支持同步/异步训练
- [x] 模型 artifact 正确保存
- [x] Registry 记录正确创建
- [x] 激活/回滚功能正常
- [x] 单元测试覆盖核心流程

## 六、使用示例

### 1. 训练新模型

```bash
# 同步训练
python manage.py train_qlib_model \
    --name mlp_csi300_v2 \
    --type LGBModel \
    --universe csi300 \
    --start-date 2025-01-01 \
    --end-date 2026-01-01 \
    --learning-rate 0.02 \
    --epochs 200 \
    --activate

# 输出示例：
# Qlib 模型训练
#   模型名称: mlp_csi300_v2
#   模型类型: LGBModel
#   ...
#   ✓ 模型训练完成
#     Artifact Hash: abc12345...
#     IC: 0.0523
#     ICIR: 0.8234
```

### 2. 异步训练

```bash
# 提交训练任务
python manage.py train_qlib_model \
    --name lstm_csi500 \
    --type LSTMModel \
    --universe csi500 \
    --async

# 查看任务
celery -A core inspect active

# 查看结果（需要 Celery worker 运行）
# 任务完成后，检查模型
python manage.py list_models --model-name lstm_csi500
```

### 3. 模型管理

```bash
# 列出所有模型
python manage.py list_models

# 激活模型
python manage.py activate_model abc123...

# 查看激活状态
python manage.py list_models --active

# 回滚到上一个版本
python manage.py rollback_model --model-name mlp_csi300 --prev
```

### 4. Python 代码

```python
from apps.alpha.application.tasks import qlib_train_model

# 异步训练
result = qlib_train_model.delay(
    model_name="mlp_csi300",
    model_type="LGBModel",
    train_config={
        "universe": "csi300",
        "learning_rate": 0.01,
        "epochs": 100,
    }
)

print(f"Task ID: {result.id}")
```

## 七、故障排查

| 问题 | 可能原因 | 解决方法 |
|------|----------|----------|
| 训练任务不执行 | Celery worker 未启动 | `celery -A core worker -Q qlib_train` |
| 模型保存失败 | 目录权限不足 | 检查 `/models/qlib` 权限 |
| Registry 记录重复 | artifact_hash 冲突 | 使用新的模型名称或参数 |
| 激活失败 | 模型不存在 | 检查 `artifact_hash` |
| 回滚失败 | 没有上一个版本 | 检查模型历史 |

## 八、下一步 (Phase 4)

实现评估闭环 + 监控：
1. 实现 `qlib_evaluate_model` 任务（完整 IC/ICIR 计算）
2. 监控指标埋点（Prometheus/日志）
3. 告警规则配置
4. 滚动 IC 计算
5. 队列积压监控

## 九、文件清单

### 创建的新文件
```
apps/alpha/management/commands/
├── train_qlib_model.py      # 训练命令
├── activate_model.py         # 激活命令
├── rollback_model.py         # 回滚命令
└── list_models.py            # 列出模型命令

tests/unit/
└── test_qlib_training.py     # 训练单元测试

docs/plans/
└── phase3-training-summary.md  # 本文档
```

### 修改的文件
```
apps/alpha/application/tasks.py  # 完善训练任务
```

## 十、验证方法

### 开发环境验证

```bash
# 1. 训练一个模型（使用模拟模式）
python manage.py train_qlib_model \
    --name test_model \
    --type LGBModel \
    --activate

# 2. 列出模型
python manage.py list_models

# 3. 查看模型详情
python manage.py shell
>>> from apps.alpha.infrastructure.models import QlibModelRegistryModel
>>> model = QlibModelRegistryModel.objects.get(artifact_hash="...")
>>> print(f"IC: {model.ic}, ICIR: {model.icir}")

# 4. 测试回滚
python manage.py rollback_model --model-name test_model --prev
```

### Artifact 验证

```bash
# 检查 artifact 目录结构
ls -la /models/qlib/test_model/abc123.../

# 应该包含：
# model.pkl
# config.json
# metrics.json
# feature_schema.json
# data_version.txt
```
