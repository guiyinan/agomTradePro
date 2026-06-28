# AgomTradePro 系统初始化指南

> **最后更新**: 2026-06-28
> **版本**: 0.7.0
> **版本管理**: [VERSION.md](../VERSION.md)

---

## 快速开始（全新安装）

### 方式一：网页安装向导（推荐）

首次启动后，访问 http://127.0.0.1:8000/setup/ 进入安装向导：

```bash
# 1. 激活虚拟环境
agomtradepro\Scripts\activate

# 2. 数据库迁移
python manage.py migrate

# 3. 启动服务
python manage.py runserver

# 4. 访问 http://127.0.0.1:8000/setup/ 完成安装向导
```

**安装向导功能**：
- 引导创建管理员账户（首次安装）
- 配置 AI 服务商（可选）
- 配置数据源（可选）
- **已初始化系统**：需要输入管理员密码才能修改配置

### 方式二：命令行初始化

```bash
# 1. 激活虚拟环境
agomtradepro\Scripts\activate

# 2. 数据库迁移
python manage.py migrate

# 3. 一键初始化冷启动配置
python manage.py bootstrap_cold_start

# 4. 创建管理员
python manage.py createsuperuser

# 5. 启动服务
python manage.py runserver
```

访问管理后台：http://127.0.0.1:8000/admin/

---

## 初始化命令详解

### `bootstrap_cold_start` - 冷启动初始化（推荐）

**位置**: `apps/account/management/commands/bootstrap_cold_start.py`

**功能**: 幂等初始化新环境所需的基础配置、文档、Prompt、调度任务、RSS 权威源、策略参数和 MCP/SDK 冷启动默认值。

```bash
# 默认：只初始化本地配置，不主动做网络同步
python manage.py bootstrap_cold_start

# 同步宏观数据（需要网络和数据源可用）
python manage.py bootstrap_cold_start --with-macro-sync

# 修复决策级 quote / Pulse / Alpha readiness（需要数据源、Qlib 或对应降级链路可用）
python manage.py bootstrap_cold_start --with-decision-repair

# Alpha 冷启动
python manage.py bootstrap_cold_start --with-alpha
```

**初始化顺序**:
1. 资产分类和币种 (`init_classification`)
2. 投资规则 (`init_enhanced_rules`)
3. 系统文档 (`init_docs`)
4. Regime 阈值 (`init_regime_thresholds`)
5. Audit 指标阈值与置信度配置
6. Equity 权重与筛选配置
7. Prompt 模板与 Chain
8. 默认计划任务 (`init_scheduler_defaults`)
9. 权威 RSS 源 (`init_authoritative_rss_sources`)
10. Rotation / Hedge / Factor 默认配置
11. MCP 冷启动默认值
12. Decision Model Params
13. 仓位管理规则

`init_authoritative_rss_sources` 会启用 RSSHub 全局配置，并初始化政策/监管/财经新闻源：
国家统计局、发改委、证监会、上交所、深交所、财联社、格隆汇。该命令会停用
IT之家、V2EX、少数派等非投研/政策新闻源，但不会删除历史 RSS 抓取日志或政策事件。

---

### `init_all` - 旧版轻量初始化（保留）

**位置**: `apps/account/management/commands/init_all.py`

**功能**: 按旧版顺序初始化一部分基础数据。覆盖范围比 `bootstrap_cold_start` 小，主要用于兼容历史脚本；全新环境优先使用 `bootstrap_cold_start`。

```bash
# 默认：初始化所有数据
python manage.py init_all

# 跳过交互确认（脚本化/CI 推荐）
python manage.py init_all -y

# 跳过宏观数据同步（无需网络）
python manage.py init_all --skip-macro

# 跳过宏观数据同步 + 跳过确认
python manage.py init_all --skip-macro -y

# 强制覆盖现有数据
python manage.py init_all --force

# 只执行特定步骤
python manage.py init_all --step classification
```

**旧版初始化顺序**:
1. 资产分类和币种 (`init_classification`)
2. 投资规则 (`init_enhanced_rules`)
3. 系统文档 (`init_docs`)
4. Regime 阈值 (`init_regime_thresholds`)
5. 股票评分权重 (`init_scoring_weights`)
6. Prompt 模板 (`init_prompt_templates`)
7. 默认计划任务 (`init_scheduler_defaults`)
8. 权威 RSS 源 (`init_authoritative_rss_sources`)
9. 宏观数据 (`sync_macro_data`, 可选)

### 单独初始化命令

#### 1. `init_classification` - 资产分类和币种

**位置**: `apps/account/management/commands/init_classification.py`

```bash
python manage.py init_classification
```

**初始化内容**:

| 类型 | 数据 | 说明 |
|------|------|------|
| 币种 | CNY, USD, EUR, HKD, JPY, GBP | CNY 为基准货币 |
| 资产分类 | 9 个一级分类 | FUND, STOCK, BOND, WEALTH, DEPOSIT 等 |
| 资产子类 | 13 个二级分类 | 股票基金、债券基金、活期存款等 |
| 汇率 | 初始汇率数据 | USD/CNY, EUR/CNY 等 |

**Admin 路径**: `/admin/account/`

---

#### 2. `init_enhanced_rules` - 投资规则（增强版）

**位置**: `apps/account/management/commands/init_enhanced_rules.py`

```bash
python manage.py init_enhanced_rules
```

**初始化的规则类型**:

| 规则类型 | 说明 | 示例 |
|---------|------|------|
| `regime_advice` | Regime 环境建议 | 复苏期增持股票 |
| `position_advice` | 仓位建议 | 高仓位/低仓位提示 |
| `match_advice` | Regime 匹配度 | 当前 Regime 适合的投资 |
| `signal_advice` | 投资信号建议 | 信号与持仓关系 |
| `risk_alert` | 风险提示 | 高亏损/高盈利警告 |

**Admin 路径**: `/admin/account/investmentrulemodel/`

---

#### RSS 源初始化 - `init_authoritative_rss_sources`

**位置**: `apps/policy/management/commands/init_authoritative_rss_sources.py`

```bash
# 本地开发，RSSHub 在宿主机 1200 端口
python manage.py init_authoritative_rss_sources --base-url http://127.0.0.1:1200

# Docker/VPS，RSSHub 作为 compose 服务运行
python manage.py init_authoritative_rss_sources --base-url http://rsshub:1200

# 只查看将要写入的配置
python manage.py init_authoritative_rss_sources --dry-run
```

**初始化内容**:

| 类型 | 数据 | 说明 |
|------|------|------|
| RSSHub 全局配置 | `base_url`, `enabled=True`, `default_format=rss` | 用于统一拼接 RSSHub 路由 |
| 政府/监管源 | 国家统计局、发改委、证监会、上交所、深交所 | 用于政策闸门和监管事件 |
| 财经媒体源 | 财联社、格隆汇 | 用于市场热点和情绪补充 |
| 旧源清理 | IT之家、V2EX、少数派、金十数据 | 默认停用，不删除历史数据 |

---

#### 3. `init_docs` - 系统文档

**位置**: `apps/account/management/commands/init_docs.py`

```bash
python manage.py init_docs
```

**初始化的文档**:
- 投资信号与持仓关系说明
- Regime 投资象限说明
- 用户操作指南
- 常见问题解答

**Admin 路径**: `/admin/documentation/documentmodel/`

---

#### 4. `init_regime_thresholds` - Regime 阈值配置

**位置**: `apps/regime/management/commands/init_regime_thresholds.py`

```bash
python manage.py init_regime_thresholds
```

**初始化内容**:

| 指标 | 阈值范围 | 说明 |
|------|---------|------|
| GDP 增长率 | 阈值点 | 判断增长/放缓 |
| CPI 通胀率 | 阈值点 | 判断通胀/通缩 |
| PMI | 阈值点 | 辅助判断经济状态 |

**Admin 路径**: `/admin/regime/regimeindicatorthreshold/`

---

#### 5. `init_scoring_weights` - 股票评分权重

**位置**: `apps/equity/management/commands/init_scoring_weights.py`

```bash
python manage.py init_scoring_weights
```

**初始化的评分配置**:

| 配置名称 | 成长性 | 盈利能力 | 估值 | 说明 |
|---------|-------|---------|------|------|
| 默认配置 | 40% | 40% | 20% | 平衡型评分 |
| 成长型配置 | 50% | 35% | 15% | 偏向高成长 |
| 价值型配置 | 30% | 35% | 35% | 偏向低估值 |

**Admin 路径**: `/admin/equity/scoringweightconfigmodel/`

---

#### 6. `init_prompt_templates` - AI Prompt 模板

**位置**: `apps/prompt/management/commands/init_prompt_templates.py`

```bash
# 默认：跳过已存在的模板
python manage.py init_prompt_templates

# 强制覆盖所有模板
python manage.py init_prompt_templates --force

# 只加载链配置
python manage.py init_prompt_templates --chains-only

# 只加载 Prompt 模板
python manage.py init_prompt_templates --templates-only
```

**初始化内容**:
- AI 分析 Prompt 模板
- Prompt 链配置
- 默认参数设置

**Admin 路径**: `/admin/prompt/`

---

#### 7. `sync_macro_data` - 宏观数据同步

**位置**: `apps/macro/management/commands/sync_macro_data.py`

```bash
# 同步最近 10 年的 PMI, CPI, PPI
python manage.py sync_macro_data

# 同步指定指标
python manage.py sync_macro_data --indicators CN_PMI CN_CPI

# 同步最近 N 年
python manage.py sync_macro_data --years 5
```

**数据源**: AKShare (https://akshare.akfamily.xyz/)

**可用指标**:
- `CN_PMI` - 中国制造业 PMI
- `CN_CPI` - 中国消费者物价指数
- `CN_PPI` - 中国生产者物价指数
- `CN_SHIBOR` - SHIBOR 利率
- `US_GDP` - 美国 GDP
- `US_CPI` - 美国 CPI

---

#### 7. `init_scheduler_defaults` - 默认计划任务

**位置**: `apps/task_monitor/management/commands/init_scheduler_defaults.py`

```bash
python manage.py init_scheduler_defaults

# 仅初始化但默认禁用
python manage.py init_scheduler_defaults --disable
```

**初始化内容**:

- 宏观同步/Regime 周期任务
- 股票估值同步/校验周期任务
- 决策工作台夜间快照周期任务

**任务存储方式**:

- 通过 `django-celery-beat` 写入数据库表
- 可在 Django Admin 的 `PeriodicTask` / `CrontabSchedule` 中继续编辑
- 统一可视化页面：`/ops/task-monitor/`

---

## 数据库迁移

### 首次安装

```bash
# 创建所有数据库表
python manage.py migrate

# 查看迁移计划
python manage.py migrate --plan
```

### 重置数据库（开发环境）

```bash
# Windows (PowerShell)
Remove-Item db.sqlite3
python manage.py migrate
python manage.py init_all --force
```

---

## 系统配置项

### 环境变量配置 (`.env`)

```bash
# Django
SECRET_KEY=your-secret-key-here
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

# Local quick start
# SQLite is used automatically, no DATABASE_URL required
# Redis is optional; leave REDIS_URL unset for synchronous local tasks

# Data Sources
TUSHARE_TOKEN=your-tushare-token
AKSHARE_ENABLED=True
```

### Tushare Token 配置

如需使用 Tushare Pro 数据源：

1. 注册账号: https://tushare.pro/
2. 获取 Token
3. 在 `.env` 中配置: `TUSHARE_TOKEN=your_token_here`

---

## 验证安装

运行以下命令验证系统状态：

```bash
# Django 系统检查
python manage.py check

# 查看已安装的应用
python manage.py showmigrations

# 检查数据库完整性
python manage.py check --database default

# 运行测试
pytest tests/unit/ -v
```

---

## Admin 后台管理

初始化完成后，访问 `/admin/` 可以管理：

| 模块 | 路径 | 说明 |
|------|------|------|
| Account | `/admin/account/` | 账户、资产、币种 |
| Regime | `/admin/regime/` | 宏观环境、阈值配置 |
| Equity | `/admin/equity/` | 股票、评分权重配置 |
| Signal | `/admin/signal/` | 投资信号、证伪逻辑 |
| Policy | `/admin/policy/` | 政策事件 |
| Prompt | `/admin/prompt/` | AI Prompt 模板 |

---

## 常见问题

### Q1: init_all 命令不存在

**A**: 确保已执行 `python manage.py migrate`

### Q2: 宏观数据同步失败

**A**:
- 检查网络连接
- 使用 `--skip-macro` 跳过宏观数据
- AKShare 接口可能暂时不可用

### Q3: 如何重置某个配置？

**A**: 使用 Django Admin 删除后重新运行对应的初始化命令

### Q4: 初始化后如何开始使用？

**A**:
1. 创建超级用户: `python manage.py createsuperuser`
2. 启动服务: `python manage.py runserver`
3. 访问 `/admin/` 配置系统
4. 访问 `/dashboard/` 查看仪表盘

---

## 定期维护

系统运行后，建议定期执行：

```bash
# 每月更新宏观数据（官方数据发布后）
python manage.py sync_macro_data

# 更新 Prompt 模板（如需要）
python manage.py init_prompt_templates --force
```

可配置 Celery 定时任务自动执行。

---

## 开发环境快速重置脚本

创建 `scripts/reset_dev.bat`:

```bat
@echo off
echo AgomTradePro Development Reset...
echo.

echo Step 1: Delete database...
del db.sqlite3 2>nul

echo Step 2: Run migrations...
python manage.py migrate

echo Step 3: Initialize all data...
python manage.py init_all --force

echo.
echo Reset complete! Start server with: python manage.py runserver
pause
```

---

## 命令速查表

| 命令 | 功能 | 频率 |
|------|------|------|
| `python manage.py migrate` | 数据库迁移 | 安装/更新时 |
| `python manage.py init_all` | 一键初始化所有数据 | 首次安装 |
| `python manage.py init_classification` | 初始化分类和币种 | 首次安装 |
| `python manage.py init_enhanced_rules` | 初始化投资规则 | 首次安装 |
| `python manage.py init_docs` | 初始化文档 | 首次安装 |
| `python manage.py init_regime_thresholds` | 初始化 Regime 阈值 | 首次安装 |
| `python manage.py init_scoring_weights` | 初始化评分权重 | 首次安装 |
| `python manage.py init_prompt_templates` | 初始化 AI 模板 | 首次安装 |
| `python manage.py sync_macro_data` | 同步宏观数据 | 每月 |
| `python manage.py createsuperuser` | 创建管理员 | 首次安装 |
| `python manage.py runserver` | 启动服务器 | 日常 |
| `python manage.py check` | 系统检查 | 调试时 |

---

## 附录：文件结构

```
AgomTradePro/
├── apps/
│   ├── account/management/commands/
│   │   ├── init_classification.py    # 资产分类和币种
│   │   ├── init_enhanced_rules.py    # 投资规则
│   │   ├── init_docs.py              # 系统文档
│   │   └── init_all.py               # 一键初始化 (NEW)
│   ├── regime/management/commands/
│   │   └── init_regime_thresholds.py # Regime 阈值
│   ├── equity/management/commands/
│   │   └── init_scoring_weights.py   # 股票评分权重
│   ├── prompt/management/commands/
│   │   └── init_prompt_templates.py  # Prompt 模板
│   └── macro/management/commands/
│       └── sync_macro_data.py        # 宏观数据同步
├── scripts/
│   └── reset_dev.bat                 # 开发环境重置脚本
└── docs/
    └── development/
        └── system_initialization.md   # 本文档
```

---

## 更多帮助

- Django 管理命令: https://docs.djangoproject.com/en/5.2/howto/custom-management-commands/
- 项目主页: `docs/business/AgomTradePro_V3.4.md`
- API 文档: 访问 `/api/docs/` 查看
