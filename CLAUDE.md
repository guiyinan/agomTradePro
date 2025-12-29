# CLAUDE.md - AgomSAAF 项目开发规则

> 本文件是 Claude Code 的项目上下文配置，每次会话自动加载。

## 项目概述

AgomSAAF (Agom Strategic Asset Allocation Framework) 是一个宏观环境准入系统，通过 Regime（增长/通胀象限）和 Policy（政策档位）过滤，确保投资者不在错误的宏观环境中下注。

## 技术栈

- Python 3.11+
- Django 5.x
- SQLite（开发）/ PostgreSQL（生产）
- Celery + Redis（异步任务）
- Pandas + NumPy（数据处理）

## 核心架构约束 ⚠️

本项目严格遵循**四层架构**，违反以下规则的代码必须拒绝：

### Domain 层 (`apps/*/domain/`)
```
✅ 允许：Python 标准库、dataclasses、typing、enum、abc
❌ 禁止：django.*、pandas、numpy、requests、任何外部库
```
- 包含：entities.py（数据实体）、rules.py（业务规则）、services.py（纯算法）
- 所有金融逻辑必须在此层
- 使用 `@dataclass(frozen=True)` 定义值对象

### Application 层 (`apps/*/application/`)
```
✅ 允许：Domain 层、Protocol 接口
❌ 禁止：直接导入 ORM Model、直接调用外部 API
```
- 包含：use_cases.py（用例编排）、tasks.py（Celery 任务）、dtos.py
- 通过依赖注入使用 Infrastructure 层

### Infrastructure 层 (`apps/*/infrastructure/`)
```
✅ 允许：Django ORM、Pandas、外部 API 客户端
```
- 包含：models.py（ORM）、repositories.py（数据仓储）、adapters/（API 适配器）
- 实现 Domain 层定义的 Protocol 接口

### Interface 层 (`apps/*/interface/`)
- 包含：views.py（DRF）、serializers.py、admin.py、urls.py
- 只做输入验证和输出格式化，禁止业务逻辑

## 目录结构

```
AgomSAAF/
├── core/                     # Django 配置
│   ├── settings/
│   │   ├── base.py
│   │   ├── development.py
│   │   └── production.py
│   ├── urls.py
│   └── celery.py
├── apps/
│   ├── macro/                # 宏观数据采集
│   ├── regime/               # Regime 判定引擎
│   ├── policy/               # 政策事件管理
│   ├── signal/               # 投资信号管理
│   ├── backtest/             # 回测引擎
│   └── audit/                # 事后审计
├── shared/                   # 跨 App 共享
│   ├── domain/interfaces.py  # Protocol 定义
│   ├── infrastructure/       # 通用实现
│   └── config/secrets.py     # 密钥管理
└── tests/
```

## 关键技术规则

### 1. HP 滤波必须使用扩张窗口
```python
# ❌ 错误：全量数据滤波（有后视偏差）
trend, _ = hpfilter(full_series, lamb=129600)

# ✅ 正确：扩张窗口
def get_trend_at(series, t):
    truncated = series[:t+1]
    trend, _ = hpfilter(truncated, lamb=129600)
    return trend[-1]
```

### 2. Kalman 滤波参数定义在 Domain 层
- `KalmanFilterParams` 在 `apps/regime/domain/entities.py`
- `LocalLinearTrendFilter` 实现在 `apps/shared/infrastructure/kalman_filter.py`

### 3. 密钥禁止硬编码
```python
# ❌ 错误
ts.pro_api("your_token_here")

# ✅ 正确
from shared.config.secrets import get_secrets
ts.pro_api(get_secrets().data_sources.tushare_token)
```

### 4. 数据源必须有 Failover
- 主数据源失败时自动切换备用源
- 切换前必须校验数据一致性（容差 1%）
- 大偏差时告警而非静默切换

### 5. 投资信号必须包含证伪逻辑
```python
# ❌ 错误：缺少证伪条件
InvestmentSignal(asset_code="000001.SH", logic_desc="看好大盘")

# ✅ 正确
InvestmentSignal(
    asset_code="000001.SH",
    logic_desc="PMI 连续回升，经济复苏",
    invalidation_logic="PMI 跌破 50 且连续 2 月低于前值",
    invalidation_threshold=49.5
)
```

## 代码风格

- 类型标注：强制，所有函数必须有类型提示
- 格式化：black + isort + ruff
- 测试：Domain 层覆盖率 ≥ 90%
- 文档：所有 public 函数必须有 docstring

```bash
# 格式化
black .
isort .
ruff check .

# 类型检查
mypy apps/ --strict

# 测试
pytest tests/ -v --cov=apps
```

## 常用命令

```bash
# 开发环境启动
python manage.py runserver

# 数据库迁移
python manage.py makemigrations
python manage.py migrate

# 创建新 App
python manage.py startapp <app_name> apps/<app_name>

# Celery Worker（另开终端）
celery -A core worker -l info

# 运行测试
pytest tests/unit/test_regime_services.py -v
```

## 数据源 API

### Tushare Pro（行情数据）
```python
# 获取 SHIBOR
pro.shibor(start_date='20240101', end_date='20241231')

# 获取指数日线
pro.index_daily(ts_code='000001.SH', start_date='20240101')
```

### AKShare（宏观数据）
```python
import akshare as ak

# PMI
ak.macro_china_pmi()

# CPI
ak.macro_china_cpi()

# M2
ak.macro_china_money_supply()
```

## 当前开发阶段

Phase 1: 基础搭建（本地开发）
- [ ] Django 项目骨架
- [ ] Domain 层 Entities
- [ ] Tushare 适配器
- [ ] AKShare 适配器

## 注意事项

1. **不要创建 docker 相关文件**，Phase 1-3 全程本地开发
2. **先写 Domain 层**，再写其他层
3. **先写测试**，再写实现（TDD 友好）
4. 遇到不确定的金融逻辑，参考 `docs/AgomSAAF_V3.4.md`
