# 投资组合策略系统 - 实施计划

> **项目**: AgomTradePro 投资组合策略管理系统
> **目标**: 为每个投资组合提供自定义交易策略、风控指标和AI集成能力
> **实施周期**: 6-8周
> **创建日期**: 2026-01-05

---

## 一、需求概述

### 1.1 核心需求

用户希望为每个投资组合实现：
1. **自定义策略**: 每个投资组合可以配置不同的交易策略
2. **多种策略定义方式**:
   - 简单规则配置（JSON格式，低门槛）
   - 脚本定义（受限Python，高灵活性）
   - AI驱动策略（集成现有AI Prompt系统）
3. **独立风控**: 每个策略有独立的风控参数
4. **AI集成**: 策略可以调用AI进行投资决策

### 1.2 用户确认的技术选型

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 规则语法 | **JSON格式** | 易读、易编辑、支持复杂逻辑 |
| 脚本语言 | **受限Python** | 用户熟悉、生态丰富、沙箱隔离 |
| AI执行模式 | **条件审核+自动执行** | 基于置信度灵活选择 |
| 实施范围 | **全部功能** | 完整的策略管理系统 |

---

## 二、系统架构设计

### 2.1 整体架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                        Interface 层                              │
│  (StrategyViewSet, RuleConditionViewSet, API端点)                │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Application 层                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐     │
│  │ RuleEngine   │  │ScriptEngine  │  │ AIStrategy       │     │
│  │              │  │              │  │ Executor         │     │
│  └──────────────┘  └──────────────┘  └──────────────────┘     │
│                              │                                   │
│                      ┌───────────────┐                          │
│                      │ Strategy      │                          │
│                      │ Executor      │                          │
│                      │ (中央调度器)  │                          │
│                      └───────────────┘                          │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                       Domain 层                                  │
│  (Strategy, RuleCondition, SignalRecommendation 实体)           │
│  (MacroIndicatorEvaluator, RegimeEvaluator 规则评估器)          │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Infrastructure 层                             │
│  (StrategyModel, RuleConditionModel, ScriptConfigModel)         │
│  (StrategyRepository, PortfolioStrategyRepository)              │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 数据模型设计

#### 新增Django模型

```python
# apps/strategy/infrastructure/models.py

class StrategyModel(models.Model):
    """策略主表"""
    name = models.CharField("策略名称", max_length=200)
    description = models.TextField("策略描述", blank=True)

    strategy_type = models.CharField(
        "策略类型",
        max_length=20,
        choices=[
            ('rule_based', '规则驱动'),
            ('script_based', '脚本驱动'),
            ('hybrid', '混合模式'),
            ('ai_driven', 'AI驱动')
        ]
    )

    version = models.PositiveIntegerField("版本号", default=1)
    is_active = models.BooleanField("是否激活", default=True)

    # 风控参数（策略级别）
    max_position_pct = models.FloatField("单资产最大持仓比例(%)", default=20.0)
    max_total_position_pct = models.FloatField("总持仓比例上限(%)", default=95.0)
    stop_loss_pct = models.FloatField("止损比例(%)", null=True, blank=True)

    # 元数据
    created_by = models.ForeignKey(
        'account.AccountProfileModel',
        on_delete=models.CASCADE,
        verbose_name="创建者"
    )
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        unique_together = [['name', 'version']]
        indexes = [
            models.Index(fields=['strategy_type', 'is_active']),
        ]

class RuleConditionModel(models.Model):
    """规则条件（用于rule_based策略）"""
    strategy = models.ForeignKey(
        StrategyModel,
        on_delete=models.CASCADE,
        related_name='rules',
        verbose_name="所属策略"
    )

    rule_name = models.CharField("规则名称", max_length=200)
    rule_type = models.CharField(
        "规则类型",
        max_length=50,
        choices=[
            ('macro', '宏观指标'),
            ('regime', 'Regime判定'),
            ('signal', '投资信号'),
            ('technical', '技术指标')
        ]
    )

    # JSON格式存储规则条件
    condition_json = models.JSONField("规则条件", verbose_name="条件表达式")

    action = models.CharField(
        "动作",
        max_length=50,
        choices=[
            ('buy', '买入'),
            ('sell', '卖出'),
            ('hold', '持有'),
            ('weight', '设置权重')
        ]
    )

    weight = models.FloatField("目标权重", null=True, blank=True)
    priority = models.IntegerField("优先级", default=0)
    is_enabled = models.BooleanField("是否启用", default=True)

    class Meta:
        verbose_name = "规则条件"
        ordering = ['-priority', 'id']

class ScriptConfigModel(models.Model):
    """脚本配置（用于script_based策略）"""
    strategy = models.OneToOneField(
        StrategyModel,
        on_delete=models.CASCADE,
        related_name='script_config',
        verbose_name="所属策略"
    )

    script_language = models.CharField(
        "脚本语言",
        max_length=20,
        choices=[('python', 'Python受限')]
    )

    script_code = models.TextField("脚本代码")
    script_hash = models.CharField("脚本哈希", max_length=64)

    # 沙箱配置
    sandbox_config = models.JSONField("沙箱配置", default=dict)
    allowed_modules = models.JSONField("允许的模块", default=list)

    class Meta:
        verbose_name = "脚本配置"

class AIStrategyConfigModel(models.Model):
    """AI策略配置"""
    strategy = models.OneToOneField(
        StrategyModel,
        on_delete=models.CASCADE,
        related_name='ai_config',
        verbose_name="所属策略"
    )

    prompt_template = models.ForeignKey(
        'prompt.PromptTemplateModel',
        on_delete=models.SET_NULL,
        null=True,
        verbose_name="Prompt模板"
    )

    chain_config = models.ForeignKey(
        'prompt.ChainConfigModel',
        on_delete=models.SET_NULL,
        null=True,
        verbose_name="链配置"
    )

    ai_provider = models.ForeignKey(
        'ai_provider.AIProviderConfigModel',
        on_delete=models.SET_NULL,
        null=True,
        verbose_name="AI服务商"
    )

    temperature = models.FloatField("温度参数", default=0.7)
    max_tokens = models.IntegerField("最大Token数", default=2000)

    # 审核模式
    approval_mode = models.CharField(
        "审核模式",
        max_length=20,
        choices=[
            ('always', '必须人工审核'),
            ('conditional', '条件审核（基于置信度）'),
            ('auto', '自动执行+监控')
        ],
        default='conditional'
    )

    confidence_threshold = models.FloatField(
        "自动执行置信度阈值",
        default=0.8,
        help_text="置信度高于此值时自动执行"
    )

    class Meta:
        verbose_name = "AI策略配置"

class PortfolioStrategyAssignmentModel(models.Model):
    """投资组合与策略的关联"""
    portfolio = models.ForeignKey(
        'simulated_trading.SimulatedAccountModel',
        on_delete=models.CASCADE,
        verbose_name="投资组合"
    )

    strategy = models.ForeignKey(
        StrategyModel,
        on_delete=models.CASCADE,
        verbose_name="策略"
    )

    assigned_at = models.DateTimeField("分配时间", auto_now_add=True)
    assigned_by = models.ForeignKey(
        'account.AccountProfileModel',
        on_delete=models.CASCADE,
        verbose_name="分配者"
    )
    is_active = models.BooleanField("是否激活", default=True)

    # 覆盖策略的默认风控参数（可选）
    override_max_position_pct = models.FloatField(null=True, blank=True)
    override_stop_loss_pct = models.FloatField(null=True, blank=True)

    class Meta:
        unique_together = [['portfolio', 'strategy']]
        verbose_name = "投资组合策略关联"

class StrategyExecutionLogModel(models.Model):
    """策略执行日志"""
    strategy = models.ForeignKey(StrategyModel, on_delete=models.CASCADE)
    portfolio = models.ForeignKey(
        'simulated_trading.SimulatedAccountModel',
        on_delete=models.CASCADE
    )

    execution_time = models.DateTimeField("执行时间", auto_now_add=True)
    execution_result = models.JSONField("执行结果")
    signals_generated = models.JSONField("生成的信号", default=list)
    error_message = models.TextField("错误信息", blank=True)
    execution_duration_ms = models.IntegerField("执行时长(ms)")

    class Meta:
        verbose_name = "策略执行日志"
        ordering = ['-execution_time']
        indexes = [
            models.Index(fields=['strategy', '-execution_time']),
            models.Index(fields=['portfolio', '-execution_time']),
        ]
```

### 2.3 规则引擎设计

#### JSON规则语法

```json
{
  "rule_name": "PMI复苏买入规则",
  "rule_type": "macro",
  "condition": {
    "operator": "AND",
    "conditions": [
      {
        "indicator": "CN_PMI_MANUFACTURING",
        "operator": ">",
        "threshold": 50
      },
      {
        "indicator": "CN_PMI_MANUFACTURING",
        "operator": "trend",
        "trend_type": "up",
        "period": 3
      },
      {
        "indicator": "regime",
        "operator": "==",
        "value": "Recovery"
      }
    ]
  },
  "action": "buy",
  "target_assets": ["000001.SH", "000300.SH"],
  "weight": 0.3
}
```

#### 支持的运算符

| 类型 | 运算符 | 说明 | 示例 |
|------|--------|------|------|
| 数值比较 | `>`, `<`, `>=`, `<=`, `==`, `!=` | 基础比较 | `{"indicator": "PMI", "operator": ">", "threshold": 50}` |
| 趋势判断 | `trend` | up/down/stable | `{"operator": "trend", "trend_type": "up", "period": 3}` |
| 逻辑运算 | `AND`, `OR`, `NOT` | 组合条件 | `{"operator": "AND", "conditions": [...]}` |
| 范围判断 | `between` | 区间内 | `{"operator": "between", "min": 40, "max": 60}` |
| 集合判断 | `in` | 包含于 | `{"operator": "in", "values": [1, 2, 3]}` |

### 2.4 脚本引擎设计

#### 脚本API

```python
# 策略脚本示例

# 获取当前Regime
regime = get_regime()
print(f"当前Regime: {regime.dominant_regime}")

# 获取PMI数据
pmi = get_macro_indicator("CN_PMI_MANUFACTURING")
print(f"PMI: {pmi}")

# 获取可投池资产
investable_pool = get_asset_pool(pool_type="INVESTABLE", min_score=60)

# 初始化目标权重
target_weights = {}

# 根据Regime调整配置
if regime.dominant_regime == "Recovery":
    # 复苏期：增加股票仓位
    for asset in investable_pool[:5]:
        target_weights[asset.asset_code] = 0.2

elif regime.dominant_regime == "Stagflation":
    # 滞胀期：增加债券和现金
    target_weights["TS01.CS"] = 0.5
    target_weights["cash"] = 0.4

# PMI特殊处理
if 50 < pmi < 52:
    target_weights["000001.SH"] = 0.3

# 返回信号列表
result = {
    "signals": [
        {
            "asset_code": code,
            "action": "buy",
            "weight": weight,
            "reason": f"Regime: {regime.dominant_regime}, PMI: {pmi}",
            "confidence": 0.8
        }
        for code, weight in target_weights.items()
    ]
}
```

#### 沙箱安全配置

```python
ALLOWED_BUILTINS = {
    'abs', 'all', 'any', 'bool', 'dict', 'enumerate', 'filter',
    'float', 'int', 'len', 'list', 'map', 'max', 'min', 'range',
    'round', 'sorted', 'str', 'sum', 'tuple', 'zip', 'print'
}

ALLOWED_MODULES = [
    'math',    # 数学函数
    'datetime', # 日期处理
    # 禁止: os, sys, subprocess, eval, exec, etc.
]
```

### 2.5 AI集成设计

#### AI策略执行流程

```
┌────────────────┐
│ 策略触发       │
└────────┬───────┘
         │
         ▼
┌────────────────┐
│ 准备上下文     │
│ - Regime状态   │
│ - 可投资产池   │
│ - 当前持仓     │
│ - 风控参数     │
└────────┬───────┘
         │
         ▼
┌────────────────┐
│ 执行AI Prompt  │
│ 或Chain        │
└────────┬───────┘
         │
         ▼
┌────────────────┐
│ 解析AI响应     │
│ - JSON解析     │
│ - 信号提取     │
└────────┬───────┘
         │
         ▼
┌────────────────┐
│ 置信度判断     │
└────┬───────┬───┘
     │       │
     ▼       ▼
  高置信   低置信
     │       │
     ▼       ▼
  自动执行  人工审核
```

#### AI Prompt模板

```
你是一位专业的投资顾问，负责根据当前的宏观环境和资产分析结果，给出投资建议。

## 当前市场环境

- Regime分布: {current_regime}
- Regime置信度: {regime_confidence}
- 政策档位: {policy_level}

## 可投资产池

{% for asset in investable_pool %}
- {{ asset.asset_code }} ({{ asset.asset_name }})
  - 总评分: {{ asset.total_score }}
  - Regime评分: {{ asset.regime_score }}
{% endfor %}

## 投资限制

- 单资产最大持仓: {max_position_pct}%
- 总持仓上限: {max_total_position_pct}%

## 任务

请返回JSON格式的信号列表：
[
  {
    "asset_code": "000001.SH",
    "action": "buy",
    "weight": 0.3,
    "reason": "决策理由",
    "confidence": 0.8
  }
]
```

---

## 三、关键文件清单

### 3.1 新增文件

```
apps/strategy/
├── domain/
│   ├── __init__.py
│   ├── entities.py                    # Strategy, RuleCondition等实体
│   ├── rule_engine.py                 # 规则引擎实现
│   └── protocols.py                   # Repository Protocol定义
│
├── application/
│   ├── __init__.py
│   ├── strategy_executor.py           # 策略执行引擎（中央调度器）
│   ├── rule_evaluator.py              # 规则评估器
│   ├── script_engine.py               # 脚本执行引擎
│   ├── ai_strategy_executor.py        # AI策略执行器
│   └── use_cases.py                   # 策略相关用例
│
├── infrastructure/
│   ├── __init__.py
│   ├── models.py                      # StrategyModel等Django模型
│   └── repositories.py                # 数据仓储实现
│
└── interface/
    ├── __init__.py
    ├── views.py                       # DRF视图集
    ├── serializers.py                 # 序列化器
    └── urls.py                        # URL配置
```

### 3.2 需要修改的现有文件

| 文件路径 | 修改内容 | 优先级 |
|----------|----------|--------|
| `apps/simulated_trading/infrastructure/models.py` | 添加strategy外键到SimulatedAccountModel | 高 |
| `apps/simulated_trading/application/auto_trading_engine.py` | 集成StrategyExecutor | 高 |
| `apps/simulated_trading/application/use_cases.py` | 添加策略相关用例 | 高 |
| `core/settings/base.py` | 注册strategy应用 | 高 |
| `core/urls.py` | 添加strategy路由 | 中 |

### 3.3 依赖的外部系统

| 系统 | 集成点 | 说明 |
|------|--------|------|
| `apps/prompt/` | AI策略执行 | 复用现有Prompt/Chain系统 |
| `apps/regime/` | 规则评估 | 获取当前Regime状态 |
| `apps/macro/` | 规则评估 | 获取宏观指标数据 |
| `apps/signal/` | 信号生成 | 集成投资信号系统 |
| `apps/asset_analysis/` | 资产池查询 | 获取可投资产 |

---

## 四、实施计划

### 阶段1：基础框架（第1-2周）

#### Week 1: 数据模型和Domain层

**任务清单**:
- [ ] 创建 `apps/strategy/` 应用目录结构
- [ ] 实现 `infrastructure/models.py`:
  - StrategyModel
  - RuleConditionModel
  - ScriptConfigModel
  - AIStrategyConfigModel
  - PortfolioStrategyAssignmentModel
  - StrategyExecutionLogModel
- [ ] 创建数据库迁移文件
- [ ] 实现 `domain/entities.py`:
  - Strategy实体
  - RuleCondition实体
  - SignalRecommendation实体
  - StrategyExecutionResult实体
- [ ] 实现 `domain/protocols.py`: 定义Repository接口

**验收标准**:
- 数据库迁移成功执行
- Django Admin可以管理所有模型
- 单元测试覆盖率 ≥ 80%

#### Week 2: Repository和基础API

**任务清单**:
- [ ] 实现 `infrastructure/repositories.py`:
  - DjangoStrategyRepository
  - DjangoPortfolioStrategyRepository
- [ ] 实现 `interface/serializers.py`:
  - StrategySerializer
  - RuleConditionSerializer
  - ScriptConfigSerializer
- [ ] 实现 `interface/views.py`:
  - StrategyViewSet (CRUD)
  - RuleConditionViewSet
- [ ] 配置 `interface/urls.py`
- [ ] 注册应用到 `INSTALLED_APPS`

**验收标准**:
- REST API可正常CRUD策略
- Postman/curl测试通过
- API文档生成

### 阶段2：规则引擎（第3-4周）

#### Week 3: 规则评估器

**任务清单**:
- [ ] 实现 `domain/rule_engine.py`:
  - RuleEvaluator基类
  - MacroIndicatorEvaluator
  - RegimeEvaluator
  - SignalEvaluator
  - CompositeEvaluator（组合条件）
- [ ] 实现JSON规则解析器
- [ ] 实现规则语法验证
- [ ] 单元测试（覆盖所有运算符）

**验收标准**:
- 所有规则类型可以正确解析
- 支持AND/OR/NOT逻辑组合
- 测试覆盖 ≥ 90%

#### Week 4: 规则执行器

**任务清单**:
- [ ] 实现 `application/rule_evaluator.py`:
  - RuleBasedStrategyExecutor
- [ ] 集成到 `application/strategy_executor.py`
- [ ] 实现规则触发日志
- [ ] 性能优化（批量评估）

**验收标准**:
- 规则策略可以正确执行
- 生成正确的交易信号
- 执行日志记录完整

### 阶段3：脚本引擎（第5-6周）

#### Week 5: 沙箱环境

**任务清单**:
- [ ] 安装和配置 `RestrictedPython`
- [ ] 实现 `application/script_engine.py`:
  - ScriptExecutionEnvironment
  - 安全的命名空间构建
  - 沙箱配置管理
- [ ] 实现脚本API:
  - get_macro_indicator()
  - get_regime()
  - get_asset_pool()
  - calculate_signal()
- [ ] 沙箱安全测试

**验收标准**:
- 脚本在沙箱中安全执行
- 禁止的模块/操作被正确拦截
- API可用性测试通过

#### Week 6: 脚本执行器

**任务清单**:
- [ ] 实现ScriptBasedStrategyExecutor
- [ ] 脚本结果解析器
- [ ] 错误处理和回滚
- [ ] 脚本版本管理（基于hash）

**验收标准**:
- 脚本策略可以正确执行
- 脚本错误不影响系统稳定性
- 支持脚本热更新（检测hash变化）

### 阶段4：AI集成（第7周）

#### Week 7: AI策略执行器

**任务清单**:
- [ ] 实现 `application/ai_strategy_executor.py`:
  - AIStrategyExecutor
  - 上下文准备（整合Regime/资产池/持仓）
  - AI响应解析
- [ ] 创建AI Prompt模板:
  - 投资决策模板
  - 信号验证模板
- [ ] 实现审核模式:
  - always: 必须人工审核
  - conditional: 基于置信度
  - auto: 自动执行+监控

**验收标准**:
- AI策略可以正确执行
- 支持三种审核模式
- AI响应解析成功率高

### 阶段5：策略执行引擎集成（第8周）

#### Week 8: 与AutoTradingEngine集成

**任务清单**:
- [ ] 修改 `AutoTradingEngine`:
  - 注入StrategyExecutor
  - 实现通过 `PortfolioStrategyAssignment` 获取账户激活策略
  - 实现execute_strategy()
- [ ] 向后兼容处理:
  - 无策略时使用原有逻辑
  - 数据迁移脚本
- [ ] 端到端测试:
  - 规则策略完整流程
  - 脚本策略完整流程
  - AI策略完整流程
- [ ] 性能测试和优化

**验收标准**:
- 所有策略类型可正常执行
- 生成交易并成功执行
- 向后兼容无问题
- 性能满足要求

### 阶段6：前端界面（可选，第9周+）

**任务清单**:
- [ ] 策略管理界面
- [ ] 规则编辑器（JSON编辑器）
- [ ] 脚本编辑器（代码高亮）
- [ ] 策略执行日志查看
- [ ] AI信号审核界面

---

## 五、向后兼容性

### 5.1 兼容策略

1. **保留原有逻辑**: 无策略的投资组合继续使用"资产池+信号"模式
2. **渐进式迁移**: 逐步将现有组合迁移到新策略系统
3. **数据迁移**: 提供迁移脚本将现有配置转换为策略

### 5.2 迁移脚本

```python
# scripts/migrate_to_strategy_system.py

def migrate_existing_portfolio_to_strategy():
    """
    将现有Portfolio迁移到策略系统
    """
    for portfolio in PortfolioModel.objects.all():
        # 创建默认规则策略
        strategy = StrategyModel.objects.create(
            name=f"{portfolio.name}默认策略",
            strategy_type='rule_based',
            max_position_pct=20.0,
            max_total_position_pct=95.0
        )

        # 创建基础规则
        RuleConditionModel.objects.create(
            strategy=strategy,
            rule_name="资产池买入规则",
            rule_type='signal',
            condition_json={
                "operator": "AND",
                "conditions": [
                    {"field": "regime_score", "operator": ">", "value": 60}
                ]
            },
            action='buy',
            priority=100
        )

        # 关联到投资组合
        PortfolioStrategyAssignmentModel.objects.create(
            portfolio=portfolio,
            strategy=strategy,
            is_active=True
        )
```

---

## 六、测试策略

### 6.1 单元测试

- Domain层规则引擎测试
- Repository测试
- 各执行器测试

### 6.2 集成测试

- 策略执行完整流程
- AI集成测试
- 与AutoTradingEngine集成

### 6.3 性能测试

- 规则评估性能（目标：< 100ms/规则）
- 脚本执行性能（目标：< 500ms/脚本）
- AI调用性能（目标：< 5s/AI决策）

---

## 七、风险和缓解措施

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 脚本沙箱被绕过 | 高 | 使用RestrictedPython + 严格的模块白名单 |
| AI信号质量不稳定 | 中 | 实施审核模式，逐步增加AI权重 |
| 规则语法复杂度高 | 中 | 提供规则模板和编辑器辅助 |
| 性能问题 | 中 | 批量处理、缓存、异步执行 |
| 向后兼容问题 | 低 | 保留原有代码路径，充分测试 |

---

## 八、后续优化

1. **规则模板库**: 预定义常用规则模板
2. **策略市场**: 用户分享和订阅策略
3. **回测集成**: 策略回测和优化
4. **实时监控**: 策略执行监控和告警
5. **策略版本控制**: Git-like版本管理
6. **多策略组合**: 一个投资组合运行多个策略

---

## 九、总结

本实施计划提供了一个完整的投资组合策略管理系统，支持：

1. **多种策略类型**: 规则驱动、脚本驱动、AI驱动
2. **灵活配置**: JSON规则、受限Python脚本、AI Prompt
3. **独立风控**: 每个策略独立的风控参数
4. **安全可控**: 沙箱隔离、审核模式、监控告警
5. **向后兼容**: 不影响现有系统

预计实施周期为 **6-8周**，核心开发工作量约 **8周**，可选前端界面约 **2周**。
