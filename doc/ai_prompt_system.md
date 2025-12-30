# AI Prompt 系统使用文档

> 版本: 1.0
> 更新时间: 2025-12-30

## 目录

1. [系统概述](#1-系统概述)
2. [架构设计](#2-架构设计)
3. [占位符语法](#3-占位符语法)
4. [链式调用配置](#4-链式调用配置)
5. [API接口文档](#5-api接口文档)
6. [使用示例](#6-使用示例)
7. [最佳实践](#7-最佳实践)

## 1. 系统概述

AI Prompt管理系统是AgomSAAF的核心组件，提供统一的Prompt模板管理、数据自动获取和链式调用能力。

### 1.1 核心功能

- **Prompt模板管理**：版本化、分类管理
- **占位符自动解析**：支持多种数据类型和函数调用
- **链式调用编排**：串行、并行、工具调用、混合模式
- **执行日志追踪**：完整的调用记录和成本统计
- **数据自动获取**：集成宏观数据、Regime状态

### 1.2 应用场景

| 场景 | 说明 |
|------|------|
| 投资分析报告 | AI自动获取宏观数据生成Regime/Policy分析 |
| 投资信号生成 | AI分析数据生成投资信号（含证伪逻辑） |
| 通用数据分析 | 可复用的AI数据分析框架 |
| 聊天提问 | 交互式AI问答 |

## 2. 架构设计

系统遵循项目的四层架构：

```
┌─────────────────────────────────────┐
│       Interface 层                   │
│  (views.py, serializers.py, urls.py) │
│  DRF视图、序列化器、API路由           │
└─────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────┐
│       Application 层                 │
│  (use_cases.py, dtos.py)             │
│  用例编排：ExecutePrompt, ExecuteChain│
└─────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────┐
│       Domain 层                      │
│  (entities.py, services.py, rules.py)│
│  实体定义、业务逻辑、验证规则         │
└─────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────┐
│    Infrastructure 层                 │
│  (models.py, repositories.py,        │
│   adapters/)                        │
│  ORM、数据仓储、数据适配器           │
└─────────────────────────────────────┘
```

## 3. 占位符语法

### 3.1 占位符类型

| 类型 | 语法 | 说明 | 示例 |
|------|------|------|------|
| 简单替换 | `{{FIELD}}` | 直接值替换 | `{{PMI}}` → 50.8 |
| 复杂数据 | `{{STRUCT}}` | JSON/表格数据 | `{{MACRO_DATA}}` → 结构化摘要 |
| 函数调用 | `{{FUNC(params)}}` | 调用预定义函数 | `{{TREND(PMI,6m)}}` → 趋势值 |
| 条件逻辑 | `{%if%}...{%endif%}` | Jinja2模板语法 | 条件渲染 |

### 3.2 内置占位符

#### 宏观数据占位符

```
{{PMI}}           # PMI最新值
{{CPI}}           # CPI最新值
{{PPI}}           # PPI最新值
{{M2}}            # M2最新值
{{MACRO_DATA}}    # 完整宏观摘要（JSON）
```

#### Regime占位符

```
{{REGIME}}                # 当前Regime状态
{{DOMINANT_REGIME}}       # 主导Regime代码
{{DOMINANT_REGIME_NAME}}  # 主导Regime名称
{{GROWTH_Z}}              # 增长动量Z-score
{{INFLATION_Z}}           # 通胀动量Z-score
{{REGIME_CONFIDENCE}}     # Regime置信度
```

#### 函数占位符

```
{{LATEST(CN_PMI)}}                     # 获取最新值
{{SERIES(CN_PMI, 90)}}                 # 获取时序数据（90天）
{{TREND(CN_PMI, 3m)}}                  # 计算趋势（3个月）
```

### 3.3 模板示例

```jinja2
请分析当前宏观经济状况：

## 宏观指标
- PMI: {{PMI}}
- CPI: {{CPI}}
- PPI: {{PPI}}

## 完整数据
{{MACRO_DATA}}

{%if GROWTH_Z > 0 %}
增长动量为正，经济处于扩张期。
{%else%}
增长动量为负，经济处于收缩期。
{%endif%}

## 趋势分析
PMI 3个月趋势：{{TREND(PMI, 3m)}}
```

## 4. 链式调用配置

### 4.1 执行模式

#### SERIAL（串行）

步骤按顺序依次执行，后一步可以使用前一步的输出。

```json
{
  "name": "串行报告生成",
  "execution_mode": "serial",
  "steps": [
    {
      "step_id": "step1",
      "template_id": "macro_summary",
      "order": 1,
      "input_mapping": {}
    },
    {
      "step_id": "step2",
      "template_id": "regime_analysis",
      "order": 2,
      "input_mapping": {
        "MACRO_SUMMARY": "step1.output.summary"
      }
    }
  ]
}
```

#### PARALLEL（并行）

同一组的步骤并行执行，然后汇总结果。

```json
{
  "name": "多指标并行分析",
  "execution_mode": "parallel",
  "steps": [
    {
      "step_id": "pmi_analysis",
      "template_id": "trend_analysis",
      "order": 1,
      "parallel_group": "group1",
      "input_mapping": {"INDICATOR": "CN_PMI"}
    },
    {
      "step_id": "cpi_analysis",
      "template_id": "trend_analysis",
      "order": 1,
      "parallel_group": "group1",
      "input_mapping": {"INDICATOR": "CN_CPI"}
    },
    {
      "step_id": "aggregate",
      "template_id": "aggregate_analysis",
      "order": 2,
      "input_mapping": {
        "PMI_RESULT": "pmi_analysis.output",
        "CPI_RESULT": "cpi_analysis.output"
      }
    }
  ]
}
```

#### TOOL_CALLING（工具调用）

AI可以主动调用预定义的工具函数获取数据。

```json
{
  "name": "信号验证链",
  "execution_mode": "tool",
  "steps": [
    {
      "step_id": "generate",
      "template_id": "signal_generation",
      "enable_tool_calling": true,
      "available_tools": [
        "get_macro_indicator",
        "get_regime_status",
        "calculate_trend"
      ]
    }
  ]
}
```

### 4.2 输入映射

`input_mapping`定义如何将前序步骤的输出映射到当前模板的占位符：

```json
{
  "input_mapping": {
    "PMI": "step1.output.indicators.PMI.value",
    "REGIME": "step2.output.dominant_regime",
    "SUMMARY": "step1.output.summary"
  }
}
```

## 5. API接口文档

### 5.1 基础URL

```
http://localhost:8000/api/prompt/
```

### 5.2 模板管理

#### 创建模板

```http
POST /api/prompt/templates/
Content-Type: application/json

{
  "name": "my_analysis_template",
  "category": "analysis",
  "template_content": "分析指标：{{INDICATOR}}",
  "placeholders": [
    {
      "name": "INDICATOR",
      "type": "simple",
      "description": "指标代码",
      "required": true
    }
  ],
  "temperature": 0.7,
  "description": "我的分析模板"
}
```

#### 列出模板

```http
GET /api/prompt/templates/?category=report&is_active=true
```

#### 执行模板

```http
POST /api/prompt/templates/{id}/execute/
Content-Type: application/json

{
  "placeholder_values": {
    "INDICATOR": "CN_PMI"
  },
  "provider_name": "openai",
  "model": "gpt-4"
}
```

响应：

```json
{
  "success": true,
  "content": "分析结果...",
  "provider_used": "openai",
  "model_used": "gpt-4",
  "total_tokens": 150,
  "estimated_cost": 0.001,
  "response_time_ms": 1200
}
```

### 5.3 链配置管理

#### 创建链配置

```http
POST /api/prompt/chains/
Content-Type: application/json

{
  "name": "my_chain",
  "category": "report",
  "description": "我的报告生成链",
  "execution_mode": "serial",
  "steps": [
    {
      "step_id": "step1",
      "template_id": "1",
      "step_name": "第一步",
      "order": 1,
      "input_mapping": {}
    }
  ]
}
```

#### 执行链

```http
POST /api/prompt/chains/{id}/execute/
Content-Type: application/json

{
  "placeholder_values": {
    "AS_OF_DATE": "2024-01-15"
  }
}
```

### 5.4 报告生成

```http
POST /api/prompt/reports/generate
Content-Type: application/json

{
  "as_of_date": "2024-01-15",
  "include_regime": true,
  "include_policy": true,
  "include_macro": true
}
```

### 5.5 信号生成

```http
POST /api/prompt/signals/generate
Content-Type: application/json

{
  "asset_code": "000001.SH",
  "analysis_context": {
    "strategy": "trend_following"
  }
}
```

### 5.6 聊天

```http
POST /api/prompt/chat
Content-Type: application/json

{
  "message": "当前PMI是多少？",
  "session_id": "optional-session-id"
}
```

### 5.7 执行日志

```http
GET /api/prompt/logs/?template_id=1&limit=50
```

## 6. 使用示例

### 6.1 Python代码示例

#### 执行单个Prompt

```python
from apps.prompt.infrastructure.repositories import DjangoPromptRepository
from apps.prompt.application.use_cases import ExecutePromptUseCase

# 创建用例
repository = DjangoPromptRepository()
use_case = ExecutePromptUseCase(
    prompt_repository=repository,
    execution_log_repository=...,
    ai_client_factory=...,
    macro_adapter=...,
    regime_adapter=...
)

# 执行
request = ExecutePromptRequest(
    template_id=1,
    placeholder_values={"PMI": 50.8}
)
result = use_case.execute(request)

print(result.content)
```

#### 执行链

```python
from apps.prompt.infrastructure.repositories import DjangoChainRepository
from apps.prompt.application.use_cases import ExecuteChainUseCase

chain_repository = DjangoChainRepository()
chain_use_case = ExecuteChainUseCase(
    chain_repository=chain_repository,
    prompt_use_case=prompt_use_case
)

request = ExecuteChainRequest(
    chain_id=1,
    placeholder_values={"AS_OF_DATE": "2024-01-15"}
)
result = chain_use_case.execute(request)
```

### 6.2 Django Shell示例

```python
# 进入Django Shell
python manage.py shell

# 加载预定义模板
from apps.prompt.infrastructure.fixtures.templates import load_predefined_templates
from apps.prompt.infrastructure.repositories import DjangoPromptRepository

repository = DjangoPromptRepository()
count = load_predefined_templates(repository)
print(f"已加载 {count} 个模板")

# 创建并执行自定义模板
from apps.prompt.domain.entities import PromptTemplate, PlaceholderDef, PlaceholderType, PromptCategory

template = PromptTemplate(
    id=None,
    name="my_template",
    category=PromptCategory.DATA_ANALYSIS,
    version="1.0",
    template_content="指标 {{INDICATOR}} 的最新值是 {{VALUE}}",
    placeholders=[
        PlaceholderDef(
            name="INDICATOR",
            type=PlaceholderType.SIMPLE,
            description="指标名称",
            required=True
        ),
        PlaceholderDef(
            name="VALUE",
            type=PlaceholderType.SIMPLE,
            description="指标值",
            required=True
        )
    ],
    description="我的模板"
)

created = repository.create_template(template)
print(f"创建模板: {created.name}")
```

## 7. 最佳实践

### 7.1 模板设计原则

1. **明确目标**：每个模板应该有明确的分析目标
2. **结构化输出**：要求AI输出JSON格式便于解析
3. **验证机制**：使用`{%if%}`处理数据缺失情况
4. **版本管理**：重要变更时创建新版本

### 7.2 链配置建议

1. **步骤拆分**：复杂任务拆分为多个小步骤
2. **并行利用**：独立分析使用并行模式提高效率
3. **错误处理**：在汇总步骤处理前序步骤可能的失败
4. **输出复用**：使用`input_mapping`合理传递中间结果

### 7.3 成本优化

1. **控制输出长度**：设置合理的`max_tokens`
2. **缓存结果**：相同输入的Prompt可以缓存结果
3. **批量处理**：使用并行模式减少总时间
4. **模型选择**：简单任务使用更便宜的模型

### 7.4 安全注意事项

1. **输入验证**：验证所有用户输入
2. **敏感数据**：避免在模板中硬编码敏感信息
3. **权限控制**：限制模板和链的修改权限
4. **日志脱敏**：执行日志中的敏感数据应脱敏

---

## 附录

### A. 预定义模板列表

| 模板名称 | 分类 | 说明 |
|---------|------|------|
| regime_analysis | report | Regime分析报告 |
| macro_summary | report | 宏观数据摘要 |
| signal_generation | signal | 投资信号生成 |
| trend_analysis | analysis | 趋势分析 |
| chat_assistant | chat | 聊天助手 |

### B. 预定义链配置列表

| 链名称 | 分类 | 执行模式 | 说明 |
|-------|------|---------|------|
| investment_report_chain | report | serial | 完整投资报告生成 |
| multi_analysis_chain | analysis | parallel | 多指标并行分析 |
| signal_validation_chain | signal | tool | 信号验证链 |

### C. 常见问题

**Q: 如何添加新的数据源占位符？**
A: 在`macro_adapter.py`的`resolve_placeholder`方法中添加新的解析逻辑。

**Q: 如何自定义函数占位符？**
A: 在`function_registry.py`中注册新的工具函数。

**Q: 链式调用失败了怎么办？**
A: 查看`prompt_execution_log`表获取详细错误信息。

**Q: 如何限制AI的输出格式？**
A: 在模板中明确要求JSON格式，并在`system_prompt`中给出示例。
