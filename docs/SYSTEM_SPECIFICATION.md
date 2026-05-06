# AgomTradePro 系统说明书

> **版本**: 0.7.0
> **生成日期**: 2026-03-05
> **更新日期**: 2026-03-28
> **项目状态**: 生产就绪
> **文档性质**: 技术与功能完整说明
> **版本管理**: [VERSION.md](VERSION.md)

---

## 目录

1. [系统概述](#1-系统概述)
2. [技术架构](#2-技术架构)
3. [核心业务模块](#3-核心业务模块)
4. [数据流与处理逻辑](#4-数据流与处理逻辑)
5. [API 接口规范](#5-api-接口规范)
6. [部署与运维](#6-部署与运维)
7. [开发指南](#7-开发指南)
8. [测试策略](#8-测试策略)
9. [扩展与集成](#9-扩展与集成)
10. [附录](#10-附录)

---

## 1. 系统概述

### 1.1 系统定位

**AgomTradePro** (Agom Strategic Asset Allocation Framework) 是个人投研平台。

**核心理念**: 通过 **Regime（增长/通胀象限）** 和 **Policy（政策档位）** 双重过滤，确保投资者 **"不在错误的宏观环境中下注"**。

### 1.2 系统规模

| 指标 | 数值 |
|------|------|
| 业务模块 | 35个 |
| MCP 工具 | 326个 |
| 测试用例 | 5,212 项（`pytest --collect-only` 快照） |
| 代码行数 | 50,000+ |
| API 路径 | 515个（OpenAPI 快照） |
| 数据库表 | 80+ |

### 1.3 核心功能

```
┌─────────────────────────────────────────────────────────────────┐
│                    AgomTradePro 核心功能矩阵                         │
├─────────────────────────────────────────────────────────────────┤
│  宏观环境分析    │  Regime 判定  │  Policy 档位  │  信号管理     │
│  ├─ 经济增长趋势 │  ├─ 四象限    │  ├─ P0-P3    │  ├─ 投资信号  │
│  ├─ 通胀趋势     │  ├─ 动量计算  │  ├─ 事件驱动 │  ├─ 证伪逻辑  │
│  └─ 政策环境     │  └─ 概率分布  │  └─ 闸门约束 │  └─ 持仓关联  │
├─────────────────────────────────────────────────────────────────┤
│  资产分析        │  AI 智能      │  风控执行     │  审计复盘     │
│  ├─ 个股评分     │  ├─ Alpha选股 │  ├─ Beta闸门 │  ├─ 绩效归因  │
│  ├─ 基金分析     │  ├─ 因子管理  │  ├─ 决策频率 │  ├─ Brinson   │
│  ├─ 板块轮动     │  └─ 对冲策略  │  └─ 模拟交易 │  └─ 回测验证  │
└─────────────────────────────────────────────────────────────────┘
```

### 1.4 用户角色

| 角色 | 职责 | 主要功能 |
|------|------|----------|
| **投资经理** | 投资决策 | Regime 查看、信号管理、审批执行 |
| **研究员** | 市场分析 | 宏观数据、资产分析、因子研究 |
| **交易员** | 执行交易 | 模拟交易、持仓管理、实时监控 |
| **风控专员** | 风险监控 | Policy 监控、闸门管理、告警处理 |
| **系统管理员** | 系统运维 | 用户管理、配置管理、系统监控 |

---

## 2. 技术架构

### 2.1 技术栈

| 类别 | 技术选型 | 版本 | 说明 |
|------|----------|------|------|
| **语言** | Python | 3.11+ | 主要开发语言 |
| **Web框架** | Django | 5.x | 后端框架 |
| **API框架** | Django REST Framework | 3.x | RESTful API |
| **数据库** | SQLite / PostgreSQL | - | 开发/生产 |
| **缓存** | Redis | 7.x | 缓存/消息队列 |
| **异步任务** | Celery | 5.x | 后台任务处理 |
| **数据处理** | Pandas + NumPy | - | 金融数据处理 |
| **统计分析** | Statsmodels | - | HP滤波等 |
| **前端交互** | HTMX + Streamlit | - | 页面交互 |
| **测试框架** | Pytest | 8.x | 单元/集成测试 |
| **E2E测试** | Playwright | - | 端到端测试 |
| **容器化** | Docker + Compose | - | 部署容器 |

### 2.2 四层架构设计

系统严格遵循 **领域驱动设计（DDD）** 四层架构：

```
┌─────────────────────────────────────────────────────────────────┐
│                      Interface 层 (接口层)                       │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
│  │    views.py     │  │  serializers.py │  │     urls.py     │  │
│  │   (DRF ViewSet) │  │   (数据序列化)   │  │   (路由配置)    │  │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘  │
│  职责：输入验证、输出格式化、HTTP 请求处理                        │
├─────────────────────────────────────────────────────────────────┤
│                    Application 层 (应用层)                       │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
│  │   use_cases.py  │  │    tasks.py     │  │     dtos.py     │  │
│  │   (用例编排)    │  │  (Celery任务)   │  │  (数据传输对象) │  │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘  │
│  职责：业务流程编排、跨模块协调、事务管理                         │
├─────────────────────────────────────────────────────────────────┤
│                  Infrastructure 层 (基础设施层)                  │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
│  │    models.py    │  │ repositories.py │  │   providers.py  │  │
│  │   (Django ORM)  │  │   (数据仓储)    │  │  (外部API适配)  │  │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘  │
│  职责：数据持久化、外部服务集成、缓存实现                         │
├─────────────────────────────────────────────────────────────────┤
│                       Domain 层 (领域层)                         │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
│  │   entities.py   │  │    rules.py     │  │   services.py   │  │
│  │   (数据实体)    │  │   (业务规则)    │  │  (纯算法服务)   │  │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘  │
│  职责：核心业务逻辑、金融算法、领域规则                           │
│  约束：禁止依赖 Django、Pandas、NumPy 等外部库                    │
└─────────────────────────────────────────────────────────────────┘
```

### 2.3 架构约束规则

#### Domain 层约束
```python
# ✅ 允许
from dataclasses import dataclass
from typing import Protocol
from enum import Enum
from abc import ABC, abstractmethod

# ❌ 禁止
import django
import pandas as pd
import numpy as np
import requests
```

#### Application 层约束
```python
# ✅ 允许
from apps.regime.domain.entities import RegimeState
from apps.regime.domain.protocols import RegimeRepositoryProtocol

# ❌ 禁止
from apps.regime.infrastructure.models import RegimeHistoryModel
```

#### Infrastructure 层约束
```python
# ✅ 允许
from django.db import models
import pandas as pd
import numpy as np

# 实现 Domain 层定义的 Protocol
class RegimeRepository(RegimeRepositoryProtocol):
    ...
```

### 2.4 目录结构

```
AgomTradePro/
├── core/                          # Django 核心配置
│   ├── settings/
│   │   ├── base.py               # 基础配置
│   │   ├── development.py        # 开发环境
│   │   └── production.py         # 生产环境
│   ├── urls.py                   # 主路由
│   ├── celery.py                 # Celery 配置
│   └── exceptions.py             # 统一异常类
│
├── apps/                          # 业务模块 (33个)
│   ├── macro/                    # 宏观采集编排与兼容实体
│   │   ├── domain/
│   │   │   ├── entities.py       # 数据实体
│   │   │   ├── protocols.py      # Protocol 接口
│   │   │   └── services.py       # 领域服务
│   │   ├── application/
│   │   │   ├── use_cases.py      # 用例编排
│   │   │   └── tasks.py          # Celery 任务
│   │   ├── infrastructure/
│   │   │   ├── models.py         # ORM 模型
│   │   │   ├── repositories.py   # 数据仓储
│   │   │   └── adapters/         # 外部适配器
│   │   └── interface/
│   │       ├── views.py          # API 视图
│   │       ├── serializers.py    # 序列化器
│   │       └── urls.py           # 路由配置
│   ├── regime/                   # Regime 判定
│   ├── policy/                   # 政策事件管理
│   ├── signal/                   # 投资信号管理
│   ├── asset_analysis/           # 资产分析框架
│   ├── equity/                   # 个股分析
│   ├── fund/                     # 基金分析
│   ├── sector/                   # 板块分析
│   ├── sentiment/                # 舆情分析
│   ├── alpha/                    # AI 选股
│   ├── factor/                   # 因子管理
│   ├── rotation/                 # 板块轮动
│   ├── hedge/                    # 对冲策略
│   ├── account/                  # 账户管理
│   ├── simulated_trading/        # 模拟交易
│   ├── realtime/                 # 实时监控
│   ├── data_center/              # 数据中台（宏观事实与指标治理真源）
│   ├── strategy/                 # 策略系统
│   ├── backtest/                 # 回测引擎
│   ├── audit/                    # 事后审计
│   ├── decision_rhythm/          # 决策频率
│   ├── beta_gate/                # Beta 闸门
│   ├── alpha_trigger/            # Alpha 触发
│   ├── ai_provider/              # AI 服务商
│   ├── prompt/                   # Prompt 模板
│   ├── dashboard/                # 仪表盘
│   ├── filter/                   # 滤波器
│   ├── events/                   # 事件系统
│   ├── terminal/                 # 终端交互
│   ├── agent_runtime/            # Agent 运行时
│   ├── ai_capability/            # AI 能力目录
│   ├── pulse/                    # Pulse 脉搏层
│   ├── setup_wizard/             # 系统初始化向导
│   ├── share/                    # 分享功能
│   └── task_monitor/             # 任务监控
│
├── shared/                        # 跨模块共享
│   ├── domain/
│   │   └── interfaces.py         # 通用 Protocol
│   ├── infrastructure/
│   │   ├── kalman_filter.py      # Kalman 滤波
│   │   └── htmx/                 # HTMX 组件
│   └── config/
│       └── secrets.py            # 密钥管理
│
├── sdk/                           # SDK & MCP
│   ├── agomtradepro/                 # Python SDK
│   │   ├── client.py
│   │   └── modules/
│   └── agomtradepro_mcp/             # MCP Server
│       └── server.py
│
├── streamlit_app/                 # Streamlit 仪表盘
│   └── app.py
│
├── tests/                         # 测试
│   ├── unit/                     # 单元测试
│   ├── integration/              # 集成测试
│   ├── playwright/               # E2E 测试
│   ├── uat/                      # UAT 测试
│   └── guardrails/               # 守护测试
│
├── docs/                          # 文档
│   ├── architecture/             # 架构文档
│   ├── business/                 # 业务文档
│   ├── development/              # 开发指南
│   ├── testing/                  # 测试文档
│   ├── deployment/               # 部署文档
│   └── modules/                  # 模块文档
│
├── scripts/                       # 脚本
│   ├── deploy-docker-dev.ps1
│   └── migrate-to-postgres.ps1
│
├── docker-compose.yml             # Docker 配置
├── docker-compose-dev.yml
├── requirements.txt
└── CLAUDE.md                      # 开发规则
```

---

## 3. 核心业务模块

### 3.1 模块总览

系统包含 **33 个业务模块**，按功能分为 6 大类：

```
┌─────────────────────────────────────────────────────────────────┐
│                        模块分类架构                              │
├─────────────────────────────────────────────────────────────────┤
│  核心引擎 (5)     │  资产分析 (5)   │  AI智能 (8)               │
│  ─────────────    │  ─────────────  │  ────────────             │
│  macro            │  asset_analysis │  alpha (Qlib)             │
│  regime           │  equity         │  alpha_trigger            │
│  policy           │  fund           │  beta_gate                │
│  signal           │  sector         │  decision_rhythm          │
│  filter           │  sentiment      │  factor                   │
│                   │                 │  rotation                 │
│                   │                 │  hedge                    │
│                   │                 │  ai_capability            │
├─────────────────────────────────────────────────────────────────┤
│  风控账户 (5)     │  工具模块 (7)   │  新增模块 (3)             │
│  ─────────────    │  ─────────────  │  ────────────             │
│  account          │  ai_provider    │  terminal                 │
│  audit            │  prompt         │  agent_runtime            │
│  simulated_trading│  dashboard      │  data_center              │
│  realtime         │  backtest       │  share                    │
│  strategy         │  events         │                           │
│                   │  task_monitor   │                           │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 核心引擎模块

#### 3.2.1 Macro 模块 - 宏观采集编排与兼容层

**功能**：承载宏观领域实体、采集编排和兼容接口，运行时事实读写已收口到 `apps/data_center`

**数据源**：
- Tushare Pro（金融数据）
- AKShare（宏观数据）
- FRED（美国经济数据）

**核心实体**：
```python
@dataclass(frozen=True)
class MacroIndicator:
    code: str                    # 指标代码
    name: str                    # 指标名称
    category: str                # 分类（增长/通胀/政策）
    unit: str                    # 单位
    frequency: str               # 频率（D/W/M/Q）
    source: str                  # 数据源

@dataclass(frozen=True)
class MacroDataPoint:
    indicator_code: str
    date: date
    value: float
    source: str
```

**运行时真源**：
- `IndicatorCatalog`：指标目录与语义定义
- `IndicatorUnitRule`：原始/存储/展示单位与换算倍率
- `data_center_macro_fact`：标准化宏观事实表

**主要功能**：
- 多数据源采集（带 Failover）
- 采集后按 `IndicatorUnitRule` 统一换算到 canonical storage unit
- 数据一致性校验（容差 1%）
- 定时同步任务
- 为 `regime`、`pulse`、`dashboard` 等消费者提供兼容领域实体

#### 3.2.2 Regime 模块 - 宏观象限判定

**功能**：判定当前宏观经济所处象限

**四象限模型**：
```
                    通胀动量 ↑
                         │
         ┌───────────────┼───────────────┐
         │   过热        │    滞胀       │
         │  Overheat     │  Stagflation  │
         │  (G↑ I↑)      │  (G↓ I↑)      │
         │               │               │
增长动量 ←───────────────┼───────────────→ 通胀动量
         │               │               │
         │   复苏        │    衰退       │
         │  Recovery     │  Deflation    │
         │  (G↑ I↓)      │  (G↓ I↓)      │
         └───────────────┼───────────────┘
                         │
                    增长动量 ↓
```

**核心计算**：
```python
# 动量计算（Z-score 标准化）
momentum = (current_value - ma_60) / std_60

# 概率转换（Sigmoid）
probability = 1 / (1 + exp(-momentum * weight))

# Regime 判定
if growth_momentum > 0 and inflation_momentum > 0:
    regime = RegimeQuadrant.OVERHEAT
elif growth_momentum > 0 and inflation_momentum <= 0:
    regime = RegimeQuadrant.RECOVERY
elif growth_momentum <= 0 and inflation_momentum > 0:
    regime = RegimeQuadrant.STAGFLATION
else:
    regime = RegimeQuadrant.DEFLATION
```

**滤波器**：
- **回测模式**：HP 滤波（扩张窗口，避免后视偏差）
- **实时模式**：Kalman 滤波（状态空间模型）

#### 3.2.3 Policy 模块 - 政策事件管理

**功能**：监控政策事件并调整风险档位

**政策档位**：
| 档位 | 名称 | 含义 | 投资约束 |
|------|------|------|----------|
| P0 | 正常 | 无重大政策事件 | 无限制 |
| P1 | 预警 | 关注潜在风险 | 减少新开仓 |
| P2 | 干预 | 政策干预市场 | 仅平仓 |
| P3 | 危机 | 重大危机事件 | 禁止交易 |

**双闸机制**：
```
┌─────────────────────────────────────────────────────────────┐
│                     Policy Workbench                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│   ┌─────────────────┐        ┌─────────────────┐           │
│   │   Policy Gate   │        │ Heat/Sentiment  │           │
│   │    (P0-P3)      │        │ Gate (L0-L3)    │           │
│   └────────┬────────┘        └────────┬────────┘           │
│            │                          │                     │
│            └──────────┬───────────────┘                     │
│                       │                                     │
│                       ▼                                     │
│              ┌─────────────────┐                            │
│              │   综合风险评级   │                            │
│              │  MAX(P, L)      │                            │
│              └─────────────────┘                            │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**事件类型**：
- `policy` - 政策事件
- `hotspot` - 热点事件
- `sentiment` - 情绪事件
- `mixed` - 混合事件

**审核流程**：
```
待审核 → 审核通过 → 生效中 → 已过期
         ↓
      审核拒绝 → 已拒绝
         ↓
      临时豁免 → 豁免中 → 已过期
```

#### 3.2.4 Signal 模块 - 投资信号管理

**功能**：管理投资信号及其证伪逻辑

**核心实体**：
```python
@dataclass(frozen=True)
class InvestmentSignal:
    id: str
    asset_code: str              # 标的代码
    direction: SignalDirection   # 方向（多/空）
    logic_desc: str              # 逻辑描述
    entry_condition: str         # 入场条件
    exit_condition: str          # 出场条件
    invalidation_logic: str      # 证伪逻辑 ⚠️ 必须
    invalidation_threshold: float # 证伪阈值 ⚠️ 必须
    status: SignalStatus
    created_at: datetime
    expires_at: datetime
```

**信号状态**：
```
待确认 → 生效中 → 已触发 → 已平仓
          ↓
       已证伪 → 已过期
```

**证伪检查**：
- 每日 2:00 自动执行
- 检查证伪条件是否触发
- 触发后自动更新状态并发送告警

#### 3.2.5 Filter 模块 - 滤波器

**功能**：提供时间序列滤波算法

**HP 滤波**（Hodrick-Prescott）：
- 用途：趋势分解
- 参数：λ = 129600（月度数据）
- **关键约束**：必须使用扩张窗口

```python
# ❌ 错误：全量滤波（有后视偏差）
trend, cycle = hpfilter(full_series, lamb=129600)

# ✅ 正确：扩张窗口
def get_trend_at(series, t):
    truncated = series[:t+1]  # 只用到时刻 t 的数据
    trend, _ = hpfilter(truncated, lamb=129600)
    return trend[-1]
```

**Kalman 滤波**：
- 用途：实时状态估计
- 模型：Local Linear Trend
- 参数定义在 Domain 层

### 3.3 资产分析模块

#### 3.3.1 Asset Analysis 模块 - 资产分析框架

**功能**：通用资产评分与筛选框架

**资产池分类**：
| 池类型 | 含义 | 评分范围 |
|--------|------|----------|
| investable | 可投资池 | ≥ 0.7 |
| watch | 观察池 | 0.5 ~ 0.7 |
| candidate | 备选池 | < 0.5 |

**评分维度**：
```python
@dataclass(frozen=True)
class AssetScore:
    asset_code: str
    total_score: float           # 综合评分
    factors: Dict[str, float]    # 因子评分
    rank: int                    # 排名
    pool: AssetPool              # 资产池
    asof_date: date
    confidence: float            # 置信度
    source: str                  # 数据来源
```

#### 3.3.2 Equity 模块 - 个股分析

**功能**：个股估值与分析

**估值方法**：
- DCF（现金流折现）
- PE Band（市盈率区间）
- PB Band（市净率区间）
- PEG（市盈率/增长率）

**分析维度**：
- 基本面分析
- 技术面分析
- 资金面分析
- 情绪面分析

#### 3.3.3 Fund 模块 - 基金分析

**功能**：基金评估与筛选

**分析维度**：
- 基金经理能力
- 历史业绩
- 风险指标（波动率、回撤）
- 持仓分析

#### 3.3.4 Sector 模块 - 板块分析

**功能**：板块热度与轮动分析

**分析内容**：
- 板块涨跌幅
- 板块资金流向
- 板块相对强度
- 板块联动性

#### 3.3.5 Sentiment 模块 - 舆情分析

**功能**：市场情绪监测

**情绪来源**：
- 新闻文本
- 社交媒体
- 研报观点

**处理流程**：
```
文本采集 → 文本清洗 → 情感分类 → 情绪指数计算 → 告警触发
```

### 3.4 AI 智能模块

#### 3.4.1 Alpha 模块 - AI 选股

**功能**：基于机器学习的股票评分

**架构**：4 层降级
```
┌─────────────────────────────────────────────────────────────┐
│                    Alpha Provider 层级                       │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  L1: Qlib Provider（优先）                                  │
│      └── 机器学习模型推理（LGBModel/MLP等）                  │
│                    ↓ 不可用时                               │
│  L2: Cache Provider                                         │
│      └── 缓存的评分结果                                     │
│                    ↓ 不可用时                               │
│  L3: Simple Provider                                        │
│      └── 简单因子组合                                       │
│                    ↓ 不可用时                               │
│  L4: ETF Provider（兜底）                                   │
│      └── 返回 ETF 推荐列表                                  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**Qlib 集成**：
- 训练流水线：数据准备 → 特征工程 → 模型训练 → 评估
- 推理流水线：模型加载 → 特征计算 → 评分输出
- 模型管理：版本控制、灰度发布、回滚

**核心实体**：
```python
@dataclass(frozen=True)
class StockScore:
    code: str                   # 股票代码
    score: float                # 评分 (0-1)
    rank: int                   # 排名
    factors: Dict[str, float]   # 因子贡献
    source: str                 # 数据来源
    confidence: float           # 置信度
    asof_date: date             # 日期
```

**可比性保障机制**：
- **API 响应增强**：返回完整的 `source`、`status`、`staleness_days`、`latency_ms` 元数据
- **Provider 切换告警**：检测降级自动创建告警（`AlphaAlertModel`）
- **数据过滤工具**：支持 `provider` 参数强制使用指定 Provider（`qlib`/`cache`/`simple`/`etf`）
- **评分日志增强**：详细日志标识降级过程（`[AlphaFallback]`、`[AlphaSuccess]`）
- **配置选项**：`SystemSettingsModel.alpha_fixed_provider` 支持全局固定 Provider

**系统配置**（`SystemSettingsModel`）：
- `alpha_fixed_provider`: 固定使用指定 Provider（`qlib`/`cache`/`simple`/`etf`/留空=自动降级）

**风险缓解**：
| 风险 | 解决方案 |
|------|----------|
| 前后不可比 | 使用 `provider` 参数固定单一 Provider 或配置 `alpha_fixed_provider` |
| 横向不可比 | 单次查询保证所有股票来自同一 Provider |
| 数据污染 | 按 `provider_source` 字段过滤查询 |

#### 3.4.2 Factor 模块 - 因子管理

**功能**：因子定义、计算与评估

**因子类型**：
- 动量因子
- 价值因子
- 质量因子
- 波动因子
- 流动性因子

**评估指标**：
- IC（信息系数）
- ICIR（信息比率）
- 因子覆盖率
- 因子单调性

#### 3.4.3 Rotation 模块 - 板块轮动

**功能**：基于 Regime 的板块配置建议

**轮动逻辑**：
```python
REGIME_SECTOR_MAPPING = {
    RegimeQuadrant.RECOVERY: ["金融", "可选消费", "工业"],
    RegimeQuadrant.OVERHEAT: ["能源", "材料", "商品"],
    RegimeQuadrant.STAGFLATION: ["必选消费", "医药", "公用事业"],
    RegimeQuadrant.DEFLATION: ["债券", "防御性股票", "现金"],
}
```

#### 3.4.4 Hedge 模块 - 对冲策略

**功能**：期货对冲计算与管理

**对冲类型**：
- 股指期货对冲
- 商品期货对冲
- 汇率对冲

**核心计算**：
- 对冲比例计算
- 保证金需求估算
- 对冲成本评估

#### 3.4.5 Beta Gate 模块 - Beta 闸门

**功能**：基于市场风险的交易控制

**闸门状态**：
| 状态 | 条件 | 限制 |
|------|------|------|
| OPEN | VIX < 20 | 无限制 |
| PARTIAL | 20 ≤ VIX < 30 | 50% 仓位上限 |
| CLOSED | VIX ≥ 30 | 禁止新开仓 |

#### 3.4.6 Decision Rhythm 模块 - 决策频率

**功能**：控制决策频率避免过度交易

**约束机制**：
- 决策配额（每日/每周上限）
- 冷却期（同一标的最小间隔）
- 强制休市期

#### 3.4.7 Alpha Trigger 模块 - Alpha 触发

**功能**：离散触发 Alpha 信号执行

**触发条件**：
- 评分变化超过阈值
- 排名变化超过阈值
- 组合偏离超过阈值

### 3.5 风控与账户模块

#### 3.5.1 Account 模块 - 账户管理

**功能**：投资账户与持仓管理

**账户类型**：
- 真实账户
- 模拟账户
- 策略账户

**持仓信息**：
```python
@dataclass(frozen=True)
class Position:
    account_id: str
    asset_code: str
    quantity: float
    cost_basis: float  # 含买入侧手续费和滑点摊薄后的持仓成本
    current_price: float
    market_value: float
    profit_loss: float
    profit_loss_pct: float
    weight: float
```

#### 3.5.2 Simulated Trading 模块 - 模拟交易

**功能**：自动化模拟交易执行

**交易流程**：
```
信号触发 → 风控检查 → 订单生成 → 执行成交 → 持仓更新 → 绩效计算
```

**定时任务**：
| 任务 | 时间 | 说明 |
|------|------|------|
| 自动交易 | 工作日 15:30 | 执行待处理信号 |
| 更新价格 | 工作日 16:00 | 通过 `apps/data_center` 统一价格接口更新持仓价格；若无价格则任务失败并返回错误，不允许静默补 0 或编造价格 |
| 计算绩效 | 周日 2:00 | 计算周度绩效 |
| 清理账户 | 周日 3:00 | 清理不活跃账户 |
| 发送摘要 | 工作日 17:00 | 发送每日摘要 |

#### 3.5.3 Realtime 模块 - 实时监控

**功能**：实时价格监控与告警

**监控内容**：
- 实时价格更新
- 价格告警触发
- 异常波动检测

**数据源**：
- AKShare 实时接口
- 轮询间隔：5 分钟

#### 3.5.4 Strategy 模块 - 策略系统

**功能**：策略配置与执行管理

**策略配置**：
```python
@dataclass(frozen=True)
class StrategyConfig:
    id: str
    name: str
    description: str
    rebalance_frequency: str     # 调仓频率
    position_rules: List[PositionRule]
    risk_limits: RiskLimits
    status: StrategyStatus
```

**仓位规则**：
- 单标的上限
- 行业上限
- 风格暴露限制

#### 3.5.5 Audit 模块 - 事后审计

**功能**：绩效归因与审计

**归因方法**：
- Brinson 归因（配置+选择效应）
- 因子归因
- 择时归因

**审计报告**：
- 绩效分析
- 风险分析
- 合规检查
- 改进建议

### 3.6 工具模块

#### 3.6.1 AI Provider 模块 - AI 服务商

**功能**：管理 AI 服务商配置

**支持的服务商**：
- OpenAI (GPT-4)
- Anthropic (Claude)
- Azure OpenAI
- 本地模型

#### 3.6.2 Prompt 模块 - Prompt 模板

**功能**：管理 AI Prompt 模板

**模板类型**：
- 宏观分析模板
- 资产分析模板
- 风险评估模板
- 报告生成模板

#### 3.6.3 Dashboard 模块 - 仪表盘

**功能**：数据可视化与交互

**技术栈**：
- Django 模板（旧版）
- Streamlit（新版）

**仪表盘内容**：
- Regime 状态
- Policy 状态
- 持仓概览
- 绩效曲线
- 信号状态

#### 3.6.4 Backtest 模块 - 回测引擎

**功能**：策略历史回测

**回测流程**：
```
策略配置 → 数据准备 → 信号生成 → 交易模拟 → 绩效计算 → 报告生成
```

**性能指标**：
- 收益率
- 夏普比率
- 最大回撤
- 胜率
- 盈亏比

#### 3.6.5 Events 模块 - 事件系统

**功能**：事件发布与订阅

**事件类型**：
- `REGIME_CHANGED` - Regime 变化
- `POLICY_CHANGED` - Policy 变化
- `SIGNAL_TRIGGERED` - 信号触发
- `TRADE_EXECUTED` - 交易执行
- `ALERT_TRIGGERED` - 告警触发

#### 3.6.6 Task Monitor 模块 - 任务监控

**功能**：Celery 任务监控

**监控内容**：
- 任务执行状态
- 任务执行时间
- 失败任务重试
- 任务积压告警

#### 3.6.7 Terminal 模块 - 终端交互

**功能**：终端风格 AI 交互界面

**命令类型**：
- `prompt` - Prompt 模板调用（通过 AI 生成响应）
- `api` - API 端点调用（直接调用系统 API）

**核心特性**：
- 可配置命令系统
- 参数定义与交互提示
- JQ 过滤器支持
- 会话管理

**依赖关系**：
- 依赖 `ai_provider` 模块的 AI 客户端工厂（AIClientFactory）
- 自身持有 `TerminalCommandORM`
- 可选关联 Prompt 模板

#### 3.6.8 Agent Runtime 模块 - Agent 运行时

**功能**：Terminal AI 后端，支持任务编排和 Facade 模式

**核心组件**：
- **Task Facades** - 任务门面模式，按领域分组
  - `ResearchTaskFacade` - 研究任务
  - `DecisionTaskFacade` - 决策任务
  - `ExecutionTaskFacade` - 执行任务
  - `MonitoringTaskFacade` - 监控任务
  - `OpsTaskFacade` - 运维任务
- **Guardrails** - 守护规则，约束 AI 行为
- **Timeline Events** - 时间线事件记录

**任务领域**：
- `RESEARCH` - 研究
- `DECISION` - 决策
- `EXECUTION` - 执行
- `MONITORING` - 监控
- `OPS` - 运维

#### 3.6.9 Data Center 模块 - 数据中台

**功能**：统一外部数据源接入、标准化、持久化、同步与查询

**数据源**：
- Tushare Pro
- AKShare
- 东方财富
- QMT
- FRED

**主要功能**：
- Provider 配置与健康检查
- 宏观 / 价格 / 基金 / 财务 / 估值统一同步
- 统一查询 API 与 SDK / MCP 对齐

#### 3.6.10 Share 模块 - 分享功能

**功能**：支持决策分享

**分享内容**：
- 投资决策
- 分析报告
- 策略配置

#### 3.6.11 AI Capability 模块 - AI 能力目录

**功能**：系统级 AI 能力目录与统一路由

**能力来源**（4种）：
- `builtin` - 内置能力（系统核心功能）
- `terminal_command` - Terminal 命令
- `mcp_tool` - MCP 工具
- `api` - API 端点

**核心特性**：
- 自动采集全站 API 端点
- 安全分层（read_api/write_api/unsafe_api）
- 三阶段路由：Retrieval → Decision → Dispatch
- 统一路由 API：POST /api/ai-capability/route/

**主要组件**：
- `AICapabilityModel` - 能力元数据存储
- `AICapabilityCatalogService` - 能力目录服务
- `AICapabilityRouterService` - 统一路由服务

---

## 4. 数据流与处理逻辑

### 4.1 核心数据流

```
┌─────────────────────────────────────────────────────────────────┐
│                     AgomTradePro 核心数据流                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐         │
│  │  外部数据源  │───→│  Macro 模块 │───→│ Regime 模块 │         │
│  │ Tushare    │    │  数据采集    │    │  象限判定   │         │
│  │ AKShare    │    │  清洗存储    │    │  概率计算   │         │
│  │ FRED       │    └─────────────┘    └──────┬──────┘         │
│  └─────────────┘                              │                 │
│                                               │                 │
│  ┌─────────────┐                              │                 │
│  │  RSS/API    │───→│  Policy 模块 │←─────────┘                 │
│  │  政策新闻    │    │  事件管理    │                           │
│  └─────────────┘    │  档位调整    │                           │
│                     └──────┬──────┘                            │
│                            │                                    │
│                            ▼                                    │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐         │
│  │ Asset 模块  │←───│  Signal     │───→│  Trading    │         │
│  │  资产分析    │    │  信号管理    │    │  交易执行   │         │
│  │  评分筛选    │    │  证伪逻辑    │    │  持仓管理   │         │
│  └─────────────┘    └─────────────┘    └──────┬──────┘         │
│                                               │                 │
│                            ┌─────────────────┐│                 │
│                            │   Audit 模块    │←┘                 │
│                            │   绩效归因      │                   │
│                            │   审计复盘      │                   │
│                            └─────────────────┘                   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 4.2 决策流程

```
┌─────────────────────────────────────────────────────────────────┐
│                      投资决策流程                                │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Step 1: 宏观环境分析                                           │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  Regime 象限: 当前处于哪个经济周期？                      │   │
│  │  Policy 档位: 当前政策环境风险等级？                      │   │
│  │  准入判断: 该环境下是否允许投资？                         │   │
│  └─────────────────────────────────────────────────────────┘   │
│                            ↓                                    │
│  Step 2: 资产分析                                               │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  Alpha 评分: 哪些标的具有投资价值？                       │   │
│  │  因子分析: 主要驱动因素是什么？                           │   │
│  │  板块轮动: 哪些板块更有优势？                             │   │
│  └─────────────────────────────────────────────────────────┘   │
│                            ↓                                    │
│  Step 3: 风控检查                                               │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  Beta Gate: 市场波动是否允许交易？                        │   │
│  │  Decision Rhythm: 是否达到决策配额？                      │   │
│  │  仓位限制: 是否超过持仓上限？                             │   │
│  └─────────────────────────────────────────────────────────┘   │
│                            ↓                                    │
│  Step 4: 执行与监控                                             │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  交易执行: 按信号执行交易                                 │   │
│  │  实时监控: 价格变动与告警                                 │   │
│  │  证伪检查: 定期检查证伪条件                               │   │
│  └─────────────────────────────────────────────────────────┘   │
│                            ↓                                    │
│  Step 5: 审计复盘                                               │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  绩效归因: 收益来源分析                                   │   │
│  │  风险分析: 风险敞口评估                                   │   │
│  │  改进建议: 优化策略参数                                   │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 4.3 关键算法

#### 4.3.1 Regime 计算算法

```python
def calculate_regime(
    growth_series: pd.Series,
    inflation_series: pd.Series,
    config: RegimeConfig
) -> RegimeState:
    """
    Regime 计算流程:
    1. 计算 60 日移动平均和标准差
    2. 计算 Z-score 标准化动量
    3. Sigmoid 转换为概率
    4. 模糊权重分配
    5. 确定象限
    """
    # Step 1-2: 动量计算
    growth_momentum = (growth_series.iloc[-1] - growth_series.rolling(60).mean().iloc[-1]) / \
                       growth_series.rolling(60).std().iloc[-1]

    inflation_momentum = (inflation_series.iloc[-1] - inflation_series.rolling(60).mean().iloc[-1]) / \
                          inflation_series.rolling(60).std().iloc[-1]

    # Step 3: 概率转换
    growth_prob = 1 / (1 + exp(-growth_momentum * config.sigmoid_weight))
    inflation_prob = 1 / (1 + exp(-inflation_momentum * config.sigmoid_weight))

    # Step 4-5: 象限判定
    if growth_momentum > 0 and inflation_momentum > 0:
        quadrant = RegimeQuadrant.OVERHEAT
    elif growth_momentum > 0 and inflation_momentum <= 0:
        quadrant = RegimeQuadrant.RECOVERY
    elif growth_momentum <= 0 and inflation_momentum > 0:
        quadrant = RegimeQuadrant.STAGFLATION
    else:
        quadrant = RegimeQuadrant.DEFLATION

    return RegimeState(
        quadrant=quadrant,
        growth_probability=growth_prob,
        inflation_probability=inflation_prob,
        calculated_at=datetime.now(timezone.utc)
    )
```

#### 4.3.2 证伪检查算法

```python
def check_invalidation(
    signal: InvestmentSignal,
    current_data: Dict[str, float]
) -> bool:
    """
    证伪检查流程:
    1. 获取证伪条件和阈值
    2. 获取当前数据
    3. 比较判断
    4. 返回结果
    """
    threshold = signal.invalidation_threshold

    # 根据证伪逻辑类型检查
    if "PMI" in signal.invalidation_logic:
        current_pmi = current_data.get("PMI", 100)
        return current_pmi < threshold

    elif "价格" in signal.invalidation_logic:
        current_price = current_data.get(signal.asset_code, 0)
        return current_price < threshold

    # ... 其他条件

    return False
```

---

## 5. API 接口规范

### 5.1 API 设计原则

**路由规范**：
- 统一格式：`/api/{module}/{resource}/`
- 认证方式：Session + Token
- 响应格式：JSON

**响应结构**：
```json
{
    "success": true,
    "data": { ... },
    "message": "操作成功",
    "timestamp": "2026-03-05T10:00:00Z"
}
```

### 5.2 核心 API 端点

#### 5.2.1 Regime API

| 端点 | 方法 | 说明 | 认证 |
|------|------|------|------|
| `/api/regime/` | GET | 获取 Regime 列表 | 需要 |
| `/api/regime/current/` | GET | 获取当前 Regime | 需要 |
| `/api/regime/calculate/` | POST | 重新计算 Regime | 需要 |
| `/api/regime/history/` | GET | 获取历史记录 | 需要 |
| `/api/regime/distribution/` | GET | 获取分布统计 | 需要 |

**响应示例**：
```json
{
    "quadrant": "RECOVERY",
    "growth_probability": 0.72,
    "inflation_probability": 0.35,
    "calculated_at": "2026-03-05T10:00:00Z",
    "factors": {
        "pmi_trend": 0.65,
        "cpi_trend": -0.12
    }
}
```

#### 5.2.2 Policy Workbench API

| 端点 | 方法 | 说明 | 认证 |
|------|------|------|------|
| `/api/policy/workbench/summary/` | GET | 工作台概览 | 需要 |
| `/api/policy/workbench/items/` | GET | 事件列表 | 需要 |
| `/api/policy/workbench/items/{id}/approve/` | POST | 审核通过 | 需要 |
| `/api/policy/workbench/items/{id}/reject/` | POST | 审核拒绝 | 需要 |
| `/api/policy/workbench/items/{id}/rollback/` | POST | 回滚生效 | 需要 |
| `/api/policy/workbench/items/{id}/override/` | POST | 临时豁免 | 需要 |
| `/api/policy/sentiment-gate/state/` | GET | 闸门状态 | 需要 |

#### 5.2.3 Signal API

| 端点 | 方法 | 说明 | 认证 |
|------|------|------|------|
| `/api/signal/` | GET/POST | 列出/创建信号 | 需要 |
| `/api/signal/{id}/` | GET | 获取信号详情 | 需要 |
| `/api/signal/{id}/invalidate/` | POST | 手动证伪 | 需要 |

#### 5.2.4 Alpha API

| 端点 | 方法 | 说明 | 认证 |
|------|------|------|------|
| `/api/alpha/scores/` | GET | 获取股票评分 | 需要 |
| `/api/alpha/providers/status/` | GET | Provider 状态 | 需要 |

**Query Parameters**:
| 参数 | 类型 | 说明 | 默认值 |
|------|------|------|--------|
| universe | string | 股票池标识 | csi300 |
| trade_date | date | 交易日期（ISO 格式） | 今天 |
| top_n | integer | 返回前 N 只 | 30 |
| provider | string | 强制 Provider（qlib/cache/simple/etf） | 自动降级 |

**响应示例**：
```json
{
    "success": true,
    "source": "cache",
    "status": "available",
    "timestamp": "2026-03-22T10:00:00Z",
    "latency_ms": 150,
    "staleness_days": 1,
    "stocks": [
        {
            "code": "000001.SZ",
            "name": "平安银行",
            "score": 0.85,
            "rank": 1,
            "factors": {
                "momentum": 0.82,
                "value": 0.78,
                "quality": 0.91
            },
            "confidence": 0.88,
            "source": "cache",
            "asof_date": "2026-03-22",
            "intended_trade_date": "2026-03-22",
            "universe_id": "csi300"
        }
    ],
    "metadata": {
        "cache_date": "2026-03-22",
        "asof_date": "2026-03-22",
        "provider_source": "cache"
    }
}
```

**响应示例**：
```json
{
    "scores": [
        {
            "code": "000001.SZ",
            "name": "平安银行",
            "score": 0.85,
            "rank": 1,
            "factors": {
                "momentum": 0.82,
                "value": 0.78,
                "quality": 0.91
            },
            "confidence": 0.88,
            "source": "qlib"
        }
    ],
    "asof_date": "2026-03-05"
}
```

#### 5.2.5 Asset Analysis API

| 端点 | 方法 | 说明 | 认证 |
|------|------|------|------|
| `/api/asset-analysis/screen/{asset_type}/` | GET | 资产筛选 | 需要 |
| `/api/asset-analysis/pool-summary/` | GET | 资产池摘要 | 需要 |
| `/api/asset-analysis/score/{asset_code}/` | GET | 资产评分 | 需要 |

#### 5.2.6 Simulated Trading API

| 端点 | 方法 | 说明 | 认证 |
|------|------|------|------|
| `/api/account/accounts/` | GET/POST | 当前登录用户统一账户列表/创建 | 需要 |
| `/api/account/accounts/{id}/` | GET | 当前登录用户统一账户详情 | 需要 |
| `/api/account/accounts/{id}/positions/` | GET | 当前登录用户持仓列表，`avg_cost` 为含买入侧手续费和滑点的摊薄成本 | 需要 |
| `/api/account/accounts/{id}/trades/` | GET | 当前登录用户交易记录 | 需要 |
| `/api/account/accounts/{id}/performance/` | GET | 当前登录用户账户绩效 | 需要 |
| `/api/simulated-trading/manual-trade/` | POST | 手动交易 | 需要 |

#### 5.2.7 Dashboard API

| 端点 | 方法 | 说明 | 认证 |
|------|------|------|------|
| `/api/dashboard/performance/` | GET | 获取首页收益趋势图历史数据 | 需要 |
| `/api/dashboard/v1/equity-curve/` | GET | 获取 Streamlit 净值曲线序列 | 需要 |

**实现说明**：
- 数据来源：`account.PortfolioDailySnapshotModel`
- 输出字段：`date`、`portfolio_value`、`return_pct`，并附带 `cash_balance`、`invested_value`、`position_count`
- 口径对齐：历史序列以当前组合 `total_return_pct` 锚定，确保最新点与首页总收益一致
- 无历史数据时：接口仍保留单点兜底，避免前端空图

### 5.3 错误处理

**错误响应格式**：
```json
{
    "success": false,
    "error": {
        "code": "VALIDATION_ERROR",
        "message": "参数验证失败",
        "details": {
            "field": "asset_code",
            "reason": "无效的资产代码"
        }
    },
    "timestamp": "2026-03-05T10:00:00Z"
}
```

**错误码定义**：
| 错误码 | HTTP 状态码 | 说明 |
|--------|-------------|------|
| VALIDATION_ERROR | 400 | 参数验证失败 |
| AUTHENTICATION_ERROR | 401 | 认证失败 |
| PERMISSION_DENIED | 403 | 权限不足 |
| NOT_FOUND | 404 | 资源不存在 |
| BUSINESS_ERROR | 422 | 业务规则违反 |
| INTERNAL_ERROR | 500 | 内部错误 |

---

## 6. 部署与运维

### 6.1 部署架构

```
┌─────────────────────────────────────────────────────────────────┐
│                      生产环境部署架构                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│                    ┌─────────────┐                              │
│                    │   Nginx     │                              │
│                    │  反向代理   │                              │
│                    └──────┬──────┘                              │
│                           │                                     │
│         ┌─────────────────┼─────────────────┐                  │
│         │                 │                 │                  │
│         ▼                 ▼                 ▼                  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐            │
│  │  Django     │  │  Django     │  │  Django     │            │
│  │  Gunicorn   │  │  Gunicorn   │  │  Gunicorn   │            │
│  │  Worker 1   │  │  Worker 2   │  │  Worker N   │            │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘            │
│         │                 │                 │                  │
│         └─────────────────┼─────────────────┘                  │
│                           │                                     │
│         ┌─────────────────┼─────────────────┐                  │
│         │                 │                 │                  │
│         ▼                 ▼                 ▼                  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐            │
│  │  PostgreSQL │  │    Redis    │  │   Celery    │            │
│  │   主数据库   │  │  缓存/队列  │  │   Worker    │            │
│  └─────────────┘  └─────────────┘  └─────────────┘            │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 6.2 Docker 部署

**开发环境** (`docker-compose-dev.yml`)：
```yaml
services:
  postgres:
    image: postgres:15
    environment:
      POSTGRES_DB: agomtradepro
      POSTGRES_USER: agomtradepro
      POSTGRES_PASSWORD: changeme
    ports:
      - "5432:5432"
    volumes:
      - postgres_dev_data:/var/lib/postgresql/data

  redis:
    image: redis:7
    ports:
      - "6379:6379"
    volumes:
      - redis_dev_data:/data
```

**生产环境** (`docker-compose.yml`)：
```yaml
services:
  nginx:
    image: nginx:latest
    ports:
      - "80:80"
      - "443:443"
    depends_on:
      - django

  django:
    build: .
    command: gunicorn core.wsgi:application --bind 0.0.0.0:8000
    depends_on:
      - postgres
      - redis

  celery_worker:
    build: .
    command: celery -A core worker -l info

  celery_beat:
    build: .
    command: celery -A core beat -l info

  postgres:
    image: postgres:15
    volumes:
      - postgres_data:/var/lib/postgresql/data

  redis:
    image: redis:7
    volumes:
      - redis_data:/data
```

### 6.3 环境配置

**.env 文件**：
```env
# 数据库
DATABASE_URL=postgresql://agomtradepro:password@localhost:5432/agomtradepro

# Redis
REDIS_URL=redis://localhost:6379/0

# Django
SECRET_KEY=your-secret-key
DEBUG=False
ALLOWED_HOSTS=your-domain.com

# 数据源
TUSHARE_TOKEN=your-token
FRED_API_KEY=your-key

# 告警
SLACK_WEBHOOK_URL=https://hooks.slack.com/...
ALERT_EMAIL=alert@example.com

# Streamlit
STREAMLIT_DASHBOARD_ENABLED=True
STREAMLIT_DASHBOARD_URL=http://127.0.0.1:8501
```

### 6.4 Celery 定时任务

| 任务名称 | 调度时间 | 说明 |
|---------|---------|------|
| `daily-sync-and-calculate` | 每天 8:00 | 同步宏观数据并计算 Regime |
| `daily-signal-invalidation` | 每天 2:00 | 检查信号证伪条件 |
| `hourly-stop-loss-check` | 每小时 | 检查止损触发 |
| `simulated-trading-daily` | 工作日 15:30 | 模拟盘自动交易 |
| `realtime-update-after-close` | 工作日 16:30 | 收盘后更新价格 |
| `fetch_rss_sources` | 每 6 小时 | RSS 源抓取 |
| `auto_assign_pending_audits` | 每 15 分钟 | 自动分配审核 |
| `monitor_sla_exceeded` | 每 10 分钟 | SLA 超时监控 |

### 6.5 监控与告警

**监控指标**：
- 系统健康：`/api/health/`
- 数据库连接数
- Redis 内存使用
- Celery 任务积压
- API 响应时间

**告警渠道**：
- Slack Webhook
- 邮件通知
- 系统日志

---

## 7. 开发指南

### 7.1 开发环境搭建

```bash
# 1. 克隆代码
git clone https://github.com/your-org/agomtradepro.git
cd agomtradepro

# 2. 创建虚拟环境
python -m venv agomtradepro
agomtradepro\Scripts\activate  # Windows
source agomtradepro/bin/activate  # Linux/Mac

# 3. 安装依赖
pip install -r requirements.txt

# 4. 启动 Docker 服务
docker-compose -f docker-compose-dev.yml up -d

# 5. 数据库迁移
python manage.py migrate

# 6. 初始化数据
python manage.py init_asset_codes
python manage.py init_indicators
python manage.py init_thresholds

# 7. 创建超级用户
python manage.py createsuperuser

# 8. 启动开发服务器
python manage.py runserver
```

### 7.2 代码规范

**格式化工具**：
```bash
# 代码格式化
black .
isort .

# Lint 检查
ruff check .

# 类型检查
mypy apps/ --strict
```

**命名规范**：
| 类型 | 命名风格 | 示例 |
|------|----------|------|
| 模块 | snake_case | `regime` |
| 类 | PascalCase | `RegimeState` |
| 函数 | snake_case | `calculate_regime` |
| 变量 | snake_case | `growth_momentum` |
| 常量 | UPPER_SNAKE | `DEFAULT_LAMBDA` |

### 7.3 添加新模块

```bash
# 1. 创建模块目录
python manage.py startapp new_module apps/new_module

# 2. 创建四层结构
mkdir apps/new_module/{domain,application,infrastructure,interface}

# 3. 创建文件
touch apps/new_module/domain/{entities,protocols,services}.py
touch apps/new_module/application/{use_cases,tasks,dtos}.py
touch apps/new_module/infrastructure/{models,repositories,providers}.py
touch apps/new_module/interface/{views,serializers,urls}.py

# 4. 注册模块
# 在 core/settings/base.py 的 INSTALLED_APPS 添加 'apps.new_module'

# 5. 创建数据库迁移
python manage.py makemigrations new_module
python manage.py migrate
```

### 7.4 常用命令

```bash
# Django 命令
python manage.py runserver           # 启动服务器
python manage.py migrate             # 数据库迁移
python manage.py createsuperuser     # 创建管理员
python manage.py collectstatic       # 收集静态文件

# 数据初始化
python manage.py init_asset_codes    # 初始化资产代码
python manage.py init_indicators     # 初始化指标
python manage.py init_thresholds     # 初始化阈值
python manage.py sync_macro_data     # 同步宏观数据

# Celery 命令
celery -A core worker -l info        # 启动 Worker
celery -A core beat -l info          # 启动 Beat

# 测试命令
pytest tests/ -v                     # 运行全部测试
pytest tests/unit/ -v                # 单元测试
pytest tests/integration/ -v         # 集成测试
pytest tests/ --cov=apps             # 覆盖率报告

# Streamlit
streamlit run streamlit_app/app.py   # 启动仪表盘
```

---

## 8. 测试策略

### 8.1 测试分层模型

```
┌─────────────────────────────────────────────────────────────────┐
│                     8 层测试模型                                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  L7: 生产守护层 ─── 上线后冒烟、关键任务、监控告警              │
│                                                                 │
│  L6: UAT 层 ─────── 用户旅程、手工可用性、视觉一致性            │
│                                                                 │
│  L5: E2E 层 ─────── Playwright 浏览器测试、关键路径             │
│                                                                 │
│  L4: API 合同层 ─── OpenAPI、鉴权、状态码、字段契约             │
│                                                                 │
│  L3: 集成层 ─────── 模块内/模块间流程测试                       │
│                                                                 │
│  L2: 组件层 ─────── use_case + repository + serializer          │
│                                                                 │
│  L1: 单元层 ─────── Domain 规则、算法、边界值                   │
│                                                                 │
│  L0: 静态质量层 ─── ruff/black/mypy、安全扫描                   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 8.2 质量门禁

#### PR Gate（10-15 分钟）
```bash
pytest -q \
  tests/guardrails/test_logic_guardrails.py \
  tests/integration/policy/test_policy_integration.py \
  tests/unit/policy/test_fetch_rss_use_case.py
```

#### Nightly Gate（30-60 分钟）
```bash
# 全量单元测试
pytest tests/unit/ -v

# 核心集成测试
pytest tests/integration/ -v

# Playwright smoke
pytest tests/playwright/tests/smoke/ -v
```

#### RC Gate（发布前）
| 条件 | 要求 |
|------|------|
| 关键旅程通过率 | ≥ 90% |
| 主导航 404 | = 0 |
| P0 缺陷 | = 0 |
| P1 缺陷 | ≤ 2 |
| API 命名规范覆盖率 | = 100% |

### 8.3 测试覆盖要求

| 层级 | 覆盖率要求 |
|------|-----------|
| Domain 层 | ≥ 90% |
| Application 层 | ≥ 80% |
| Infrastructure 层 | ≥ 70% |
| Interface 层 | ≥ 60% |

---

## 9. 扩展与集成

### 9.1 SDK 集成

**Python SDK** (`sdk/agomtradepro`)：
```python
from agomtradepro import AgomTradeProClient

# 初始化客户端
client = AgomTradeProClient(
    base_url="http://localhost:8000",
    api_key="your-api-key"
)

# 获取当前 Regime
regime = client.regime.get_current()
print(f"当前象限: {regime.quadrant}")

# 获取 Alpha 评分
scores = client.alpha.get_scores(limit=10)
for score in scores:
    print(f"{score.code}: {score.score}")
```

### 9.2 MCP Server 集成

**AI Agent 集成** (`sdk/agomtradepro_mcp`)：
```python
# MCP Server 为 AI Agent 提供工具调用
# 支持 Claude、GPT 等 AI 模型

tools = [
    "regime_get_current",
    "policy_get_workbench_summary",
    "signal_list",
    "alpha_get_scores",
    "account_get_positions",
    # ... 更多工具
]
```

### 9.3 RBAC 权限

| 角色 | 权限范围 |
|------|----------|
| admin | 系统管理、所有操作 |
| owner | 账户管理、策略管理 |
| investment_manager | 投资决策、信号管理 |
| analyst | 数据查看、分析报告 |
| trader | 交易执行、持仓查看 |
| read_only | 只读访问 |

---

## 10. 附录

### 10.1 术语表

| 术语 | 英文 | 说明 |
|------|------|------|
| Regime | - | 宏观经济象限（四象限） |
| Policy | - | 政策风险档位（P0-P3） |
| Signal | - | 投资信号 |
| Alpha | - | 超额收益 |
| Beta | - | 市场风险 |
| HP 滤波 | Hodrick-Prescott Filter | 趋势分解滤波器 |
| Kalman 滤波 | Kalman Filter | 状态估计滤波器 |
| Brison 归因 | Brinson Attribution | 绩效归因方法 |
| IC | Information Coefficient | 信息系数 |
| ICIR | Information Ratio | 信息比率 |

### 10.2 参考资料

**内部文档**：
- [系统基线](governance/SYSTEM_BASELINE.md) - 单一叙事来源
- [模块分级表](governance/MODULE_CLASSIFICATION.md) - 模块治理
- [开发禁令](governance/DEVELOPMENT_BANLIST.md) - 开发约束
- [业务需求文档](business/AgomTradePro_V3.4.md)
- [开发快速参考](development/quick-reference.md)
- [测试策略文档](testing/master-test-strategy-2026-02.md)

**外部资源**：
- Django 文档：https://docs.djangoproject.com/
- DRF 文档：https://www.django-rest-framework.org/
- Celery 文档：https://docs.celeryq.dev/
- Qlib 文档：https://qlib.readthedocs.io/

### 10.3 更新日志

| 日期 | 版本 | 更新内容 |
|------|------|----------|
| 2026-03-22 | V3.6 | 新增 ai_capability 模块（AI 能力目录），更新模块数量(32→33) |
| 2026-03-22 | V3.5 | Alpha Provider 可比性改进（5 个方案）：API 响应增强、Provider 切换告警、数据过滤工具、评分日志增强、配置选项 |
| 2026-03-05 | V1.0 | 初始版本 |
| 2026-02-26 | V3.4 | 估值定价引擎 Phase 1 |
| 2026-02-27 | V3.4 | Policy 工作台一体化 |
| 2026-02-28 | V3.4 | 导航与文档口径同步 |

---

**文档维护**: AgomTradePro Team
**最后更新**: 2026-03-22
**文档版本**: V1.3
