# Qlib Model Training Guide

> **最后更新**: 2026-03-03
> **版本**: V1.0

本指南介绍如何使用 Qlib 训练 Alpha 模型，包括环境配置、数据准备、模型训练、评估和部署。

## 目录

1. [环境配置](#1-环境配置)
2. [数据准备](#2-数据准备)
3. [模型训练](#3-模型训练)
4. [模型评估](#4-模型评估)
5. [生产部署](#5-生产部署)
6. [故障排查](#6-故障排查)

---

## 1. 环境配置

### 1.1 安装 Qlib

```bash
# 激活虚拟环境
conda activate agomtradepro
# 或
source agomtradepro/bin/activate

# 安装 Qlib
pip install pyqlib

# 验证安装
python -c "import qlib; print(qlib.__version__)"
```

### 1.2 安装依赖

```bash
# 核心依赖
pip install lightgbm xgboost
pip install torch torchvision  # 如需使用 LSTM/MLP

# 数据处理
pip install pandas numpy pyyaml
```

### 1.3 配置数据源

编辑 `shared/config/secrets.py`：

```python
# Tushare 配置
data_sources:
  tushare_token: "your_token_here"
```

---

## 2. 数据准备

### 2.1 使用数据准备脚本

```bash
# 准备 CSI300 数据（默认）
python scripts/prepare_qlib_training_data.py --universe csi300 --start-date 2020-01-01

# 准备 CSI500 数据
python scripts/prepare_qlib_training_data.py --universe csi500 --start-date 2020-01-01

# 使用 AKShare 数据源
python scripts/prepare_qlib_training_data.py --universe csi300 --source akshare

# 检查现有数据
python scripts/prepare_qlib_training_data.py --check
```

### 2.2 数据格式要求

Qlib 训练数据需要以下格式：

| 字段 | 说明 | 示例 |
|------|------|------|
| date | 交易日期 | 2026-03-03 |
| open | 开盘价 | 10.50 |
| high | 最高价 | 10.80 |
| low | 最低价 | 10.40 |
| close | 收盘价 | 10.70 |
| volume | 成交量 | 1000000 |
| amount | 成交额 | 10700000 |

### 2.3 特征工程

特征定义位于 `config/qlib/features.yaml`：

```yaml
features:
  # 收益率特征
  - Ref($close, 1) / $close - 1
  - Ref($close, 5) / $close - 1

  # 移动平均
  - Mean($close, 5) / $close
  - Mean($close, 20) / $close

  # 波动率
  - Std($close, 20) / $close

  # 动量
  - $close / Ref($close, 5) - 1
```

自定义特征：

1. 编辑 `config/qlib/features.yaml`
2. 重新运行数据准备脚本
3. 重新训练模型

---

## 3. 模型训练

### 3.1 使用管理命令训练

```bash
# 基础训练
python manage.py train_qlib_model --name lgb_csi300 --type LGBModel

# 指定配置文件
python manage.py train_qlib_model --name lgb_csi300 --type LGBModel \
    --config config/qlib/lgb_csi300.yaml

# 训练完成后自动激活
python manage.py train_qlib_model --name lgb_csi300 --type LGBModel --activate

# 异步训练（推荐）
python manage.py train_qlib_model --name lgb_csi300 --type LGBModel --async
```

### 3.1.1 使用 Admin 页面提交训练

现在系统也支持从 Django Admin 发起训练任务：

```text
/admin/alpha/qlibmodelregistrymodel/
```

列表页右上角有：

- `发起训练`
- `导入模型`

点击 `发起训练` 后可填写：

- 模型名称
- 模型类型
- 股票池
- 训练开始/结束日期
- 特征集标识 / 标签标识
- 学习率 / 训练轮数
- 模型参数 JSON
- 附加训练配置 JSON
- 是否训练完成后自动激活

提交后系统会把任务投递到 `qlib_train` Celery 队列。

### 3.2 模型类型选择

| 模型类型 | 特点 | 训练时间 | 适用场景 |
|---------|------|---------|---------|
| LGBModel | 训练快，效果好 | 短 | 推荐首选 |
| MLPModel | 轻量级神经网络 | 中 | 特征复杂场景 |
| LSTMModel | 捕捉时序依赖 | 长 | 有明确趋势 |

### 3.3 超参数调优

编辑配置文件 `config/qlib/lgb_csi300.yaml`：

```yaml
model:
  learning_rate: 0.0421    # 学习率
  num_leaves: 210          # 叶子节点数
  max_depth: 8             # 树深度
  subsample: 0.8789        # 采样比例
  lambda_l1: 205.6999      # L1 正则化
  lambda_l2: 580.9768      # L2 正则化
```

### 3.4 异步训练（Celery）

```bash
# 启动 Celery Worker
celery -A core worker -l info -Q qlib_train

# 提交训练任务
python manage.py train_qlib_model --name lgb_csi300 --type LGBModel --async

# 查看任务状态
celery -A core inspect active
```

---

## 4. 模型评估

### 4.1 IC/ICIR 指标说明

| 指标 | 全称 | 说明 | 目标值 |
|------|------|------|--------|
| IC | Information Coefficient | 预测值与真实值的相关系数 | > 0.05 |
| ICIR | Information Coefficient IR | IC 的均值/标准差 | > 0.5 |
| Rank IC | 排名相关性 | 排序预测与真实排序的相关性 | > 0.04 |

### 4.2 查看模型列表

```bash
# 列出所有模型
python manage.py list_models

# 查看模型详情
python manage.py list_models --model-name lgb_csi300
```

输出示例：
```
Model Registry
=============
Name          | Type    | IC    | ICIR  | Active
--------------|---------|-------|-------|--------
lgb_csi300    | LGBModel| 0.052 | 0.82  | Yes
mlp_csi300    | MLPModel| 0.041 | 0.65  | No
```

### 4.3 模型比较

```python
# 在 Django shell 中
python manage.py shell

from apps.alpha.infrastructure.models import QlibModelRegistryModel

# 获取所有模型
models = QlibModelRegistryModel.objects.all()

# 按 IC 排序
for model in models.order_by('-ic'):
    print(f"{model.model_name}: IC={model.ic}, ICIR={model.icir}")
```

### 4.4 模型回测

```bash
# 运行回测
python apps/alpha/management/commands/backtest_model.py \
    --model-name lgb_csi300 \
    --start-date 2024-01-01 \
    --end-date 2024-12-31
```

---

## 5. 生产部署

### 5.1 激活模型

```bash
# 激活模型
python manage.py activate_model --model-name lgb_csi300 --version <artifact_hash>

# 使用最新版本
python manage.py activate_model --model-name lgb_csi300
```

### 5.2 定时推理任务

配置 Celery Beat：

```python
# core/celery.py
CELERY_BEAT_SCHEDULE = {
    'qlib-daily-inference': {
        'task': 'apps.alpha.application.tasks.qlib_predict_scores',
        'schedule': crontab(hour=18, minute=0),  # 每天 18:00
        'args': ('csi300', date.today().isoformat(), 30)
    },
}
```

### 5.3 监控和告警

查看告警记录：

```python
from apps.alpha.infrastructure.models import AlphaAlertModel

# 查看最近告警
alerts = AlphaAlertModel.objects.filter(
    created_at__gte=timezone.now() - timedelta(days=7)
)

for alert in alerts:
    print(f"{alert.severity}: {alert.title}")
```

### 5.4 模型回滚

```bash
# 回滚到上一个版本
python manage.py rollback_model --model-name lgb_csi300

# 回滚到指定版本
python manage.py rollback_model --model-name lgb_csi300 --version <hash>
```

---

## 6. 故障排查

### 6.1 Qlib 初始化失败

**症状**: `RuntimeError: qlib not initialized`

**解决**:
```bash
# 检查数据目录
ls ~/.qlib/qlib_data/cn_data

# 初始化 Qlib 数据
python manage.py init_qlib_data
```

### 6.2 训练数据缺失

**症状**: `ValueError: No data found for date range`

**解决**:
```bash
# 重新准备数据
python scripts/prepare_qlib_training_data.py --universe csi300 --force
```

### 6.3 模型评估指标异常

**症状**: IC < 0 或 ICIR 过低

**可能原因**:
1. 数据质量问题（检查数据源）
2. 特征工程不足（修改 features.yaml）
3. 模型过拟合（调整正则化参数）

### 6.4 推理任务失败

**症状**: Celery 任务一直 Pending

**检查**:
```bash
# 检查 Celery 状态
celery -A core inspect active

# 检查队列配置
celery -A core inspect active_queues
```

### 6.5 模型激活失败

**症状**: `CommandError: Model not found`

**检查**:
```bash
# 列出可用模型
python manage.py list_models

# 检查模型文件
ls /models/qlib/<model_name>/
```

---

## 附录

### A. 配置文件路径

| 文件 | 路径 |
|------|------|
| LightGBM 配置 | `config/qlib/lgb_csi300.yaml` |
| LSTM 配置 | `config/qlib/lstm_csi300.yaml` |
| MLP 配置 | `config/qlib/mlp_csi300.yaml` |
| 特征定义 | `config/qlib/features.yaml` |

### B. 管理命令速查

| 命令 | 说明 |
|------|------|
| `init_qlib_data` | 初始化 Qlib 数据 |
| `train_qlib_model` | 训练模型 |
| `list_models` | 列出模型 |
| `activate_model` | 激活模型 |
| `rollback_model` | 回滚模型 |

### C. 常用 Celery 任务

| 任务 | 队列 | 说明 |
|------|------|------|
| `qlib_train_model` | qlib_train | 模型训练 |
| `qlib_predict_scores` | qlib_infer | 推理预测 |
| `qlib_evaluate_model` | qlib_train | 模型评估 |
| `qlib_refresh_cache` | qlib_infer | 刷新缓存 |

---

**参考文档**:
- [Alpha 模块指南](./alpha-guide.md)
- [Qlib 官方文档](https://qlib.readthedocs.io/)
- [CLAUDE.md](../../../CLAUDE.md)
