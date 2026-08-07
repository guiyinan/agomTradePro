# AGENTS.md - AgomTradePro 项目开发规则

> 本文件是 AgomTradePro 项目的统一代理指引主文件，适用于 Codex、Claude Code 等代码代理。
> 如存在其他代理说明文件，应以本文件为准，并链接回本文件，避免规则漂移。

## 项目概述

> **最后更新**: 2026-07-09
> **系统版本**: AgomTradePro 0.8.0
> **项目状态**: 生产就绪
> **规模口径**: 机器唯一真源为 `governance/governance_baseline.json`
> （[docs/governance/SYSTEM_BASELINE.md](docs/governance/SYSTEM_BASELINE.md) 只保留叙事索引，不复制动态治理数字）

AgomTradePro (Agom Strategic Asset Allocation Framework) 是个人投研平台，通过 Regime（增长/通胀象限）和 Policy（政策档位）过滤，确保投资者不在错误的宏观环境中下注。

**最新完成** (0.8.0):
- 正式切出 `0.8.0` 版本线并统一版本口径
- 完成 `task_monitor + readiness + VPS` 运维闭环文档收口
- 明确正式生产数据库策略为 PostgreSQL
- 拆分 TUI runtime metadata 中心文件，降低单点膨胀风险

**版本管理**: 参见 [docs/VERSION.md](docs/VERSION.md)

## 技术栈

- Python 3.11+
- Django 5.x
- SQLite（本地开发/单机演示）/ PostgreSQL（正式生产）
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
- **新增/修改代码必须满足 CI 架构护栏**：
  - 不得新增 `from apps.*.infrastructure.models import ...`
  - 不得新增 `from ..infrastructure.models import ...`
  - 不得新增 `from apps.*.infrastructure.repositories import ...`
  - 不得新增 `from ..infrastructure.repositories import ...`
  - 不得新增任何 `.objects.` / `Model.objects` 直接 ORM 访问
  - 不得在函数内部用延迟 import 绕过上述规则
- Application 层如需读写数据库，必须通过以下方式之一：
  - 调用本 App 已暴露的 Application Facade / Query Service / Provider Factory
  - 调用其他 App 已暴露的 Application UseCase / Service
  - 通过构造函数注入 Repository Protocol，测试中用 fake/mock 替换
  - 在 Interface 或 composition root 中组装 concrete repository，再传入 Application

```python
# ❌ 错误：Application 层直接碰 ORM，会触发 Architecture Layer Guard
from apps.equity.infrastructure.models import StockInfoModel

def execute():
    return StockInfoModel.objects.filter(is_active=True)

# ✅ 正确：ORM 查询放在 Infrastructure Repository
class EquityReadRepository:
    def list_active_stocks(self):
        from apps.equity.infrastructure.models import StockInfoModel
        return StockInfoModel._default_manager.filter(is_active=True)

class SomeUseCase:
    def __init__(self, equity_repo: EquityReadRepository):
        self.equity_repo = equity_repo

    def execute(self):
        return self.equity_repo.list_active_stocks()
```

### Infrastructure 层 (`apps/*/infrastructure/`)
```
✅ 允许：Django ORM、Pandas、外部 API 客户端
```
- 包含：models.py（ORM）、repositories.py（数据仓储）、adapters/（API 适配器）
- 实现 Domain 层定义的 Protocol 接口

### Interface 层 (`apps/*/interface/`)
- 包含：views.py（DRF）、serializers.py、admin.py、urls.py
- 只做输入验证和输出格式化，禁止业务逻辑
- 不得新增 `from apps.*.infrastructure...`；Interface 必须调用 Application UseCase / Query Service。

### CI 架构护栏（开发前必须内化）

GitHub Actions 会对本次新增行做结构扫描。以下新增代码会直接失败：

```text
apps/*/domain/      禁止 import django / pandas / numpy / requests
apps/*/application/ 禁止 import *.infrastructure.models / *.infrastructure.repositories，禁止 .objects.
apps/*/interface/   禁止 import *.infrastructure.
```

开发时的判断原则：

- **Domain**：只放业务实体、值对象、纯规则，不知道 Django 存在。
- **Application**：只编排业务流程，不知道 ORM Model 存在。
- **Infrastructure**：负责 ORM、Pandas、外部 API、缓存、文件和网络 I/O。
- **Interface**：负责 HTTP/DRF 输入输出，不直接查数据库、不拼业务规则。
- 如果一个 Application 方法“只是查几张表组装上下文”，也必须把查表部分下沉到 Infrastructure Repository。
- 如果跨 App 需要数据，优先调用对方 Application UseCase；没有合适 UseCase 时，在拥有数据的 App Infrastructure 增加 Repository 方法，再通过依赖注入使用。

## 目录结构

```
AgomTradePro/
├── core/                     # Django 配置
│   ├── settings/
│   │   ├── base.py
│   │   ├── development.py
│   │   └── production.py
│   ├── urls.py
│   └── celery.py
├── apps/                     # 业务模块目录
│   ├── macro/                # 宏观数据采集
│   ├── macro_factor/         # 宏观因子研究与时点治理
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
│   ├── data_center/          # 数据中台
│   ├── config_center/        # 全局运行时配置中心
│   ├── risk_center/          # 风险规则与风险状态中心
│   ├── strategy/             # 策略系统
│   ├── ai_provider/          # AI 服务商管理
│   ├── prompt/               # AI Prompt 模板
│   ├── dashboard/            # 仪表盘
│   ├── filter/               # 筛选器管理
│   ├── alpha/                # AI 选股信号（Qlib 集成）
│   ├── alpha_trigger/        # Alpha 离散触发
│   ├── beta_gate/            # Beta 闸门
│   ├── decision_rhythm/      # 决策频率约束
│   ├── valuation/            # 独立估值引擎（快照、价格带、质量/新鲜度规则）
│   ├── factor/               # 因子管理
│   ├── fixed_income/         # 固收研究与风险分析
│   ├── rotation/             # 板块轮动
│   ├── hedge/                # 对冲策略
│   ├── events/               # 事件系统
│   ├── terminal/             # 终端 CLI（AI 交互界面）
│   ├── agent_runtime/        # Agent 运行时（Terminal AI 后端）
│   ├── ai_capability/        # AI 能力目录（统一路由）
│   ├── pulse/                # Pulse 脉搏层（战术指标聚合与转折预警）
│   ├── share/                # 分享功能
│   ├── task_monitor/         # 任务监控
│   ├── operational_readiness/ # 生产 readiness 取证与验收
│   ├── broker_execution/     # 券商执行与成交回报接入
│   ├── portfolio/            # 投资组合与持仓管理
│   ├── research/             # 投研完整性与可复现性
│   └── setup_wizard/         # 系统初始化向导
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

### 循环依赖与模块归属（新增硬约束）

- 新增代码不得引入 app 级循环依赖；双向依赖会被 CI 视为架构回退
- 跨 App 调用优先使用 Protocol、Facade、Registry、Domain Event，而不是互相 import implementation
- `shared/` 禁止新增 Django Model、业务规则、业务默认配置
- `data_center/` 只负责 provider 协议、注册表、统一查询和标准化存储，不得反向 import 业务模块 infrastructure 实现
- 全局运行时配置归独立配置中心模块（后续 `config_center`），不得继续沉积在 `account`
- 账户身份归 `account`；组合/持仓/交易流水归独立组合模块（后续 `portfolio`）；角色与授权归独立权限模块（后续 `rbac`）

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
- 货币类数据必须统一转换为 canonical storage unit 后再入库，货币类默认是"元"层级
- 运行时真源固定为 `IndicatorCatalog`、`IndicatorUnitRule`、`data_center_macro_fact`
- `data_center_macro_fact.value/unit` 存 canonical 值与单位，`extra.original_unit` 持久化原始单位供审计使用
- 禁止在业务代码里新增单位映射硬编码；新增指标或量纲规则必须走 `data_center` Admin 或 `/api/data-center/indicators/*`

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

### 7. 时区感知 datetime（必须遵守）⚠️

Django 项目启用了 `USE_TZ=True`，所有 datetime 操作必须使用 timezone-aware 版本。

```python
# ❌ 错误：naive datetime（会触发 RuntimeWarning）
from datetime import datetime
now = datetime.now()

# ✅ 正确：timezone-aware datetime
from datetime import datetime, timezone
now = datetime.now(timezone.utc)

# ✅ 或者使用 Django 的 timezone 工具
from django.utils import timezone
now = timezone.now()
```

**适用范围**：
- Domain 层：使用 `datetime.now(timezone.utc)`
- Application/Infrastructure 层：可使用 Django 的 `timezone.now()`
- 所有时间比较、存储、序列化都必须使用 timezone-aware datetime

### 8. 实体接口一致性（跨模块协作）⚠️

编写测试或调用其他模块实体时，必须先查看实体定义，确保参数匹配。

```python
# ❌ 错误：未查看实体定义，使用不存在的参数
StockScore(
    code="000001",
    score=0.8,
    timestamp=datetime.now().isoformat(),  # StockScore 没有 timestamp 字段！
)

# ✅ 正确：查看实体定义后使用正确的参数
StockScore(
    code="000001",
    score=0.8,
    rank=1,
    factors={"momentum": 0.8},  # 必需字段
    source="cache",
    confidence=0.85,  # 必需字段
    asof_date=date.today(),
)
```

**检查清单**：
- [ ] 查看目标实体的完整定义（所有字段和类型）
- [ ] 确认哪些字段是必需的，哪些有默认值
- [ ] 检查字段类型（如 `date` vs `datetime`）
- [ ] 运行测试验证参数正确性

### 9. 事件类型处理规范

处理未知事件类型时，不得映射到业务事件类型，应使用专门的 `UNKNOWN` 类型。

```python
# ❌ 错误：未知类型映射到业务事件
try:
    event_type = EventType(model.event_type)
except ValueError:
    event_type = EventType.REGIME_CHANGED  # 会污染业务数据！

# ✅ 正确：使用 UNKNOWN 类型并记录日志
try:
    event_type = EventType(model.event_type)
except ValueError:
    logger.warning(f"Unknown event type: {model.event_type}")
    event_type = EventType.UNKNOWN
```

### 10. 测试数据构造规范

构造测试数据时，必须符合实体定义的所有约束。

```python
# ✅ 正确的测试数据构造流程
# 1. 先导入并查看实体定义
from apps.alpha.domain.entities import StockScore

# 2. 查看实体字段（通过 IDE 或阅读源码）
# StockScore 需要：code, score, rank, factors, source, confidence

# 3. 构造完整的测试数据
test_score = StockScore(
    code="000001",
    score=0.8,
    rank=1,
    factors={"momentum": 0.8, "value": 0.7},
    source="test",
    confidence=0.85,
)
```

### 11. Celery 批量任务契约（数据新鲜度/数据写入）

凡直接影响数据新鲜度或批量写入的 Celery 任务，必须满足以下约束：

- 在 Celery/Application 入口校验任务参数；HTTP Serializer 不能替代任务边界校验，因为 beat、CLI、测试和其他任务都可直接调用任务
- 业务结果必须发布规范化 `outcome`：`success / partial / noop / blocked / failed`；兼容字段 `success` 不得作为唯一判定依据
- 批量任务必须区分 `requested / succeeded / failed / stored`，且计数单位一致；逐项错误非空时不得无条件返回成功
- 全部项目失败时必须为 `outcome=failed` 且 `success=false`；部分失败必须为 `outcome=partial`；零写入必须为 `outcome=noop` 或 `failed`，并提供原因
- Task Monitor、指标和告警必须读取业务 `outcome`，不得只依赖 Celery 自身的 `SUCCESS/FAILURE`
- 新增或修改关键任务时，必须更新 `governance/celery_task_contracts.json`，并为适用场景登记精确测试：非法输入、全成功、部分失败、全部失败、零产出、业务阻断
- PR 必须运行 `python scripts/check_celery_task_contracts.py`；CI 还会差异扫描新增的 Application `@shared_task`，未登记的新任务直接失败

详细规则：`docs/development/celery-task-contract-guard.md`

### 12. 当前数据新鲜度语义契约

凡接口、SDK、MCP、Terminal 或内部服务使用 `current`、`latest`、`realtime`、`summary` 等语义发布决策数据，必须满足：

- `latest` 只表示排序最新，不自动等于 `fresh/current`；必须基于源观测时间执行 freshness 校验。
- 源 `observed_at / snapshot_at / bar_date / as_of` 不可被请求时间、计算时间或序列化时间覆盖；历史日线不得用 `timezone.now()` 包装成实时行情。
- failover 遇到过期结果必须继续尝试后续数据源；不得把“非空旧值”当成成功命中并截断降级链。
- 面向决策的响应必须发布源观测时间、freshness/reliability 状态、`must_not_use_for_decision` 与稳定阻断原因。
- 新增或修改当前数据面时，必须更新 `governance/current_data_contracts.json`，登记 stale、fresh、fallback 与 observation-preservation 测试证据。
- PR 必须运行 `python scripts/check_current_data_contracts.py`；AST 门禁会拒绝历史价格/元数据的时间戳洗白。

详细规则：`docs/development/data-freshness-contract-guard.md`

### 13. TUI 面向用户设计约束

`/tui/` 是面向用户完成任务的产品界面，不是 API 目录或调试壳。新增或修改 TUI metadata、runtime injection、promotion 脚本时，必须同时满足以下规则：

- 一个 screen 只服务一个主用户任务，必须发布 `user_experience.primary_task` 与 `primary_outcome`
- 用户首屏必须能看到 P0 信息，不得把 Token、Endpoint、Prompt 之类关键接入物料埋在泛型 detail/datagrid 里
- `dashboard_panels` 必须使用 `user_priority`（`p0/p1/p2`）和 `presentation_semantic` 表达信息层级
- Token、Endpoint、Prompt 等可复制工件必须使用专门语义：`copyable_secret`、`endpoint_list`、`multiline_prompt`
- 非 dashboard screen 必须有 `default_action_key`；dashboard screen 必须有可执行的 P0 panel
- 普通用户可见文案不得泄露 `/api/`、`auto.api`、`param.api`、HTTP method、path placeholder 或其他实现细节
- 相关改动必须同步更新 `config/tui/schema/tui_metadata.schema.v3.json`、`apps/terminal/application/tui_metadata.py`、相关 compiler/runtime metadata 注入与测试，禁止只写口头约定

设计标准文档：`docs/development/tui-user-facing-design-standard.md`

### 14. Web → TUI 迁移期页面冻结约束（临时）

在 `docs/plans/web-to-tui-migration-plan-2026-07-25.md` 完成并归档前：

- 新业务主任务默认只允许进入 `/tui/`，不得新增 Classic Django 业务页面。
- `docs/plans/web-to-tui-migration-matrix-2026-07-25.csv` 当前覆盖 196 个模板（含迁移期共用提示组件；M0 初始基线为 195）；新增、删除或移动模板必须同步更新矩阵，并执行 `python scripts/web_template_migration_inventory.py --check`。
- C 档保留流程、错误页、基座、Django Admin 与 TUI shell 如确需新增模板，PR 必须写明用户群、TUI 不适用原因、owner、保留期限，并同步更新 `config/tui/migration/web_template_migration.v1.json` 与计划 §8。
- 既有 Classic 页面只允许缺陷修复、兼容提示和迁移导流，不得借修复扩展新的 Classic 主任务。
- D 档模板必须有 URL/view、Django loader origin、继承/include、邮件/任务和测试引用证据，按独立 M0-D commit 删除。

## 代码风格

- 类型标注：强制，所有生产代码函数必须完整标注参数与返回值
- 禁止裸 `dict` / `list` / `tuple` / `set` / `Callable`；必须声明元素、键值或调用签名类型
- 可空值必须显式使用 `T | None`，不得依赖隐式 Optional
- `Any` 只能停留在 JSON、ORM、动态导入和第三方 API 等边界，并在进入 Domain/Application 前通过 `TypedDict`、dataclass、Protocol、类型守卫或局部 `cast` 收窄
- 禁止模块级或文件级 `ignore_errors`，禁止用宽泛 `type: ignore` 掩盖历史债务
- 新增或修改的 `apps/`、`core/`、`shared/` 生产 Python 文件必须通过增量 mypy 门禁
- 全仓生产代码 mypy 债务按文件和错误码治理，只允许下降；修复后必须同步收紧 `governance/mypy_debt_baseline.json`，不得为接受新增错误而抬高基线
- 格式化：black + isort + ruff
- 测试：Domain 层覆盖率 ≥ 90%
- 文档：所有 public 函数必须有 docstring

### Django Admin 类型规范

- Admin 类必须继承 `shared.infrastructure.django_admin.TypedModelAdmin[ConcreteModel]`，不得使用裸 `admin.ModelAdmin`。
- Admin 表单必须继承 `TypedModelForm[ConcreteModel]`，不得使用裸 `forms.ModelForm`。
- 展示列必须使用 `@admin.display(description=..., ordering=...)`；批量动作必须使用 `@admin.action(description=...)`。
- 禁止通过 `method.short_description = ...`、`method.admin_order_field = ...` 动态挂载元数据。
- Admin handler 必须标注 `HttpRequest`、`QuerySet[ConcreteModel]` 和精确返回类型；审核写入前必须验证用户已认证且主键非空。
- 每个 App 只保留一个真实 Admin 注册入口；禁止在 `infrastructure/admin.py` 与 `interface/admin.py` 重复注册同一组模型。

```bash
# 格式化
black .
isort .
ruff check .

# 类型检查
python scripts/check_mypy_regression.py <changed-production-python-files>
python scripts/check_mypy_debt_ceiling.py

# 仅在历史债务实际下降后刷新全仓基线
python scripts/check_mypy_debt_ceiling.py --write-baseline

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

## Git 工作流规范

> 公开仓库后的默认 Git 规则：`main` 保持稳定展示，日常开发统一使用 `dev/*` 分支。
> 详细说明参见 `docs/GIT_WORKFLOW.md`。

### 1. 分支命名

- 开发分支统一使用 `dev/` 前缀
- 不再使用 `codex/` 作为仓库开发分支命名
- 格式：

```text
dev/<type>-<scope>-<short-description>
```

示例：

```text
dev/feat-terminal-routing
dev/fix-mcp-tool-toggle
dev/refactor-decision-workflow
dev/docs-readme-polish
dev/test-regime-api-contract
```

### 2. main 分支约束

- `main` 只放可展示、可合并、相对稳定的内容
- 非紧急情况不要直接在 `main` 上开发
- README、API、SDK、MCP、大功能修改也应优先走分支后再合并

### 3. 标准开发流程

```bash
git checkout main
git pull origin main
git checkout -b dev/feat-terminal-routing
```

开发完成后：

```bash
git add .
git commit -m "feat: improve terminal command routing"
git push origin dev/feat-terminal-routing
```

再通过 PR 或本地验证后合并回 `main`。

### 3.1 开发节奏与主线切分（新增要求）

- 不得在同一个开发批次中无边界并行推进 `功能实现 + 架构重构 + 部署修复 + 治理文档` 四类高耦合工作；如必须并行，必须在计划文档中显式拆成独立主线。
- 单日允许集中推进一个“大主线”加一个“小收口”，不鼓励同时推进多个高风险主线。
- 以下类型的工作应优先拆分到独立分支阶段或独立 commit 组，而不是混在一次收口中：
  - `terminal / tui`
  - `agent_runtime / sdk / mcp`
  - `deploy / vps / production settings`
  - `governance / inventory / docs standard`
- 当工作已进入“持续 2 个以上提交仍在扩展边界”的状态，必须补充阶段计划文档，写清：
  - 当前阶段目标
  - 已完成项
  - 剩余项
  - 回归测试范围
  - 风险与回滚点

### 4. Commit 规范

提交信息统一采用：

```text
<type>: <summary>
```

推荐类型：

- `feat`
- `fix`
- `refactor`
- `docs`
- `test`
- `chore`
- `perf`

示例：

```text
feat: add terminal routing controls
fix: correct ai capability toggle behavior
docs: add git workflow and commit conventions
test: add contract coverage for regime api
```

### 5. 提交要求

- 一个 commit 尽量只做一件事
- 一个 commit 不得同时混入“功能改动、部署修复、文档治理、测试重写”四种性质中的多种，除非该提交的主题本身就是收口某一主线
- 提交主题使用英文，简短明确
- 提交说明要能回答“这次只解决什么，不解决什么”
- 当改动面跨 `Python + JS + 模板 + 文档 + 配置` 中的 3 类及以上时，应优先拆成多个可验证提交，而不是堆成单个大提交
- 禁止使用无意义提交信息，如：
  - `update`
  - `fix bug`
  - `wip`
  - `misc`
  - `final`

### 6. 固定最小回归包（高风险链路）

- 涉及 `terminal / tui / mcp / sdk / deploy` 任一链路时，提交前应优先运行对应最小回归包，而不是只做人工点测。
- 当前建议固定最小回归包：
  - `pytest tests/unit/test_tui_workbench.py -q`
  - `pytest tests/unit/test_terminal_agent_service.py -q`
  - `pytest sdk/tests/test_sdk/test_client.py -q`
  - `pytest tests/unit/test_internal_ssl_redirect.py -q`
- 若本次改动未运行上述相关测试，必须在总结、PR 或交接说明中明确写出“未验证项”。
- 若某条主线已有更小的局部测试集，可先运行局部集；但进入合并前，仍应补齐对应链路的最小回归包。

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

**项目状态**: `0.8.0` 已正式收口发布，仓库继续迭代

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
- ✅ Terminal 模块（终端 CLI，AI 交互界面）
- ✅ Agent Runtime 模块（Terminal AI 后端）
- ✅ Config Center 模块（全局运行时配置统一入口）
- ✅ Risk Center 模块（风险规则、检查与状态统一入口）
- ✅ Valuation 模块（估值快照、价格带、质量/新鲜度规则与来源选择）
- ✅ Share 模块（决策分享）
- ✅ Task Monitor 模块（任务监控）
- ✅ Pulse 模块（脉搏层，战术指标聚合与转折预警）

**Phase 8: 发布收口与稳定化** ✅:
- [x] Audit 模块补全 ✅ (含 Brinson 归因 + 完整测试覆盖)
- [x] Dashboard 图表优化 ✅ (Streamlit 集成)
- [x] 定时任务监控 / readiness / VPS 验收闭环

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
4. 遇到不确定的金融逻辑，参考 `docs/business/AgomTradePro_V3.4.md`
5. 拒绝硬编码，对于资产类型、数据指标代码等，应该写在数据库里，然后有初始化脚本。
6. 每步工作后，更新 docs 下的对应文档
7. **文档索引**: 查看 `docs/INDEX.md` 获取完整文档导航
8. **快速参考**: 查看 `docs/development/quick-reference.md` 获取常用命令和 API 端点
9. **外包工作指南**: 查看 `docs/development/outsourcing-work-guidelines.md` 了解代码规范和质量要求
10. 大型整改不得长期处于“边开发边扩散”状态；当一条主线已形成独立阶段时，必须补对应 plan / remediation 文档并持续更新完成状态
11. 做用户面改动时，不要只验证“代码能跑”，还要验证“用户能完成主任务”；尤其是 `TUI / terminal workbench / MCP self-service` 一类页面
12. 对高风险链路优先采用“功能推进日”和“治理收口日”分离的节奏，减少在同一天内同时修改运行面、接入面和部署面的耦合
13. 任何涉及 `terminal / tui / mcp / sdk / deploy` 的改动，在结束前都要明确列出：
    - 已完成项
    - 未完成项
    - 已验证测试
    - 未验证风险
14. **依赖唯一真源**：运行与开发依赖只在 `pyproject.toml` 声明；`requirements-prod.txt`、`requirements-dev.txt` 是生成投影，禁止手工编辑，使用 `python scripts/sync_dependency_projections.py` 更新

## 外包团队必读规则

> 技术团队审核发现的问题及改进要求，详见 `docs/development/outsourcing-work-guidelines.md`
> 甲方验收整改报告，详见 `docs/development/rectification-2026-02-23.md`

### 关键改进点

1. **数据解析健壮性**: 所有从外部获取的数值统一使用 `from shared.numeric import safe_float`；缺失值默认返回 `None`，需要业务默认值、去格式字符或缩放时显式传入 `default`、`strip_chars`、`scale`
2. **错误处理规范**: 使用 `core/exceptions.py` 中的异常类，禁止裸 `Exception`
3. **测试驱动**: 任何修复必须配合测试用例，测试覆盖率要求 Domain ≥ 90%
4. **文档同步**: 代码修改后必须更新相关文档
5. **提交规范**: 单一职责提交，清晰的提交消息
6. **API 路由分离**: API 路由放在 `api_urls.py`，页面路由放在 `urls.py`，不得混用
7. **API 契约测试**: 每个 API 端点必须有契约测试，验证 Content-Type 和状态码
8. **成对操作一致性**: CRUD 操作的参数签名必须保持一致（如 Delete 支持 event_id，Update 也必须支持）
9. **修复完整性**: 修复问题时必须检查所有相关场景，不可只修复"眼前"问题
10. **路由重命名同步**: 修改路由名时必须同步更新模板、JS、Python 中的所有引用，并添加模板渲染测试
11. **时区感知 datetime**: 必须使用 `datetime.now(timezone.utc)` 或 Django 的 `timezone.now()`，禁止使用 `datetime.now()`
12. **实体参数验证**: 构造实体或编写测试时，必须先查看实体定义，确保参数名和类型完全匹配
13. **事件类型处理**: 未知事件类型必须使用 `UNKNOWN` 类型，不得映射到业务事件类型
14. **主线切分**: 不得把功能实现、部署修复、治理文档、测试重写无边界混在同一批提交里，必须按主线拆分
15. **回归显式化**: 涉及 `terminal / tui / mcp / sdk / deploy` 时，必须说明运行了哪些测试，未跑哪些测试
16. **收口定义**: 进入整改阶段的工作必须定义完成标准，不得长期停留在“还差一点”的模糊状态

**环境配置**:
- python 虚拟环境为 `agomtradepro`
- PowerShell 脚本必须使用英文

**新增模块说明**:
- `alpha/` - AI 选股模块，与 Qlib 松耦合集成，支持 4 层降级（Qlib → Cache → Simple → ETF）
- `factor/` - 因子管理模块，支持因子计算、分析、IC/ICIR 评估
- `rotation/` - 板块轮动模块，基于 Regime 的板块配置建议
- `hedge/` - 对冲策略模块，支持期货对冲计算和管理
- `terminal/` - 终端 CLI 模块，提供终端风格的 AI 交互界面，支持可配置命令系统
- `agent_runtime/` - Agent 运行时模块，Terminal AI 后端，支持任务编排和 Facade 模式
- `ai_capability/` - AI 能力目录模块，系统级 AI 能力目录与统一路由
- `data_center/` - 数据中台，统一外部数据源接入、标准化、同步与查询
- `valuation/` - 独立估值引擎；R3-lite 阶段由 decision_rhythm 兼容承载现有 ORM 表与 `/api/valuation/**` 路径
- `share/` - 分享功能模块，支持决策分享
- `task_monitor/` - 任务监控模块，Celery 任务状态追踪
- `operational_readiness/` - 生产 readiness 证据、连续窗口验收与调度运行状态
- `broker_execution/` - 券商执行模块，负责订单提交、状态同步与成交回报
- `portfolio/` - 投资组合模块，负责组合、持仓、交易流水与组合读模型
- `research/` - 投研治理模块，负责研究证据、运行快照和结果可复现性
- `setup_wizard/` - 系统初始化向导模块，首次安装引导配置管理员密码、AI API、数据源

