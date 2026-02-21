# CLAUDE.md - AgomSAAF 项目开发规则

> 本文件是 Claude Code 的项目上下文配置，每次会话自动加载。

## 项目概述

> **最后更新**: 2026-02-20
> **系统版本**: AgomSAAF V3.4
> **项目状态**: 生产就绪
> **业务模块**: 27个
> **测试覆盖**: 1,395个测试用例，100%通过率

AgomSAAF (Agom Strategic Asset Allocation Framework) 是一个宏观环境准入系统，通过 Regime（增长/通胀象限）和 Policy（政策档位）过滤，确保投资者不在错误的宏观环境中下注。

**最新完成**:
- Alpha 模块与 Qlib 深度集成（Phase 1-5 全部完成）
- 新增 Factor/Rotation/Hedge 智能模块
- 架构合规性修复（2026-02-20）

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
├── apps/                     # 27个业务模块
│   ├── macro/                # 宏观数据采集
│   ├── regime/               # Regime 判定引擎
│   ├── policy/               # 政策事件管理
│   ├── signal/               # 投资信号管理
│   ├── backtest/             # 回测引擎
│   ├── audit/                # 事后审计
│   ├── asset_analysis/       # 通用资产分析框架
│   ├── equity/               # 个股分析
│   ├── fund/                 # 基金分析
│   ├── sector/               # 板块分析
│   ├── sentiment/            # 舆情情感分析
│   ├── account/              # 账户与持仓管理
│   ├── simulated_trading/    # 模拟盘自动交易
│   ├── realtime/             # 实时价格监控
│   ├── strategy/             # 策略系统
│   ├── ai_provider/          # AI 服务商管理
│   ├── prompt/               # AI Prompt 模板
│   ├── dashboard/            # 仪表盘
│   ├── filter/               # 筛选器管理
│   ├── alpha/                # AI 选股信号（Qlib 集成）
│   ├── alpha_trigger/        # Alpha 离散触发
│   ├── beta_gate/            # Beta 闸门
│   ├── decision_rhythm/      # 决策频率约束
│   ├── factor/               # 因子管理
│   ├── rotation/             # 板块轮动
│   ├── hedge/                # 对冲策略
│   └── events/               # 事件系统
├── shared/                   # 跨 App 共享（仅技术性组件）
│   ├── domain/interfaces.py  # Protocol 定义
│   ├── infrastructure/       # 通用算法实现（如 Kalman 滤波）
│   └── config/secrets.py     # 密钥管理
└── tests/
```

## apps/ vs shared/ 架构边界 ⚠️

### apps/ - 业务模块（Business Modules）

**定义：** 拥有独立业务能力的完整四层架构模块

**必须放在 apps/ 的条件：**
1. ✅ 提供独立的业务能力（如"资产评分"、"回测计算"）
2. ✅ 拥有完整的四层架构（Domain/Application/Infrastructure/Interface）
3. ✅ 包含业务实体和业务规则
4. ✅ 拥有独立的数据模型（Django Model）
5. ✅ 提供 API 接口或 UI 界面

**示例：**
- `apps/asset_analysis/` - 资产评分与推荐（业务能力）
- `apps/regime/` - Regime 判定引擎（业务能力）
- `apps/backtest/` - 回测引擎（业务能力）

### shared/ - 技术性组件（Technical Components）

**定义：** 纯技术性的、无业务语义的通用组件

**只能放在 shared/ 的内容：**
1. ✅ Protocol 接口定义（`RepositoryProtocol`、`FilterProtocol`）
2. ✅ 纯算法实现（`KalmanFilter`、`HPFilter`）
3. ✅ 配置管理（`secrets.py`、`settings_loader.py`）
4. ✅ 工具函数（`date_utils.py`、`validators.py`）

**禁止放在 shared/ 的内容：**
- ❌ 完整的四层架构模块
- ❌ 业务实体（`AssetScore`、`RegimeState`）
- ❌ 业务规则（`RegimeMatcher`、`PolicyMatcher`）
- ❌ Django Model（ORM 模型）
- ❌ API 视图（DRF ViewSet）

### 跨 App 依赖管理

**允许的依赖关系：**
```python
# ✅ 业务模块依赖其他业务模块（明确声明）
from apps.asset_analysis.domain.entities import AssetScore
from apps.regime.application.use_cases import GetCurrentRegimeUseCase

# ✅ 业务模块依赖 shared 组件
from shared.domain.interfaces import RepositoryProtocol
from shared.infrastructure.kalman_filter import LocalLinearTrendFilter
from shared.config.secrets import get_secrets
```

**禁止的依赖关系：**
```python
# ❌ shared 依赖 apps（违反依赖方向）
from apps.regime.domain.entities import RegimeState  # 错误！

# ❌ 循环依赖
# apps/fund → apps/asset_analysis → apps/fund  # 错误！
```

**依赖方向：**
```
apps/fund ─────┐
               ├──→ apps/asset_analysis ──→ shared/
apps/equity ───┘

✅ 正确：业务模块 → 业务模块 → shared
❌ 错误：shared → 业务模块
❌ 错误：循环依赖
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
- `LocalLinearTrendFilter` 实现在 `shared/infrastructure/kalman_filter.py`

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

### 6. 宏观数据单位规范
- 所有宏观数据必须包含单位信息（`unit` 字段）
- 货币类数据必须统一转换为"元"层级存储
- 单位信息存储在数据库 `macro_indicator.unit` 字段中

```python
# 单位转换示例（Domain 层提供）
from apps.macro.domain.entities import normalize_currency_unit

# 将亿元转换为元
value, unit = normalize_currency_unit(1.5, "亿元")
# 结果: (150000000.0, "元")

# 将万亿美元转换为元
value, unit = normalize_currency_unit(3.2, "万亿美元")
# 结果: (32000000000000.0, "元")
```

**支持的货币单位转换：**
- `万元` → `元` (×10,000)
- `亿元` → `元` (×100,000,000)
- `万亿元` → `元` (×1,000,000,000,000)
- `万亿美元` → `元` (×10,000,000,000,000)
- `亿美元` → `元` (×1,000,000,000)
- `百万美元` → `元` (×1,000,000)
- `十亿美元` → `元` (×1,000,000,000)

**非货币类单位：**
- `%` - 百分比（利率、通胀率、增长率等）
- `指数` - 指数类（PMI等）
- `点` - 股票指数点数
- `元/g` - 元/克（黄金期货）
- `元/吨` - 元/吨（铜期货）

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

**项目状态**: 核心功能已完成 (98%)

**Phase 1-7 已完成** ✅:
- ✅ Django 项目骨架
- ✅ Domain 层 Entities
- ✅ Tushare 适配器
- ✅ AKShare 适配器
- ✅ 完整四层架构
- ✅ 模拟盘自动交易
- ✅ 实时价格监控

**Qlib 集成 Phase 1-5 已完成** ✅:
- ✅ Phase 1: Alpha 抽象层 + Cache Provider
- ✅ Phase 2: Qlib 推理异步产出
- ✅ Phase 3: 训练流水线
- ✅ Phase 4: 评估闭环 + 监控
- ✅ Phase 5: 宏观集成 + 全链路联调

**新增智能模块** ✅:
- ✅ Alpha 模块（AI 选股信号，4 层降级）
- ✅ Factor 模块（因子管理）
- ✅ Rotation 模块（板块轮动）
- ✅ Hedge 模块（对冲策略）

**Phase 8: 功能完善** (进行中):
- [x] Audit 模块补全 ✅ (含 Brinson 归因 + 完整测试覆盖)
- [x] Dashboard 图表优化 ✅ (Streamlit 集成)
- [ ] 定时任务监控完善

**架构合规性修复 (2026-02-20)** ✅:
- ✅ 删除 `apps/shared/` 目录，移动到 `shared/infrastructure/htmx/`
- ✅ 修复 `shared/` 对 `apps/` 的违规依赖（4 处）
- ✅ 创建 `core/exceptions.py` 统一异常类
- ✅ 补充 sentiment 模块路由配置
- ✅ 修复 ai_provider 模块架构
- ✅ 新增 31 个单元测试

## 注意事项

1. **不要创建 docker 相关文件**，Phase 1-3 全程本地开发
2. **先写 Domain 层**，再写其他层
3. **先写测试**，再写实现（TDD 友好）
4. 遇到不确定的金融逻辑，参考 `docs/business/AgomSAAF_V3.4.md`
5. 拒绝硬编码，对于资产类型、数据指标代码等，应该写在数据库里，然后有初始化脚本。
6. 每步工作后，更新 docs 下的对应文档
7. **文档索引**: 查看 `docs/INDEX.md` 获取完整文档导航
8. **快速参考**: 查看 `docs/development/quick-reference.md` 获取常用命令和 API 端点
9. **外包工作指南**: 查看 `docs/development/outsourcing-work-guidelines.md` 了解代码规范和质量要求

## 外包团队必读规则

> 技术团队审核发现的问题及改进要求，详见 `docs/development/outsourcing-work-guidelines.md`

### 关键改进点

1. **数据解析健壮性**: 所有从外部获取的数值必须使用 `_safe_float()` 等安全解析函数
2. **错误处理规范**: 使用 `core/exceptions.py` 中的异常类，禁止裸 `Exception`
3. **测试驱动**: 任何修复必须配合测试用例，测试覆盖率要求 Domain ≥ 90%
4. **文档同步**: 代码修改后必须更新相关文档
5. **提交规范**: 单一职责提交，清晰的提交消息

**环境配置**:
- python 虚拟环境为 `agomsaaf`
- PowerShell 脚本必须使用英文

**新增模块说明**:
- `alpha/` - AI 选股模块，与 Qlib 松耦合集成，支持 4 层降级（Qlib → Cache → Simple → ETF）
- `factor/` - 因子管理模块，支持因子计算、分析、IC/ICIR 评估
- `rotation/` - 板块轮动模块，基于 Regime 的板块配置建议
- `hedge/` - 对冲策略模块，支持期货对冲计算和管理