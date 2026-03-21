# Alpha 模块指南

> **最后更新**: 2026-03-03

## 概述

Alpha 模块是 AgomTradePro 的 AI 选股信号抽象层，与 Qlib 深度集成，支持 4 层降级机制。

**相关文档**:
- [Qlib 模型训练指南](./training-guide.md) - 详细的模型训练、评估和部署指南
- [Qlib 模型导入说明](./qlib-model-import-guide.md) - `model.pkl` 来源、Admin 导入、目录结构与限制
- [Qlib 训练运行时搭建与接入指南](../../deployment/QLIB_TRAIN_RUNTIME_SETUP.md) - 如何让系统真正训练出模型并接入当前 Admin / Celery

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
| `GET /api/alpha/scores/?user_id=<id>` | 管理员按用户查看个人评分 |
| `POST /api/alpha/scores/upload/` | 上传本地 Qlib / 离线评分 |
| `GET /api/alpha/providers/status/` | Provider 状态 |
| `GET /api/alpha/universes/` | 股票池 |
| `GET /api/alpha/health/` | 健康检查 |

## 用户隔离与本地上传

- `user=NULL`：系统级评分，所有用户可回退读取
- `user=<当前用户>`：个人评分，仅本人和 admin 可见
- 读取优先级：个人评分优先，找不到再回退到系统级

### 本地上传方式

- SDK：`client.alpha.upload_scores(...)`
- CLI：`python tools/qlib_uploader.py --input scores.json ...`
- MCP：`upload_alpha_scores(...)`

### MCP 支持

MCP 现已支持这条工作流：

- `get_alpha_stock_scores(...)`
- `upload_alpha_scores(...)`

其中 admin 可通过 `user_id` 参数查看指定用户的个人评分。

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

## 模型训练

详见 [training-guide.md](./training-guide.md) 获取：
- 环境配置步骤
- 数据准备指南
- 模型训练命令
- IC/ICIR 指标说明
- 生产部署流程

## 模型导入

如果你手上已经有离线训练好的 `model.pkl`，而不是准备在当前项目里重新训练，详见 [qlib-model-import-guide.md](./qlib-model-import-guide.md)。
