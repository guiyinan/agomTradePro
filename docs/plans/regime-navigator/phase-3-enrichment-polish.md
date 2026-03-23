# Phase 3: 增强与打磨

> **父文档**: [regime-navigator-pulse-redesign-260323.md](regime-navigator-pulse-redesign-260323.md)
> **前置依赖**: Phase 1 + Phase 2 完成
> **预估周期**: 3-4 周
> **目标**: 补充 Pulse 指标、配置化、历史回溯、前端打磨

---

## 1. Pulse V2: 流动性脉搏补全（Week 12-13）

### 1.1 新增 DR007 Fetcher

DR007（银行间质押式回购加权利率 7 天）是中国银行间市场最核心的利率指标，比 SHIBOR 更真实地反映短期流动性松紧。

**文件**: `apps/macro/infrastructure/adapters/fetchers/financial_fetchers.py`（追加方法）

```python
def fetch_dr007(self, start_date: date, end_date: date) -> list[MacroDataPoint]:
    """获取 DR007 数据

    数据源: akshare - macro_china_market_interest_rate
    频率: 日频
    """
```

**指标代码**: `CN_DR007`
**单位**: `%`
**信号逻辑**:
- DR007 < 央行逆回购利率 → 流动性宽松 → bullish (+0.8)
- DR007 > 逆回购利率 + 50BP → 流动性紧张 → bearish (-0.8)
- 否则线性插值

### 1.2 新增央行公开市场操作 Fetcher

央行每日逆回购操作的净投放/回笼是最直接的政策意图信号。

**文件**: `apps/macro/infrastructure/adapters/fetchers/financial_fetchers.py`（追加方法）

```python
def fetch_pboc_open_market(self, start_date: date, end_date: date) -> list[MacroDataPoint]:
    """获取央行公开市场操作数据

    数据源: akshare - macro_china_open_market / 央行公开市场数据
    频率: 日频，汇总为周频
    计算: 周净投放 = 本周逆回购投放 + MLF投放 - 本周到期量
    """
```

**指标代码**: `CN_PBOC_NET_INJECTION`
**单位**: `亿元`
**信号逻辑**:
- 周净投放 > 1000亿 → 积极放松 → bullish (+0.8)
- 周净投放 < -500亿 → 回笼流动性 → bearish (-0.6)
- 连续 3 周净投放 → 强 bullish (+1.0)

### 1.3 更新 Pulse 指标注册

**文件**: `apps/pulse/infrastructure/data_provider.py`

在指标列表中注册新指标并设置维度归属：

```python
PULSE_INDICATORS = [
    # Growth
    {"code": "CN_TERM_SPREAD_10Y2Y", "dimension": "growth", "name": "国债利差(10Y-2Y)"},
    {"code": "CN_NEW_CREDIT", "dimension": "growth", "name": "新增信贷"},
    # Inflation
    {"code": "CN_NHCI", "dimension": "inflation", "name": "南华商品指数"},
    # Liquidity (扩充)
    {"code": "CN_SHIBOR", "dimension": "liquidity", "name": "SHIBOR(1M)"},
    {"code": "CN_CREDIT_SPREAD", "dimension": "liquidity", "name": "信用利差"},
    {"code": "CN_M2", "dimension": "liquidity", "name": "M2增速"},
    {"code": "CN_DR007", "dimension": "liquidity", "name": "DR007"},           # NEW
    {"code": "CN_PBOC_NET_INJECTION", "dimension": "liquidity", "name": "央行净投放"},  # NEW
    # Sentiment
    {"code": "VIX_INDEX", "dimension": "sentiment", "name": "VIX恐慌指数"},
    {"code": "USD_INDEX", "dimension": "sentiment", "name": "美元指数"},
]
```

流动性脉搏从 3 个指标扩展到 5 个，成为信号最密集的维度——符合"流动性是A股核心驱动力"的市场特征。

---

## 2. Pulse 配置化（Week 13）

### 2.1 数据库配置模型

**文件**: `apps/pulse/infrastructure/models.py`（追加）

```python
class PulseWeightConfig(models.Model):
    """Pulse 指标权重配置"""

    name = models.CharField("配置名称", max_length=100)
    is_active = models.BooleanField("是否激活", default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "pulse_weight_config"


class PulseIndicatorWeight(models.Model):
    """单个指标的权重配置"""

    config = models.ForeignKey(PulseWeightConfig, on_delete=models.CASCADE, related_name="weights")
    indicator_code = models.CharField("指标代码", max_length=50)
    dimension = models.CharField("维度", max_length=20)
    weight = models.FloatField("权重", default=1.0)
    is_enabled = models.BooleanField("是否启用", default=True)

    class Meta:
        db_table = "pulse_indicator_weight"
```

### 2.2 Management Command

```bash
# 初始化默认权重
python manage.py init_pulse_weights

# 调整权重
python manage.py set_pulse_weight --indicator CN_DR007 --weight 1.2

# 查看当前配置
python manage.py show_pulse_config
```

### 2.3 维度权重配置

Phase 1 使用等权（每个维度 0.25）。Phase 3 支持通过数据库调整维度权重。

初始推荐值（基于A股市场特征）：

| 维度 | Phase 1 权重 | Phase 3 推荐 | 理由 |
|------|-------------|-------------|------|
| 增长 | 0.25 | 0.30 | 增长是 regime 最核心的驱动 |
| 通胀 | 0.25 | 0.20 | 中国通胀波动较小，区分度低 |
| 流动性 | 0.25 | 0.30 | A股流动性驱动特征强 |
| 情绪 | 0.25 | 0.20 | 外部指标，影响间接 |

---

## 3. 历史 Regime + Pulse 时序图（Week 13-14）

### 3.1 API

**端点**: `GET /api/regime/navigator/history/?months=12`

返回指定时间范围内的历史数据：

```json
{
  "period": {"start": "2025-03-01", "end": "2026-03-23"},
  "regime_transitions": [
    {"date": "2025-04-15", "from": "Deflation", "to": "Recovery", "confidence": 0.45},
    {"date": "2025-09-20", "from": "Recovery", "to": "Overheat", "confidence": 0.52}
  ],
  "pulse_history": [
    {"date": "2026-03-14", "composite": 0.15, "growth": 0.3, "inflation": -0.1, "liquidity": -0.2, "sentiment": 0.6},
    {"date": "2026-03-07", "composite": 0.22, ...}
  ],
  "action_history": [
    {"date": "2026-03-14", "equity": 0.55, "bond": 0.30, "commodity": 0.05, "cash": 0.10}
  ]
}
```

### 3.2 ECharts 可视化

在 Dashboard 或独立页面增加历史时序图：

- **上方面板**: Regime 象限色带（用颜色块标记每个时期的 regime）
- **中间折线**: Pulse 综合分数时序（含 4 维度分线可切换显示）
- **下方堆叠面积图**: Action Recommendation 资产配置历史

交互：鼠标悬停某个日期可查看当时的完整 Navigator 输出。

### 3.3 数据来源

- Regime 历史：`RegimeLog` 模型（已有）
- Pulse 历史：`PulseLog` 模型（Phase 1 创建）
- Action 历史：需在 Phase 1 的 `GetActionRecommendationUseCase` 中增加持久化

---

## 4. 前端打磨（Week 14-15）

### 4.1 Regime 色调体系

Dashboard 和决策工作台的整体色调随 regime 变化：

```css
/* 页面级微妙色调（不是背景色，是 subtle tint） */
body.regime-recovery    { --regime-tint: rgba(16, 185, 129, 0.03); }
body.regime-overheat    { --regime-tint: rgba(245, 158, 11, 0.03); }
body.regime-stagflation { --regime-tint: rgba(239, 68, 68, 0.03); }
body.regime-deflation   { --regime-tint: rgba(59, 130, 246, 0.03); }

.main-content {
    background-color: var(--regime-tint);
}
```

### 4.2 响应式适配

确保 regime 状态栏和 pulse 仪表盘在移动端可用：

- 状态栏在窄屏时折叠为 icon + badge
- Pulse 四维仪表盘在移动端变为 2×2 网格
- 决策漏斗步骤器变为垂直布局

### 4.3 引导教学

首次使用时展示引导覆盖层，解释：
1. 什么是 Regime（30 秒）
2. 什么是 Pulse（30 秒）
3. 日常模式怎么用（30 秒）
4. 怎么发起新决策（30 秒）

复用现有 `core/static/css/teaching.css` 样式。

### 4.4 Pulse 变化通知

当 Pulse 综合评估从 strong 变为 weak，或触发转折预警时：

- Dashboard "今日关注"卡片新增 pulse 变化条目
- 可选：浏览器 Notification（用户可在设置中开启）

---

## 5. 回测验证（可选，Phase 3+）

### 5.1 Pulse 历史回测

使用历史数据验证 Pulse 信号的有效性：

```bash
python manage.py backtest_pulse --start 2020-01-01 --end 2025-12-31
```

输出：
- 各维度信号的准确率 / 召回率
- Pulse 综合分数与市场收益的相关性
- 转折预警的领先天数统计

### 5.2 Action Recommendation 回测

```bash
python manage.py backtest_action --start 2020-01-01 --end 2025-12-31
```

输出：
- Regime + Pulse 联合推荐的配置 vs 等权配置 vs 固定 60/40 配置
- 各 regime 阶段推荐的 Sharpe Ratio
- 最大回撤对比

---

## 6. 交付物清单

| 交付物 | 类型 |
|--------|------|
| `apps/macro/.../financial_fetchers.py` DR007 + 央行净投放 fetcher | 修改 |
| `apps/pulse/infrastructure/models.py` PulseWeightConfig | 修改 |
| `apps/pulse/management/commands/init_pulse_weights.py` | 新建 |
| `apps/pulse/management/commands/set_pulse_weight.py` | 新建 |
| `/api/regime/navigator/history/` 端点 | 新建 |
| 历史时序图 ECharts 模板 | 新建 |
| Regime 色调 CSS | 修改 |
| 响应式适配 | 修改 |
| 引导教学覆盖层 | 新建 |
| `management/commands/backtest_pulse.py` (可选) | 新建 |
| `management/commands/backtest_action.py` (可选) | 新建 |
