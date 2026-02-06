# Alpha 模块指南

> **最后更新**: 2026-02-06

## 概述

Alpha 模块是 AgomSAAF 的 AI 选股信号抽象层，与 Qlib 深度集成，支持 4 层降级机制。

## 架构

### 四层降级机制

1. **Qlib Provider** - Qlib 模型推理（最高优先级）
2. **Cache Provider** - 缓存预测结果
3. **Simple Provider** - 简单因子模型
4. **ETF Provider** - ETF 替代方案（兜底）

## API 端点

| 端点 | 说明 |
|------|------|
| `GET /api/alpha/scores/` | 获取股票评分 |
| `GET /api/alpha/providers/status/` | Provider 状态 |
| `GET /api/alpha/universes/` | 股票池 |
| `GET /api/alpha/health/` | 健康检查 |

## 管理命令

```bash
# 初始化 Qlib 数据
python manage.py init_qlib_data --check

# 训练模型
python manage.py train_qlib_model --name mlp_csi300 --type LGBModel --activate

# 激活模型
python manage.py activate_model --model-name mlp_csi300 --version <hash>

# 列出模型
python manage.py list_models
```

## Celery 任务

| 任务 | 队列 | 说明 |
|------|------|------|
| `qlib_predict_scores` | qlib_infer | Qlib 推理 |
| `qlib_train_model` | qlib_train | Qlib 训练 |
| `qlib_evaluate_model` | qlib_train | Qlib 评估 |
| `qlib_refresh_cache` | qlib_infer | 刷新缓存 |

## 快速开始

详见 [alpha-quickstart.md](../../business/alpha-quickstart.md)
