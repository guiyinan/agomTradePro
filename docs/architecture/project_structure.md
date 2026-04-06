# AgomTradePro 项目结构说明

> 生成时间: 2025-12-30
> 更新时间: 2026-03-28
> 项目版本: 1.4
> 模块数量: 35个业务模块

## 1. 项目概述

AgomTradePro (Agom Strategic Asset Allocation Framework) 是个人投研平台，通过 Regime（增长/通胀象限）和 Policy（政策档位）过滤，确保投资者不在错误的宏观环境中下注。

**系统状态**: 生产就绪
**测试覆盖**: 1,600+个测试用例，100%通过率

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
AgomTradePro/
├── apps/                        # 应用程序目录
│   ├── ai_provider/             # AI服务提供商管理
│   │   ├── domain/              #   领域层：实体和业务规则
│   │   │   ├── entities.py      #     AIProviderConfig, AIUsageRecord等
│   │   │   └── services.py      #     AICostCalculator, BudgetChecker
│   │   ├── application/         #   应用层：用例编排
│   │   │   ├── use_cases.py     #     ListProviders, CreateProvider, CheckBudget等
│   │   │   └── dtos.py          #     ProviderStatsDTO, BudgetCheckResultDTO等
│   │   ├── infrastructure/      #   基础设施层
│   │   │   ├── models.py        #     Django ORM 模型
│   │   │   ├── repositories.py  #     数据仓储
│   │   │   └── adapters.py      #     AI API适配器
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
│   ├── realtime/                # ⭐ 实时价格监控系统（新增）
│   │   ├── domain/              #   实体：RealtimePrice, PriceUpdate, PriceSnapshot
│   │   │   ├── entities.py      #     价格实体定义
│   │   │   └── protocols.py     #     Protocol 接口定义
│   │   ├── application/         #   应用层：价格轮询服务
│   │   │   └── price_polling_service.py  # 价格轮询和更新用例
│   │   ├── infrastructure/      #   基础设施层
│   │   │   └── repositories.py  #     Redis仓储、Tushare数据提供者
│   │   └── interface/           #   接口层
│   │       ├── views.py         #     价格API视图
│   │       └── urls.py          #     URL配置
│   │
│   ├── simulated_trading/       # ⭐ 模拟盘/投资组合模块（重构）
│   │   ├── domain/              #   实体和业务规则
│   │   │   ├── entities.py      #     SimulatedAccount, Position, Trade, FeeConfig
│   │   │   └── rules.py         #     仓位管理规则、交易约束规则
│   │   ├── application/         #   用例编排
│   │   │   ├── use_cases.py     #     创建账户、执行交易、计算绩效
│   │   │   ├── auto_trading_engine.py  # 自动交易引擎
│   │   │   ├── performance_calculator.py  # 绩效计算器
│   │   │   ├── asset_pool_query_service.py  # 资产池查询
│   │   │   └── tasks.py         #     Celery 定时任务
│   │   ├── infrastructure/      #   基础设施层
│   │   │   ├── models.py        #     SimulatedAccountModel, PositionModel, TradeModel, FeeConfigModel
│   │   │   ├── repositories.py  #     数据仓储（含 get_by_user 方法）
│   │   │   └── price_provider.py        # Data Center 价格提供者
│   │   └── interface/           #   接口层
│   │       ├── views.py         #     页面视图（my_accounts_page 等）
│   │       ├── urls.py          #     URL 配置
│   │       └── serializers.py   #     DRF 序列化器
│   │
│   ├── account/                 # ⭐ 账户管理模块（重构）
│   │   ├── domain/
│   │   ├── infrastructure/
│   │   │   └── models.py        #     UserModel, AccountProfileModel（简化）
│   │   └── interface/
│   │       ├── views.py         #     页面视图
│   │       └── urls.py          #     URL 配置
│
│   ├── strategy/                # ⭐ 策略系统（新增）
│   │   ├── domain/              #   实体：StrategyConfig, AllocationMatrix, RebalanceRule
│   │   ├── application/         #   应用层：allocation_service.py
│   │   ├── infrastructure/      #   基础设施层
│   │   │   └── models.py        #     StrategyConfigModel
│   │   └── interface/           #   接口层
│   │       └── views.py         #     策略配置视图
│
│   ├── sentiment/               # ⭐ 舆情情感分析（新增）
│   │   ├── domain/              #   实体：SentimentIndex, SentimentRecord
│   │   ├── application/         #   应用层：情感分析服务
│   │   ├── infrastructure/      #   基础设施层
│   │   │   └── models.py        #     SentimentIndexModel
│   │   └── interface/           #   接口层
│   │       └── views.py         #     情感指数视图
│
│   ├── equity/                  # 个股分析模块
│   │   ├── domain/              #   实体：StockInfo, ValuationMetrics
│   │   ├── application/         #   应用层：估值分析服务
│   │   ├── infrastructure/      #   基础设施层
│   │   │   ├── models.py        #     ORM 模型
│   │   │   └── adapters/        #     数据适配器
│   │   └── interface/           #   接口层
│   │       ├── views.py         #     个股筛选 API
│   │       └── urls.py
│
│   ├── fund/                    # 基金分析模块
│   │   ├── domain/              #   实体：FundInfo, FundManager
│   │   ├── application/         #   应用层：基金对比服务
│   │   ├── infrastructure/      #   基础设施层
│   │   │   ├── models.py        #     ORM 模型
│   │   │   └── adapters/        #     数据适配器
│   │   └── interface/           #   接口层
│   │       ├── views.py         #     基金筛选 API
│   │       └── urls.py
│
│   ├── sector/                  # 板块分析模块
│   │   ├── domain/              #   实体：SectorInfo, SectorRotation
│   │   ├── application/         #   应用层：板块轮动服务
│   │   ├── infrastructure/      #   基础设施层
│   │   │   └── models.py        #     ORM 模型
│   │   └── interface/           #   接口层
│   │       └── views.py
│
│   ├── asset_analysis/          # 通用资产分析框架（新增）
│   │   ├── domain/              #   实体：AssetScore, PoolEntry
│   │   ├── application/         #   应用层：pool_service.py
│   │   ├── infrastructure/      #   基础设施层
│   │   │   └── models.py        #     ORM 模型
│   │   └── interface/           #   接口层
│   │       └── views.py
│
│   ├── filter/                  # 筛选器管理
│   │   ├── domain/              #   实体：FilterCriteria
│   │   ├── infrastructure/      #   基础设施层
│   │   │   └── models.py        #     ORM 模型
│   │   └── interface/           #   接口层
│   │       └── views.py
│
│   ├── alpha/                   # ⭐ AI 选股信号（Qlib 集成）
│   │   ├── domain/              #   实体：StockScore, AlphaResult
│   │   ├── application/         #   应用层：AlphaService
│   │   ├── infrastructure/      #   基础设施层
│   │   │   ├── models.py        #     ORM 模型
│   │   │   └── adapters/        #     Provider 适配器
│   │   └── interface/           #   接口层
│   │       └── views.py
│
│   ├── alpha_trigger/           # ⭐ Alpha 离散触发
│   │   ├── domain/
│   │   ├── application/
│   │   └── infrastructure/
│
│   ├── beta_gate/               # ⭐ Beta 闸门
│   │   ├── domain/
│   │   ├── application/
│   │   └── infrastructure/
│
│   ├── decision_rhythm/         # ⭐ 决策频率约束
│   │   ├── domain/
│   │   ├── application/
│   │   └── infrastructure/
│
│   ├── factor/                  # ⭐ 因子管理
│   │   ├── domain/
│   │   ├── application/
│   │   └── infrastructure/
│
│   ├── rotation/                # ⭐ 板块轮动
│   │   ├── domain/
│   │   ├── application/
│   │   └── infrastructure/
│
│   ├── hedge/                   # ⭐ 对冲策略
│   │   ├── domain/
│   │   ├── application/
│   │   └── infrastructure/
│
│   ├── terminal/                # ⭐ 终端 CLI（AI 交互界面）
│   │   ├── domain/
│   │   ├── application/
│   │   ├── infrastructure/
│   │   └── interface/
│
│   ├── agent_runtime/           # ⭐ Agent 运行时（Terminal AI 后端）
│   │   ├── domain/
│   │   ├── application/
│   │   └── infrastructure/
│
│   ├── ai_capability/           # ⭐ AI 能力目录（统一路由）
│   │   ├── domain/
│   │   ├── application/
│   │   ├── infrastructure/
│   │   └── interface/
│
│   ├── share/                   # ⭐ 分享功能
│   │   ├── domain/
│   │   ├── application/
│   │   └── infrastructure/
│   │
│   ├── task_monitor/            # ⭐ 任务监控
│   │   ├── domain/
│   │   ├── application/
│   │   └── infrastructure/
│   │
│   ├── setup_wizard/            # ⭐ 系统初始化向导
│   │   ├── domain/
│   │   ├── application/
│   │   ├── infrastructure/
│   │   └── interface/
│   │
│   ├── pulse/                   # ⭐ Pulse 脉搏层（战术指标聚合与转折预警）
│   │   ├── domain/              #   PulseDimension, PulseIndicatorReading, PulseSnapshot
│   │   ├── application/         #   CalculatePulseUseCase, GetLatestPulseUseCase
│   │   ├── infrastructure/      #   models.py, repositories.py, data_provider.py
│   │   ├── interface/           #   api_views.py, admin.py
│   │   ├── management/commands/ #   init_pulse_config, set_pulse_weight, etc.
│   │   └── migrations/
│   │
│   ├── dashboard/               # 仪表盘
│   │   ├── application/         #   应用层：仪表盘数据聚合
│   │   └── interface/           #   接口层
│   │       └── views.py         #     页面视图
│
├── core/                        # Django 核心配置
│   ├── settings/                #   分环境配置
│   │   ├── base.py              #     基础配置
│   │   ├── development.py       #     开发环境
│   │   └── production.py        #     生产环境
│   ├── urls.py                  #   根路由配置
│   └── celery.py                #   Celery 配置
│
├── shared/                      # 跨应用共享模块（纯技术组件）
│   ├── config/                  #   配置管理
│   │   └── secrets.py           #     密钥管理
│   ├── domain/                  #   共享领域逻辑
│   │   ├── interfaces.py        #     Protocol 定义
│   │   ├── value_objects.py     #     值对象
│   │   └── asset_eligibility.py #     资产准入（待迁移）
│   ├── infrastructure/          #   共享基础设施
│   │   ├── kalman_filter.py     #     Kalman 滤波器
│   │   ├── calculators.py       #     HP 滤波、Z-score 计算
│   │   ├── alert_service.py     #     告警服务
│   │   ├── cache_service.py     #     缓存服务
│   │   ├── resilience.py        #     弹性重试
│   │   ├── models.py            #     共享 ORM 模型（配置表）
│   │   └── config_init.py       #     配置初始化
│   ├── admin.py                 #   Django Admin 配置
│   ├── apps.py                  #   Django App 配置
│   └── migrations/              #   数据库迁移
│       ├── 0001_initial.py
│       ├── 0002_*.py
│       └── 0003_*.py
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
│   ├── validate_backtest.py     #   验证回测结果
│   └── migrate_portfolio_to_investment_account.py  # ⭐ 数据迁移脚本
│
├── tests/                       # 测试文件
│   ├── unit/                    #   单元测试
│   │   ├── domain/              #     Domain 层测试（137个）
│   │   └── test_*.py            #     其他单元测试
│   ├── integration/             #   集成测试
│   │   ├── test_*.py            #     集成测试（50个）
│   └── playwright/              #   端到端测试
│
├── docs/                        # 项目文档（重组）
│   ├── architecture/            #   架构文档
│   │   ├── project_structure.md #     项目结构
│   │   ├── MODULE_DEPENDENCIES.md #   模块依赖关系
│   │   ├── asset_analysis_framework.md
│   │   ├── simulated_trading_design.md
│   │   ├── strategy_system_design.md
│   │   └── frontend_design_guide.md
│   ├── business/                #   业务文档
│   │   ├── AgomTradePro_V3.4.md    #     业务需求
│   │   ├── signal_and_position.md
│   │   └── equity-valuation-logic.md
│   ├── development/             #   开发文档
│   │   ├── coding_standards.md
│   │   ├── api_structure_guide.md
│   │   ├── quick-reference.md
│   │   └── module-ledger.md
│   ├── testing/                 #   测试文档
│   ├── governance/              #   治理文档
│   │   ├── SYSTEM_BASELINE.md  #     系统基线
│   │   ├── MODULE_CLASSIFICATION.md # 模块分级
│   │   └── DEVELOPMENT_BANLIST.md   # 开发禁令
│   ├── modules/                 #   模块文档
│   └── deployment/              #   部署文档
│
├── manage.py                    # Django 管理脚本
├── AGENTS.md                    # 项目开发规则
├── pyproject.toml               # Python 项目配置
├── pytest.ini                   # pytest 配置
├── package.json                 # Node.js 配置
├── requirements.txt             # Python 依赖
├── .env.example                 # 环境变量模板
└── .gitignore                   # Git 忽略规则
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

### 6.5 realtime 应用 - 实时价格监控系统 ⭐

提供实时市场价格数据接入能力。

**核心功能：**
- 高频轮询：每30秒自动轮询持仓资产价格
- Redis缓存：价格数据缓存5分钟
- 自动更新：收盘后批量更新（16:30定时任务）
- 前端实时展示：价格变化自动高亮

**API端点：**
| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/realtime/prices/` | GET | 查询价格（支持`?assets=`参数） |
| `/api/realtime/prices/` | POST | 手动触发价格轮询 |
| `/api/realtime/prices/{code}/` | GET | 查询单个资产价格 |
| `/api/realtime/poll/` | POST | 触发轮询 |
| `/api/realtime/health/` | GET | 健康检查 |

**数据源：**
- Tushare Pro（已实现）
- FRED（待实现）

### 6.6 ai_provider 应用 - AI 服务商管理

统一的 AI 服务商配置和成本管理系统。

**核心功能：**
- 多服务商管理：支持 OpenAI、DeepSeek、通义千问、Moonshot 等
- 配置管理：API Key、Base URL、默认模型、优先级
- 预算控制：每日/每月预算限制，自动监控
- 成本追踪：记录每次 API 调用的 token 使用和成本
- 使用统计：按日期、按模型统计使用情况

**支持的 AI 服务商：**
| 服务商 | 类型 | 默认模型 |
|--------|------|----------|
| OpenAI | openai | gpt-3.5-turbo, gpt-4, gpt-4-turbo |
| DeepSeek | deepseek | deepseek-chat, deepseek-coder |
| 通义千问 | qwen | qwen-turbo, qwen-plus, qwen-max |
| Moonshot | moonshot | moonshot-v1-8k, moonshot-v1-32k |

**Application 层用例：**
| 用例 | 说明 |
|------|------|
| `ListProvidersUseCase` | 获取提供商列表（带统计数据） |
| `CreateProviderUseCase` | 创建新提供商配置 |
| `UpdateProviderUseCase` | 更新提供商配置 |
| `DeleteProviderUseCase` | 删除提供商 |
| `ToggleProviderUseCase` | 切换启用/禁用状态 |
| `GetProviderStatsUseCase` | 获取提供商详细统计 |
| `GetOverallStatsUseCase` | 获取总体统计 |
| `CheckBudgetUseCase` | 检查预算限制 |

**API端点：**
| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/ai/providers/` | GET | 获取提供商列表 |
| `/api/ai/providers/` | POST | 创建新提供商 |
| `/api/ai/providers/{id}/` | PUT/PATCH | 更新提供商 |
| `/api/ai/providers/{id}/` | DELETE | 删除提供商 |
| `/api/ai/providers/{id}/toggle_active/` | POST | 切换启用状态 |
| `/api/ai/providers/{id}/usage_stats/` | GET | 获取使用统计 |
| `/api/ai/providers/overall_stats/` | GET | 获取总体统计 |
| `/api/ai/logs/` | GET | 获取使用日志 |

### 6.7 prompt 应用 - AI Prompt管理系统

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

### 7.8 AI 服务商配置表 (ai_provider_aiproviderconfig)

| 字段 | 类型 | 说明 |
|------|------|------|
| name | String | 配置名称（唯一） |
| provider_type | String | 服务商类型（openai/deepseek/qwen/moonshot/custom） |
| is_active | Boolean | 是否启用 |
| priority | Int | 优先级（数字越小越优先） |
| base_url | URL | API Base URL |
| api_key | String | API Key |
| default_model | String | 默认模型名称 |
| daily_budget_limit | Decimal | 每日预算限制（美元） |
| monthly_budget_limit | Decimal | 每月预算限制（美元） |
| extra_config | JSON | 额外配置参数 |
| last_used_at | DateTime | 最后使用时间 |

### 7.9 AI 使用日志表 (ai_provider_aiusagelog)

| 字段 | 类型 | 说明 |
|------|------|------|
| provider | ForeignKey | 关联的提供商配置 |
| model | String | 使用的模型 |
| request_type | String | 请求类型（chat/completion/embedding等） |
| prompt_tokens | Int | 输入 token 数量 |
| completion_tokens | Int | 输出 token 数量 |
| total_tokens | Int | 总 token 数量 |
| response_time_ms | Int | 响应时间（毫秒） |
| estimated_cost | Decimal | 预估成本（美元） |
| status | String | 调用状态（success/error/timeout/rate_limited） |
| error_message | Text | 错误信息 |
| request_metadata | JSON | 请求元数据 |
| created_at | DateTime | 创建时间 |

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
agomtradepro/Scripts/python manage.py runserver

# 数据库迁移
agomtradepro/Scripts/python manage.py makemigrations
agomtradepro/Scripts/python manage.py migrate

# 创建超级用户
agomtradepro/Scripts/python manage.py createsuperuser

# 同步宏观数据
agomtradepro/Scripts/python manage.py sync_macro_data
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
agomtradepro/Scripts/python -m pytest

# 运行特定测试
agomtradepro/Scripts/python -m pytest tests/unit/test_regime_services.py

# 查看覆盖率
agomtradepro/Scripts/python -m pytest --cov=apps
```

### 9.4 回测脚本

```bash
# 运行回测
agomtradepro/Scripts/python scripts/run_backtest.py --start 2020-01-01 --end 2024-12-31

# 验证回测结果
agomtradepro/Scripts/python scripts/validate_backtest.py --compare --report report.html
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

项目使用 `agomtradepro` 作为 Python 虚拟环境名称：

```bash
# 激活虚拟环境
agomtradepro/Scripts/activate

# 安装依赖
agomtradepro/Scripts/pip install -r requirements.txt
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

#### 12.1.1 严格依赖方向（强制）

1. `Interface -> Application -> Domain`
2. `Infrastructure -> Domain`
3. 禁止：`Domain -> 其他三层`
4. 禁止：`Application -> Interface`
5. 禁止：`Interface -> Infrastructure`（接口层必须通过 UseCase）

#### 12.1.2 快速自检命令

```bash
# Domain 层禁止外部依赖
rg -n "from django|import django|import pandas|import numpy|import requests" apps/*/domain -S

# Application 层禁止直接使用 ORM
rg -n "from .*infrastructure\\.models|\\.objects\\." apps/*/application -S

# Interface 层禁止越层调用 Infrastructure
rg -n "from .*infrastructure\\." apps/*/interface -S
```

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

- [业务需求文档](../business/AgomTradePro_V3.4.md)
- [前端设计指南](frontend_design_guide.md)
- [项目开发规则](../../AGENTS.md)
- [AI Prompt系统使用文档](../ai/ai_prompt_system.md)
- [实时价格监控系统文档](../integration/realtime_data_system.md)
- [模块依赖关系](MODULE_DEPENDENCIES.md)

## 15. 更新记录

### 2026-03-28

1. **文档全面对齐更新**
   - 更新模块数量 (33 → 35)
   - 新增 pulse 模块文档（战术指标聚合与转折预警）
   - 新增 setup_wizard 模块目录
   - 删除已归档的 `apps/shared/` 引用
   - 修正 `CLAUDE.md` → `AGENTS.md`
   - 修正 `SYSTEM_OVERVIEW.md` → 已归档
   - 更新测试用例数 (1,395 → 1,600+)
   - 更新 docs 目录树，反映当前实际结构

1. **新增 realtime 模块**
   - 实现实时价格监控系统
   - 支持 Tushare 数据源
   - 前端每30秒自动轮询
   - 收盘后自动批量更新（16:30）

2. **更新项目结构文档**
   - 添加 realtime 模块说明
   - 添加 API 端点文档

### 2026-02-06

1. **ai_provider 模块四层架构补全**
   - 新增 `application/` 层
   - 实现 9 个 Use Cases（ListProviders, CreateProvider, UpdateProvider, DeleteProvider, ToggleProvider, GetProviderStats, GetOverallStats, ListUsageLogs, CheckBudget）
   - 定义 6 个 DTOs（ProviderStatsDTO, UsageStatsDTO, OverallStatsDTO, ProviderListItemDTO, BudgetCheckResultDTO, UsageLogListItemDTO）
   - 重构 Interface 层，移除对 Infrastructure 层的直接依赖

2. **更新项目结构文档**
   - 添加 ai_provider 模块完整四层架构说明
   - 添加 AI 服务商配置表和使用日志表结构
   - 添加 ai_provider API 端点文档
