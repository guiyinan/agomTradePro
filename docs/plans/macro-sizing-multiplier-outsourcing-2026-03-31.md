# 宏观感知仓位系数模块 外包实施任务书

> 生效日期：2026-03-31
> 文档类型：外包实施规格 + 开发任务书 + 验收清单
> 适用团队：外包开发团队、外包测试团队、内部技术验收团队
> 适用范围：`apps/account/` domain 层新增、interface 层新增 API 端点
> 依赖模块（只读调用，不得修改）：`apps/regime/`、`apps/pulse/`

---

## 1. 背景与目标

### 1.1 问题陈述

当前系统已有 Regime 判断（四象限宏观环境）、Pulse 脉搏（战术层强弱 + 转折预警）、Beta Gate（资产可见性过滤）、PositionService（单笔仓位计算），但各模块之间缺少一个桥接层：

> 系统知道"现在宏观信号很弱"，却没有自动告诉用户"所以这笔单的建议仓位应该只开到平时的 50%"。

具体三个缺口：

| 缺口 | 现状 | 目标 |
|------|------|------|
| 仓位大小不感知宏观 | `PositionService` 用固定比例，不随 Regime 置信度 / Pulse 状态动态调整 | 输出动态系数供调用方使用 |
| 实盘账户无运行中回撤保护 | Backtest/Hedge 有 max_drawdown，但 live PortfolioSnapshot 没有"已回撤多少、还能开多大"的逻辑 | 计算当前回撤并纳入系数 |
| Pulse 预警无行动路径 | `transition_warning=True` 只是布尔值，用户不知道该把仓位砍多少 | 预警直接映射为系数折减 |

### 1.2 目标

新增一个**宏观感知仓位系数（MacroSizingMultiplier）** 模块：
- 读取 Regime 置信度 + Pulse 脉搏 + 实时组合回撤
- 计算 `0.0–1.0` 之间的系数
- 提供 REST API 端点供前端/外部调用
- **所有阈值参数可配置，存储在数据库，不硬编码**

### 1.3 本期明确不做

1. 不自动修改仓位（系统定位是决策辅助，最终操作由用户完成）
2. 不新增 Dashboard 前端 UI（API 先行，UI 后续可选）
3. 不修改现有 `PositionService`、`SizingEngine`、`BetaGate`、`PulseSnapshot` 任何代码
4. 不新增 Celery 异步任务
5. 不引入新的外部依赖

---

## 2. 架构设计

### 2.1 模块位置

本次所有新增代码位于 `apps/account/`，严格遵循四层架构：

```
apps/account/
├── domain/
│   ├── services.py          ← [追加] MacroSizingContext / SizingMultiplierResult / 两个纯函数
│   └── entities.py          ← [追加] MacroSizingConfig（值对象，不含 ORM）
├── infrastructure/
│   ├── models.py            ← [追加] MacroSizingConfigModel（ORM）
│   └── repositories.py      ← [追加] MacroSizingConfigRepository
├── application/
│   └── use_cases.py         ← [追加] GetSizingContextUseCase
└── interface/
    ├── sizing_views.py      ← [新建] SizingContextView
    └── api_urls.py          ← [追加 1 行] 注册路由
```

### 2.2 数据流

```
HTTP GET /api/account/sizing-context/
          │
          ▼
GetSizingContextUseCase
  ├── resolve_current_regime()        → regime_confidence, regime_name
  │     (apps/regime/application/current_regime.py，只读调用)
  ├── GetLatestPulseUseCase()         → pulse_composite, pulse_warning
  │     (apps/pulse/application/use_cases.py，只读调用)
  ├── MacroSizingConfigRepository     → MacroSizingConfig（阈值配置）
  ├── PortfolioSnapshotRepository     → value_history（历史总价值序列）
  │     (apps/account/infrastructure/repositories.py，已有，只读调用)
  │
  ▼
calculate_portfolio_drawdown(value_history) → drawdown_pct
calculate_macro_multiplier(context, config) → SizingMultiplierResult
          │
          ▼
JSON Response
```

### 2.3 依赖方向约束

```
apps/account 依赖 apps/regime   ✅ 允许（业务模块间依赖）
apps/account 依赖 apps/pulse    ✅ 允许（业务模块间依赖）
apps/regime / apps/pulse        ❌ 不得反向依赖 apps/account
```

---

## 3. Domain 层规格

### 3.1 `MacroSizingConfig`（值对象）

**文件**：`apps/account/domain/entities.py`（追加，不改现有代码）

```python
from dataclasses import dataclass, field


@dataclass(frozen=True)
class RegimeTier:
    """Regime 置信度档位配置（单档）"""
    min_confidence: float   # 该档最低置信度（含）
    factor: float           # 对应系数乘子 0.0–1.0


@dataclass(frozen=True)
class PulseTier:
    """Pulse 脉搏档位配置（单档）"""
    min_composite: float    # composite_score 下限（含）
    max_composite: float    # composite_score 上限（不含，最高档可设 float('inf')）
    factor: float           # 对应系数乘子 0.0–1.0


@dataclass(frozen=True)
class DrawdownTier:
    """回撤档位配置（单档）"""
    min_drawdown: float     # 该档最低回撤（含）0.0–1.0
    factor: float           # 对应系数乘子 0.0–1.0


@dataclass(frozen=True)
class MacroSizingConfig:
    """
    宏观感知仓位系数配置（值对象）。
    所有阈值参数由数据库持久化，通过 MacroSizingConfigRepository 注入。
    Domain 层不得直接访问 ORM，仅接受此值对象。

    字段说明：
    - regime_tiers: Regime 置信度档位列表，按 min_confidence 降序排列，
                    匹配第一个 confidence >= min_confidence 的档位
    - pulse_tiers: Pulse 复合分档位列表，按 min_composite 降序排列，
                   transition_warning=True 时优先使用 warning_factor，忽略 pulse_tiers
    - warning_factor: Pulse 转折预警时的系数覆盖值（优先于 pulse_tiers）
    - drawdown_tiers: 回撤档位列表，按 min_drawdown 降序排列
    - version: 配置版本号，用于日志追踪
    """
    regime_tiers: list[RegimeTier]
    pulse_tiers: list[PulseTier]
    warning_factor: float
    drawdown_tiers: list[DrawdownTier]
    version: int = 1

    def get_regime_factor(self, confidence: float) -> float:
        """查找 confidence 对应的系数，无匹配档位时返回最小档的 factor。"""
        for tier in sorted(self.regime_tiers, key=lambda t: t.min_confidence, reverse=True):
            if confidence >= tier.min_confidence:
                return tier.factor
        return self.regime_tiers[-1].factor if self.regime_tiers else 1.0

    def get_pulse_factor(self, composite: float, warning: bool) -> float:
        """
        若 warning=True 返回 warning_factor（覆盖 pulse_tiers）；
        否则按 composite_score 查找对应档位。
        """
        if warning:
            return self.warning_factor
        for tier in sorted(self.pulse_tiers, key=lambda t: t.min_composite, reverse=True):
            if composite >= tier.min_composite:
                return tier.factor
        return self.pulse_tiers[-1].factor if self.pulse_tiers else 1.0

    def get_drawdown_factor(self, drawdown_pct: float) -> float:
        """按回撤比例查找对应系数。回撤越大系数越小，超过最高档返回 0.0。"""
        for tier in sorted(self.drawdown_tiers, key=lambda t: t.min_drawdown, reverse=True):
            if drawdown_pct >= tier.min_drawdown:
                return tier.factor
        return 1.0
```

### 3.2 `MacroSizingContext` 和计算函数

**文件**：`apps/account/domain/services.py`（追加，不改现有代码）

```python
from dataclasses import dataclass
from apps.account.domain.entities import MacroSizingConfig


@dataclass(frozen=True)
class MacroSizingContext:
    """
    宏观感知仓位系数计算所需的输入数据。
    由 Application 层组装后传入 Domain 层，Domain 层不做 I/O。
    """
    regime_confidence: float       # 0.0–1.0，来自 Regime 模块
    regime_name: str               # 如 "Recovery"，仅用于日志/响应展示
    pulse_composite: float         # -1.0 到 +1.0，来自 Pulse 模块
    pulse_warning: bool            # 是否有象限转折预警
    portfolio_drawdown_pct: float  # 0.0–1.0，当前从历史峰值的回撤比例


@dataclass(frozen=True)
class SizingMultiplierResult:
    """宏观感知仓位系数计算结果。"""
    multiplier: float          # 最终系数，0.0–1.0（0.0 = 暂停新仓，1.0 = 正常开仓）
    regime_factor: float       # Regime 置信度贡献系数
    pulse_factor: float        # Pulse 脉搏贡献系数
    drawdown_factor: float     # 回撤保护贡献系数
    action_hint: str           # "正常开仓" / "减仓操作" / "缩半开仓" / "暂停新仓"
    reasoning: str             # 中文解释（拼接三因子说明）
    config_version: int        # 所用配置的版本号，便于追踪


def calculate_macro_multiplier(
    ctx: MacroSizingContext,
    config: MacroSizingConfig,
) -> SizingMultiplierResult:
    """
    根据宏观环境三因子计算仓位系数。
    三因子相乘：最终系数 = regime_factor × pulse_factor × drawdown_factor。

    业务规则：
    - 三因子均可独立配置，修改阈值不需要改代码
    - 所有因子值来自 MacroSizingConfig，不含任何硬编码数字

    Args:
        ctx: 当前宏观状态快照
        config: 从数据库读取的阈值配置

    Returns:
        SizingMultiplierResult
    """
    regime_factor = config.get_regime_factor(ctx.regime_confidence)
    pulse_factor = config.get_pulse_factor(ctx.pulse_composite, ctx.pulse_warning)
    drawdown_factor = config.get_drawdown_factor(ctx.portfolio_drawdown_pct)

    multiplier = round(regime_factor * pulse_factor * drawdown_factor, 4)

    regime_desc = _describe_regime_factor(regime_factor, ctx.regime_confidence)
    pulse_desc = _describe_pulse_factor(pulse_factor, ctx.pulse_composite, ctx.pulse_warning)
    drawdown_desc = _describe_drawdown_factor(drawdown_factor, ctx.portfolio_drawdown_pct)
    reasoning = "；".join([regime_desc, pulse_desc, drawdown_desc])

    return SizingMultiplierResult(
        multiplier=multiplier,
        regime_factor=regime_factor,
        pulse_factor=pulse_factor,
        drawdown_factor=drawdown_factor,
        action_hint=_derive_action_hint(multiplier),
        reasoning=reasoning,
        config_version=config.version,
    )


def calculate_portfolio_drawdown(value_history: list[float]) -> float:
    """
    从组合历史价值序列计算当前从峰值的回撤比例。
    参考 apps/backtest/domain/services.py::_calculate_max_drawdown 算法，
    在 account domain 层独立实现（不跨 app 调用）。

    Args:
        value_history: 按时间升序排列的组合总价值列表（最新值在末尾）
                       少于 2 个数据点时返回 0.0

    Returns:
        当前从峰值的回撤比例 0.0–1.0（0.0 = 未回撤，0.10 = 已回撤 10%）
    """
    if len(value_history) < 2:
        return 0.0
    peak = max(value_history)
    current = value_history[-1]
    if peak <= 0:
        return 0.0
    return max(0.0, (peak - current) / peak)


# ── 内部辅助函数（不对外暴露）──────────────────────────────────────────────

def _describe_regime_factor(factor: float, confidence: float) -> str:
    return f"Regime置信度{confidence:.0%}（系数{factor:.2f}）"


def _describe_pulse_factor(factor: float, composite: float, warning: bool) -> str:
    if warning:
        return f"Pulse转折预警激活（系数{factor:.2f}）"
    return f"Pulse综合分{composite:+.2f}（系数{factor:.2f}）"


def _describe_drawdown_factor(factor: float, drawdown: float) -> str:
    if factor == 0.0:
        return f"组合回撤{drawdown:.1%}已超上限，暂停新仓"
    return f"组合回撤{drawdown:.1%}（系数{factor:.2f}）"


def _derive_action_hint(multiplier: float) -> str:
    if multiplier == 0.0:
        return "暂停新仓"
    elif multiplier < 0.5:
        return "缩半开仓"
    elif multiplier < 0.85:
        return "减仓操作"
    else:
        return "正常开仓"
```

---

## 4. Infrastructure 层规格

### 4.1 ORM 模型

**文件**：`apps/account/infrastructure/models.py`（追加，不改现有 Model）

```python
from django.db import models


class MacroSizingConfigModel(models.Model):
    """
    宏观感知仓位系数配置持久化模型。
    支持多版本配置，is_active=True 且 version 最大的一条为生效配置。

    字段说明：
    - regime_tiers_json:    JSON 数组，每项为 {"min_confidence": float, "factor": float}
    - pulse_tiers_json:     JSON 数组，每项为 {"min_composite": float, "max_composite": float, "factor": float}
    - warning_factor:       Pulse 转折预警时的系数覆盖值（优先于 pulse_tiers）
    - drawdown_tiers_json:  JSON 数组，每项为 {"min_drawdown": float, "factor": float}
    - version:              整数版本号，新建时应手动递增
    - is_active:            是否参与生效配置查询
    - description:          人类可读备注
    """
    regime_tiers_json = models.JSONField(
        help_text='格式：[{"min_confidence": 0.6, "factor": 1.0}, ...]，按 min_confidence 降序'
    )
    pulse_tiers_json = models.JSONField(
        help_text='格式：[{"min_composite": 0.3, "max_composite": 99, "factor": 1.0}, ...]'
    )
    warning_factor = models.FloatField(
        default=0.5,
        help_text="Pulse 转折预警时的系数覆盖值（0.0–1.0），优先于 pulse_tiers"
    )
    drawdown_tiers_json = models.JSONField(
        help_text='格式：[{"min_drawdown": 0.15, "factor": 0.0}, ...]，按 min_drawdown 降序'
    )
    version = models.PositiveIntegerField(default=1)
    is_active = models.BooleanField(default=True)
    description = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "account"
        ordering = ["-version"]
        verbose_name = "宏观仓位系数配置"
        verbose_name_plural = "宏观仓位系数配置"

    def __str__(self) -> str:
        return f"MacroSizingConfig v{self.version} (active={self.is_active})"
```

### 4.2 默认初始配置（数据迁移）

新建 `apps/account/migrations/XXXX_macro_sizing_config.py`，通过 `RunPython` 写入以下默认值：

```python
DEFAULT_CONFIG = {
    "regime_tiers_json": [
        {"min_confidence": 0.6, "factor": 1.0},
        {"min_confidence": 0.4, "factor": 0.8},
        {"min_confidence": 0.0, "factor": 0.5},
    ],
    "pulse_tiers_json": [
        {"min_composite":  0.3, "max_composite":  99, "factor": 1.00},
        {"min_composite": -0.3, "max_composite": 0.3, "factor": 0.85},
        {"min_composite": -99,  "max_composite":-0.3, "factor": 0.70},
    ],
    "warning_factor": 0.5,
    "drawdown_tiers_json": [
        {"min_drawdown": 0.15, "factor": 0.0},
        {"min_drawdown": 0.10, "factor": 0.5},
        {"min_drawdown": 0.05, "factor": 0.8},
        {"min_drawdown": 0.00, "factor": 1.0},
    ],
    "version": 1,
    "is_active": True,
    "description": "默认配置（系统初始化自动写入）",
}
```

> **说明**：默认档位对应的业务含义（以默认值为例，可在 Admin 中调参）：
>
> | 因子 | 档位条件 | 系数 | 含义 |
> |------|---------|------|------|
> | Regime 置信度 | ≥ 60% | 1.00 | 信号清晰，正常开仓 |
> | Regime 置信度 | 40–60% | 0.80 | 信号偏弱，缩 20% |
> | Regime 置信度 | < 40% | 0.50 | 信号模糊，缩半 |
> | Pulse 脉搏 | composite > 0.3 | 1.00 | 象限内强势 |
> | Pulse 脉搏 | -0.3 到 0.3 | 0.85 | 中性 |
> | Pulse 脉搏 | composite < -0.3 | 0.70 | 象限内走弱 |
> | Pulse 转折预警 | warning=True | 0.50 | 覆盖上述档位 |
> | 组合回撤 | < 5% | 1.00 | 正常 |
> | 组合回撤 | 5–10% | 0.80 | 警戒区 |
> | 组合回撤 | 10–15% | 0.50 | 危险区 |
> | 组合回撤 | > 15% | 0.00 | 停止新仓 |

### 4.3 Repository

**文件**：`apps/account/infrastructure/repositories.py`（追加）

```python
class MacroSizingConfigRepository:
    """
    读取宏观仓位系数配置。只提供读操作，写操作通过 Admin 完成。

    get_active_config() 查询条件：is_active=True，按 version 降序取第一条。
    若数据库无配置，返回内置保守默认值（不报错，降级处理）。
    """

    def get_active_config(self) -> "MacroSizingConfig":
        """返回当前生效的 MacroSizingConfig 值对象。"""
        ...  # 实现者负责填写，需将 ORM Model 转换为 Domain 值对象
```

---

## 5. Application 层规格

**文件**：`apps/account/application/use_cases.py`（追加）

```python
class GetSizingContextUseCase:
    """
    获取当前宏观仓位系数的用例。

    依赖注入（__init__ 参数）：
    - regime_resolver:  Callable[[], CurrentRegimeResult]
                        注入 resolve_current_regime（来自 apps/regime/application/current_regime.py）
    - pulse_use_case:   GetLatestPulseUseCase（来自 apps/pulse/application/use_cases.py）
    - portfolio_repo:   读取 PortfolioSnapshot 历史的 Repository（已有）
    - config_repo:      MacroSizingConfigRepository

    execute() 流程：
    1. 调用 regime_resolver()：获取 regime_confidence, regime_name
       若失败：regime_confidence=0.0，warnings 追加 "regime_unavailable"
    2. 调用 pulse_use_case.execute()：获取 pulse_composite, pulse_warning
       若失败：pulse_composite=0.0, pulse_warning=False，warnings 追加 "pulse_unavailable"
    3. 调用 portfolio_repo 获取最近 90 天组合总价值历史
       若无数据：drawdown_pct=0.0
    4. calculate_portfolio_drawdown(value_history) → drawdown_pct
    5. config_repo.get_active_config() → MacroSizingConfig
    6. 构造 MacroSizingContext，调用 calculate_macro_multiplier()
    7. 返回包含结果 + warnings 的 DTO

    异常处理规则：
    - 任意外部调用失败时 catch 异常，记录 logger.warning，使用降级值继续
    - 不允许因单一依赖失败而抛出 HTTP 500
    - 所有 datetime 使用 timezone-aware（timezone.now() 或 datetime.now(timezone.utc)）
    """
```

---

## 6. Interface 层规格

### 6.1 路由注册

**文件**：`apps/account/interface/api_urls.py`（追加 1 行）

```python
path("sizing-context/", sizing_views.SizingContextView.as_view(), name="sizing-context"),
```

完整路由：`GET /api/account/sizing-context/`

注意：路由必须注册到 `api_urls.py`，不得放入 `urls.py`（页面路由文件）。

### 6.2 权限

登录认证（与其他 account API 一致），只读，无写操作。

### 6.3 正常响应（HTTP 200）

```json
{
  "multiplier": 0.72,
  "action_hint": "缩半开仓",
  "reasoning": "Regime置信度52%（系数0.80）；Pulse转折预警激活（系数0.50）；组合回撤3.0%（系数1.00）",
  "components": {
    "regime_factor": 0.80,
    "pulse_factor": 0.50,
    "drawdown_factor": 1.00
  },
  "context": {
    "regime": "Recovery",
    "regime_confidence": 0.52,
    "pulse_composite": 0.12,
    "pulse_warning": true,
    "portfolio_drawdown_pct": 0.03
  },
  "config_version": 1,
  "warnings": [],
  "calculated_at": "2026-03-31T10:00:00+08:00"
}
```

### 6.4 降级响应（HTTP 200，部分数据不可用）

```json
{
  "multiplier": 0.5,
  "action_hint": "缩半开仓",
  "reasoning": "Regime数据不可用，使用最保守置信度（系数0.50）；...",
  "components": { ... },
  "context": { ... },
  "config_version": 1,
  "warnings": ["regime_unavailable"],
  "calculated_at": "2026-03-31T10:00:00+08:00"
}
```

### 6.5 视图实现要求

**文件**：`apps/account/interface/sizing_views.py`（新建）

```python
class SizingContextView(APIView):
    """
    GET /api/account/sizing-context/

    Interface 层只做：鉴权 → 调用 use_case → 序列化 → 返回。
    禁止在此层编写业务逻辑。
    """
```

---

## 7. Admin 配置管理

**文件**：`apps/account/infrastructure/admin.py`（追加）

要求：
- list_display 包含：version, is_active, warning_factor, description, created_at
- JSON 字段使用 `readonly_fields` 展示（不允许直接在 Admin 内联编辑 JSON）
- 支持在 Admin 中新建配置版本；不得直接覆盖旧版本
- `is_active` 字段变更需记录到 `audit.OperationLog`（调用已有审计机制，优先级低，可延后）

---

## 8. 测试规格

### 8.1 单元测试

**文件**：`tests/unit/test_account_macro_sizing.py`（新建）

测试框架：pytest，**纯 Python，不依赖 Django ORM**。

#### `calculate_macro_multiplier()` 测试用例（基于默认配置）

| 场景 | regime_confidence | pulse_composite | pulse_warning | drawdown_pct | 期望 multiplier | 期望 action_hint |
|------|:-----------------:|:---------------:|:-------------:|:------------:|:--------------:|:---------------:|
| 全优 | 0.8 | 0.5 | False | 0.02 | 1.0000 | 正常开仓 |
| 置信度低 | 0.3 | 0.5 | False | 0.0 | 0.5000 | 缩半开仓 |
| Pulse 预警 | 0.7 | 0.5 | True | 0.0 | 0.5000 | 缩半开仓 |
| 置信度低 + 预警 | 0.3 | 0.5 | True | 0.0 | 0.2500 | 缩半开仓 |
| 回撤超限 | 0.9 | 0.9 | False | 0.16 | 0.0000 | 暂停新仓 |
| 回撤警戒区 | 0.7 | 0.5 | False | 0.08 | 0.8000 | 正常开仓 |
| 三因子最差 | 0.0 | -0.5 | True | 0.20 | 0.0000 | 暂停新仓 |
| Pulse 弱 | 0.7 | -0.5 | False | 0.0 | 0.7000 | 减仓操作 |

> 测试需构造对应 `MacroSizingConfig` 实例，不从数据库读取。

#### `calculate_portfolio_drawdown()` 测试用例

```python
# 正常回撤：峰值 100，当前 90，回撤 10%
assert calculate_portfolio_drawdown([80, 100, 90]) == pytest.approx(0.10)

# 持续上涨：无回撤
assert calculate_portfolio_drawdown([80, 90, 100]) == 0.0

# 空序列 / 单点 → 返回 0.0
assert calculate_portfolio_drawdown([]) == 0.0
assert calculate_portfolio_drawdown([100]) == 0.0

# 当前在历史最高点
assert calculate_portfolio_drawdown([80, 90, 100]) == 0.0

# 峰值为 0 的边界（不得除以零）
assert calculate_portfolio_drawdown([0, 0, 0]) == 0.0
```

#### `MacroSizingConfig` 档位查找测试

```python
config = build_default_config()  # 用 DEFAULT_CONFIG 构造

# get_regime_factor
assert config.get_regime_factor(0.7) == 1.0
assert config.get_regime_factor(0.5) == 0.8
assert config.get_regime_factor(0.2) == 0.5

# get_pulse_factor：warning 覆盖 tiers
assert config.get_pulse_factor(composite=0.9, warning=True) == config.warning_factor
assert config.get_pulse_factor(composite=0.9, warning=False) == 1.0

# get_drawdown_factor：超过最高档返回 0.0
assert config.get_drawdown_factor(0.20) == 0.0
assert config.get_drawdown_factor(0.00) == 1.0
```

### 8.2 集成测试

**文件**：`tests/integration/test_sizing_context_api.py`（新建）

- 未登录请求 → 返回 401/403
- 正常请求 → 返回 200，`multiplier` 在 `[0.0, 1.0]` 范围内
- 响应包含字段：`multiplier`, `action_hint`, `reasoning`, `components`, `context`, `config_version`, `warnings`, `calculated_at`
- `calculated_at` 必须是 timezone-aware 的 ISO 8601 格式

---

## 9. 改动文件清单

### 需新建或追加的文件

| 文件路径 | 操作 | 说明 |
|----------|------|------|
| `apps/account/domain/entities.py` | 追加 | RegimeTier / PulseTier / DrawdownTier / MacroSizingConfig |
| `apps/account/domain/services.py` | 追加 | MacroSizingContext / SizingMultiplierResult / calculate_macro_multiplier / calculate_portfolio_drawdown |
| `apps/account/infrastructure/models.py` | 追加 | MacroSizingConfigModel |
| `apps/account/infrastructure/repositories.py` | 追加 | MacroSizingConfigRepository |
| `apps/account/infrastructure/admin.py` | 追加 | MacroSizingConfigModel Admin 注册 |
| `apps/account/application/use_cases.py` | 追加 | GetSizingContextUseCase |
| `apps/account/interface/sizing_views.py` | 新建 | SizingContextView |
| `apps/account/interface/api_urls.py` | 追加 1 行 | 注册路由 |
| `apps/account/migrations/XXXX_macro_sizing_config.py` | 新建 | ORM 迁移 + 默认数据 RunPython |
| `tests/unit/test_account_macro_sizing.py` | 新建 | 单元测试 |
| `tests/integration/test_sizing_context_api.py` | 新建 | 集成测试 |

### 禁止修改的文件

| 文件路径 | 原因 |
|----------|------|
| `apps/regime/application/current_regime.py` | 只读调用，不得修改 |
| `apps/pulse/application/use_cases.py` | 只读调用，不得修改 |
| `apps/account/domain/services.py` 现有代码 | 只在文件末尾追加，不改现有函数 |
| `apps/account/domain/entities.py` 现有代码 | 只在文件末尾追加，不改现有类 |
| `apps/backtest/domain/services.py` | 参考算法逻辑，不跨 app 直接调用 |
| `apps/strategy/domain/services.py` | 不修改 SizingEngine |

---

## 10. 复用的现有能力（勿重复实现）

| 现有实现 | 文件位置 | 本次如何复用 |
|----------|----------|-------------|
| `resolve_current_regime()` | `apps/regime/application/current_regime.py` | Application 层注入，获取 regime_confidence + regime_name |
| `GetLatestPulseUseCase` | `apps/pulse/application/use_cases.py` | Application 层注入，获取 pulse_composite + pulse_warning |
| `PortfolioSnapshotRepository` | `apps/account/infrastructure/repositories.py` | 查询最近 90 天总价值历史（已有方法，只读调用） |
| 回撤计算逻辑 | `apps/backtest/domain/services.py` 中的 `_calculate_max_drawdown` | 参考算法，在 account domain 层独立重写，不跨 app 调用 |
| `core/exceptions.py` 异常类 | `core/exceptions.py` | 所有异常使用统一异常类，禁止裸 `Exception` |
| timezone-aware datetime 规范 | `AGENTS.md §7` | 所有 datetime 必须 aware |

---

## 11. 验收清单

外包团队提交 PR 前必须自查：

### Domain 层
- [ ] `MacroSizingConfig` 是 `@dataclass(frozen=True)`，无任何 Django/ORM 导入
- [ ] `calculate_macro_multiplier()` 无硬编码数字，所有阈值来自 `MacroSizingConfig` 方法
- [ ] `calculate_portfolio_drawdown()` 可处理空列表、单元素列表、全零列表
- [ ] 所有新增 dataclass 字段有完整类型标注
- [ ] 所有 public 函数有 docstring

### Infrastructure 层
- [ ] `python manage.py migrate account` 可正向执行无报错
- [ ] 迁移包含默认配置数据写入（`RunPython`）
- [ ] `MacroSizingConfigRepository.get_active_config()` 在数据库无数据时有降级返回（不抛异常）

### Application 层
- [ ] `GetSizingContextUseCase` 任意单一外部依赖失败时不抛出 HTTP 500
- [ ] 降级情况下 `warnings` 字段有对应标注
- [ ] 所有 datetime 使用 timezone-aware

### Interface 层
- [ ] `sizing_views.py` 无业务逻辑（只做鉴权 + 调用 use_case + 序列化）
- [ ] 路由在 `api_urls.py` 而非 `urls.py`
- [ ] 响应字段与第 6.3 节格式完全一致

### 测试
- [ ] `pytest tests/unit/test_account_macro_sizing.py -v` 全部通过，无 Django 依赖
- [ ] `pytest tests/integration/test_sizing_context_api.py -v` 全部通过
- [ ] Domain 层测试覆盖率 ≥ 90%（`pytest --cov=apps/account/domain`）

### 代码规范（参考 `docs/development/outsourcing-work-guidelines.md`）
- [ ] 无裸 `Exception`，使用 `core/exceptions.py` 中的异常类
- [ ] black + isort + ruff 格式化通过
- [ ] Commit 信息符合规范，例：`feat: add macro sizing multiplier domain service`

---

## 12. 不在本期范围

| 功能 | 理由 |
|------|------|
| Dashboard 前端卡片 | UI 后续可选，API 先行 |
| 自动调仓执行 | 系统定位是决策辅助，不自动下单 |
| 仓位优化器（Kelly / 风险平价） | 复杂度较高，下一期评估 |
| MacroSizingConfig 前端编辑页 | Django Admin 已足够，不新建前端页面 |
| Pulse 指标数据源配置 | 已有 PulseConfig，不重复 |
