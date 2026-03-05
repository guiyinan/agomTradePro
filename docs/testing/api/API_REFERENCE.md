# AgomSAAF API 参考文档

> **版本**: v1.0
> **更新**: 2026-03-05
> **Base URL**: `http://localhost:8000/api/`

---

## 概述

AgomSAAF 提供完整的 RESTful API，支持宏观环境准入系统的全部功能，包括：
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

---

## 1. 宏观模块 (Macro)

### 1.1 宏观数据 API

> **标准前缀**: `/api/macro/`
> **兼容前缀**: `/macro/api/`（legacy，逐步迁移中）

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
> **向后兼容**: 旧格式 `/policy/api/{endpoint}/` 仍可用

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/policy/events/` | GET | 获取政策事件列表 (需认证) |
| `/api/policy/events/{event_date}/` | GET | 获取指定日期政策事件 (需认证) |
| `/policy/events/` | GET | 获取政策事件列表 (页面路由) |
| `/policy/events/{event_date}/` | GET | 获取指定日期政策事件 (页面路由) |
| `/policy/events/create/` | POST | 创建政策事件 |
| `/policy/status/` | GET | 获取当前政策档位 |
| `/policy/hedges/` | GET | 获取对冲头寸 |
| `/policy/hedges/execute/` | POST | 执行对冲操作 |

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
> **兼容路径**: `/equity/api/`

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
| `/sector/sectors/` | GET | 获取板块列表 |
| `/sector/sectors/{sector_code}/performance/` | GET | 获取板块表现 |
| `/sector/update-data/` | POST | 更新板块数据 |
| `/sector/relative-strength/` | GET | 获取相对强弱 |

#### 请求示例

```bash
# 获取板块轮动
GET /api/sector/rotation/?window=20

# 获取板块表现
GET /api/sector/sectors/801010/performance/?start_date=2024-01-01
```

---

## 7. 基金分析 (Fund)

### 7.1 基金分析 API

> **主路径**: `/api/fund/`
> **兼容路径**: `/fund/api/`

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
| `/backtest/api/backtests/` | GET | 获取回测列表 |
| `/backtest/api/backtests/{id}/` | GET | 获取回测详情 |
| `/backtest/api/run/` | POST | 运行回测 |
| `/backtest/api/validate/` | POST | 验证策略 |

#### 请求示例

```bash
# 运行回测
POST /api/backtest/api/run/
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
| `/account/portfolios/` | GET | 获取投资组合列表 |
| `/account/portfolios/{id}/` | GET | 获取组合详情 |
| `/account/positions/` | GET | 获取持仓列表 |
| `/account/transactions/` | GET | 获取交易记录 |
| `/account/capital-flows/` | GET | 获取资金流水 |
| `/account/profile/` | GET | 获取账户配置 |
| `/account/allocation/` | GET | 获取资产配置 |
| `/account/api/health/` | GET | 账户健康检查 |

---

## 10. 审计分析 (Audit)

### 10.1 审计 API

| 端点 | 方法 | 描述 |
|------|------|------|
| `/audit/reports/` | GET | 获取审计报告列表 |
| `/audit/reports/{id}/` | GET | 获取审计报告详情 |
| `/audit/attribution/` | POST | 生成归因分析 |
| `/audit/analyze/` | POST | 分析投资结果 |

---

## 11. AI 分析 (Prompt)

### 11.1 AI 分析 API

| 端点 | 方法 | 描述 |
|------|------|------|
| `/prompt/chat/` | POST | AI 对话 |
| `/prompt/providers/` | GET | 获取 AI 提供商列表 |
| `/prompt/models/` | GET | 获取 AI 模型列表 |
| `/prompt/signal-generation/` | POST | 生成投资信号 |
| `/prompt/report-generation/` | POST | 生成分析报告 |
| `/prompt/chains/` | GET | 获取 Chain 列表 |
| `/prompt/templates/` | GET | 获取 Prompt 模板 |

#### 请求示例

```bash
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
| `/filter/filters/` | GET | 获取筛选器列表 |
| `/filter/filters/{id}/` | GET | 获取筛选器详情 |
| `/filter/apply/` | POST | 应用筛选器 |
| `/filter/api/health/` | GET | 筛选器健康检查 |

---

## 13. 决策工作流 (Decision Workflow)

### 13.1 决策工作流 API

> **注意**: 所有端点需要认证

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/decision-workflow/precheck/` | POST | 决策预检查 |
| `/api/decision-workflow/check-beta-gate/` | POST | 检查 Beta Gate |
| `/api/decision-workflow/check-quota/` | POST | 检查配额状态 |
| `/api/decision-workflow/check-cooldown/` | POST | 检查冷却期 |

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
| `beta_gate_passed` | 资产是否通过 Beta Gate（宏观环境准入） |
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
