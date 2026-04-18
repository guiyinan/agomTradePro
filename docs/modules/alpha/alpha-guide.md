# Alpha 模块指南

> **最后更新**: 2026-04-18

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
| `GET /api/dashboard/alpha/stocks/?format=json` | 获取首页账户驱动 Alpha 候选/排名、可行动候选、待执行队列 |
| `POST /api/dashboard/alpha/refresh/` | 手动触发首页账户驱动池的 Qlib 异步实时推理 |
| `GET /api/dashboard/alpha/history/` | 获取首页 Alpha 历史 run 列表 |
| `GET /api/dashboard/alpha/history/<run_id>/` | 获取单次历史 run 的逐票快照详情 |
| `POST /api/alpha/scores/upload/` | 上传本地 Qlib / 离线评分 |
| `GET /api/alpha/providers/status/` | Provider 状态 |
| `GET /api/alpha/universes/` | 股票池 |
| `GET /api/alpha/health/` | 健康检查 |

## 两条 Alpha 读取口径

### 1. Universe / 研究口径

- 使用 `/api/alpha/scores/`、SDK `client.alpha.get_stock_scores(...)`、MCP `get_alpha_stock_scores(...)`
- 适合研究固定 universe，如 `csi300`、`csi500`
- 返回的是 Alpha 排名结果，不包含账户级风控和建议仓位

### 2. Dashboard / 账户口径

- 使用 `/api/dashboard/alpha/stocks/?format=json`
- 默认按当前激活组合解析账户驱动池，不再固定绑定 `csi300`
- 返回三层视图：
  - `Alpha Top 候选/排名`
  - `可行动候选`
- `待执行队列`
- 同时返回：
  - 池子说明、池子规模、组合信息
  - 缓存日期 / 回退原因 / 实时刷新状态
  - 买入理由 / 不买理由 / 证伪条件
  - 风控闸门 / 建议仓位 / 建议数量
  - 最近历史 run 摘要
- 如果账户驱动池暂无真实 Qlib 推理或缓存结果，Dashboard 不会回退到硬编码股票池、静态名单或默认 ETF 来冒充推荐；页面会明确显示“暂无可信 Alpha 推荐”，并提示触发实时推理。
- 当账户池 cache 缺失时，Dashboard 会异步触发当前账户池 scope 的 Qlib 推理任务，并通过前端轻状态提示“后台正在生成账户池 Alpha cache”；页面轮询刷新，直到真实 cache 落库后再展示推荐。

## 用户隔离与本地上传

- `user=NULL`：系统级评分，所有用户可回退读取
- `user=<当前用户>`：个人评分，仅本人和 admin 可见
- 读取优先级：个人评分优先，找不到再回退到系统级

### Dashboard 展示规则

- Dashboard Alpha 卡片与 `GET /api/dashboard/alpha/stocks/` 现在会显式携带当前登录用户。
- 这保证了页面只读取当前账户池 scope 的 Alpha 缓存；不得回退到固定 `csi300`、全局静态列表、ETF 兜底或任何硬编码推荐。
- 首页首屏不再同步执行 Qlib 推理或 Provider 深度健康检查；登录到首页时只读取缓存/轻量注册状态。若账户池 cache 缺失，后台会自动异步投递 scoped Qlib 推理，前端只显示状态并按 `poll_after_ms` 轮询。
- 手动实时刷新可通过 `/api/dashboard/alpha/refresh/`、页面“实时刷新”按钮或 MCP `trigger_dashboard_alpha_refresh(...)` 触发；它只排队后台任务，不直接产生推荐。
- 自动或手动触发的后台推理必须携带账户池 `scope_payload`，不得固定使用 `csi300` 或任何硬编码 universe；同一 scope/date/top_n 会用短 TTL 锁去重，避免用户刷新页面时重复投递任务。
- 首页主 Workflow 面板只展示有真实模型/缓存依据的 `Alpha Top 候选/排名`；当当前 Top 排名为空时，不再使用可行动候选或待执行请求顶替推荐资产。
- `待执行队列` 来自已审批且 `execution_status` 为 `PENDING` / `FAILED` 的决策请求，不等于当前 Alpha Top 排名；页面可将其“丢弃待执行”，后台会调用取消接口把状态改为 `CANCELLED`，记录仍保留用于回溯。
- 每条推荐必须带出明确依据：Provider / score source、账户池 scope、评分日、rank、score、confidence，以及可展示的因子明细。
- SDK/MCP `get_dashboard_alpha_candidates(...)` 会附带 `contract`；只有 `contract.recommendation_ready=true` 才能被 Agent 当成可展示推荐，`async_refresh_queued=true` 或 `must_not_treat_as_recommendation=true` 只能说明后台正在生成 cache。
- 首页 AI 建议默认使用本地规则生成，避免登录跳转时等待外部 AI API；如确需同步调用外部 AI，可显式开启 `DASHBOARD_SYNC_AI_INSIGHTS_ENABLED=True`。
- 如果 `/api/alpha/scores/` 有数据而 Dashboard 为空，先检查当前登录用户是否就是缓存所属用户、是否存在 `user=NULL` 的系统级缓存，以及账户池 `scope_hash` 是否已有专属缓存。只有全局 `csi300` 缓存而没有账户池 scope 缓存时，Dashboard 仍应保持为空并提示触发账户池实时推理。
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
- `get_dashboard_alpha_candidates(...)`
- `get_dashboard_alpha_history(...)`
- `get_dashboard_alpha_history_detail(...)`
- `trigger_dashboard_alpha_refresh(...)`

其中：

- admin 可通过 `user_id` 参数查看指定用户的个人评分
- `get_alpha_stock_scores(...)` 仍是 universe / 研究视角
- `get_dashboard_alpha_candidates(...)` 是首页账户驱动视角
- 历史回溯通过 `get_dashboard_alpha_history(...)` 与 `get_dashboard_alpha_history_detail(...)` 获取
- `trigger_dashboard_alpha_refresh(...)` 返回 Celery `task_id`，实际任务是 `apps.alpha.application.tasks.qlib_predict_scores`，路由到 `qlib_infer` 队列

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
