<div align="center">

**[English](README_EN.md) | [中文](README.md)**

# AgomTradePro

### 别在错误的宏观环境里下注，哪怕你的逻辑是对的。

**一套宏观准入投资系统 —— 在你出手之前，先确认大环境没有站在你的对立面。**

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Django 5.x](https://img.shields.io/badge/django-5.x-green.svg)](https://www.djangoproject.com/)
[![Tests](https://img.shields.io/badge/tests-1%2C600+-brightgreen.svg)](#测试)
[![Modules](https://img.shields.io/badge/业务模块-34-purple.svg)](#架构)
[![MCP Tools](https://img.shields.io/badge/MCP_工具-65+-orange.svg)](#ai-原生集成)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)

[快速开始](#快速开始) · [为什么做这个](#为什么做这个) · [功能](#功能一览) · [AI 集成](#ai-原生集成) · [截图](#截图) · [文档](docs/INDEX.md)

</div>

---

## 为什么做这个

大部分散户亏钱，不是因为选股差，而是因为**在错误的时间出手**。

- 你买了好股票 —— **但正值滞胀周期**
- 你执行了好策略 —— **但政策正在收紧**
- 你看到了明确信号 —— **但脚下的宏观地基正在移动**

**结果是什么？** 逻辑正确，世界不对。亏钱。

AgomTradePro 只相信一个原则：

> **"不要在错误的宏观世界里，用正确的逻辑下注。"**

它是一个**宏观守门员** —— 在你每一笔投资决策执行之前，先用 Regime（增长 × 通胀象限）和 Policy（政策档位）过滤一遍。它不预测价格，它阻止错误。

---

## 它解决什么问题

### 1. 信息过载 → 结构化宏观情报

PMI 发布了、CPI 出来了、M2 又变了、政策又吹风了…… 你淹没在噪音里。AgomTradePro 从多个数据源采集宏观数据，标准化处理，用 Kalman/HP 滤波提取趋势，最终浓缩成一个清晰的答案：**我们现在处于哪个 Regime？**

| Regime | 增长 | 通胀 | 应对策略 |
|--------|------|------|----------|
| **复苏 Recovery** | ↑ | ↓ | 进攻，加仓权益 |
| **过热 Overheat** | ↑ | ↑ | 精选，注意通胀风险 |
| **滞胀 Stagflation** | ↓ | ↑ | 防御，减仓观望 |
| **通缩 Deflation** | ↓ | ↓ | 等待，保留现金 |

不用猜了。不用听各路大V互相矛盾。一个宏观状态，用真实数据计算。

### 2. 情绪化交易 → 系统化纪律

每一笔交易在执行前都必须过关：

```
你的想法 → Regime 闸门 → Policy 闸门 → 信号验证 → 审批 → 执行
               ↓              ↓              ↓
          "宏观环境        "政策面         "这个信号有
           支持吗？"      配合吗？"       证伪条件吗？"
```

- **没有证伪逻辑的信号不能创建** —— 你必须在入场前定义"什么情况下我是错的"
- **敌对 Regime 下不能交易** —— 系统会物理阻止你
- **决策频率约束** —— 防止过度交易和 FOMO
- **完整审计链** —— 每一个决策都有记录，事后可复盘

这不是建议，这是**纪律的执行基础设施**。

### 3. 手动流程 → AI 原生自动化

不是后期加个 API 就叫 AI。AgomTradePro 从底层为 AI Agent 时代而设计：

- **Python SDK** — 32 个模块的完整编程接口
- **MCP Server（65+ 工具）** — 直接接入 Claude、Cursor 或任何支持 MCP 的 AI
- **Terminal CLI** — 终端风格的 AI 交互界面
- **Agent Runtime** — 任务编排，支持 提案 → 审批 → 执行 全生命周期

你的 AI Agent 可以检查宏观环境、评估信号、提出交易建议 —— 但执行仍需要人类审批。**AI 的速度，人类的判断。**

---

## 截图

<details>
<summary><b>投资指挥台（Dashboard）</b></summary>

![Dashboard](output/playwright/dashboard.png)

*一屏总览：账户、持仓、Regime 状态、活跃信号、收益表现。*

</details>

<details>
<summary><b>Regime 分析面板</b></summary>

![Regime Dashboard](output/playwright/regime_dashboard.png)

*四象限 Regime 可视化：动量趋势、置信度指标、历史追踪。*

</details>

<details>
<summary><b>宏观数据中心</b></summary>

![Macro Data](output/playwright/macro_data.png)

*实时宏观指标追踪：多源同步、趋势图表、AI 对话式数据探索。*

</details>

---

## 功能一览

### 核心系统
| 模块 | 做什么 |
|------|--------|
| **Regime 引擎** | 从增长/通胀指标计算当前宏观象限，Z-score 标准化 |
| **Policy 闸门** | 追踪财政/货币政策事件，评估对风险偏好的影响 |
| **信号管理器** | 创建、验证、追踪投资信号，强制要求证伪逻辑 |
| **决策工作流** | 预检 → 审批 → 执行流水线，带频率约束 |
| **回测引擎** | 历史验证，支持 Brinson 归因分析 |
| **审计系统** | 事后复盘，完整决策链路追踪和绩效归因 |

### 组合与执行
| 模块 | 做什么 |
|------|--------|
| **模拟交易** | 模拟盘交易，保证金追踪，每日巡检 |
| **实时监控** | 价格预警、涨跌排行、市场监控 |
| **策略系统** | 数据库驱动的仓位规则，按组合绑定策略 |
| **板块轮动** | 基于 Regime 的板块配置建议 |

### AI 与智能分析
| 模块 | 做什么 |
|------|--------|
| **Alpha 评分** | AI 选股评分，4 层降级（Qlib → 缓存 → 简单 → ETF） |
| **因子管理** | 因子计算、IC/ICIR 评估 |
| **对冲策略** | 期货对冲计算和组合保护 |
| **舆情闸门** | 新闻/舆情分析作为额外风险过滤 |

### 数据源
| 数据源 | 覆盖范围 |
|--------|----------|
| **Tushare Pro** | A 股行情、SHIBOR、指数数据 |
| **AKShare** | 宏观指标（PMI、CPI、M2、GDP 等） |
| **自动容灾** | 主备切换，1% 容差验证 |

---

## 架构

严格的**领域驱动设计（DDD）**，四层架构强制执行：

```
┌─────────────────────────────────────────────────────────┐
│  Interface 层      │ REST API、Admin UI、序列化          │
├─────────────────────┼───────────────────────────────────┤
│  Application 层    │ 用例编排、Celery 任务、DTO         │
├─────────────────────┼───────────────────────────────────┤
│  Infrastructure 层 │ Django ORM、API 适配器、仓储       │
├─────────────────────┼───────────────────────────────────┤
│  Domain 层         │ 实体、规则、服务                    │
│  （纯 Python）      │ 禁止 Django、Pandas、NumPy        │
└─────────────────────────────────────────────────────────┘
```

**为什么重要：** Domain 层零外部依赖，完全可测试、可移植。金融规则放在它该在的地方 —— 纯 Python 代码里，不跟任何框架绑定。

**34 个业务模块**，每个都有完整的四层实现。没有捷径。

---

## AI 原生集成

### Python SDK

```python
from agomtradepro import AgomTradeProClient

client = AgomTradeProClient(
    base_url="http://localhost:8000",
    api_token="your_token"
)

# 现在是什么宏观 Regime？
regime = client.regime.get_current()
print(f"当前 Regime: {regime.dominant_regime}")  # 比如 "Recovery"

# 这个标的现在能交易吗？
check = client.signal.check_eligibility(
    asset_code="000001.SH",
    logic_desc="PMI 连续回升，经济复苏"
)

# 创建信号（必须包含证伪条件）
if check["is_eligible"]:
    signal = client.signal.create(
        asset_code="000001.SH",
        logic_desc="PMI 连续回升，经济复苏",
        invalidation_logic="PMI 跌破 50 且连续 2 月低于前值",
        invalidation_threshold=49.5
    )
```

### MCP Server —— 给 AI Agent 用

把 AgomTradePro 接入 Claude Code、Cursor 或任何支持 MCP 的 AI：

```json
{
  "mcpServers": {
    "agomtradepro": {
      "command": "python",
      "args": ["-m", "agomtradepro_mcp.server"],
      "env": {
        "AGOMTRADEPRO_BASE_URL": "http://localhost:8000",
        "AGOMTRADEPRO_API_TOKEN": "your_token"
      }
    }
  }
}
```

然后直接跟 AI 对话：

```
你：   "现在宏观环境怎么样？我能加仓权益吗？"

Claude: [调用 get_current_regime] → 滞胀（增长 ↓，通胀 ↑）
        [调用 get_policy_status] → 货币政策偏紧

        "当前处于滞胀 Regime，货币政策偏紧。这是防御性环境，
         加仓权益与 Regime 信号相悖。建议等待 Regime 转换，
         或者考虑对冲仓位。"
```

**65+ MCP 工具**覆盖所有模块 —— Regime、信号、宏观数据、回测、交易、组合管理等。

### AI 决策工作流

```
AI Agent 提出交易建议
        ↓
系统自动预检（Regime 闸门 → Policy 闸门 → 频率检查）
        ↓
生成提案，包含完整上下文
        ↓
人类审核，批准或驳回
        ↓
受保护的执行，全程审计
```

AI 负责分析速度。人类负责执行判断。全链路可追溯。

---

## 快速开始

### 前置条件

- Python 3.11+
- Redis（Celery 任务队列需要）

### 安装

```bash
# 克隆
git clone https://github.com/guiyinan/agomTradePro.git
cd agomTradePro

# 创建虚拟环境
python -m venv agomtradepro
source agomtradepro/bin/activate  # Linux/Mac
# 或: agomtradepro\Scripts\activate  # Windows

# 安装依赖
pip install -r requirements.txt

# 数据库初始化
python manage.py migrate

# 启动开发服务器
python manage.py runserver

# 访问 http://localhost:8000/setup/ 完成安装向导
```

安装向导会引导你完成：
1. 创建管理员账户
2. 配置 AI 服务商（可选）
3. 配置数据源（可选）

### 安装 SDK（可选）

```bash
cd sdk
pip install -e ".[dev]"
```

### 运行测试

```bash
pytest tests/ -v --cov=apps
```

---

## 技术栈

| 层级 | 技术选型 |
|------|----------|
| **后端** | Python 3.11+、Django 5.x、DRF |
| **数据库** | SQLite（开发）/ PostgreSQL（生产） |
| **任务队列** | Celery + Redis |
| **数据处理** | Pandas、NumPy、Statsmodels |
| **可视化** | Streamlit、Plotly |
| **前端** | Django Templates + HTMX |
| **AI 集成** | MCP Server、Python SDK |
| **测试** | Pytest（1,600+ 用例）、Playwright（E2E） |

---

## 项目规模

```
34    业务模块（每个都有完整 DDD 四层实现）
65+   MCP 工具（供 AI Agent 调用）
100+  REST API 端点
1,600+ 自动化测试用例
230+  文档文件
```

---

## 文档

| 文档 | 说明 |
|------|------|
| **[上手手册](docs/QUICK_START.md)** | 从零到跑模拟盘的操作指南 |
| **[系统规格书](docs/SYSTEM_SPECIFICATION.md)** | 完整技术 + 功能规格 |
| **[SDK 参考](sdk/README.md)** | Python SDK 和 MCP Server 指南 |
| **[架构设计](docs/architecture/)** | DDD 设计、模块依赖关系 |
| **[文档索引](docs/INDEX.md)** | 全部文档导航 |

---

## 适合谁用

- **个人投资者** —— 想用系统化纪律替代情绪化操作
- **量化开发者** —— 需要一个生产级的宏观叠加层来增强策略
- **AI/LLM 爱好者** —— 想构建有护栏的投资 Agent，而不是裸奔的 GPT wrapper
- **金融学生** —— 用真实代码学习宏观驱动的投资框架

---

## 参与贡献

欢迎贡献！提交 PR 前请阅读[开发规范](docs/development/outsourcing-work-guidelines.md)。

```bash
# 格式化
black . && isort . && ruff check .

# 类型检查
mypy apps/ --strict

# 测试（Domain 层覆盖率 ≥ 90%）
pytest tests/ -v --cov=apps
```

---

## 开源协议

Apache License 2.0 —— 详见 [LICENSE](LICENSE)。

---

<div align="center">

**如果这个项目帮你少亏了一次钱，请给个 Star 吧**

*源于太多次"逻辑没错、时机全错"的惨痛教训。*

</div>
