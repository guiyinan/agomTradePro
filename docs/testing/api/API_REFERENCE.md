# AgomTradePro API 参考文档

> **版本**: v1.1
> **更新**: 2026-03-31
> **Base URL**: `http://localhost:8000/api/`

---

## 概述

AgomTradePro 提供完整的 RESTful API，支持个人投研平台的全部功能，包括：
- 宏观数据采集与 Regime 判定
- 政策事件管理与投资信号验证
- 个股/板块/基金分析
- 回测引擎与事后审计
- 账户管理与风控体系
- AI 辅助分析与报告生成

---

## 目录

1. [宏观模块 (Macro)](#1-宏观模块-macro)
2. [Regime 判定 (Regime)](#2-regime-判定-regime)
3. [政策管理 (Policy)](#3-政策管理-policy)
4. [投资信号 (Signal)](#4-投资信号-signal)
5. [个股分析 (Equity)](#5-个股分析-equity)
6. [板块分析 (Sector)](#6-板块分析-sector)
7. [基金分析 (Fund)](#7-基金分析-fund)
8. [回测引擎 (Backtest)](#8-回测引擎-backtest)
9. [账户管理 (Account)](#9-账户管理-account)
10. [审计分析 (Audit)](#10-审计分析-audit)
11. [AI 分析 (Prompt)](#11-ai-分析-prompt)
12. [筛选器 (Filter)](#12-筛选器-filter)
13. [市场数据 (Market Data)](#13-市场数据-market-data)

---

## 1. 宏观模块 (Macro)

### 1.1 宏观数据 API

> **标准前缀**: `/api/macro/`
> **说明**: 仅文档化 canonical `/api/macro/` 前缀。

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/macro/supported-indicators/` | GET | 获取支持的指标列表 |
| `/api/macro/indicator-data/?code={code}` | GET | 获取指定指标数据 |
| `/api/macro/fetch/` | POST | 按条件抓取数据 |
| `/api/macro/quick-sync/` | POST | 快速同步（页面按钮调用） |
| `/api/macro/table/` | GET | 数据管理器表格分页 |
| `/api/health/` | GET | 系统 liveness 健康检查 |
| `/api/ready/` | GET | 系统 readiness 检查（DB/Redis/Celery） |

#### 请求示例

```bash
# 获取指标数据
GET /api/macro/indicator-data/?code=CN_PMI

# 快速同步
POST /api/macro/quick-sync/
{
  "codes": ["CN_PMI", "CN_CPI", "M2"]
}
```

#### 响应示例

```json
{
  "count": 120,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 1,
      "code": "china_pmi",
      "value": 50.8,
      "reporting_period": "2024-12-01",
      "period_type": "month",
      "published_at": "2024-12-31",
      "source": "stats_gov",
      "unit": "指数"
    }
  ]
}
```

---

## 2. Regime 判定 (Regime)

### 2.1 Regime API

> **注意**: 大部分端点需要认证
> **路由格式**: 统一使用 `/api/{module}/{endpoint}/` 格式
> **向后兼容**: 旧格式 `/api/{module}/api/{endpoint}/` 仍可用

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/regime/` | GET | 获取 Regime 历史记录 (需认证) |
| `/api/regime/{id}/` | GET | 获取指定 Regime 详情 (需认证) |
| `/api/regime/health/` | GET | Regime 模块健康检查 (需认证) |
| `/api/regime/current/` | GET | 获取当前 Regime 状态 (需认证) |
| `/api/regime/calculate/` | POST | 计算 Regime 判定 (需认证) |
| `/api/regime/history/` | GET | 获取 Regime 历史趋势 (需认证) |
| `/api/regime/distribution/` | GET | 获取 Regime 分布统计 (需认证) |
| `/regime/dashboard/` | GET | Regime 仪表盘页面 |

#### 请求示例

```bash
# 获取 Regime 列表 (需要认证)
GET /api/regime/
Authorization: Token your_api_token_here

# 获取当前 Regime (需要认证)
GET /api/regime/current/
Authorization: Token your_api_token_here

# 健康检查 (需要认证)
GET /api/regime/health/
```

---

## 3. 政策管理 (Policy)

### 3.1 政策事件 API

> **路由格式**: 统一使用 `/api/{module}/{endpoint}/` 格式
> **说明**: 仅文档化 canonical `/api/policy/` 前缀。

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/policy/events/` | GET | 获取政策事件列表 (需认证) |
| `/api/policy/events/{event_date}/` | GET | 获取指定日期政策事件 (需认证) |
| `/api/policy/events/` | POST | 创建政策事件 (需认证) |
| `/policy/events/` | GET | 政策事件列表页 |
| `/policy/events/new/` | GET | 新增政策事件页面 |
| `/policy/events/{event_date}/` | GET | 兼容详情入口，当前重定向到 `/policy/workbench/` |
| `/policy/status/` | GET | 获取当前政策档位 |
| `/api/hedge/pairs/` | GET | 获取对冲配对 |
| `/api/hedge/actions/` | POST | 执行对冲相关计算/动作 |

#### 请求示例

```bash
# 创建政策事件
POST /policy/events/new/
{
  "event_date": "2024-12-31",
  "level": "P1",
  "title": "央行降息",
  "description": "央行下调LPR利率25bp",
  "evidence_url": "https://..."
}
```

#### 响应示例

```json
{
  "id": 1,
  "event_date": "2024-12-31",
  "level": "P1",
  "title": "央行降息",
  "current_level": "P1",
  "is_p2": false,
  "is_p3": false
}
```

---

## 4. 投资信号 (Signal)

### 4.1 投资信号 API

> **注意**: 大部分端点需要认证

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/signal/` | GET/POST | 获取/创建投资信号 (需认证) |
| `/api/signal/{id}/` | GET | 获取信号详情 (需认证) |
| `/api/signal/health/` | GET | 信号模块健康检查 (需认证) |
| `/signal/manage/` | GET | 信号管理页面 |

#### 请求示例

```bash
# 获取信号列表 (需要认证)
GET /api/signal/
Authorization: Token your_api_token_here

# 健康检查 (需要认证)
GET /api/signal/health/
```

---

## 4.1 舆情分析 (Sentiment)

### 4.1.1 Sentiment API

> **注意**: 所有端点需要认证

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/sentiment/analyze/` | POST | 分析单条文本情感 |
| `/api/sentiment/batch-analyze/` | POST | 批量分析多条文本 |
| `/api/sentiment/index/` | GET | 获取情绪指数 |
| `/api/sentiment/index/range/` | GET | 获取日期范围内指数 |
| `/api/sentiment/index/recent/` | GET | 获取最近N天指数 |
| `/api/sentiment/health/` | GET | 健康检查 |
| `/sentiment/dashboard/` | GET | 舆情仪表盘页面 |

#### 请求示例

```bash
# 分析文本情感 (需要认证)
POST /api/sentiment/analyze/
Authorization: Token your_api_token_here
{
  "text": "市场今日大涨，投资者信心恢复",
  "source": "news"
}

# 获取情绪指数
GET /api/sentiment/index/?date=2024-12-31
```

---

## 5. 个股分析 (Equity)

### 5.1 个股分析 API

> **主路径**: `/api/equity/`
> **说明**: 仅文档化 canonical `/api/equity/` 前缀。

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/equity/screen/` | POST | 股票筛选 |
| `/api/equity/valuation/{stock_code}/` | GET | 估值分析 |
| `/api/equity/dcf/` | POST | DCF 绝对估值 |
| `/api/equity/regime-correlation/{stock_code}/` | GET | Regime 相关性分析 |
| `/api/equity/comprehensive-valuation/` | POST | 综合估值分析 |
| `/api/equity/multidim-screen/` | POST | 多维度筛选 |
| `/api/equity/pool/` | GET | 获取股票池 |
| `/api/equity/pool/refresh/` | POST | 刷新股票池 |

#### 请求示例

```bash
# 股票筛选
POST /api/equity/screen/
{
  "sector": "医药生物",
  "min_pe": 10,
  "max_pe": 30,
  "min_roe": 15,
  "min_revenue_growth": 10
}
```

#### 响应示例

```json
{
  "count": 25,
  "results": [
    {
      "stock_code": "600519.SH",
      "name": "贵州茅台",
      "sector": "食品饮料",
      "pe_ttm": 28.5,
      "pb": 8.2,
      "roe": 25.3,
      "revenue_growth": 15.2
    }
  ]
}
```

---

## 6. 板块分析 (Sector)

### 6.1 板块分析 API

| 端点 | 方法 | 描述 |
|------|------|------|
| `/sector/rotation/` | GET | 获取板块轮动分析 |
| `/api/sector/analyze/` | POST | 分析板块轮动 |
| `/api/sector/rotation/` | GET | 获取板块轮动推荐 |
| `/api/sector/update-data/` | POST | 更新板块数据 |

#### 请求示例

```bash
# 获取板块轮动
GET /api/sector/rotation/?window=20

# 获取板块表现
GET /api/sector/rotation/?regime=Recovery&top_n=10
```

---

## 7. 基金分析 (Fund)

### 7.1 基金分析 API

> **主路径**: `/api/fund/`
> **说明**: 仅文档化 canonical `/api/fund/` 前缀。

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/fund/` | GET | 基金 API 根路径（端点清单） |
| `/api/fund/screen/` | POST | 基金筛选 |
| `/api/fund/rank/` | GET | 基金排名 |
| `/api/fund/style/{fund_code}/` | GET | 分析基金风格 |
| `/api/fund/performance/calculate/` | POST | 计算基金业绩 |
| `/api/fund/info/{fund_code}/` | GET | 获取基金信息 |
| `/api/fund/nav/{fund_code}/` | GET | 获取基金净值 |
| `/api/fund/holding/{fund_code}/` | GET | 获取基金持仓 |
| `/api/fund/multidim-screen/` | POST | 多维度筛选 |

#### 请求示例

```bash
# 基金筛选
POST /api/fund/screen/
{
  "fund_type": "股票型",
  "min_annual_return": 10,
  "max_drawdown": 30,
  "min_sharpe": 0.5
}
```

---

## 8. 回测引擎 (Backtest)

### 8.1 回测 API

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/backtest/backtests/` | GET | 获取回测列表 |
| `/api/backtest/backtests/{id}/` | GET | 获取回测详情 |
| `/api/backtest/run/` | POST | 运行回测 |
| `/api/backtest/validate/` | POST | 验证策略 |

#### 请求示例

```bash
# 运行回测
POST /api/backtest/run/
{
  "start_date": "2020-01-01",
  "end_date": "2024-12-31",
  "rebalance_frequency": "monthly",
  "signals": ["000300.SH", "000905.SH"],
  "initial_capital": 1000000,
  "use_pit": true
}
```

#### 响应示例

```json
{
  "id": 1,
  "total_return": 85.5,
  "annualized_return": 16.8,
  "sharpe_ratio": 1.2,
  "max_drawdown": -18.5,
  "trade_count": 48
}
```

---

## 9. 账户管理 (Account)

### 9.1 账户 API

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/account/portfolios/` | GET | 获取投资组合列表 |
| `/api/account/portfolios/{id}/` | GET | 获取组合详情 |
| `/api/account/positions/` | GET | 获取持仓列表 |
| `/api/account/transactions/` | GET | 获取交易记录 |
| `/api/account/capital-flows/` | GET | 获取资金流水 |
| `/api/account/profile/` | GET | 获取账户配置 |
| `/api/account/portfolios/{id}/allocation/` | GET | 获取资产配置 |
| `/api/account/health/` | GET | 账户健康检查 |

---

## 10. 审计分析 (Audit)

### 10.1 审计 API

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/audit/reports/generate/` | POST | 生成审计/归因报告 |
| `/api/audit/summary/` | GET | 获取审计汇总 |
| `/api/audit/operation-logs/` | GET | 获取操作日志 |
| `/api/audit/decision-traces/` | GET | 获取决策轨迹 |

---

## 11. AI 分析 (Prompt)

### 11.1 AI 分析 API

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/chat/web/` | POST | 网页端统一聊天接口，供首页与 `AgomChatWidget` 复用 |
| `/api/prompt/chat` | POST | AI 对话 |
| `/api/prompt/chat/providers` | GET | 获取 AI 提供商列表 |
| `/api/prompt/chat/models` | GET | 获取 AI 模型列表 |
| `/api/prompt/signals/generate` | POST | 生成投资信号 |
| `/api/prompt/reports/generate` | POST | 生成分析报告 |
| `/api/prompt/chains/` | GET | 获取 Chain 列表 |
| `/api/prompt/templates/` | GET | 获取 Prompt 模板 |

补充文档：

- [Shared Web Chat API 文档](/D:/githv/agomTradePro/docs/api/web-chat-api.md)

#### 请求示例

```bash
# 网页端统一聊天
POST /api/chat/web/
{
  "message": "当前系统是什么状态",
  "session_id": "optional-session-id",
  "context": {
    "history": []
  }
}

# AI 对话
POST /api/prompt/chat/
{
  "provider": "openai",
  "model": "gpt-4",
  "messages": [
    {"role": "user", "content": "分析当前 Regime 并给出投资建议"}
  ]
}

# 生成报告
POST /api/prompt/report-generation/
{
  "template_id": "regime_analysis_report",
  "context": {"as_of_date": "2024-12-31"}
}
```

---

## 12. 筛选器 (Filter)

### 12.1 筛选器 API

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/filter/` | GET | 获取筛选器列表 |
| `/api/filter/get-data/` | POST | 获取已保存筛选/滤波数据 |
| `/api/filter/` | POST | 应用筛选器 |
| `/api/filter/health/` | GET | 筛选器健康检查 |

---

## 13. 决策工作流 (Decision Workflow)

### 13.1 决策工作流 API

> **注意**: 所有端点需要认证

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/decision-workflow/precheck/` | POST | 决策预检查 |
| `/api/decision/workspace/recommendations/` | GET | 获取统一推荐列表 |
| `/api/decision/workspace/recommendations/refresh/` | POST | 刷新统一推荐 |
| `/api/decision/workspace/recommendations/action/` | POST | 记录用户对推荐的动作 |
| `/api/decision/funnel/context/` | GET | 获取决策漏斗上下文 |

#### `/api/decision/funnel/context/` Step 3 补充字段

`data.step3_sectors` 除 `sector_recommendations` 和 `rotation_signals` 外，还返回轮动可靠性元数据：

| 字段 | 类型 | 说明 |
|------|------|------|
| `rotation_data_source` | string \| null | `fresh_generation` / `stored_signal` / `stored_signal_fallback` |
| `rotation_is_stale` | boolean | 是否回退到历史已落库 signal |
| `rotation_warning_message` | string \| null | 回退时给前端/Agent 的提示文案 |
| `rotation_signal_date` | string \| null | 当前轮动信号日期 |

### 13.2 决策预检查 API

`POST /api/decision-workflow/precheck/`

执行决策前的综合检查，包括 Beta Gate、配额、冷却期和候选状态。

#### 请求示例

```bash
POST /api/decision-workflow/precheck/
Authorization: Token your_api_token_here
{
  "candidate_id": "cand_xxx"
}
```

#### 响应示例

```json
{
  "success": true,
  "result": {
    "candidate_id": "cand_xxx",
    "beta_gate_passed": true,
    "quota_ok": true,
    "cooldown_ok": true,
    "candidate_valid": true,
    "warnings": [],
    "errors": []
  }
}
```

#### 检查项说明

| 检查项 | 说明 |
|--------|------|
| `beta_gate_passed` | 资产是否通过 Beta Gate（环境准入） |
| `quota_ok` | 配额是否充足（决策次数限制） |
| `cooldown_ok` | 是否在冷却期外 |
| `candidate_valid` | 候选状态是否仍有效（ACTIONABLE） |

---

## 14. 决策频率 (Decision Rhythm)

### 14.1 决策频率 API

> **注意**: 大部分端点需要认证

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/decision-rhythm/quotas/` | GET | 获取配额列表 |
| `/api/decision-rhythm/cooldowns/` | GET | 获取冷却期列表 |
| `/api/decision-rhythm/requests/` | GET | 获取决策请求列表 |
| `/api/decision-rhythm/requests/{request_id}/` | GET | 获取决策请求详情 |
| `/api/decision-rhythm/submit/` | POST | 提交决策请求 |
| `/api/decision-rhythm/submit-batch/` | POST | 批量提交决策请求 |
| `/api/decision-rhythm/requests/{request_id}/execute/` | POST | 执行决策请求 |
| `/api/decision-rhythm/requests/{request_id}/cancel/` | POST | 取消决策请求 |
| `/api/decision-rhythm/reset-quota/` | POST | 重置配额 |
| `/api/decision-rhythm/summary/` | GET/POST | 获取决策摘要 |
| `/api/decision-rhythm/trend-data/` | GET/POST | 获取趋势数据 |

### 14.2 提交决策请求 API

`POST /api/decision-rhythm/submit/`

#### 请求示例

```bash
POST /api/decision-rhythm/submit/
Authorization: Token your_api_token_here
{
  "asset_code": "000001.SH",
  "asset_class": "a_share",
  "direction": "BUY",
  "priority": "HIGH",
  "trigger_id": "cand_xxx",
  "candidate_id": "cand_xxx",
  "execution_target": "SIMULATED",
  "reason": "来源候选 cand_xxx",
  "expected_confidence": 0.78,
  "quota_period": "WEEKLY"
}
```

#### 新增字段说明（V3.4+）

| 字段 | 类型 | 说明 |
|------|------|------|
| `candidate_id` | string | 关联的 Alpha 候选 ID（可选） |
| `execution_target` | string | 执行目标：NONE/SIMULATED/ACCOUNT（可选，默认 NONE） |

### 14.3 执行决策请求 API

`POST /api/decision-rhythm/requests/{request_id}/execute/`

将已批准的决策请求执行到指定目标（模拟盘或账户持仓）。

> **权限要求**: 仅 admin、owner、investment_manager 可执行

#### 模拟盘执行请求

```bash
POST /api/decision-rhythm/requests/req_xxx/execute/
Authorization: Token your_api_token_here
{
  "target": "SIMULATED",
  "sim_account_id": 1,
  "asset_code": "000001.SH",
  "action": "buy",
  "quantity": 1000,
  "price": 12.35,
  "reason": "按决策请求执行"
}
```

#### 账户记录请求

```bash
POST /api/decision-rhythm/requests/req_xxx/execute/
Authorization: Token your_api_token_here
{
  "target": "ACCOUNT",
  "portfolio_id": 9,
  "asset_code": "000001.SH",
  "shares": 1000,
  "avg_cost": 12.35,
  "current_price": 12.35,
  "reason": "按决策请求落地持仓"
}
```

#### 执行成功响应

```json
{
  "success": true,
  "result": {
    "request_id": "req_xxx",
    "execution_status": "EXECUTED",
    "executed_at": "2026-03-01T10:00:00+08:00",
    "execution_ref": {
      "trade_id": "trd_xxx",
      "account_id": 1
    },
    "candidate_status": "EXECUTED"
  }
}
```

### 14.4 取消决策请求 API

`POST /api/decision-rhythm/requests/{request_id}/cancel/`

#### 请求示例

```bash
POST /api/decision-rhythm/requests/req_xxx/cancel/
Authorization: Token your_api_token_here
{
  "reason": "市场条件变化"
}
```

### 14.5 决策请求状态机

| 状态 | 说明 |
|------|------|
| `PENDING` | 待执行 |
| `EXECUTED` | 已执行 |
| `FAILED` | 执行失败 |
| `CANCELLED` | 已取消 |

---

## 错误码

| 状态码 | 描述 |
|--------|------|
| 200 | 成功 |
| 201 | 创建成功 |
| 400 | 请求参数错误 |
| 401 | 未授权 |
| 403 | 禁止访问 |
| 404 | 资源不存在 |
| 500 | 服务器错误 |

#### 错误响应示例

```json
{
  "error": "Validation Error",
  "detail": "Invalid asset_code format",
  "code": "invalid_asset_code"
}
```

---

## 认证

API 使用 Token 认证：

```bash
# 请求头
Authorization: Token your_api_token_here
```

---

## 13. 市场数据 (Market Data)

### 13.1 统一数据源 API

> **标准前缀**: `/api/market-data/`
> **页面路由**: `/market-data/providers/`（Provider 管理页面，`/market-data/` 为兼容跳转）

统一数据源接入层，支持多 Provider（东方财富、AKShare 通用、Tushare）自动 failover 和交叉校验。

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/market-data/quotes/?codes={codes}` | GET | 获取实时行情快照 |
| `/api/market-data/capital-flows/?code={code}&period={period}` | GET | 获取个股资金流向 |
| `/api/market-data/capital-flows/sync/` | POST | 同步资金流向到数据库 |
| `/api/market-data/news/?code={code}&limit={limit}` | GET | 获取个股新闻 |
| `/api/market-data/news/ingest/` | POST | 采集新闻到数据库 |
| `/api/market-data/providers/health/` | GET | 获取 Provider 健康状态 |
| `/api/market-data/cross-validate/?codes={codes}` | GET | 交叉校验多源行情一致性 |

#### 请求示例

```bash
# 获取实时行情（自动 failover：东方财富 → AKShare → Tushare）
GET /api/market-data/quotes/?codes=000001.SZ,600000.SH

# 获取资金流向
GET /api/market-data/capital-flows/?code=000001.SZ&period=10d

# 交叉校验（比对主/备源价格偏差）
GET /api/market-data/cross-validate/?codes=000001.SZ,600000.SH

# 同步资金流向
POST /api/market-data/capital-flows/sync/
{
  "stock_code": "000001.SZ",
  "period": "5d"
}

# 采集新闻
POST /api/market-data/news/ingest/
{
  "stock_code": "000001.SZ",
  "limit": 20
}
```

#### 响应示例

```json
// GET /api/market-data/quotes/?codes=000001.SZ
{
  "data": [
    {
      "stock_code": "000001.SZ",
      "price": "15.50",
      "change": "0.30",
      "change_pct": 1.97,
      "volume": 1000000,
      "amount": "15500000",
      "turnover_rate": 3.2,
      "source": "eastmoney"
    }
  ]
}

// GET /api/market-data/providers/health/
{
  "data": [
    {
      "provider_name": "eastmoney",
      "capability": "realtime_quote",
      "is_healthy": true,
      "consecutive_failures": 0,
      "avg_latency_ms": 120.5
    },
    {
      "provider_name": "akshare_general",
      "capability": "realtime_quote",
      "is_healthy": true,
      "consecutive_failures": 0,
      "avg_latency_ms": null
    }
  ]
}

// GET /api/market-data/cross-validate/?codes=000001.SZ
{
  "data": {
    "quotes_count": 1,
    "validation": {
      "total_checked": 1,
      "matches": 1,
      "deviations": [],
      "alerts": [],
      "missing_in_primary": [],
      "missing_in_secondary": [],
      "is_clean": true
    }
  }
}
```

#### Failover 机制

系统注册 3 个数据源，按优先级自动切换：

| Provider | 优先级 | 能力 | 说明 |
|----------|--------|------|------|
| 东方财富 (eastmoney) | 10 | 行情/资金流/新闻/技术指标 | 主源，通过 AKShare 封装 |
| AKShare 通用 (akshare_general) | 20 | 行情/技术指标 | 备用 |
| Tushare (tushare) | 30 | 行情/技术指标 | 第三备用，日线级 |

- 单次请求失败自动尝试下一个 provider
- 连续失败 5 次触发熔断（300 秒后自动恢复）
- 交叉校验容差 1%，超过 5% 告警

---

## 速率限制

- 每分钟最多 100 次请求
- 超过限制返回 429 状态码

---

## OpenAPI 文档

完整的 OpenAPI 3.0 规范文档请参考：
- **Swagger UI**: `http://localhost:8000/api/schema/swagger-ui/`
- **ReDoc**: `http://localhost:8000/api/schema/redoc/`
- **OpenAPI YAML**: `docs/api/openapi.yaml`

---

**维护**: 本文档随项目更新同步更新
**反馈**: 如有问题请提交 Issue
