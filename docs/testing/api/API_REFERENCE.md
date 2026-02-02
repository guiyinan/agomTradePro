# AgomSAAF API 参考文档

> **版本**: v1.0
> **更新**: 2026-01-03
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

| 端点 | 方法 | 描述 |
|------|------|------|
| `/macro/indicators/` | GET | 获取宏观数据列表 |
| `/macro/indicators/{code}/` | GET | 获取指定指标数据 |
| `/macro/indicators/sync/` | POST | 同步最新宏观数据 |
| `/macro/health/` | GET | 宏观数据健康检查 |

#### 请求示例

```bash
# 获取 PMI 数据
GET /api/macro/indicators/?code=china_pmi

# 同步最新数据
POST /api/macro/indicators/sync/
{
  "indicators": ["china_pmi", "china_cpi", "china_m2"]
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

| 端点 | 方法 | 描述 |
|------|------|------|
| `/regime/snapshots/` | GET | 获取 Regime 历史记录 |
| `/regime/current/` | GET | 获取当前 Regime 状态 |
| `/regime/calculate/` | POST | 手动触发 Regime 计算 |
| `/regime/health/` | GET | Regime 模块健康检查 |

#### 请求示例

```bash
# 获取当前 Regime
GET /api/regime/current/

# 计算 Regime
POST /api/regime/calculate/
{
  "as_of_date": "2024-12-31",
  "use_pit": true
}
```

#### 响应示例

```json
{
  "as_of_date": "2024-12-31",
  "growth_momentum": 1.2,
  "inflation_momentum": 0.8,
  "growth_z_score": 0.5,
  "inflation_z_score": 0.3,
  "distribution": {
    "Recovery": 0.35,
    "Overheat": 0.25,
    "Stagflation": 0.20,
    "Deflation": 0.20
  },
  "regime": "Recovery",
  "confidence": 0.85
}
```

---

## 3. 政策管理 (Policy)

### 3.1 政策事件 API

| 端点 | 方法 | 描述 |
|------|------|------|
| `/policy/events/` | GET | 获取政策事件列表 |
| `/policy/events/{event_date}/` | GET | 获取指定日期政策事件 |
| `/policy/events/create/` | POST | 创建政策事件 |
| `/policy/status/` | GET | 获取当前政策档位 |
| `/policy/hedges/` | GET | 获取对冲头寸 |
| `/policy/hedges/execute/` | POST | 执行对冲操作 |

#### 请求示例

```bash
# 创建政策事件
POST /api/policy/events/create/
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

| 端点 | 方法 | 描述 |
|------|------|------|
| `/signal/signals/` | GET | 获取投资信号列表 |
| `/signal/signals/create/` | POST | 创建投资信号 |
| `/signal/signals/{id}/validate/` | POST | 验证信号准入 |
| `/signal/signals/{id}/approve/` | POST | 批准信号 |
| `/signal/signals/{id}/reject/` | POST | 拒绝信号 |
| `/signal/health/` | GET | 信号模块健康检查 |

#### 请求示例

```bash
# 创建信号
POST /api/signal/signals/create/
{
  "asset_code": "000300.SH",
  "logic_desc": "经济复苏预期强烈，买入沪深300",
  "invalidation_logic": "PMI跌破49且连续2个月低于前值",
  "invalidation_threshold": 49.0,
  "target_weight": 0.3
}

# 验证信号
POST /api/signal/signals/1/validate/
```

#### 响应示例

```json
{
  "id": 1,
  "asset_code": "000300.SH",
  "status": "APPROVED",
  "eligibility": "PREFERRED",
  "regime": "Recovery",
  "policy_level": "P1",
  "warnings": []
}
```

---

## 5. 个股分析 (Equity)

### 5.1 个股分析 API

| 端点 | 方法 | 描述 |
|------|------|------|
| `/equity/stocks/` | GET | 获取股票列表 |
| `/equity/stocks/{stock_code}/` | GET | 获取股票详情 |
| `/equity/stocks/{stock_code}/valuation/` | GET | 获取估值指标 |
| `/equity/stocks/{stock_code}/financial/` | GET | 获取财务数据 |
| `/equity/screener/` | POST | 股票筛选 |
| `/equity/analysis/comprehensive/` | POST | 综合估值分析 |

#### 请求示例

```bash
# 股票筛选
POST /api/equity/screener/
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

| 端点 | 方法 | 描述 |
|------|------|------|
| `/fund/screen/` | POST | 基金筛选 |
| `/fund/analyze-style/` | POST | 分析基金风格 |
| `/fund/rank/` | POST | 基金排名 |
| `/fund/info/` | GET | 获取基金信息 |
| `/fund/nav/` | GET | 获取基金净值 |
| `/fund/holdings/` | GET | 获取基金持仓 |
| `/fund/performance/` | POST | 计算基金业绩 |

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
| `/account/health/` | GET | 账户健康检查 |

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
| `/filter/health/` | GET | 筛选器健康检查 |

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
