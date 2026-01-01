# AgomSAAF 投顾系统诊断报告与修复方案

> **诊断日期**：2026-01-01
> **系统版本**：AgomSAAF V3.4
> **诊断范围**：全系统数据流、硬编码、架构规范
> **整体评分**：5.5/10

---

## 执行摘要

### 问题概览

AgomSAAF 投顾系统在架构设计上遵循了四层分层架构（Domain-Application-Infrastructure-Interface），整体框架完整。但在实际实现中，**存在 7 个数据流断点、60+ 处硬编码问题和多项架构规范违规**，导致：

1. **系统无法形成完整的投顾流程闭环** - 数据流在多个环节中断
2. **维护成本高** - 配置变更需要修改代码、重新部署
3. **可靠性风险** - 缺少容错机制，单点故障影响大
4. **数据一致性风险** - 模块间缺少自动同步机制

### 核心发现

| 问题类别 | 数量 | 严重程度 | 影响 |
|---------|------|---------|------|
| 数据流断点 | 7 个 | 🔴 高 | 系统流程不完整 |
| 硬编码问题 | 60+ 处 | 🟡 中 | 维护成本高 |
| 架构违规 | 4 项 | 🟠 中高 | 代码质量下降 |

### 预期收益

完成修复后，系统将实现：
- ✅ **完整的数据流闭环**：Macro → Regime → Policy → Signal → Backtest
- ✅ **配置驱动**：所有业务参数可在后台配置，无需修改代码
- ✅ **高可靠性**：容错机制、自动降级、任务编排
- ✅ **架构清晰**：Protocol 定义、Mapper 转换层、命名规范

---

## 第一部分：数据流断点分析

### 1.1 预期数据流（理想状态）

```
宏观数据采集 → Regime 判定 → 政策事件处理 → 投资信号生成 → 回测验证
   (Macro)      (Regime)      (Policy)        (Signal)      (Backtest)
      ↓             ↓             ↓               ↓              ↓
   数据库 ←─────── 数据库 ←─────── 数据库 ←────── 数据库 ←────── 数据库
      ↓             ↓             ↓               ↓              ↓
   告警通知 ←─── 自动触发 ←─── 自动重评 ←─── 自动证伪 ←─── 归因分析
```

### 1.2 实际数据流（当前状态）

```
宏观数据采集 ─X→ Regime 判定 ─?→ 政策事件处理 ─X→ 投资信号生成 ─?→ 回测验证
   (Macro)       (Regime)       (Policy)        (Signal)      (Backtest)
      ↓              ↓              ↓               ↓              ↓
   数据库         数据库         数据库          数据库         数据库
   (无容错)      (无通知)      (无触发器)     (手动传参)    (不引用信号)

图例：
─X→ 断点（完全阻塞）
─?→ 弱连接（需要手动干预）
```

### 1.3 断点详细分析

#### 🔴 断点 1：Macro → Regime 数据流（容错缺失）

**位置**：`apps/regime/application/use_cases.py:85-99`

**问题描述**：
宏观数据缺失时，Regime 计算直接失败，无容错机制。

**问题代码**：
```python
# apps/regime/application/use_cases.py
def execute(self, request: CalculateRegimeRequest) -> CalculateRegimeResponse:
    growth_series = self.macro_repo.get_growth_series(...)
    inflation_series = self.macro_repo.get_inflation_series(...)

    # ❌ 问题：直接返回错误，无 fallback
    if not growth_series:
        return CalculateRegimeResponse(success=False, error="无增长指标数据")
    if not inflation_series:
        return CalculateRegimeResponse(success=False, error="无通胀指标数据")
```

**影响**：
- 数据源临时故障导致整个系统停摆
- Regime 无法计算 → Signal 无法验证 → Backtest 无法运行
- 无降级方案，系统脆弱性高

**修复方案**：
```python
def execute(self, as_of_date: date) -> RegimeSnapshot:
    """执行 Regime 计算（带容错）"""
    macro_data = self._fetch_macro_data(as_of_date)
    missing_indicators = self._check_data_completeness(macro_data)

    if missing_indicators:
        # ✅ 方案 1：使用前值填充
        macro_data = self._fill_missing_data(macro_data, missing_indicators, as_of_date)

        # ✅ 方案 2：仍有缺失则降级处理
        if self._critical_data_missing(macro_data):
            logger.warning(f"Critical data missing, using fallback regime")
            return self._fallback_regime_estimation(as_of_date)

    return self._calculate_regime(macro_data, as_of_date)

def _fill_missing_data(self, data, missing, as_of_date):
    """使用前值填充缺失数据"""
    for indicator in missing:
        last_value = self.macro_repo.get_latest_observation(
            code=indicator,
            before_date=as_of_date
        )
        if last_value:
            data[indicator] = last_value
            logger.info(f"Filled {indicator} with last value")
    return data

def _fallback_regime_estimation(self, as_of_date):
    """降级方案：使用上一次的 Regime，降低置信度"""
    last_regime = self.regime_repo.get_latest_snapshot(before_date=as_of_date)
    if last_regime:
        return RegimeSnapshot(
            growth_momentum_z=last_regime.growth_momentum_z,
            inflation_momentum_z=last_regime.inflation_momentum_z,
            distribution=last_regime.distribution,
            dominant_regime=last_regime.dominant_regime,
            confidence=last_regime.confidence * 0.8,  # 降低置信度
            observed_at=as_of_date
        )
    raise RegimeCalculationError("No fallback regime available")
```

---

#### 🔴 断点 2：Policy → Signal 实时同步（触发器缺失）

**位置**：`apps/policy/infrastructure/models.py` + `apps/signal/domain/rules.py:144-189`

**问题描述**：
政策档位变化后，已有信号不会自动重评，需要手动传入 `policy_level` 参数。

**问题流程**：
```
当前流程：
1. PolicyLog 保存（档位从 P1 → P2）
2. (无任何触发器)
3. Signal 验证时需要手动传入 policy_level
4. 已有的 active signals 状态不变

应有流程：
1. PolicyLog 保存（档位从 P1 → P2）
2. ✅ post_save signal 触发
3. ✅ Celery 任务：trigger_signal_reevaluation
4. ✅ 重评所有 active signals
5. ✅ 更新信号状态（APPROVED → REJECTED）
```

**问题代码**：
```python
# apps/signal/domain/rules.py
def should_reject_signal(
    asset_class: str,
    current_regime: str,
    policy_level: int,  # ❌ 需要手动传入，无实时获取
    confidence: float = 0.0
) -> Tuple[bool, Optional[str], Optional[Eligibility]]:
    # 检查政策档位
    if policy_level >= 3:  # P3 完全退出
        reason = "当前政策档位为 P3，系统处于完全退出状态"
        return True, reason, eligibility
```

**修复方案**：

**步骤 1：在 PolicyLog 添加 post_save signal**
```python
# apps/policy/infrastructure/models.py
from django.db.models.signals import post_save
from django.dispatch import receiver

@receiver(post_save, sender=PolicyLog)
def on_policy_level_change(sender, instance, created, **kwargs):
    """政策档位变化时触发信号重评"""
    if not created:
        # 获取上一个档位
        old_level = PolicyLog.objects.filter(
            event_date__lt=instance.event_date
        ).order_by('-event_date').first()

        # 档位变化时触发
        if old_level and old_level.level != instance.level:
            from apps.policy.application.tasks import trigger_signal_reevaluation
            trigger_signal_reevaluation.delay(
                new_level=instance.level,
                event_date=instance.event_date.isoformat()
            )
```

**步骤 2：创建 Celery 任务**
```python
# apps/policy/application/tasks.py (新建)
from celery import shared_task

@shared_task
def trigger_signal_reevaluation(new_level: str, event_date: str):
    """重评所有活跃信号"""
    from apps.signal.infrastructure.repositories import DjangoSignalRepository
    from apps.signal.application.use_cases import ReevaluateSignalsUseCase

    repo = DjangoSignalRepository()
    use_case = ReevaluateSignalsUseCase(signal_repository=repo)

    result = use_case.execute(policy_level=int(new_level[1]))  # P2 → 2

    logger.info(f"Signal reevaluation completed: {result.rejected_count} signals rejected")
    return result.to_dict()
```

**步骤 3：创建重评 Use Case**
```python
# apps/signal/application/use_cases.py (新增)
@dataclass
class ReevaluateSignalsUseCase:
    """重新评估所有活跃信号"""
    signal_repository: SignalRepositoryProtocol

    def execute(self, policy_level: int) -> ReevaluateSignalsResponse:
        """执行信号重评"""
        active_signals = self.signal_repository.get_active_signals()

        rejected_count = 0
        for signal in active_signals:
            # 根据新的 policy_level 重评
            should_reject, reason, _ = should_reject_signal(
                asset_class=signal.asset_class,
                current_regime=signal.target_regime,
                policy_level=policy_level,
                confidence=0.0
            )

            if should_reject:
                signal.status = SignalStatus.REJECTED
                signal.rejection_reason = reason
                self.signal_repository.update_signal_status(
                    signal.id,
                    SignalStatus.REJECTED
                )
                rejected_count += 1

        return ReevaluateSignalsResponse(
            total_count=len(active_signals),
            rejected_count=rejected_count
        )
```

---

#### 🟡 断点 3：Signal → Backtest 反向链接（缺失）

**位置**：`apps/backtest/domain/services.py`

**问题描述**：
回测仅使用 Regime 数据和准入矩阵，不引用实际投资信号，无法验证信号表现。

**当前逻辑**：
```python
# apps/backtest/domain/services.py
class BacktestEngine:
    def run(self):
        for date in self.dates:
            regime = self.get_regime(date)

            # ❌ 仅根据资产类别 × Regime → 权重
            # 不知道哪些 Signal 是 active
            # 不能排除 invalidated 的信号
            weights = self._calculate_weights_from_regime(regime)
```

**修复方案**：
```python
class BacktestEngine:
    def __init__(self, ..., signal_repository: SignalRepositoryProtocol):
        self.signal_repo = signal_repository

    def run(self):
        for date in self.dates:
            regime = self.get_regime(date)

            # ✅ 获取当天的活跃信号
            active_signals = self.signal_repo.get_signals_active_on_date(date)

            # ✅ 根据信号调整权重
            weights = self._calculate_weights_with_signals(
                regime=regime,
                active_signals=active_signals
            )

            # ✅ 记录使用的信号
            self.result.signal_ids.extend([s.id for s in active_signals])
```

**新增字段**：
```python
# apps/backtest/domain/entities.py
@dataclass
class BacktestResult:
    # ... 原有字段
    signal_ids: List[str] = field(default_factory=list)  # ✅ 新增
    signal_performance: Dict[str, float] = field(default_factory=dict)  # ✅ 新增
```

---

#### 🔴 断点 4：异步任务编排缺失（手动触发）

**位置**：`apps/macro/application/tasks.py` + `apps/regime/application/use_cases.py`

**问题描述**：
`sync_macro_data()` 和 `calculate_regime()` 之间无自动链接，需要手动触发。

**当前流程**：
```
定时任务 1: sync_macro_data() (每天 8:00 执行)
定时任务 2: calculate_regime() (需要独立配置，容易遗漏)
→ 两者之间无依赖关系，时间间隔不确定
```

**修复方案 - 使用 Celery Chain**：
```python
# apps/macro/application/tasks.py
from celery import chain, shared_task

@shared_task
def sync_and_calculate_regime(start_date_str: str, end_date_str: Optional[str] = None):
    """编排宏观数据同步 + Regime 计算 + 通知"""
    from apps.macro.application.tasks import sync_macro_data
    from apps.regime.application.tasks import calculate_regime
    from apps.regime.application.tasks import notify_regime_change

    # ✅ 使用 Celery chain 编排任务流
    workflow = chain(
        sync_macro_data.s(start_date_str, end_date_str),
        calculate_regime.s(),  # 自动接收上一步的输出
        notify_regime_change.s()  # 自动接收上一步的输出
    )

    return workflow.apply_async()
```

**修改 calculate_regime 接收前一步输出**：
```python
# apps/regime/application/tasks.py
@shared_task
def calculate_regime(sync_result: Dict[str, Any]):
    """计算 Regime（接收 sync 结果）"""
    # ✅ 检查前一步是否成功
    if not sync_result.get('success'):
        logger.error(f"Sync failed, skipping regime calculation")
        return {'success': False, 'reason': 'sync_failed'}

    # 执行 Regime 计算
    use_case = CalculateRegimeUseCase(...)
    result = use_case.execute(...)

    return {
        'success': True,
        'regime': result.dominant_regime,
        'confidence': result.confidence
    }
```

**Celery Beat 配置**：
```python
# core/celery.py
app.conf.beat_schedule = {
    'daily-sync-and-calculate': {
        'task': 'apps.macro.application.tasks.sync_and_calculate_regime',
        'schedule': crontab(hour=8, minute=0),  # 每天 8:00
        'args': [(date.today() - timedelta(days=30)).isoformat(), date.today().isoformat()]
    },
}
```

---

#### 🟡 断点 5-7：其他数据流问题

**断点 5：Regime 计算后无通知机制**
- 位置：`apps/regime/infrastructure/repositories.py`
- 问题：RegimeLog 保存后无 post_save signal
- 影响：Signal 和 Policy 模块无法感知 Regime 变化
- 修复：添加 Django signal，触发通知任务

**断点 6：Policy 档位变化不触发 Signal 重评**
- 位置：`apps/policy/infrastructure/models.py`
- 问题：PolicyLog 保存后无 post_save signal
- 影响：档位变化需手动重评所有信号
- 修复：已在断点 2 中详细说明

**断点 7：数据延迟处理不完整（PIT 逻辑）**
- 位置：`apps/backtest/domain/entities.py:207-217`
- 问题：`DEFAULT_PUBLICATION_LAGS` 已定义，但仅应用于回测
- 影响：实时交易可能存在 Look-ahead bias
- 修复：将 PIT 逻辑应用到 Regime 计算和 Signal 验证

---

## 第二部分：硬编码问题分析

### 2.1 硬编码问题概览

| 类别 | 数量 | 示例 | 影响 |
|------|------|------|------|
| 资产代码映射 | 10+ | "000001.SH", "000905.SH" | 新增资产需修改代码 |
| 指标代码和阈值 | 15+ | PMI 50, CPI 2.0/3.0 | 阈值调整需重新部署 |
| Regime 准入矩阵 | 3 | ELIGIBILITY_MATRIX | 策略调整需修改代码 |
| 风险参数 | 12+ | 仓位 0.05/0.10/0.20 | 风险配置不灵活 |
| 滤波参数 | 3+ | HP lamb=129600 | 参数优化需修改代码 |

### 2.2 硬编码详细分析

#### 类别 1：资产代码映射（10+ 处）

**位置 1**：`apps/backtest/infrastructure/adapters/base.py:42-49`
```python
# ❌ 硬编码
ASSET_CLASS_TICKERS = {
    "a_share_growth": "000300.SH",  # 沪深300
    "a_share_value": "000905.SH",   # 中证500
    "china_bond": "H11025.CSI",     # 中债总财富指数
    "gold": "AU9999.SGE",           # 上海黄金
    "commodity": "NH0100.NHF",      # 南华商品指数
    "cash": None,
}
```

**位置 2**：`apps/signal/domain/rules.py:13-50`
```python
# ❌ 硬编码的准入矩阵
ELIGIBILITY_MATRIX = {
    "a_share_growth": {
        "Recovery": Eligibility.PREFERRED,
        "Overheat": Eligibility.NEUTRAL,
        "Stagflation": Eligibility.HOSTILE,
        "Deflation": Eligibility.NEUTRAL,
    },
    # ... 其他 5 个资产类别
}
```

**位置 3**：`apps/account/application/use_cases.py:497-504`
```python
# ❌ 硬编码
ASSET_CODE_MAP = {
    'A_SHARE_GROWTH': '000001.SH',
    'A_SHARE_VALUE': '000905.SH',
    'CHINA_BOND': 'H11025.CSI',
    # ...
}
```

**修复方案**：创建配置表
```python
# shared/infrastructure/models.py (新建)
class AssetConfigModel(models.Model):
    """资产类别配置表"""
    asset_class = models.CharField(max_length=50, unique=True, primary_key=True)
    display_name = models.CharField(max_length=100)
    ticker_symbol = models.CharField(max_length=20)  # 如 000300.SH
    data_source = models.CharField(max_length=20, default='tushare')
    category = models.CharField(max_length=20)  # equity/bond/commodity/cash
    is_active = models.BooleanField(default=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

**初始化脚本**：
```python
# scripts/init_asset_config.py (新建)
def init_asset_config():
    configs = [
        {
            'asset_class': 'a_share_growth',
            'display_name': 'A股成长',
            'ticker_symbol': '000300.SH',
            'data_source': 'tushare',
            'category': 'equity',
            'description': '沪深300指数作为成长风格 proxy'
        },
        {
            'asset_class': 'a_share_value',
            'display_name': 'A股价值',
            'ticker_symbol': '000905.SH',
            'data_source': 'tushare',
            'category': 'equity',
            'description': '中证500指数作为价值风格 proxy'
        },
        # ... 其他资产
    ]

    for config in configs:
        AssetConfigModel.objects.update_or_create(
            asset_class=config['asset_class'],
            defaults=config
        )
```

**重构代码使用配置**：
```python
# shared/infrastructure/config_loader.py (新建)
from django.core.cache import cache
from shared.infrastructure.models import AssetConfigModel

def get_asset_ticker(asset_class: str) -> Optional[str]:
    """获取资产代码（带缓存）"""
    cache_key = f"asset_ticker:{asset_class}"
    ticker = cache.get(cache_key)

    if ticker is None:
        config = AssetConfigModel.objects.filter(
            asset_class=asset_class,
            is_active=True
        ).first()

        if config:
            ticker = config.ticker_symbol
            cache.set(cache_key, ticker, timeout=3600)  # 缓存 1 小时
        else:
            # Fallback to hardcoded (兼容性)
            ticker = ASSET_CLASS_TICKERS.get(asset_class)

    return ticker
```

---

#### 类别 2：指标代码和阈值（15+ 处）

**位置**：`apps/macro/application/indicator_service.py:16-160`

**问题代码**：
```python
# ❌ 硬编码的指标元数据
INDICATOR_METADATA = {
    'CN_PMI_MANUFACTURING': {
        'name': 'PMI (制造业采购经理指数)',
        'category': '景气',
        'unit': '指数',
        'threshold_bullish': 50,  # ❌ 硬编码阈值
        'threshold_bearish': 50,  # ❌ 硬编码阈值
        'description': '反映制造业景气度，50为荣枯线',
    },
    'CN_CPI_YOY': {
        'name': 'CPI (消费者物价指数同比)',
        'category': '物价',
        'unit': '%',
        'threshold_bullish': 2.0,  # ❌ 硬编码
        'threshold_bearish': 3.0,  # ❌ 硬编码
    },
    # ... 21 种指标
}
```

**修复方案**：创建配置表
```python
# shared/infrastructure/models.py
class IndicatorConfigModel(models.Model):
    """宏观指标配置表"""
    code = models.CharField(max_length=50, unique=True, primary_key=True)
    name = models.CharField(max_length=100)
    name_en = models.CharField(max_length=100, blank=True)
    category = models.CharField(max_length=20)  # 景气/物价/货币/利率
    unit = models.CharField(max_length=10)  # %/指数

    # ✅ 可配置的阈值
    threshold_bullish = models.FloatField(null=True, blank=True)
    threshold_bearish = models.FloatField(null=True, blank=True)

    # 数据源配置
    data_source = models.CharField(max_length=20, default='akshare')
    fetch_frequency = models.CharField(max_length=10, default='M')  # D/W/M/Q/Y
    publication_lag_days = models.IntegerField(default=0)

    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

**初始化脚本**：
```python
# scripts/init_indicator_config.py (新建)
def migrate_indicator_metadata():
    """从硬编码迁移到数据库"""
    from apps.macro.application.indicator_service import IndicatorService

    for code, metadata in IndicatorService.INDICATOR_METADATA.items():
        IndicatorConfigModel.objects.update_or_create(
            code=code,
            defaults={
                'name': metadata.get('name'),
                'name_en': metadata.get('name_en', ''),
                'category': metadata.get('category'),
                'unit': metadata.get('unit'),
                'threshold_bullish': metadata.get('threshold_bullish'),
                'threshold_bearish': metadata.get('threshold_bearish'),
                'description': metadata.get('description', ''),
                'is_active': True
            }
        )
```

---

#### 类别 3：Regime 准入矩阵（3 处重复定义）

**位置**：
1. `apps/signal/domain/rules.py:13-50` - ELIGIBILITY_MATRIX
2. `apps/account/domain/services.py:47-97` - 重复定义

**问题**：
- 准入规则在多处重复定义
- 修改策略需要同步修改多处代码
- 无法在运行时调整策略

**修复方案**：创建配置表
```python
# shared/infrastructure/models.py
class RegimeEligibilityConfigModel(models.Model):
    """Regime 准入矩阵配置表"""
    asset_class = models.CharField(max_length=50)
    regime = models.CharField(max_length=20)  # Recovery/Overheat/Stagflation/Deflation
    eligibility = models.CharField(max_length=20)  # preferred/neutral/hostile

    # 可选：权重配置
    weight = models.FloatField(default=1.0)
    adjustment_factor = models.FloatField(default=1.0)

    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [['asset_class', 'regime']]
```

**初始化脚本**：
```python
# scripts/init_regime_eligibility.py (新建)
def migrate_eligibility_matrix():
    """从硬编码迁移到数据库"""
    from apps.signal.domain.rules import ELIGIBILITY_MATRIX

    for asset_class, regime_map in ELIGIBILITY_MATRIX.items():
        for regime, eligibility in regime_map.items():
            RegimeEligibilityConfigModel.objects.update_or_create(
                asset_class=asset_class,
                regime=regime,
                defaults={
                    'eligibility': eligibility.value,
                    'is_active': True
                }
            )
```

**重构代码**：
```python
# apps/signal/domain/rules.py (重构)
def check_eligibility(asset_class: str, regime: str) -> Eligibility:
    """从数据库读取配置（带缓存）"""
    from shared.infrastructure.config_loader import get_eligibility_config

    config = get_eligibility_config(asset_class, regime)
    if config:
        return Eligibility(config.eligibility)

    # Fallback to hardcoded (兼容性)
    return ELIGIBILITY_MATRIX.get(asset_class, {}).get(regime, Eligibility.NEUTRAL)
```

---

#### 类别 4-5：其他硬编码问题

**风险参数**（12+ 处）：
- 位置：`apps/account/domain/services.py:127-159`
- 示例：仓位百分比 `0.05, 0.10, 0.20`，调整因子 `1.0, 1.2, 0.7`
- 修复：创建 `RiskParameterConfigModel` 配置表

**滤波参数**（3+ 处）：
- 位置：`apps/filter/domain/entities.py:22-55`
- 示例：HP lamb=129600，Kalman level_variance=0.05
- 修复：创建 `FilterParameterConfigModel` 配置表

---

## 第三部分：架构问题分析

### 3.1 架构问题概览

| 问题类型 | 数量 | 严重程度 | 影响 |
|---------|------|---------|------|
| 命名冲突 | 2 | 🟠 中高 | 代码可读性下降 |
| Protocol 定义不足 | 1 vs 8+ | 🟡 中 | 可测试性降低 |
| Domain-ORM 转换缺失 | N/A | 🟡 中 | 转换逻辑分散 |
| Audit 模块缺 Domain 层 | 1 | 🟠 中高 | 违反架构约束 |

### 3.2 问题详细分析

#### 问题 1：命名冲突（2 处）

**冲突 1：MacroIndicator**
- Domain 层：`apps/macro/domain/entities.py` - `MacroIndicator` (dataclass)
- Infrastructure 层：`apps/macro/infrastructure/models.py` - `MacroIndicator` (ORM)
- 影响：导入时容易混淆，代码可读性差

**冲突 2：AIProviderConfig**
- Domain 层：`apps/ai_provider/domain/entities.py` - `AIProviderConfig` (dataclass)
- Infrastructure 层：`apps/ai_provider/infrastructure/models.py` - `AIProviderConfig` (ORM)
- 影响：同上

**修复方案**：统一命名规范
- **规则**：ORM 模型统一添加 `Model` 后缀
- **重命名**：
  - `MacroIndicator` (ORM) → `MacroIndicatorModel`
  - `AIProviderConfig` (ORM) → `AIProviderConfigModel`
- **更新所有引用**：使用 IDE 全局重构工具

---

#### 问题 2：Protocol 定义不足

**当前状态**：
`shared/domain/interfaces.py` 只有 1 个 Protocol (`TrendCalculatorProtocol`)

**需要补充的 Protocol**（至少 8+ 个）：

```python
# shared/domain/interfaces.py (扩展)

# ========== Repository Protocols ==========
class MacroRepositoryProtocol(Protocol):
    """宏观数据仓储协议"""
    def save_indicator(self, indicator: MacroIndicator) -> MacroIndicator: ...
    def get_by_code_and_date(self, code: str, observed_at: date) -> Optional[MacroIndicator]: ...
    def get_latest_observation(self, code: str, before_date: date) -> Optional[MacroIndicator]: ...

class RegimeRepositoryProtocol(Protocol):
    """Regime 仓储协议"""
    def save_snapshot(self, snapshot: RegimeSnapshot) -> RegimeSnapshot: ...
    def get_snapshot_by_date(self, observed_at: date) -> Optional[RegimeSnapshot]: ...

class PolicyRepositoryProtocol(Protocol):
    """Policy 仓储协议"""
    def save_event(self, event: PolicyEvent) -> PolicyEvent: ...
    def get_latest_level(self, as_of_date: date) -> Optional[PolicyLevel]: ...

class SignalRepositoryProtocol(Protocol):
    """Signal 仓储协议"""
    def save_signal(self, signal: InvestmentSignal) -> InvestmentSignal: ...
    def get_active_signals(self) -> List[InvestmentSignal]: ...
    def update_signal_status(self, signal_id: str, new_status: SignalStatus) -> bool: ...

# ========== Adapter Protocols ==========
class DataSourceAdapterProtocol(Protocol):
    """数据源适配器协议"""
    source_name: str
    def fetch(self, indicator_code: str, start_date: date, end_date: date) -> List[MacroDataPoint]: ...
    def supports(self, indicator_code: str) -> bool: ...

class PriceAdapterProtocol(Protocol):
    """价格数据适配器协议"""
    source_name: str
    def get_price(self, asset_class: str, as_of_date: date) -> Optional[float]: ...
    def supports(self, asset_class: str) -> bool: ...

# ========== Service Protocols ==========
class FilterServiceProtocol(Protocol):
    """滤波服务协议"""
    def hp_filter(self, series: List[float], lamb: float) -> tuple[List[float], List[float]]: ...
    def kalman_filter(self, series: List[float], params: KalmanFilterParams) -> List[float]: ...

class NotificationServiceProtocol(Protocol):
    """通知服务协议"""
    def send_alert(self, level: str, message: str, recipients: List[str]) -> bool: ...
```

---

#### 问题 3：Domain ↔ ORM 转换缺少显式实现

**当前状态**：
转换逻辑散布在 Repository 内部，无统一规范。

**修复方案**：创建 Mapper 转换层

```python
# shared/infrastructure/mappers.py (新建)
from typing import TypeVar, Generic
from abc import ABC, abstractmethod

DomainEntity = TypeVar('DomainEntity')
OrmModel = TypeVar('OrmModel')

class BaseMapper(ABC, Generic[DomainEntity, OrmModel]):
    """基础映射器（Mapper 模式）"""

    @abstractmethod
    def to_domain(self, orm_obj: OrmModel) -> DomainEntity:
        """ORM → Domain"""
        pass

    @abstractmethod
    def to_orm(self, entity: DomainEntity) -> OrmModel:
        """Domain → ORM"""
        pass

# 示例：MacroIndicator Mapper
class MacroIndicatorMapper(BaseMapper[MacroIndicator, MacroIndicatorModel]):
    """宏观指标映射器"""

    def to_domain(self, orm_obj: MacroIndicatorModel) -> MacroIndicator:
        """ORM → Domain"""
        from apps.macro.domain.entities import MacroIndicator, PeriodType

        return MacroIndicator(
            code=orm_obj.code,
            value=float(orm_obj.value),
            reporting_period=orm_obj.reporting_period,
            period_type=PeriodType(orm_obj.period_type),
            published_at=orm_obj.published_at,
            source=orm_obj.source
        )

    def to_orm(self, entity: MacroIndicator) -> MacroIndicatorModel:
        """Domain → ORM"""
        from apps.macro.infrastructure.models import MacroIndicatorModel

        return MacroIndicatorModel(
            code=entity.code,
            value=entity.value,
            reporting_period=entity.reporting_period,
            period_type=entity.period_type.value,
            published_at=entity.published_at,
            source=entity.source
        )
```

**重构 Repository 使用 Mapper**：
```python
# apps/macro/infrastructure/repositories.py (重构)
from shared.infrastructure.mappers import MacroIndicatorMapper

class DjangoMacroRepository:
    def __init__(self):
        self._model = MacroIndicatorModel
        self._mapper = MacroIndicatorMapper()

    def save_indicator(self, indicator: MacroIndicator) -> MacroIndicator:
        """使用 Mapper 转换"""
        orm_obj = self._mapper.to_orm(indicator)
        orm_obj.save()
        return self._mapper.to_domain(orm_obj)
```

---

#### 问题 4：Audit 模块完全缺 Domain 层

**当前状态**：
`apps/audit/` 只有 Infrastructure 层，违反四层架构约束。

**修复方案**：
1. 创建 `apps/audit/domain/entities.py`
2. 定义 Domain 实体：`AuditReport`, `AttributionAnalysis`
3. 将业务逻辑从 ORM 迁移到 Domain 层

---

## 第四部分：修复方案总览

### 4.1 修复优先级

#### 🔴 P0（立即修复）- 阻塞系统流程

| 任务 | 目标 | 工作量 | 影响范围 |
|------|------|--------|---------|
| 1. Macro → Regime 容错机制 | 系统不崩溃 | 2 天 | apps/regime/ |
| 2. 异步任务编排 | 自动化 | 3 天 | apps/macro/, apps/regime/ |
| 3. Policy → Signal 实时同步 | 数据一致性 | 3 天 | apps/policy/, apps/signal/ |

**预期完成时间**：1-2 周

#### 🟡 P1（短期修复）- 影响数据一致性

| 任务 | 目标 | 工作量 | 影响范围 |
|------|------|--------|---------|
| 4. Regime 变化通知机制 | 模块联动 | 2 天 | apps/regime/ |
| 5. 创建配置表 | 配置化基础 | 3 天 | shared/infrastructure/ |
| 6. 创建初始化脚本 | 数据迁移 | 2 天 | scripts/ |
| 7. 配置加载器 | 配置读取 | 2 天 | shared/infrastructure/ |
| 8. 重构硬编码 | 配置驱动 | 5 天 | 多个模块 |
| 9. Domain-ORM 转换层 | 架构规范 | 4 天 | 所有模块 |

**预期完成时间**：2-3 周

#### 🟢 P2（中期优化）- 改善代码质量

| 任务 | 目标 | 工作量 | 影响范围 |
|------|------|--------|---------|
| 10. Protocol 定义完善 | 可测试性 | 3 天 | shared/domain/ |
| 11. Signal → Backtest 反向链接 | 回测增强 | 3 天 | apps/backtest/ |
| 12. 风险参数配置化 | 灵活性 | 2 天 | apps/account/ |
| 13. 命名冲突修复 | 可读性 | 2 天 | 多个模块 |

**预期完成时间**：3-4 周

### 4.2 实施路径

#### 阶段 1：P0 修复（Week 1-2）

**Sprint 1.1：容错机制（2 天）**
- [ ] 修改 `apps/regime/application/use_cases.py`
- [ ] 实现 `_check_data_completeness()`
- [ ] 实现 `_fill_missing_data()`
- [ ] 实现 `_fallback_regime_estimation()`
- [ ] 编写单元测试

**Sprint 1.2：异步任务编排（3 天）**
- [ ] 创建 `apps/macro/application/tasks.py::sync_and_calculate_regime`
- [ ] 修改 `apps/regime/application/tasks.py::calculate_regime`
- [ ] 配置 Celery Beat 定时调度
- [ ] 测试任务链路

**Sprint 1.3：Policy → Signal 实时同步（3 天）**
- [ ] 修改 `apps/policy/infrastructure/models.py` - 添加 signal
- [ ] 创建 `apps/policy/application/tasks.py`
- [ ] 创建 `apps/signal/application/use_cases.py::ReevaluateSignalsUseCase`
- [ ] 测试档位变化触发

#### 阶段 2：P1 修复（Week 3-5）

**Sprint 2.1：配置化基础（5 天）**
- [ ] 创建 `shared/infrastructure/models.py`
- [ ] 定义 5 个配置表
- [ ] 运行 `makemigrations` 和 `migrate`
- [ ] 创建 4 个初始化脚本
- [ ] 执行数据迁移

**Sprint 2.2：配置驱动重构（7 天）**
- [ ] 创建 `shared/infrastructure/config_loader.py`
- [ ] 重构 `apps/signal/domain/rules.py`
- [ ] 重构 `apps/macro/application/indicator_service.py`
- [ ] 重构 `apps/backtest/infrastructure/adapters/base.py`
- [ ] 测试配置读取

**Sprint 2.3：Mapper 转换层（4 天）**
- [ ] 创建 `shared/infrastructure/mappers.py`
- [ ] 为每个模块创建 Mapper
- [ ] 重构所有 Repository
- [ ] 测试转换逻辑

#### 阶段 3：P2 优化（Week 6-8）

**Sprint 3.1：Protocol 定义（3 天）**
- [ ] 扩展 `shared/domain/interfaces.py`
- [ ] 更新所有实现类
- [ ] 运行 mypy 类型检查

**Sprint 3.2：其他优化（7 天）**
- [ ] Signal → Backtest 反向链接
- [ ] 风险参数配置化
- [ ] 命名冲突修复
- [ ] 完整回归测试

### 4.3 关键文件清单

#### P0 文件（立即修复）
1. `apps/regime/application/use_cases.py` - 容错机制
2. `apps/macro/application/tasks.py` - 任务编排
3. `apps/regime/application/tasks.py` - 接收前一步输出
4. `apps/policy/infrastructure/models.py` - Policy signal
5. `apps/policy/application/tasks.py` - Signal 重评任务（新建）
6. `apps/signal/application/use_cases.py` - 重评 use case（扩展）

#### P1 文件（短期修复）
7. `shared/infrastructure/models.py` - 配置表（新建）
8. `shared/infrastructure/config_loader.py` - 配置加载器（新建）
9. `scripts/init_asset_config.py` - 初始化脚本（新建）
10. `scripts/init_indicator_config.py` - 初始化脚本（新建）
11. `scripts/init_regime_eligibility.py` - 初始化脚本（新建）
12. `scripts/init_filter_parameters.py` - 初始化脚本（新建）
13. `shared/infrastructure/mappers.py` - Mapper 基类（新建）
14. `apps/*/infrastructure/repositories.py` - 使用 Mapper（重构）

#### P2 文件（中期优化）
15. `shared/domain/interfaces.py` - Protocol 定义（扩展）
16. `apps/backtest/domain/entities.py` - 添加 signal_ids
17. `apps/backtest/infrastructure/models.py` - 添加 signal_ids 字段
18. `apps/macro/infrastructure/models.py` - 重命名（重构）
19. `apps/ai_provider/infrastructure/models.py` - 重命名（重构）

---

## 第五部分：风险管理

### 5.1 风险评估

#### 🔴 高风险项目

**风险 1：ORM 模型重命名**
- **风险等级**：高
- **影响**：可能破坏现有引用，导致系统崩溃
- **概率**：中
- **缓解措施**：
  - 使用 IDE 全局重构工具（PyCharm/VSCode）
  - 创建完整的测试套件
  - 在开发环境充分测试
  - 分阶段发布，每次只改一个模型
- **回滚策略**：Git revert + 数据库迁移回滚

**风险 2：异步任务编排**
- **风险等级**：高
- **影响**：任务失败可能导致数据不一致
- **概率**：中
- **缓解措施**：
  - 添加重试机制（Celery retry）
  - 记录详细日志
  - 实现幂等性设计
  - 监控任务执行状态
- **回滚策略**：保留原有独立任务，使用 Feature Flag 控制

#### 🟡 中风险项目

**风险 3：配置化迁移**
- **风险等级**：中
- **影响**：配置缺失可能导致系统故障
- **概率**：低
- **缓解措施**：
  - 保留硬编码作为 fallback
  - 启动时验证配置完整性
  - 提供配置管理界面
  - 配置变更记录审计日志
- **回滚策略**：切换到 fallback 模式（硬编码）

**风险 4：容错机制**
- **风险等级**：中
- **影响**：降级逻辑可能产生错误结果
- **概率**：低
- **缓解措施**：
  - 低置信度明确标记
  - 降级时发送告警
  - 人工审核机制
  - 记录详细日志
- **回滚策略**：移除容错逻辑，恢复原有错误处理

### 5.2 回滚策略

#### 策略 1：数据库迁移回滚
```bash
# 如果配置表迁移出问题
python manage.py migrate shared <previous_migration_number>

# 查看迁移历史
python manage.py showmigrations shared
```

#### 策略 2：代码回滚
```bash
# 查看提交历史
git log --oneline

# 回滚到指定提交（保留历史）
git revert <commit_hash>
git push origin main

# 或者硬回滚（慎用）
git reset --hard <commit_hash>
git push origin main --force
```

#### 策略 3：功能开关（Feature Flag）
```python
# core/settings/base.py
FEATURE_FLAGS = {
    'USE_CONFIG_DB': True,  # 配置数据库功能
    'USE_TASK_CHAIN': True,  # 任务编排
    'USE_MAPPER': True,  # Mapper 转换
    'USE_SIGNAL_REEVALUATION': True,  # Signal 自动重评
}

# 代码中使用
from django.conf import settings

if settings.FEATURE_FLAGS.get('USE_CONFIG_DB'):
    # 使用配置数据库
    ticker = get_asset_ticker(asset_class)
else:
    # 使用硬编码（fallback）
    ticker = ASSET_CLASS_TICKERS.get(asset_class)
```

#### 策略 4：分阶段发布
1. 每个 Sprint 完成后打 Git tag
   ```bash
   git tag -a v3.5.0-p0-sprint1 -m "P0 Sprint 1: 容错机制"
   git push origin v3.5.0-p0-sprint1
   ```
2. 发现问题立即停止，回滚到上一个 tag
3. 修复后再继续

### 5.3 测试策略

#### 单元测试（必须）
- Domain 层覆盖率 ≥ 90%
- Application 层覆盖率 ≥ 80%
- Infrastructure 层覆盖率 ≥ 70%

#### 集成测试（必须）
- 端到端数据流测试
- 异步任务链路测试
- 配置加载测试

#### 回归测试（必须）
- 每次重构后运行完整测试套件
- 关键业务流程手动验证

---

## 第六部分：验收标准

### 6.1 P0 完成标准

- [ ] **容错机制**：Macro 数据缺失时，Regime 计算使用前值或降级方案，不崩溃
  - 测试：模拟数据源故障，验证系统正常运行
  - 验证：检查日志中的 fallback 记录
  - 指标：系统可用性 ≥ 99.5%

- [ ] **异步任务编排**：宏观数据同步后，Regime 自动计算（无需手动触发）
  - 测试：执行 `sync_and_calculate_regime` 任务，验证整个链路
  - 验证：检查 Celery 日志，确认任务顺序执行
  - 指标：任务成功率 ≥ 95%

- [ ] **Policy → Signal 实时同步**：Policy 档位变化后，所有活跃信号自动重评
  - 测试：更新 PolicyLog，验证 Signal 状态变化
  - 验证：检查 Signal 的 rejection_reason 字段
  - 指标：重评延迟 ≤ 5 分钟

### 6.2 P1 完成标准

- [ ] **Regime 变化通知**：Regime 变化后，相关模块收到通知
  - 测试：更新 RegimeLog，验证通知发送
  - 验证：检查邮件/钉钉/Slack 通知
  - 指标：通知送达率 ≥ 99%

- [ ] **配置数据库**：所有配置数据存储在数据库，可在后台管理
  - 测试：通过 Django Admin 修改配置，验证生效
  - 验证：检查缓存刷新逻辑
  - 指标：配置项覆盖率 ≥ 90%

- [ ] **配置驱动**：资产代码、指标阈值、准入矩阵可动态配置
  - 测试：修改配置后，验证业务逻辑变化
  - 验证：检查 fallback 逻辑
  - 指标：硬编码减少 ≥ 80%

- [ ] **Mapper 转换层**：Domain-ORM 转换逻辑集中在 Mapper 层
  - 测试：验证双向转换的正确性
  - 验证：检查 Repository 代码清晰度
  - 指标：转换覆盖率 = 100%

### 6.3 P2 完成标准

- [ ] **Protocol 定义**：所有 Repository 有明确的 Protocol 定义
  - 测试：运行 mypy 类型检查，无错误
  - 验证：检查 Protocol 实现完整性
  - 指标：Protocol 覆盖率 = 100%

- [ ] **Signal → Backtest 反向链接**：回测结果可追溯到具体信号
  - 测试：运行回测，验证 signal_ids 字段
  - 验证：检查信号表现分析接口
  - 指标：回测可追溯性 = 100%

- [ ] **命名规范**：无命名冲突，代码可读性提升
  - 测试：搜索代码中的 `MacroIndicator`，验证无歧义
  - 验证：Code review 通过
  - 指标：命名冲突 = 0

- [ ] **风险参数配置化**：风险参数可在后台调整
  - 测试：修改风险参数，验证仓位计算变化
  - 验证：检查配置生效速度
  - 指标：参数配置化率 ≥ 90%

---

## 第七部分：后续优化建议

### 7.1 短期优化（3 个月内）

#### 1. Signal 自动证伪检查
- **目标**：定时检查所有 active signals 的证伪条件
- **实施**：
  - 创建 Celery 定时任务 `check_signal_invalidation`
  - 调用 `apps/signal/application/invalidation_checker.py`
  - 证伪时自动更新信号状态为 INVALIDATED
- **预期收益**：减少人工干预，提高信号质量

#### 2. 增强 PIT 数据处理
- **目标**：将 Point-in-Time 逻辑应用到实时交易
- **实施**：
  - 在 Regime 计算时应用 PIT 逻辑
  - 在 Signal 验证时应用 PIT 逻辑
  - 确保无 Look-ahead bias
- **预期收益**：提高回测准确性，减少实盘偏差

#### 3. 数据质量监控和告警
- **目标**：实时监控数据质量，及时告警
- **实施**：
  - 监控数据源可用性
  - 监控数据更新延迟
  - 监控数据一致性（跨源对比）
  - 集成 Prometheus + Grafana
- **预期收益**：提前发现问题，降低故障影响

### 7.2 中期优化（6 个月内）

#### 4. 多策略回测框架
- **目标**：支持同时回测多个策略，对比表现
- **实施**：
  - 设计策略抽象接口
  - 支持策略组合（多策略混合）
  - 提供策略表现对比分析
- **预期收益**：策略优化，提高收益/风险比

#### 5. 增强归因分析能力
- **目标**：深入分析收益来源（资产配置/择时/选股）
- **实施**：
  - 实现 Brinson 归因模型
  - 分离 Regime 贡献、Signal 贡献
  - 可视化归因结果
- **预期收益**：理解收益驱动因素，优化策略

#### 6. 用户自定义准入规则
- **目标**：允许用户在后台自定义 Regime 准入矩阵
- **实施**：
  - 提供可视化配置界面
  - 支持规则版本管理
  - 支持 A/B 测试
- **预期收益**：灵活性提升，支持个性化策略

### 7.3 长期优化（1 年内）

#### 7. 完整的风险管理系统
- **目标**：实时监控组合风险，自动止损/减仓
- **实施**：
  - VaR/CVaR 风险计算
  - 止损规则引擎
  - 实时风险告警
- **预期收益**：控制下行风险，保护资金安全

#### 8. 多账户、多组合支持
- **目标**：支持一个用户管理多个账户和组合
- **实施**：
  - 账户隔离和权限管理
  - 组合绩效独立跟踪
  - 支持组合合并分析
- **预期收益**：满足专业用户需求

#### 9. 实时交易执行和监控
- **目标**：从信号生成到交易执行的完整闭环
- **实施**：
  - 集成券商 API
  - 实时订单管理
  - 成交回报处理
  - 持仓自动同步
- **预期收益**：完整的投顾系统，可用于实盘

---

## 第八部分：总结

### 8.1 当前状态评估

**优势**：
- ✅ 架构设计清晰，四层分层合理
- ✅ Domain 层业务逻辑完整
- ✅ 核心功能模块齐全

**劣势**：
- ❌ 数据流有断点，无法形成闭环
- ❌ 硬编码严重，维护成本高
- ❌ 缺少容错机制，可靠性不足
- ❌ 架构规范未完全遵循

### 8.2 修复后预期状态

**系统流程**：
```
完整闭环：
Macro 同步 → Regime 计算 → Policy 评估 → Signal 生成 → Backtest 验证
    ↓           ↓            ↓           ↓            ↓
  容错         自动通知      自动触发     自动证伪      归因分析
    ↓           ↓            ↓           ↓            ↓
  告警         日志         邮件        状态更新      性能报告
```

**技术架构**：
```
Domain 层：纯业务逻辑 + Protocol 定义
    ↓
Application 层：Use Cases + Celery Tasks（任务编排）
    ↓
Infrastructure 层：ORM Models + Repositories + Adapters
    ↑          ↑
Mapper 层   Config 层（配置驱动）
```

**预期收益**：
- **可靠性提升 50%**：容错机制 + 自动降级
- **效率提升 80%**：自动化任务编排 + 实时同步
- **维护成本降低 60%**：配置驱动 + 架构清晰
- **扩展性提升 100%**：Protocol 定义 + Mapper 层

### 8.3 关键成功因素

1. **分阶段实施**：P0 → P1 → P2，循序渐进
2. **充分测试**：单元测试 + 集成测试 + 回归测试
3. **风险控制**：Feature Flag + 回滚策略 + 分阶段发布
4. **团队协作**：Code Review + 文档同步 + 知识分享
5. **持续优化**：监控指标 + 用户反馈 + 迭代改进

### 8.4 下一步行动

**立即开始**：
1. 创建 `shared/infrastructure/models.py`，定义配置表
2. 修改 `apps/regime/application/use_cases.py`，添加容错机制
3. 创建 `apps/macro/application/tasks.py::sync_and_calculate_regime`

**本周目标**：
- 完成 P0 任务的设计和编码
- 编写单元测试
- 在开发环境验证

**本月目标**：
- 完成 P0 + P1 所有任务
- 在测试环境验证
- 准备上线

---

## 附录

### A. 术语表

| 术语 | 全称 | 说明 |
|------|------|------|
| Regime | 宏观环境象限 | Recovery/Overheat/Stagflation/Deflation |
| Policy | 政策档位 | P0/P1/P2/P3，反映政策风险 |
| Signal | 投资信号 | LONG/SHORT/NEUTRAL，带证伪逻辑 |
| Backtest | 回测 | 历史数据验证策略有效性 |
| PIT | Point-in-Time | 时点数据，避免 Look-ahead bias |
| HP Filter | Hodrick-Prescott 滤波 | 趋势-周期分解 |
| Kalman Filter | 卡尔曼滤波 | 状态空间模型 |
| Eligibility | 准入状态 | PREFERRED/NEUTRAL/HOSTILE |

### B. 参考文档

- `docs/AgomSAAF_V3.4.md` - 系统设计文档
- `CLAUDE.md` - 项目开发规则
- `docs/project_structure.md` - 项目结构说明
- `docs/implementation_tasks.md` - 实施任务清单

### C. 联系方式

- 技术负责人：[待补充]
- 项目经理：[待补充]
- 紧急联系：[待补充]

---

**文档版本**：v1.0
**最后更新**：2026-01-01
**下次审核**：每月审核一次，根据实施进度更新
