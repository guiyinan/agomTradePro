# Regime Dashboard 前端展示改进方案

## 概述

本文档说明 Regime 判定结果的前端展示改进，基于新的 V2.0 判定逻辑。

### 2026-03-31 交互调整

- 取消 Regime Dashboard 首次访问时自动弹出的 onboarding 蒙版与欢迎模态。
- 保留手动触发的“学习Regime判定”入口，避免页面访问被强制打断。

### 2026-04-12 Alpha 表格布局调整

- Dashboard 的 `Top 10 选股结果` 区块改为更偏向左侧表格的双栏比例，减少大屏下表格可视宽度不足的问题。
- Alpha 选股表增加横向滚动容器和最小表宽，页面放大或浏览器缩放时优先横向滚动，不再因换行导致单行高度明显增大。
- 表头、单元格与操作按钮改为更紧凑的 `nowrap` 布局，保持 Top 10 列表的密度与可读性。
- Dashboard 主 Workflow 面板的“可行动候选/待执行队列”现在会补充并显示资产名称，避免只有代码不显示证券名称。

### 2026-04-12 Alpha 决策链可视化

- Dashboard 不再把 `Top 10 选股结果` 与 `可行动候选/待执行队列` 作为两块孤立信息展示。
- `Top 10 选股结果` 上方新增 `Alpha 决策链` 概览，直接显示：
  - Top 10 中有多少已进入 `可行动`
  - Top 10 中有多少已进入 `待执行`
  - 还有多少仍停留在纯排名阶段
- Top 10 表格新增 `链路状态` 列，每只股票会明确标记为：
  - `仅在 Alpha Top 排名`
  - `可行动候选`
  - `待执行队列`
- 主 Workflow 面板新增 `Alpha 决策链收束` 关系条，并在候选/待执行行内显示其当前 Top 10 位置与 Alpha 分数，形成页面内可追踪的业务链。

---

## 展示组件设计

### 1. Regime 状态卡片 (RegimeStatusCard)

**位置：** 顶部左侧

**展示内容：**
```
┌─────────────────────────────────────┐
│  当前 Regime: Deflation（通缩）      │
│  ████░░░░░  置信度: 33.5%           │
│                                     │
│  PMI: 49.3  ● 制造业收缩             │
│  CPI: 0.8%   ● 低通胀               │
│                                     │
│  [详情] [历史] [配置]                │
└─────────────────────────────────────┘
```

**样式规范：**
- **Deflation**：蓝色 (#3b82f6)
- **Overheat**：红色 (#ef4444)
- **Recovery**：绿色 (#22c55e)
- **Stagflation**：橙色 (#f59e0b)

**状态标识：**
- expansion（扩张）：绿色圆点 ●
- contraction（收缩）：红色圆点 ●
- high inflation：红色箭头 ↑
- low inflation：蓝色箭头 ↓
- deflation：蓝色双箭头 ↓↓

---

### 2. 四象限分布图 (RegimeDistributionChart)

**位置：** 顶部中央

**展示内容：**
```
┌─────────────────────────────────────┐
│         四象限概率分布                │
│                                     │
│         Recovery                    │
│     ● 29.6% (绿色)                 │
│                                     │
│  Stagflation   Overheat            │
│   ● 18.8%      ● 18.1%             │
│   (橙色)      (红色)                │
│                                     │
│       Deflation                    │
│      ● 33.5% (蓝色) ← 主导          │
│                                     │
│  [雷达图] [饼图] [柱状图]           │
└─────────────────────────────────────┘
```

**图表类型：**
1. **雷达图**：展示四象限的相对强度
2. **饼图/环形图**：展示概率分布
3. **热力图**：颜色深浅表示概率高低

---

### 3. 趋势指标面板 (TrendIndicatorsPanel)

**位置：** 顶部右侧

**展示内容：**
```
┌─────────────────────────────────────┐
│  趋势指标                            │
│                                     │
│  PMI (49.3)                          │
│  ├─ 动量: +0.3 ▲ (moderate)         │
│  ├─ Z-score: +0.5                    │
│  └─ 趋势: [=======>---] 上升         │
│                                     │
│  CPI (0.8%)                          │
│  ├─ 动量: +1.1 ▲ (strong)           │
│  ├─ Z-score: +1.7                    │
│  └─ 趋势: [========>] 强烈上升     │
│                                     │
│  [趋势图] [历史对比]                 │
└─────────────────────────────────────┘
```

**动量强度标识：**
- **weak**：浅色背景 (#e5e7eb)
- **moderate**：中等背景 (#fbbf24)
- **strong**：深色背景 (#f59e0b)

**方向图标：**
- 上升：▲
- 下降：▼
- 持平：▶

---

### 4. 预测提示 (PredictionAlert)

**位置：** 中部左侧（可折叠）

**展示内容：**
```
┌─────────────────────────────────────┐
│  📊 趋势预测                         │
│                                     │
│  基于当前数据和趋势分析：             │
│                                     │
│  ✅ PMI 呈上升趋势，经济动能增强       │
│  ⚠️  CPI 呈上升趋势，需关注压力       │
│                                     │
│  预测：可能转向复苏或滞胀            │
│       （取决于哪个指标先起）          │
│                                     │
│  [详情分析] [历史验证]               │
└─────────────────────────────────────┘
```

**预测级别：**
- 🟢 **高置信度**：趋势明确，概率 > 70%
- 🟡 **中等置信度**：趋势较明确，概率 40-70%
- 🔴 **低置信度**：趋势不明，概率 < 40%

---

### 5. 历史时间线 (RegimeTimeline)

**位置：** 中部中央

**展示内容：**
```
┌─────────────────────────────────────┐
│  Regime 历史演变                     │
│                                     │
│  2023-01 ━━━━━━━━                   │
│  ● Deflation                         │
│                                     │
│  2023-06 ━━━━━━━━                   │
│  ● Recovery                          │
│                                     │
│  2024-01 ━━━━━━━━                   │
│  ● Overheat                          │
│                                     │
│  2024-06 ━━━━━━━━                   │
│  ● Stagflation                       │
│                                     │
│  2025-01 ━━━━━━━━                   │
│  ● Deflation ◀─ 当前                │
│                                     │
│  [更多历史] [导出数据]               │
└─────────────────────────────────────┘
```

**交互功能：**
- 点击节点查看详情
- 缩放时间范围
- 悬停显示概率分布

---

### 6. 阈值配置面板 (ThresholdConfigPanel)

**位置：** 右侧边栏（可切换）

**展示内容：**
```
┌─────────────────────────────────────┐
│  ⚙️ 阈值配置                         │
│                                     │
│  PMI 阈值                            │
│  ├─ 扩张阈值: [50.0]                │
│  ├─ 收缩阈值: [50.0]                │
│  └─ [应用] [重置]                    │
│                                     │
│  CPI 阈值                            │
│  ├─ 高通胀: [2.0]%                  │
│  ├─ 低通胀: [1.0]%                  │
│  ├─ 通缩: [0.0]%                    │
│  └─ [应用] [重置]                    │
│                                     │
│  趋势权重                            │
│  ├─ 动量权重: [0.3]                 │
│  └─ [应用]                           │
│                                     │
│  [保存配置] [导出配置] [恢复默认]    │
└─────────────────────────────────────┘
```

**实时预览：**
- 调整阈值后，实时显示 Regime 变化
- 使用「应用」按钮确认修改
- 使用「重置」恢复到保存的值

---

## 页面布局

### 响应式布局

```
┌─────────────────────────────────────────────────────────────┐
│  导航栏: [仪表盘] [Regime] [宏观数据] [配置]                   │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐ │
│  │ Regime 状态     │ │ 四象限分布       │ │ 趋势指标         │ │
│  │                 │ │                 │ │                 │ │
│  │ Deflation       │ │   雷达图/饼图   │ │ PMI: ▲ moderate  │ │
│  │ ● 置信度 33.5% │ │                 │ │ CPI: ▲ strong    │ │
│  │                 │ │                 │ │                 │ │
│  └─────────────────┘ └─────────────────┘ └─────────────────┘ │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ 📊 趋势预测                                            │ │
│  │                                                         │ │
│  │ 预测: 可能转向复苏或滞胀（取决于哪个指标先起）          │ │
│  │                                                         │ │
│  └─────────────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────┤
│  ┌───────────────────────────────┐ ┌───────────────────────┐ │
│  │ Regime 历史时间线            │ │ PMI 历史趋势图        │ │
│  │                             │ │                       │ │
│  │ [时间线可视化]               │ │ [折线图 + 动量]       │ │
│  │                             │ │                       │ │
│  └───────────────────────────────┘ └───────────────────────┘ │
├─────────────────────────────────────────────────────────────┤
│  ┌───────────────────────────────┐ ┌───────────────────────┐ │
│  │ CPI 历史趋势图               │ │ 数据详情表格          │ │
│  │                             │ │                       │ │
│  │ [折线图 + 动量]               │ │ [PMI, CPI, ...]       │ │
│  │                             │ │                       │ │
│  └───────────────────────────────┘ └───────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

---

## API 接口

### 获取当前 Regime

```http
GET /api/regime/current/

Response:
{
  "regime": "Deflation",
  "confidence": 0.335,
  "growth_level": 49.3,
  "inflation_level": 0.8,
  "growth_state": "contraction",
  "inflation_state": "low",
  "distribution": {
    "Recovery": 0.296,
    "Overheat": 0.181,
    "Stagflation": 0.188,
    "Deflation": 0.335
  },
  "trend_indicators": [
    {
      "indicator_code": "PMI",
      "current_value": 49.3,
      "momentum": 0.3,
      "momentum_z": 0.5,
      "direction": "up",
      "strength": "moderate"
    },
    {
      "indicator_code": "CPI",
      "current_value": 0.8,
      "momentum": 1.1,
      "momentum_z": 1.7,
      "direction": "up",
      "strength": "strong"
    }
  ],
  "prediction": "可能转向复苏或滞胀（取决于哪个指标先起）"
}
```

### 更新阈值配置

```http
POST /api/regime/config/thresholds/

Request:
{
  "pmi_expansion": 50.0,
  "pmi_contraction": 50.0,
  "cpi_high": 2.0,
  "cpi_low": 1.0,
  "cpi_deflation": 0.0
}

Response:
{
  "success": true,
  "new_regime": "Recovery",
  "new_confidence": 0.42
}
```

---

## 颜色方案

### Regime 颜色

| Regime | 主色 | 浅色 | 文字 |
|--------|------|------|------|
| Deflation | #3b82f6 | #dbeafe | #1e40af |
| Overheat | #ef4444 | #fecaca | #991b1b |
| Recovery | #22c55e | #bbf7d0 | #15803d |
| Stagflation | #f59e0b | #fed7aa | #b45309 |

### 趋势颜色

| 趋势 | 颜色 | 图标 |
|------|------|------|
| 上升 | #22c55e | ▲ |
| 下降 | #ef4444 | ▼ |
| 持平 | #6b7280 | ▶ |

### 强度颜色

| 强度 | 颜色 | 背景 |
|------|------|------|
| weak | #9ca3af | #f3f4f6 |
| moderate | #fbbf24 | #fef3c7 |
| strong | #f59e0b | #ffedd5 |

---

## 组件实现建议

### React / TypeScript

```typescript
// types.ts
interface RegimeData {
  regime: RegimeType;
  confidence: number;
  growth_level: number;
  inflation_level: number;
  growth_state: GrowthState;
  inflation_state: InflationState;
  distribution: Record<RegimeType, number>;
  trend_indicators: TrendIndicator[];
  prediction: string | null;
}

// components/RegimeCard.tsx
export function RegimeCard({ data }: { data: RegimeData }) {
  const regimeColor = getRegimeColor(data.regime);
  const regimeIcon = getRegimeIcon(data.regime);

  return (
    <Card className="regime-card">
      <CardHeader>
        <CardTitle>
          <span className={`status-indicator ${data.regime.toLowerCase()}`}>
            {regimeIcon}
          </span>
          当前 Regime: {formatRegimeName(data.regime)}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="confidence-bar">
          <LinearProgress
            variant="determinate"
            value={data.confidence * 100}
            sx={{ backgroundColor: regimeColor }}
          />
          <Typography variant="caption">
            置信度: {formatPercent(data.confidence)}
          </Typography>
        </div>
        <div className="indicators">
          <IndicatorRow
            label="PMI"
            value={data.growth_level}
            state={data.growth_state}
          />
          <IndicatorRow
            label="CPI"
            value={data.inflation_level}
            suffix="%"
            state={data.inflation_state}
          />
        </div>
      </CardContent>
    </Card>
  );
}
```

### Django Template (传统方案)

```html
<!-- templates/regime/dashboard.html -->
<div class="regime-dashboard">
  <!-- Regime 状态卡片 -->
  <div class="regime-card regime-{{ regime|lower }}">
    <h2>
      <span class="status-icon">{{ status_icon }}</span>
      当前 Regime: {{ regime_name }}
    </h2>
    <div class="confidence-container">
      <div class="confidence-bar" style="width: {{ confidence|floatformat:0% }}"></div>
      <span class="confidence-label">{{ confidence|floatformat:0.1% }}</span>
    </div>
    <div class="indicators">
      <div class="indicator">
        <span class="label">PMI:</span>
        <span class="value">{{ growth_level }}</span>
        <span class="state state-{{ growth_state }}">{{ growth_state_name }}</span>
      </div>
      <div class="indicator">
        <span class="label">CPI:</span>
        <span class="value">{{ inflation_level }}%</span>
        <span class="state state-{{ inflation_state }}">{{ inflation_state_name }}</span>
      </div>
    </div>
  </div>

  <!-- 更多组件... -->
</div>
```

---

## 实现优先级

### Phase 1: 核心展示（P0）

1. ✅ Regime 状态卡片
2. ✅ 四象限分布图
3. ✅ 趋势指标面板
4. ✅ 基础 API 接口

### Phase 2: 增强功能（P1）

1. ⏳ 预测提示组件
2. ⏳ 历史时间线
3. ⏳ 趋势图表（Chart.js / ECharts）
4. ⏳ 数据详情表格

### Phase 3: 配置管理（P2）

1. ⏳ 阈值配置面板
2. ⏳ 实时预览功能
3. ⏳ 配置导入/导出
4. ⏳ 配置历史版本

---

## 相关文件

- **后端**: `apps/regime/interface/views.py`
- **前端**: `core/templates/regime/dashboard.html`
- **API**: `core/urls.py`
- **样式**: `core/static/css/regime.css`
