# AgomSAAF 项目结构说明

> 生成时间: 2025-12-30
> 项目版本: 1.0

## 1. 项目概述

AgomSAAF (Agom Strategic Asset Allocation Framework) 是一个宏观环境准入系统，通过 Regime（增长/通胀象限）和 Policy（政策档位）过滤，确保投资者不在错误的宏观环境中下注。

## 2. 技术栈

| 类别 | 技术 |
|------|------|
| 语言 | Python 3.11+ |
| 框架 | Django 5.x |
| 数据库 | SQLite（开发）/ PostgreSQL（生产） |
| 异步任务 | Celery + Redis |
| 数据处理 | Pandas + NumPy |
| 测试框架 | pytest |

## 3. 四层架构

项目严格遵循四层架构模式：

```
┌─────────────────────────────────────────────────────────┐
│                    Interface 层                          │
│  (views.py, serializers.py, urls.py, admin.py)          │
│  - 只做输入验证和输出格式化                               │
│  - 禁止业务逻辑                                          │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                  Application 层                          │
│  (use_cases.py, tasks.py, dtos.py)                      │
│  - 用例编排                                              │
│  - 通过依赖注入使用 Infrastructure 层                    │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                   Domain 层                              │
│  (entities.py, services.py, rules.py)                   │
│  - 纯 Python 标准库                                     │
│  - 所有金融逻辑                                          │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                Infrastructure 层                         │
│  (models.py, repositories.py, adapters/)                │
│  - Django ORM                                           │
│  - 外部 API 客户端                                       │
└─────────────────────────────────────────────────────────┘
```

## 4. 目录结构

```
AgomSAAF/
├── apps/                        # 应用程序目录
│   ├── ai_provider/             # AI服务提供商管理
│   │   ├── domain/              #   领域层：实体和业务规则
│   │   ├── infrastructure/      #   基础设施层
│   │   │   ├── models.py        #     Django ORM 模型
│   │   │   └── repositories.py  #     数据仓储
│   │   └── interface/           #   接口层：视图和序列化器
│   │
│   ├── prompt/                  # AI Prompt管理系统
│   │   ├── domain/              #   领域层：模板实体、链配置实体
│   │   ├── application/         #   应用层：用例编排（执行Prompt、执行链）
│   │   ├── infrastructure/      #   基础设施层
│   │   │   ├── models.py        #     Django ORM 模型
│   │   │   ├── repositories.py  #     数据仓储
│   │   │   └── adapters/        #     数据适配器
│   │   │       ├── macro_adapter.py    # 宏观数据适配器
│   │   │       ├── regime_adapter.py   # Regime数据适配器
│   │   │       └── function_registry.py # 工具函数注册表
│   │   └── interface/           #   接口层：DRF视图和序列化器
│   │
│   ├── audit/                   # 事后审计模块
│   │   ├── domain/
│   │   ├── application/
│   │   ├── infrastructure/
│   │   │   └── models.py        #     Django ORM 模型
│   │   └── interface/
│   │
│   ├── backtest/                # 回测引擎
│   │   ├── domain/
│   │   ├── application/
│   │   ├── infrastructure/
│   │   │   └── models.py        #     Django ORM 模型
│   │   └── interface/
│   │
│   ├── macro/                   # 宏观数据采集（最复杂）
│   │   ├── domain/              #   指标实体定义
│   │   ├── application/         #   数据同步用例
│   │   ├── infrastructure/      #   数据仓储和适配器
│   │   │   ├── models.py        #     Django ORM 模型
│   │   │   ├── repositories.py  #     数据仓储
│   │   │   └── adapters/        #     AKShare/Tushare 适配器
│   │   │       ├── base.py      #       基础适配器
│   │   │       ├── akshare_adapter.py  #       AKShare主适配器
│   │   │       └── fetchers/    #       数据获取器（按指标分类）
│   │   │           ├── base_fetchers.py       # 基础指标
│   │   │           ├── economic_fetchers.py   # 经济活动
│   │   │           ├── trade_fetchers.py      # 贸易数据
│   │   │           ├── financial_fetchers.py  # 金融指标
│   │   │           └── other_fetchers.py      # 其他指标
│   │   └── interface/           #   Django admin 和 API
│   │
│   ├── policy/                  # 政策事件管理
│   │   ├── domain/
│   │   ├── infrastructure/
│   │   │   └── models.py        #     Django ORM 模型
│   │   └── interface/
│   │
│   ├── regime/                  # Regime 判定引擎
│   │   ├── domain/
│   │   ├── infrastructure/
│   │   │   └── models.py        #     Django ORM 模型
│   │   └── interface/
│   │
│   └── signal/                  # 投资信号管理
│       ├── domain/
│       ├── infrastructure/
│       │   └── models.py        #     Django ORM 模型
│       └── interface/
│
├── core/                        # Django 核心配置
│   ├── settings/                #   分环境配置
│   │   ├── base.py              #     基础配置
│   │   ├── development.py       #     开发环境
│   │   └── production.py        #     生产环境
│   ├── urls.py                  #   根路由配置
│   └── celery.py                #   Celery 配置
│
├── shared/                      # 跨应用共享模块
│   ├── config/                  #   配置管理
│   │   └── secrets.py           #     密钥管理
│   ├── domain/                  #   共享领域逻辑
│   │   └── interfaces.py        #     Protocol 定义
│   └── infrastructure/          #   共享基础设施
│       └── kalman_filter.py     #     Kalman 滤波器
│
├── static/                      # 开发环境静态文件（源代码）
│   ├── css/                     #   项目自定义样式
│   └── js/                      #   项目自定义 JavaScript
│
├── staticfiles/                 # 生产环境静态文件（collectstatic 生成）
│   ├── admin/                   #   Django Admin 静态文件
│   ├── rest_framework/          #   DRF 静态文件
│   ├── css/                     #   收集后的样式文件
│   └── js/                      #   收集后的 JS 文件
│
├── templates/                   # 全局模板
│
├── scripts/                     # 脚本文件
│   ├── run_backtest.py          #   运行回测
│   └── validate_backtest.py     #   验证回测结果
│
├── tests/                       # 测试文件
│   ├── unit/                    #   单元测试
│   └── integration/             #   集成测试
│
├── doc/                         # 项目文档
│   ├── AgomSAAF_V3.4.md         #   业务需求文档
│   ├── frontend_design_guide.md #   前端设计指南
│   ├── admin_credentials.md     #   管理员凭证
│   ├── implementation_tasks.md  #   实施任务清单
│   └── ai_provider_requirements.md  # AI 服务商需求
│
├── manage.py                    # Django 管理脚本
├── pyproject.toml               # Python 项目配置
├── pytest.ini                   # pytest 配置
├── package.json                 # Node.js 配置
└── requirements.txt             # Python 依赖
```

## 5. 静态文件管理

### 5.1 两个目录的区别

| 目录 | 用途 | 大小 | Git | 何时更新 |
|------|------|------|-----|----------|
| `static/` | 开发源代码目录 | ~2 文件 | ✅ 提交 | 开发时修改 CSS/JS |
| `staticfiles/` | 生产部署目录 | 4.7MB | ✅ 提交 | 升级依赖后 collectstatic |

### 5.2 工作原理

```
开发环境 (DEBUG=True):
┌─────────────────────────────────────────────────────┐
│  浏览器请求 /static/css/main.css                    │
└─────────────────┬───────────────────────────────────┘
                  ▼
        ┌─────────────────────┐
        │   Django 开发服务器 │
        └─────────┬───────────┘
                  │
                  ▼
        ┌─────────────────────────────────────┐
        │  实时查找源文件                     │
        │  1. apps/*/static/                  │
        │  2. STATICFILES_DIRS (static/)      │
        └─────────────────────────────────────┘

生产环境 (DEBUG=False):
┌─────────────────────────────────────────────────────┐
│  浏览器请求 /static/css/main.css                    │
└─────────────────┬───────────────────────────────────┘
                  ▼
        ┌─────────────────────┐
        │      Nginx          │
        └─────────┬───────────┘
                  │
                  ▼
        ┌─────────────────────────────────────┐
        │  直接服务 staticfiles/ 目录          │
        │  (包含所有收集后的静态文件)          │
        └─────────────────────────────────────┘
```

### 5.3 为什么两个目录都提交 Git？

**传统做法**：只提交 `static/`，`staticfiles/` 被 `.gitignore`
**本项目的选择**：两个都提交

**理由：**
1. **部署简单**：生产服务器直接 `git pull`，无需运行 `collectstatic`
2. **版本可控**：锁定 Django Admin/DRF 的静态文件版本
3. **容器友好**：Docker 构建时不需要运行 Django 命令
4. **避免风险**：`collectstatic` 可能因环境配置失败

### 5.4 开发工作流

```bash
# 1. 修改项目静态文件（在 static/ 中编辑）
vim static/css/main.css

# 2. 开发环境测试（自动读取 static/）
python manage.py runserver

# 3. 更新生产静态文件（升级依赖后）
pip install -U djangorestframework
python manage.py collectstatic --clear

# 4. 提交更改
git add staticfiles/
git commit -m "chore: update staticfiles after DRF upgrade"
```

### 5.5 Django 配置

```python
# core/settings/base.py

STATIC_URL = '/static/'                    # URL 前缀
STATIC_ROOT = BASE_DIR / 'staticfiles'    # collectstatic 目标目录
STATICFILES_DIRS = [                       # 开发环境额外查找目录
    BASE_DIR / 'static',
]
```

## 6. 关键模块说明

### 6.1 macro 应用 - 宏观数据采集

最复杂的应用，负责从多个数据源采集中国宏观经济数据。

**目录结构：**
```
apps/macro/
├── infrastructure/adapters/
│   ├── base.py              # 基础适配器接口
│   ├── akshare_adapter.py   # AKShare 主适配器（重构后 249 行）
│   ├── tushare_adapter.py   # Tushare 适配器
│   └── failover_adapter.py  # 故障转移适配器
│   └── fetchers/            # 数据获取器模块
│       ├── base_fetchers.py       # PMI, CPI, PPI, M2
│       ├── economic_fetchers.py   # GDP, 工业增加值, 社零
│       ├── trade_fetchers.py      # 进出口, 贸易差额
│       ├── financial_fetchers.py  # 利率, 外汇储备, 信贷
│       └── other_fetchers.py      # 就业, 房价, 油价
└── management/commands/
    └── sync_macro_data.py   # Django 管理命令
```

**重构说明（2025-12-29）：**
- 原 `akshare_adapter.py` (1778行) 已按指标类别拆分为 5 个 fetcher 模块
- 主适配器现在只负责路由请求到相应的 fetcher
- 每个文件保持在 300 行以内，便于维护

### 6.2 regime 应用 - Regime 判定引擎

根据增长和通胀数据判定当前经济象限。

**核心功能：**
- HP 滤波提取趋势（使用扩张窗口，无后视偏差）
- Kalman 滤波平滑动量
- Z-score 标准化判定象限

### 6.3 backtest 应用 - 回测引擎

验证投资策略在历史数据上的表现。

**核心类：**
- `BacktestEngine`: 回测引擎
- `BacktestConfig`: 回测配置
- `BacktestResult`: 回测结果

### 6.4 audit 应用 - 事后审计

分析回测结果，归因收益来源。

### 6.5 prompt 应用 - AI Prompt管理系统

统一的AI Prompt模板管理和链式调用系统。

**核心功能：**
- Prompt模板管理：支持占位符、版本控制
- 链式调用配置：串行、并行、工具调用、混合模式
- 占位符解析：支持简单替换、复杂数据、函数调用、条件逻辑
- 数据适配器：自动获取宏观数据、Regime状态
- 执行日志：记录所有AI调用和成本

**支持的占位符类型：**
| 类型 | 语法 | 示例 |
|------|------|------|
| 简单替换 | `{{FIELD}}` | `{{PMI}}` → 50.8 |
| 复杂数据 | `{{STRUCT}}` | `{{MACRO_DATA}}` → JSON表格 |
| 函数调用 | `{{FUNC(params)}}` | `{{TREND(PMI,6m)}}` → 趋势值 |
| 条件逻辑 | `{%if%}...{%endif%}` | Jinja2模板语法 |

**链式执行模式：**
- **SERIAL（串行）**：Step1 → Step2 → Step3
- **PARALLEL（并行）**：多步骤同时执行 → 汇总
- **TOOL_CALLING（工具调用）**：AI主动调用数据获取函数
- **HYBRID（混合）**：以上组合

## 7. 数据模型

### 7.1 数据模型概览

项目中共有 8 个 Django ORM 模型文件，位于各应用的 `infrastructure/models.py`：

| 应用 | 模型文件 | 主要表 |
|------|----------|--------|
| `macro` | models.py | MacroIndicator (宏观数据) |
| `regime` | models.py | RegimeHistory (Regime历史) |
| `policy` | models.py | PolicyEvent (政策事件) |
| `signal` | models.py | InvestmentSignal (投资信号) |
| `backtest` | models.py | BacktestResult (回测结果) |
| `audit` | models.py | AuditRecord (审计记录) |
| `ai_provider` | models.py | AIProviderConfig, AIUsageLog (AI配置) |
| `prompt` | models.py | PromptTemplate, ChainConfig, PromptExecutionLog, ChatSession (AI Prompt) |

### 7.2 宏观数据表 (macro_macroindicator)

| 字段 | 类型 | 说明 |
|------|------|------|
| code | String | 指标代码（如 CN_PMI） |
| value | Decimal | 指标值 |
| reporting_period | Date | 报告期 |
| period_type | String | 周期类型（day/month/quarter） |
| published_at | Date | 发布日期 |
| source | String | 数据源（akshare/tushare） |
| revision_number | Int | 修订版本号 |

### 7.3 Regime 历史表 (regime_regimehistory)

| 字段 | 类型 | 说明 |
|------|------|------|
| as_of_date | Date | 判定日期 |
| dominant_regime | String | 主导象限 |
| confidence | Decimal | 置信度 |
| distribution | JSON | 象限分布 |

### 7.4 投资信号表 (signal_investmentsignal)

| 字段 | 类型 | 说明 |
|------|------|------|
| asset_code | String | 资产代码 |
| signal_type | String | 信号类型（BUY/SELL） |
| regime_requirement | String | 要求的 Regime |
| logic_desc | Text | 逻辑描述 |
| invalidation_logic | Text | 证伪逻辑 |
| created_at | DateTime | 创建时间 |

### 7.5 Prompt模板表 (prompt_prompttemplate)

| 字段 | 类型 | 说明 |
|------|------|------|
| name | String | 模板名称（唯一） |
| category | String | 分类（report/signal/analysis/chat） |
| version | String | 版本号 |
| template_content | Text | 模板内容（支持Jinja2语法） |
| system_prompt | Text | 系统提示词 |
| placeholders | JSON | 占位符定义列表 |
| temperature | Float | 温度参数（0.0-2.0） |
| max_tokens | Int | 最大token数 |
| is_active | Boolean | 是否激活 |

### 7.6 链配置表 (prompt_chainconfig)

| 字段 | 类型 | 说明 |
|------|------|------|
| name | String | 链名称（唯一） |
| category | String | 分类 |
| steps | JSON | 步骤定义列表 |
| execution_mode | String | 执行模式（serial/parallel/tool/hybrid） |
| aggregate_step | JSON | 汇总步骤配置 |

### 7.7 执行日志表 (prompt_promptexecutionlog)

| 字段 | 类型 | 说明 |
|------|------|------|
| execution_id | String | 执行ID |
| template_id | Int | 关联的模板ID |
| chain_id | Int | 关联的链ID |
| rendered_prompt | Text | 渲染后的Prompt |
| ai_response | Text | AI响应内容 |
| status | String | 状态（success/error/timeout） |
| total_tokens | Int | 总token数 |
| estimated_cost | Decimal | 预估成本 |
| response_time_ms | Int | 响应时间（毫秒） |

## 8. 外部依赖

### 8.1 数据源 API

| 数据源 | 用途 | 库 |
|--------|------|------|
| AKShare | 宏观数据 | akshare |
| Tushare Pro | 行情数据 | tushare |

### 8.2 Python 依赖

```txt
Django>=5.0
celery[redis]>=5.3
pandas>=2.0
numpy>=1.24
statsmodels>=0.14
akshare>=1.12
tushare>=1.4
```

## 9. 常用命令

### 9.1 Django 命令

```bash
# 启动开发服务器
agomsaaf/Scripts/python manage.py runserver

# 数据库迁移
agomsaaf/Scripts/python manage.py makemigrations
agomsaaf/Scripts/python manage.py migrate

# 创建超级用户
agomsaaf/Scripts/python manage.py createsuperuser

# 同步宏观数据
agomsaaf/Scripts/python manage.py sync_macro_data
```

### 9.2 Celery 命令

```bash
# 启动 Celery Worker（另开终端）
celery -A core worker -l info

# 启动 Celery Beat（定时任务）
celery -A core beat -l info
```

### 9.3 测试命令

```bash
# 运行所有测试
agomsaaf/Scripts/python -m pytest

# 运行特定测试
agomsaaf/Scripts/python -m pytest tests/unit/test_regime_services.py

# 查看覆盖率
agomsaaf/Scripts/python -m pytest --cov=apps
```

### 9.4 回测脚本

```bash
# 运行回测
agomsaaf/Scripts/python scripts/run_backtest.py --start 2020-01-01 --end 2024-12-31

# 验证回测结果
agomsaaf/Scripts/python scripts/validate_backtest.py --compare --report report.html
```

### 9.5 代码质量检查

```bash
# 格式化代码
black .
isort .

# 类型检查
mypy apps/ --strict

# Lint 检查
ruff check .
```

### 9.6 静态文件管理

```bash
# 收集静态文件（升级依赖后）
python manage.py collectstatic --clear

# 清空后重新收集（生产部署前）
python manage.py collectstatic --clear --noinput
```

## 10. 虚拟环境

项目使用 `agomsaaf` 作为 Python 虚拟环境名称：

```bash
# 激活虚拟环境
agomsaaf/Scripts/activate

# 安装依赖
agomsaaf/Scripts/pip install -r requirements.txt
```

## 11. 重构记录

### 2025-12-30

1. **静态文件策略调整**
   - 决定将 `staticfiles/` 也提交 Git（4.7MB）
   - 简化部署流程，无需在生产环境运行 collectstatic

2. **更新项目结构文档**
   - 添加静态文件管理章节
   - 详细说明 static/ 和 staticfiles/ 的关系

### 2025-12-29

1. **合并文档目录**
   - 将 `docs/` 目录合并到 `doc/`
   - 删除冗余的 `docs/` 目录

2. **清理备份文件**
   - 删除 `apps/macro/interface/views.py.backup`

3. **重构 akshare_adapter.py**
   - 原 1778 行拆分为 5 个 fetcher 模块
   - 主适配器精简至 249 行
   - 每个模块负责一类指标

## 12. 开发规范

### 12.1 分层约束

| 层 | 允许 | 禁止 |
|----|------|------|
| Domain | Python 标准库 | Django, pandas, 外部库 |
| Application | Domain 层 | 直接导入 ORM Model |
| Infrastructure | Django ORM, pandas | 业务逻辑 |
| Interface | 输入验证/输出格式化 | 业务逻辑 |

### 12.2 关键规则

1. **HP 滤波必须使用扩张窗口**（避免后视偏差）
2. **密钥禁止硬编码**（使用 `shared.config.secrets`）
3. **数据源必须有 Failover**（主源失败自动切换）
4. **投资信号必须包含证伪逻辑**

### 12.3 代码风格

- 类型标注：强制
- 格式化：black + isort + ruff
- 测试覆盖率：Domain 层 ≥ 90%
- 文档：所有 public 函数必须有 docstring

## 13. 部署架构（生产环境）

```
                     ┌─────────────┐
                     │   Nginx     │
                     │  (反向代理)  │
                     └──────┬──────┘
                            │
                     ┌──────▼──────┐
                     │   Gunicorn   │
                     │ (Django WSGI)│
                     └──────┬──────┘
                            │
        ┌───────────────────┼───────────────────┐
        │                   │                   │
┌───────▼────────┐  ┌───────▼────────┐  ┌──────▼─────┐
│   PostgreSQL   │  │     Redis      │  │   Celery    │
│   (数据库)     │  │   (缓存/队列)  │  │  (Worker)   │
└────────────────┘  └────────────────┘  └─────────────┘
```

## 14. 相关文档

- [业务需求文档](doc/AgomSAAF_V3.4.md)
- [前端设计指南](doc/frontend_design_guide.md)
- [项目开发规则](CLAUDE.md)
- [AI Prompt系统使用文档](doc/ai_prompt_system.md)
