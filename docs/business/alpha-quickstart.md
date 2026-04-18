# AgomTradePro Alpha 模块快速开始指南

> **版本**: 1.1
> **更新日期**: 2026-02-06

## 📦 安装与配置

### 1. 数据库迁移

```bash
python manage.py makemigrations alpha
python manage.py migrate
```

### 2. （可选）安装 Qlib

```bash
pip install pyqlib lightgbm scikit-learn
```

### 3. （可选）初始化 Qlib 数据

```bash
# 检查 Qlib 数据状态
python manage.py init_qlib_data --check

# 检查自建更新是否具备前置条件
python manage.py build_qlib_data --check-only

# 使用 Tushare 自建最近窗口 Qlib 数据
python manage.py build_qlib_data

# 只更新指定股票池
python manage.py build_qlib_data --universes csi300,csi500

# 下载并初始化数据
python manage.py init_qlib_data --download --universe=csi300
```

## 🚀 启动服务

### Django 服务

```bash
python manage.py runserver
```

### Celery Workers

```bash
# Qlib 推理队列（可选，如果使用 Qlib）
celery -A core worker -l info -Q qlib_infer --max-tasks-per-child=10

# Qlib 训练队列（可选）
celery -A core worker -l info -Q qlib_train --max-tasks-per-child=1
```

## 📊 API 使用

### 获取股票评分

```bash
curl "http://localhost:8000/api/alpha/scores/?universe=csi300&top_n=10"
```

**响应示例**：
```json
{
  "success": true,
  "source": "qlib",
  "status": "available",
  "metadata": {
    "requested_trade_date": "2026-04-06",
    "effective_trade_date": "2026-04-03",
    "trade_date_adjusted": true,
    "trade_date_adjust_reason": "请求交易日 2026-04-06 尚无本地 Qlib 日线，已回退到最新可用交易日 2026-04-03。"
  },
  "stocks": [
    {
      "code": "600519.SH",
      "score": 0.8234,
      "rank": 1,
      "factors": {},
      "source": "qlib",
      "confidence": 0.8,
      "asof_date": "2026-04-03"
    }
  ]
}
```

### 获取首页账户驱动 Alpha 候选

```bash
curl "http://localhost:8000/api/dashboard/alpha/stocks/?format=json&top_n=10"
```

说明：

- 这条接口不是固定查 `csi300`
- 默认会按当前激活组合生成账户驱动池
- 返回 `Alpha Top 候选/排名`、`可行动候选`、`待执行队列`
- 同时包含缓存日期、回退原因、买入理由、不买理由、证伪条件、建议仓位与最近历史 run

### 查看 Provider 状态

```bash
curl "http://localhost:8000/api/alpha/providers/status/"
```

**响应示例**：
```json
{
  "cache": {
    "priority": 10,
    "status": "available",
    "max_staleness_days": 5
  },
  "simple": {
    "priority": 100,
    "status": "available",
    "max_staleness_days": 7
  },
  "etf": {
    "priority": 1000,
    "status": "available",
    "max_staleness_days": 30
  },
  "qlib": {
    "priority": 1,
    "status": "available",
    "max_staleness_days": 2
  }
}
```

## 🐍 Python SDK

### 基础使用

```python
from agomtradepro import AgomTradeProClient

client = AgomTradeProClient()

# 获取 universe / 研究视角评分
result = client.alpha.get_stock_scores("csi300", top_n=10)

print(f"数据源: {result['source']}")
print(f"状态: {result['status']}")
print(f"股票数量: {len(result['stocks'])}")

for stock in result['stocks']:
    print(f"{stock['rank']}. {stock['code']}: {stock['score']:.3f}")

# 获取首页账户驱动候选
dashboard_alpha = client.dashboard.alpha_stocks(top_n=10, portfolio_id=21)
print(dashboard_alpha["data"]["pool"]["label"])
print(len(dashboard_alpha["data"]["top_candidates"]))
```

### 便捷方法

```python
# 获取排名前 N 的股票
top_stocks = client.alpha.get_top_stocks("csi300", top_n=5)

# 比较多只股票
comparison = client.alpha.compare_stocks(
    stock_codes=["600519.SH", "000333.SH", "000858.SH"],
    universe="csi300"
)

# 健康检查
health = client.alpha.check_health()
print(f"系统状态: {health['status']}")
```

## 🔧 模型管理

### 训练模型

```bash
# 同步训练
python manage.py train_qlib_model \
    --name mlp_csi300 \
    --type LGBModel \
    --universe csi300 \
    --activate

# 异步训练（后台执行）
python manage.py train_qlib_model \
    --name lstm_csi500 \
    --async
```

### 模型管理命令

```bash
# 列出所有模型
python manage.py list_models

# 只显示激活的模型
python manage.py list_models --active

# 激活指定模型
python manage.py activate_model abc123...

# 回滚到上一版本
python manage.py rollback_model --model-name mlp_csi300 --prev
```

## 📝 MCP 工具

### 在 Claude Code 中使用

```python
# 获取 universe / 研究视角评分
get_alpha_stock_scores(universe="csi300", top_n=10)

# 获取首页账户驱动 Alpha 候选
get_dashboard_alpha_candidates(top_n=10, portfolio_id=21)

# 查询历史 run 列表
get_dashboard_alpha_history(portfolio_id=21, stage="actionable")

# 查看单次历史 run 详情
get_dashboard_alpha_history_detail(run_id=128)

# 手动触发当前组合实时刷新
trigger_dashboard_alpha_refresh(top_n=10, portfolio_id=21)

# 查看 Provider 状态
get_alpha_provider_status()

# 健康检查
check_alpha_health()
```

提示：

- `get_alpha_stock_scores(...)` 仍按 `universe` 查询，适合研究池和离线评分上传链路
- 首页/账户候选请改用 `get_dashboard_alpha_candidates(...)`
- 历史回溯请用 `get_dashboard_alpha_history(...)` 和 `get_dashboard_alpha_history_detail(...)`

## 🔍 故障排查

### Provider 不可用

```bash
# 检查 Provider 状态
curl "http://localhost:8000/api/alpha/providers/status/"

# 检查日志
tail -f logs/alpha.log
```

### Qlib 相关问题

```bash
# 检查 Qlib 数据
python manage.py init_qlib_data --check
python manage.py build_qlib_data --check-only

# 自建最近窗口数据
python manage.py build_qlib_data

# 检查 Celery 任务
celery -A core inspect active

# 查看 Qlib worker 日志
celery -A core worker -l info -Q qlib_infer
```

### 缓存过期

```python
from apps.alpha.application.services import AlphaService

service = AlphaService()
result = service.get_stock_scores("csi300")

# 检查 staleness
if result['staleness_days']:
    print(f"数据过期 {result['staleness_days']} 天")
```

## 📚 更多信息

- [完整实施方案](../plans/agomtradepro-qlib-integration-plan-v1.1.md)
- [实施进度总结](../plans/implementation-progress-summary.md)
- [项目规则](../../CLAUDE.md)
- [Alpha 模块指南](../modules/alpha/alpha-guide.md)
