# Alpha 模块指南

> **最后更新**: 2026-03-30

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
| `GET /api/alpha/scores/` + `universe` / `trade_date` / `top_n` 查询参数 | 按股票池、交易日和返回数量读取评分 |
| `POST /api/alpha/scores/upload/` | 上传本地 Qlib / 离线评分 |
| `GET /api/alpha/providers/status/` | Provider 状态 |
| `GET /api/alpha/universes/` | 股票池 |
| `GET /api/alpha/health/` | 健康检查 |

## 用户隔离与本地上传

- `user=NULL`：系统级评分，所有用户可回退读取
- `user=<当前用户>`：个人评分，仅本人和 admin 可见
- 读取优先级：个人评分优先，找不到再回退到系统级

### Dashboard 展示规则

- Dashboard Alpha 卡片与 `GET /api/dashboard/alpha/stocks/` 现在会显式携带当前登录用户。
- 这保证了页面会先读取“当前用户的 Alpha 缓存”，再按既有逻辑回退到系统级缓存。
- 当更高优先级 Provider 不可用、而较低优先级只剩过期缓存时，系统会返回“最优过期结果（degraded）”，避免页面出现空白。
- 如果 `/api/alpha/scores/` 有数据而 Dashboard 为空，先检查当前登录用户是否就是缓存所属用户，或是否存在 `user=NULL` 的系统级缓存。
- 当本地 Celery worker 未监听 `qlib_infer` 时，Qlib 异步推理会自动回退投递到默认 `celery` 队列，避免开发环境任务堆在死队列。
- 当当日 Qlib 实时推理失败但历史 Qlib 缓存仍可用时，系统会把最近一次可用结果前推写入当天槽位，并标记为 `degraded`，保证 dashboard 仍能展示 Alpha 推荐。
- 当前前端、`/api/alpha/scores/` 与 MCP `get_alpha_stock_scores` 都会显式返回 `reliability_notice` / `warning_message`，说明是否使用缓存、是否为前推结果、信号日期和降级原因。

### 常见排查项

- `qlib` 为 `degraded` 且提示“触发异步推理任务”：说明模型存在，但当天缓存尚未产出。
- `cache` 为 `degraded`：说明最近缓存日期已超过 `max_staleness_days`。
- `simple` 为 `unavailable`：通常是估值/财务数据超过 7 天未刷新。
- `etf` 为 `unavailable`：通常是 ETF 持仓表为空，无法生成替代推荐。
- 如果提示“本地 Qlib 数据最新交易日为 2020-09-25”这类信息，说明不是代码逻辑静默失败，而是本地 qlib 数据集未同步到当前交易日；系统会继续展示前推缓存，但不会把它伪装成新鲜数据。
- `system_settings.qlib_enabled=1` 但数据库里的 `qlib_provider_uri` / `qlib_model_path` 为空：说明系统正在依赖代码 fallback 路径运行。生产和本地正式库都应把这两个字段显式写回数据库，避免环境迁移时出现“开关已开但路径丢失”的隐性故障。

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

## Provider 配置 (V3.6 新增)

### Provider 过滤器

通过 API 参数强制使用指定 Provider：

```
GET /api/alpha/scores/?provider=qlib     # 强制使用 Qlib Provider
GET /api/alpha/scores/?provider=cache    # 强制使用缓存
GET /api/alpha/scores/?provider=simple   # 强制使用简单模型
GET /api/alpha/scores/?provider=etf      # 强制使用 ETF 兜底
```

### 固定 Provider 配置

在系统设置中配置全局固定 Provider：

```python
# SystemSettingsModel.alpha_fixed_provider
# 可选值: qlib / cache / simple / etf / 留空（自动降级）
```

配置后，所有 Alpha 查询将强制使用指定 Provider，不会自动降级。

### 诊断端点

```
GET /api/alpha/providers/status/    # 查看所有 Provider 状态
GET /api/alpha/health/              # 健康检查 + 诊断信息
```
