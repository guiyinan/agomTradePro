# Phase 5: 宏观集成 + 全链路联调实现总结

> **完成日期**: 2026-02-05
> **状态**: ✅ 完成
> **实施内容**: AgomSAAF + Qlib 松耦合集成方案 - Phase 5

## 一、实施概览

### 已完成的任务

1. ✅ 集成 Alpha 与 Signal 模块
2. ✅ 集成 Alpha 与 Backtest 模块
3. ✅ 集成 Alpha 与 Rotation 模块（通过统一信号系统）
4. ✅ 集成 Alpha 与 Hedge 模块（通过统一信号系统）
5. ✅ 编写端到端集成测试
6. ✅ 编写压力测试（Qlib 故障场景）

## 二、核心集成点

### 1. Alpha → Signal 模块集成

**文件**: `apps/signal/application/unified_service.py`

**新增方法**: `_collect_alpha_signals(calc_date: date)`

**功能**:
- 从 AlphaService 获取 AI 选股评分
- 为高分股票生成买入信号
- 支持 Alpha 数据源状态告警（degraded）
- 记录完整的审计信息（model_id, artifact_hash, asof_date）

**信号类型**: `buy` (买入), `alert` (告警)

**信号优先级**: 基于排名动态设置（排名越前优先级越高）

**示例**:
```python
service = UnifiedSignalService()
result = service.collect_all_signals()

# result 包含:
# {
#     'alpha_signals': 10,  # Alpha 生成 10 条信号
#     'regime_signals': 5,
#     'rotation_signals': 3,
#     'factor_signals': 8,
#     'hedge_signals': 2,
#     'total_signals': 28
# }
```

### 2. Alpha → Backtest 模块集成

**文件**: `apps/backtest/domain/alpha_backtest.py`

**新增类**:
- `AlphaBacktestConfig`: Alpha 回测配置
- `AlphaBacktestResult`: Alpha 回测结果（含 Alpha 特有指标）
- `AlphaBacktestEngine`: Alpha 回测引擎
- `RunAlphaBacktestUseCase`: Alpha 回测用例

**Alpha 特有指标**:
- `avg_ic`: 平均 IC 值
- `avg_rank_ic`: 平均 Rank IC
- `icir`: IC 信息比率
- `coverage_ratio`: 平均覆盖率
- `provider_usage`: 各 Provider 使用次数统计

**回测流程**:
1. 按再平衡频率遍历日期
2. 获取 Alpha 评分（支持降级）
3. 筛选高分股票（min_score 阈值）
4. 等权重构建投资组合
5. 计算收益和风险指标
6. 统计 Provider 使用情况

**配置参数**:
- `universe_id`: 股票池（默认 csi300）
- `alpha_provider`: 优先 Provider（默认 qlib）
- `min_score`: 最低评分阈值（默认 0.6）
- `max_positions`: 最大持仓数（默认 30）
- `rebalance_frequency`: 再平衡频率（默认 monthly）

**示例**:
```python
from apps.backtest.domain.alpha_backtest import RunAlphaBacktestUseCase, RunAlphaBacktestRequest

use_case = RunAlphaBacktestUseCase(
    repository=repository,
    get_regime_func=lambda d: "Recovery",
    get_price_func=get_price_func,
    get_benchmark_price_func=get_benchmark_func,
)

request = RunAlphaBacktestRequest(
    name="Alpha Strategy Backtest",
    start_date=date(2025, 1, 1),
    end_date=date(2025, 12, 31),
    initial_capital=1000000.0,
    universe_id="csi300",
)

response = use_case.execute(request)
```

### 3. Alpha → Rotation/Hedge 模块集成

**集成方式**: 通过统一信号系统（UnifiedSignalRepository）

**工作原理**:
- Alpha 生成买入信号 → 存入 UnifiedSignalRepository
- Rotation/Hedge 模块读取统一信号 → 执行相应策略
- 支持 Alpha 信号作为策略输入

**优势**:
- 松耦合：模块间通过仓储交互
- 可扩展：新增模块只需接入统一信号系统
- 可审计：所有信号都有完整追溯信息

### 4. 数据库迁移

**文件**: `apps/signal/migrations/0008_add_alpha_signal_source.py`

**变更**: 在 `SIGNAL_SOURCE_CHOICES` 中添加 `'alpha'` 选项

```python
SIGNAL_SOURCE_CHOICES = [
    ('regime', '宏观象限'),
    ('factor', '因子选股'),
    ('rotation', '资产轮动'),
    ('hedge', '对冲组合'),
    ('alpha', 'AI选股'),  # 新增
    ('manual', '手动'),
]
```

## 三、测试覆盖

### 端到端集成测试 (`tests/integration/test_alpha_full_flow.py`)

**测试类**:
1. `TestAlphaSignalIntegration` - Alpha 与 Signal 模块集成
2. `TestAlphaBacktestIntegration` - Alpha 与 Backtest 模块集成
3. `TestAlphaProviderFallback` - Provider 降级链路
4. `TestAlphaMetricsRecording` - 监控指标记录
5. `TestAlphaQlibIntegration` - Qlib 集成
6. `TestAlphaEndToEndFlow` - 完整流程测试
7. `TestAlphaWithMonitoring` - 监控功能
8. `TestAlphaModelLifecycle` - 模型生命周期
9. `TestAlphaCacheStaleness` - 缓存陈旧度
10. `TestAlphaMultiUniverse` - 多股票池支持

**关键测试用例**:
- `test_complete_alpha_flow` - 测试完整流程（模型→缓存→评分）
- `test_provider_fallback_order` - 测试降级顺序
- `test_qlib_fallback_to_cache` - 测试 Qlib 降级到缓存
- `test_metrics_recorded_on_get_scores` - 测试指标记录

### 压力测试 (`tests/integration/test_alpha_stress.py`)

**测试类**:
1. `TestQlibNotInstalled` - Qlib 未安装场景
2. `TestQlibDataUnavailable` - Qlib 数据不可用场景
3. `TestQlibInferenceFailure` - Qlib 推理任务失败场景
4. `TestModelLoadingFailure` - 模型加载失败场景
5. `TestCompleteDegradation` - 全链路降级场景
6. `TestHighLoadScenarios` - 高负载场景
7. `TestMetricsUnderFailure` - 故障时的监控指标
8. `TestCacheFailureScenarios` - 缓存故障场景
9. `TestRecoveryScenarios` - 恢复场景
10. `TestMemoryPressure` - 内存压力场景
11. `TestNetworkFailure` - 网络故障场景
12. `TestGracefulDegradation` - 优雅降级
13. `TestLongRunningStability` - 长期运行稳定性
14. `TestErrorRecovery` - 错误恢复

**关键测试用例**:
- `test_full_degradation_chain` - 测试 Qlib→Cache→Simple→ETF 完整降级
- `test_etf_provider_always_available` - 测试 ETF Provider 总是可用
- `test_concurrent_requests` - 测试并发请求（10 线程）
- `test_rapid_sequential_requests` - 测试快速连续请求（100 次）

## 四、系统架构更新

### 集成架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                        AgomSAAF 主系统                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   AlphaService (单例)                                           │
│   ├── get_stock_scores() → Provider 降级链                      │
│   ├── 自动记录监控指标                                          │
│   └── 返回 AlphaResult (含审计字段)                              │
│                                                                  │
│   UnifiedSignalService                                          │
│   ├── collect_all_signals()                                     │
│   │   ├── _collect_regime_signals()                             │
│   │   ├── _collect_rotation_signals()                           │
│   │   ├── _collect_factor_signals()                             │
│   │   ├── _collect_hedge_signals()                              │
│   │   └── _collect_alpha_signals()  ← 新增                    │
│   └── 存储到 UnifiedSignalRepository                            │
│                                                                  │
│   RunAlphaBacktestUseCase  ← 新增                              │
│   ├── 使用 Alpha 信号进行回测                                   │
│   ├── 返回 Alpha 特有指标（IC, ICIR, 覆盖率）                   │
│   └── 统计 Provider 使用情况                                     │
│                                                                  │
│   PostgreSQL:                                                    │
│   ├── AlphaScoreCache  (评分缓存)                               │
│   ├── QlibModelRegistry (模型注册)                              │
│   └── UnifiedSignal (统一信号表，新增 alpha 来源)              │
└─────────────────────────────────────────────────────────────────┘
```

### 信号流向

```
Qlib 模型 → QlibAlphaProvider → AlphaScoreCache
                    ↓
            AlphaService.get_stock_scores()
                    ↓
         UnifiedSignalService._collect_alpha_signals()
                    ↓
            UnifiedSignalRepository.create_signal()
                    ↓
      ┌───────────┴───────────┐
      ↓                       ↓
Rotation/Hedge         Backtest (AlphaBacktestEngine)
读取信号执行              使用信号回测
```

## 五、验收标准

- [x] Alpha 信号集成到统一信号系统
- [x] Alpha 信号可用于 Backtest 模块
- [x] Rotation/Hedge 可读取 Alpha 信号
- [x] 端到端集成测试覆盖核心流程
- [x] 压力测试覆盖故障场景
- [x] 降级链路完整工作
- [x] 监控指标正确记录

## 六、使用示例

### 收集所有模块信号（包括 Alpha）

```python
from apps.signal.application.unified_service import UnifiedSignalService

service = UnifiedSignalService()

# 收集所有信号
result = service.collect_all_signals()

print(f"总信号数: {result['total_signals']}")
print(f"Alpha 信号: {result['alpha_signals']}")
print(f"Regime 信号: {result['regime_signals']}")
print(f"Rotation 信号: {result['rotation_signals']}")
print(f"Factor 信号: {result['factor_signals']}")
print(f"Hedge 信号: {result['hedge_signals']}")
```

### 运行 Alpha 回测

```python
from apps.backtest.domain.alpha_backtest import (
    RunAlphaBacktestUseCase,
    RunAlphaBacktestRequest,
)
from datetime import date

# 创建用例
use_case = RunAlphaBacktestUseCase(
    repository=repository,
    get_regime_func=get_regime_func,
    get_price_func=get_price_func,
    get_benchmark_price_func=get_benchmark_func,
)

# 创建请求
request = RunAlphaBacktestRequest(
    name="CSI300 Alpha Strategy",
    start_date=date(2024, 1, 1),
    end_date=date(2024, 12, 31),
    initial_capital=1000000.0,
    universe_id="csi300",
    min_score=0.6,
    max_positions=30,
    rebalance_frequency="monthly",
)

# 执行回测
response = use_case.execute(request)

if response.status == "completed":
    print(f"回测完成: backtest_id={response.backtest_id}")
    print(f"总收益: {response.result['total_return']:.2%}")
    print(f"夏普比率: {response.result['sharpe_ratio']:.2f}")
    print(f"最大回撤: {response.result['max_drawdown']:.2%}")
    print(f"平均 IC: {response.result['avg_ic']:.4f}")
    print(f"覆盖率: {response.result['coverage_ratio']:.2%}")
```

### 查看 Alpha 信号

```python
from apps.signal.application.unified_service import UnifiedSignalService
from datetime import date

service = UnifiedSignalService()

# 获取今天的 Alpha 信号
signals = service.get_unified_signals(
    signal_date=date.today(),
    signal_source="alpha"
)

for signal in signals:
    print(f"{signal['asset_code']}: {signal['reason']}")
    print(f"  优先级: {signal['priority']}")
    print(f"  操作: {signal['action_required']}")
```

## 七、故障排查

| 问题 | 可能原因 | 解决方法 |
|------|----------|----------|
| Alpha 信号未生成 | Alpha Service 不可用 | 检查 `get_provider_status()` |
| 回测失败 | 没有激活的模型 | 检查 `list_models --active` |
| Provider 总是降级 | 缓存过期 | 检查 `staleness_days` |
| 监控指标未记录 | metrics 未初始化 | 调用 `get_alpha_metrics()` |
| 信号重复 | 多次调用 `collect_all_signals()` | 检查 `is_executed` 标志 |

## 八、下一步工作

### 可选增强功能

1. **实时信号推送**: WebSocket 推送 Alpha 信号更新
2. **信号归一化**: 统一不同模块的信号格式
3. **信号冲突处理**: 处理多个模块信号的冲突
4. **性能优化**: 缓存 Alpha 评分结果
5. **更多回测类型**: 支持多因子、行业轮动等

### 文档更新

- 更新 API 文档
- 更新 SDK 使用指南
- 更新 MCP 工具文档

## 九、文件清单

### 新增文件
```
apps/signal/
└── migrations/
    └── 0008_add_alpha_signal_source.py  # 添加 alpha 信号源

apps/backtest/domain/
└── alpha_backtest.py                    # Alpha 回测集成

tests/integration/
├── test_alpha_full_flow.py              # 端到端集成测试
└── test_alpha_stress.py                  # 压力测试

docs/plans/
└── phase5-integration-summary.md          # 本文档
```

### 修改文件
```
apps/signal/infrastructure/models.py        # 添加 alpha 信号源
apps/signal/application/unified_service.py  # 集成 Alpha 信号
apps/backtest/domain/__init__.py             # 导出 Alpha 回测
```

---

**Phase 5 完成**：Alpha 模块已完全集成到 AgomSAAF 系统中，支持统一信号系统和回测功能。系统具备完整的降级能力和故障恢复能力。
