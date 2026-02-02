# AgomSAAF Bug 修复执行计划

> 创建时间: 2026-01-31
> 状态: 待执行
> **重要**: 本系统涉及真实交易资金，所有修复必须遵循"安全第一"原则

---

## 核心原则

```
Domain 层宁可炸，也不要悄悄容错
有备份，才敢真跑
默认值仅用于兜底，不用于精确分析
```

---

## 修复范围

### 🔴 第一优先级（今日完成，4-6小时）

1. **波动率控制 min/max 逻辑错误** - `apps/account/domain/services.py:760-762`
2. **美元单位换算缺少汇率转换** - `apps/macro/domain/entities.py:14-47`

### 🟡 第二优先级（本周内，3-5天）

3. **固定止损 API 改为正数语义** - `apps/account/domain/services.py:446-497`
4. **重命名"启发式归因"** - `apps/audit/domain/services.py:243-274`

---

## Bug #1: 波动率控制修复

### 问题

```python
# 错误代码 (第 760-762 行)
suggested_multiplier = min(
    target_volatility / current_volatility,
    1.0 - max_reduction,
)
```

**影响**: 轻微超限时，本应保留 83% 仓位，实际只保留 50%

### 修复方案

#### 1. 修复核心逻辑

**文件**: `apps/account/domain/services.py`

```python
# 第 760-762 行替换为：
lower_bound = 1.0 - max_reduction  # hard floor
suggested_multiplier = max(
    target_volatility / current_volatility,
    lower_bound,
)
```

#### 2. 添加负波动率校验（新增）

**位置**: `VolatilityTargetService.assess_volatility_adjustment()` 方法开头

```python
@staticmethod
def assess_volatility_adjustment(
    current_volatility: float,
    target_volatility: float,
    tolerance: float = 0.2,
    max_reduction: float = 0.5,
) -> VolatilityAdjustmentResult:
    """
    评估是否需要调整仓位

    ⚠️ Domain 层校验：宁可炸，也不要容错
    """
    # 🔒 安全校验：波动率不能为负
    if current_volatility < 0:
        raise ValueError(
            f"current_volatility 不能为负数，当前值: {current_volatility}。"
            f"这通常是上游计算错误的信号，请检查数据源。"
        )

    if target_volatility <= 0:
        raise ValueError(f"target_volatility 必须大于0，当前值: {target_volatility}")

    volatility_ratio = current_volatility / target_volatility
    # ... 后续逻辑
```

**原因**:
- 负波动率在数学上不可能（标准差 >= 0）
- 一旦出现，说明上游计算错误或数据损坏
- Domain 层必须立即暴露，不能静默处理

#### 3. 更新测试

**文件**: `tests/unit/test_volatility_control.py`

```python
def test_negative_volatility_raises_error(self):
    """测试：负波动率应该抛出异常"""
    with pytest.raises(ValueError, match="不能为负数"):
        VolatilityTargetService.assess_volatility_adjustment(
            current_volatility=-0.05,
            target_volatility=0.15,
        )
```

---

## Bug #2: 美元单位换算修复

### 问题

```python
# 当前代码 (apps/macro/domain/entities.py)
UNIT_CONVERSION_FACTORS: Dict[str, float] = {
    '亿美元': 100000000,      # ❌ 缺少汇率
}
# 1 亿美元 → 100,000,000 元（错误）
# 应该是：1 亿美元 × 100,000,000 × 7.2 = 720,000,000 元
```

**影响**:
- 所有美元口径宏观数据量级错误（误差 -99.28%）
- Regime 判定基于错误数据，可能导致错误交易决策

### 修复方案

#### 1. 修复单位转换函数

**文件**: `apps/macro/domain/entities.py`

```python
def normalize_currency_unit(
    value: float,
    unit: str,
    exchange_rate: float = 1.0
) -> Tuple[float, str]:
    """
    将货币类数据统一转换为"元"层级

    Args:
        value: 原始值
        unit: 原始单位
        exchange_rate: USD/CNY 汇率（仅对美元单位有效）
                     ⚠️ 默认值 7.0 仅用于系统兜底，不用于历史回测的精确分析
                     回测场景必须使用历史汇率！

    Returns:
        tuple: (转换后的值, "元")
    """
    if unit in UNIT_CONVERSION_FACTORS:
        factor = UNIT_CONVERSION_FACTORS[unit]

        # 🔧 修复：美元单位需要额外乘汇率
        if "美元" in unit or "USD" in unit.upper():
            return (value * factor * exchange_rate, "元")

        return (value * factor, "元")

    return (value, unit)
```

#### 2. 新增汇率服务

**新建文件**: `apps/macro/infrastructure/exchange_rate_config.py`

```python
"""
汇率配置服务

优先级：cache > DB > env > default(7.0)

⚠️ 默认汇率 7.0 仅用于系统兜底
不用于历史回测的精确分析
"""

import os
from django.core.cache import cache

class ExchangeRateService:
    @staticmethod
    def get_usd_cny_rate(as_of_date=None) -> float:
        """
        获取 USD/CNY 汇率

        Returns:
            float: USD/CNY 汇率

        ⚠️ 重要：默认值 7.0 仅用于系统兜底
                  不用于历史回测的精确分析
        """
        cache_key = f"usd_cny_rate:{as_of_date}" if as_of_date else "usd_cny_rate:latest"
        cached_rate = cache.get(cache_key)
        if cached_rate is not None:
            return float(cached_rate)

        # 环境变量
        env_rate = os.getenv('USD_CNY_EXCHANGE_RATE')
        if env_rate:
            rate = float(env_rate)
            cache.set(cache_key, rate, 3600)
            return rate

        # 默认值
        default_rate = 7.0
        cache.set(cache_key, default_rate, 3600)
        return default_rate
```

#### 3. 数据迁移脚本（关键：强制备份）

**新建文件**: `apps/macro/management/commands/migrate_usd_data.py`

```python
"""
数据迁移命令：修复美元口径数据

⚠️ 安全第一：执行前必须做全量备份
"""

from django.core.management.base import BaseCommand

class Command(BaseCommand):
    help = '迁移美元口径宏观数据，添加汇率转换'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--exchange-rate', type=float, default=None)

    def handle(self, *args, **options):
        # 🔒 安全检查：强制先做备份
        self.stdout.write(self.style.WARNING("=" * 60))
        self.stdout.write(self.style.WARNING("⚠️  安全第一：执行迁移前必须做全量备份"))
        self.stdout.write(self.style.WARNING("=" * 60))
        self.stdout.write("请按以下步骤操作：")
        self.stdout.write("1. 备份数据：")
        self.stdout.write("   python manage.py dumpdata macro.MacroIndicatorModel > backup_before_usd_fix.json")
        self.stdout.write("")
        self.stdout.write("2. 确认备份完成后，运行模拟迁移：")
        self.stdout.write("   python manage.py migrate_usd_data --dry-run")
        self.stdout.write("")
        self.stdout.write("3. 确认无误后，执行正式迁移：")
        self.stdout.write("   python manage.py migrate_usd_data")
        self.stdout.write("")
        self.stdout.write("=" * 60)

        # 询问用户是否已备份
        confirm = input("请确认您已完成数据备份 (输入 'yes' 继续): ")
        if confirm.lower() != 'yes':
            self.stdout.write(self.style.ERROR("❌ 未确认备份，迁移已取消"))
            return

        # 继续执行迁移...
```

---

## 执行步骤（今日完成）

### 步骤 1: 波动率控制修复（1小时）

```bash
# 1. 修改代码
# 文件: apps/account/domain/services.py
# 第 760-762 行：将 min() 改为 max()

# 2. 添加负波动率校验
# 在 assess_volatility_adjustment() 方法开头添加校验

# 3. 创建测试文件
# tests/unit/test_volatility_control.py

# 4. 运行测试
pytest tests/unit/test_volatility_control.py -v
```

### 步骤 2: 美元换算修复（2-3小时）

```bash
# 1. ⚠️ 先做备份（必须）
python manage.py dumpdata macro.MacroIndicatorModel > backup_before_usd_fix.json

# 2. 修改代码
# 文件: apps/macro/domain/entities.py
# 修改 normalize_currency_unit() 函数，添加汇率参数

# 3. 新建汇率服务
# apps/macro/infrastructure/exchange_rate_config.py

# 4. 创建迁移脚本
# apps/macro/management/commands/migrate_usd_data.py

# 5. 创建测试文件
# tests/unit/test_currency_conversion.py

# 6. 运行测试
pytest tests/unit/test_currency_conversion.py -v

# 7. 模拟迁移
python manage.py migrate_usd_data --dry-run --exchange-rate 7.2

# 8. 确认后执行迁移
python manage.py migrate_usd_data --exchange-rate 7.2
```

### 步骤 3: 验证（30分钟）

```bash
# 1. 运行所有测试
pytest tests/unit/ -v

# 2. 检查迁移结果
python manage.py shell
>>> from apps.macro.infrastructure.models import MacroIndicatorModel
>>> MacroIndicatorModel.objects.filter(original_unit__icontains='美元').count()
# 应该显示迁移后的数据量

# 3. 验证 Regime 计算
python manage.py calculate_regime
# 检查输出是否合理
```

---

## 回滚方案

### 如果出现问题

```bash
# 1. 代码回滚
git revert HEAD
git push

# 2. 数据回滚
python manage.py loaddata backup_before_usd_fix.json

# 3. 禁用 Celery 任务（如果已启用）
python manage.py shell
>>> from django_celery_beat.models import PeriodicTask
>>> PeriodicTask.objects.filter(task__contains='stop_loss').update(enabled=False)
>>> PeriodicTask.objects.filter(task__contains='volatility').update(enabled=False)
```

---

## 新增文件清单

| 文件路径 | 用途 |
|----------|------|
| `tests/unit/test_volatility_control.py` | 波动率控制测试 |
| `tests/unit/test_currency_conversion.py` | 货币转换测试 |
| `apps/macro/infrastructure/exchange_rate_config.py` | 汇率服务 |
| `apps/macro/management/commands/migrate_usd_data.py` | 数据迁移脚本 |

---

## 修改文件清单

| 文件路径 | 修改内容 |
|----------|----------|
| `apps/account/domain/services.py` | 1. 修复 min/max 逻辑；2. 添加负波动率校验 |
| `apps/macro/domain/entities.py` | 修复 normalize_currency_unit() 添加汇率转换 |
