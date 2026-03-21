# Prompt 模板系统使用指南

> AgomTradePro 内置可复用的 AI 分析模板系统

## 一、系统概述

Prompt 模板系统是 AgomTradePro 的核心 AI 能力层，提供：
- **预置分析模板**：开箱即用的专业分析模板
- **占位符自动解析**：自动获取宏观数据、Regime状态
- **链式编排能力**：支持串行、并行、工具调用等复杂流程
- **执行日志追踪**：完整的调用记录和成本统计

## 二、快速开始

### 2.1 初始化模板

首次安装后，执行以下命令加载预置模板：

```bash
# 初始化所有模板和链配置
python manage.py init_prompt_templates

# 强制重新加载（覆盖已存在的模板）
python manage.py init_prompt_templates --force

# 只加载模板
python manage.py init_prompt_templates --templates-only

# 只加载链配置
python manage.py init_prompt_templates --chains-only

# 预览将要加载的内容（不实际写入）
python manage.py init_prompt_templates --dry-run
```

### 2.2 访问管理界面

启动服务后，访问：`http://127.0.0.1:8000/prompt/manage/`

## 三、预置模板清单

### 3.1 报告分析类

| 模板名称 | 分类 | 说明 |
|---------|------|------|
| `regime_analysis` | report | Regime四象限分析报告 |
| `macro_summary` | report | 宏观数据摘要分析 |
| `weekly_market_report` | report | 周度市场分析报告 |
| `monetary_policy_interpretation` | report | 货币政策解读 |
| `risk_warning_analysis` | report | 市场风险预警分析 |

**使用场景**：定期生成投资分析报告、市场策略报告

### 3.2 数据分析类

| 模板名称 | 分类 | 说明 |
|---------|------|------|
| `trend_analysis` | analysis | 指标趋势分析 |
| `pmi_deep_analysis` | analysis | PMI专项深度分析 |
| `cpi_inflation_analysis` | analysis | CPI通胀专项分析 |
| `bond_market_analysis` | analysis | 债券市场投资分析 |
| `event_impact_assessment` | analysis | 重大事件影响评估 |
| `quick_analysis` | analysis | 快速简易分析 |

**使用场景**：单指标深度分析、事件影响评估

### 3.3 信号生成类

| 模板名称 | 分类 | 说明 |
|---------|------|------|
| `signal_generation` | signal | 投资信号生成（含证伪逻辑） |
| `asset_allocation_advice` | signal | 资产配置建议 |
| `sector_rotation_advice` | signal | 行业轮动建议 |

**使用场景**：生成具体的投资建议和配置方案

### 3.4 聊天类

| 模板名称 | 分类 | 说明 |
|---------|------|------|
| `chat_assistant` | chat | 智能问答助手 |

**使用场景**：交互式问答、临时分析需求

## 四、链配置

### 4.1 预置链

| 链名称 | 执行模式 | 说明 |
|-------|---------|------|
| `investment_report_chain` | serial | 完整投资报告生成（宏观摘要→Regime分析→综合报告） |
| `multi_analysis_chain` | parallel | 多指标并行分析（PMI/CPI/PPI同时分析→汇总） |
| `signal_validation_chain` | tool | 信号验证链（AI生成信号→自动验证证伪逻辑） |

### 4.2 执行模式说明

| 模式 | 说明 | 适用场景 |
|-----|------|---------|
| **serial** | 串行执行，后一步可用前一步输出 | 逐步深入的复杂分析 |
| **parallel** | 并行执行，同时处理多个任务 | 多指标对比分析 |
| **tool** | AI主动调用工具函数获取数据 | 需要动态获取数据的场景 |
| **hybrid** | 混合模式 | 复杂业务流程 |

## 五、使用方式

### 5.1 方式一：前端界面

1. 访问 `http://127.0.0.1:8000/prompt/manage/`
2. 选择模板或链配置
3. 填写占位符参数
4. 点击"执行测试"

### 5.2 方式二：Python 调用

```python
from apps.prompt.application.use_cases import ExecutePromptUseCase
from apps.prompt.infrastructure.repositories import DjangoPromptRepository

# 创建用例
use_case = ExecutePromptUseCase(
    prompt_repository=DjangoPromptRepository(),
    execution_log_repository=DjangoExecutionLogRepository(),
    ai_client_factory=AIClientFactory(),
    macro_adapter=MacroDataAdapter(),
    regime_adapter=RegimeDataAdapter()
)

# 执行模板
result = use_case.execute({
    "template_id": 1,  # regime_analysis
    "placeholder_values": {
        "DOMINANT_REGIME_NAME": "复苏",
        "REGIME_CONFIDENCE": "0.85",
        "GROWTH_Z": "1.2",
        "INFLATION_Z": "-0.3"
    }
})

print(result.content)
```

### 5.3 方式三：HTTP API

```bash
# 执行模板
curl -X POST http://127.0.0.1:8000/api/prompt/templates/1/execute/ \
  -H "Content-Type: application/json" \
  -d '{
    "placeholder_values": {
      "PMI": 50.8,
      "CPI": 0.2
    }
  }'

# 执行链配置
curl -X POST http://127.0.0.1:8000/api/prompt/chains/1/execute/ \
  -H "Content-Type: application/json" \
  -d '{
    "placeholder_values": {
      "AS_OF_DATE": "2024-01-15"
    }
  }'
```

## 六、占位符说明

### 6.1 内置数据占位符

| 占位符 | 说明 | 来源 |
|-------|------|------|
| `{{PMI}}` | PMI最新值 | macro app |
| `{{CPI}}` | CPI最新值 | macro app |
| `{{MACRO_DATA}}` | 宏观摘要数据 | macro app |
| `{{DOMINANT_REGIME_NAME}}` | 主导Regime名称 | regime app |
| `{{REGIME_CONFIDENCE}}` | Regime置信度 | regime app |
| `{{GROWTH_Z}}` | 增长Z-score | regime app |
| `{{INFLATION_Z}}` | 通胀Z-score | regime app |

### 6.2 占位符类型

| 类型 | 语法 | 示例 |
|-----|------|------|
| 简单替换 | `{{FIELD}}` | `{{PMI}}` |
| 复杂数据 | `{{STRUCT}}` | `{{MACRO_DATA}}` |
| 函数调用 | `{{FUNC(params)}}` | `{{TREND(PMI,3m)}}` |
| 条件逻辑 | `{%if%}...{%endif%}` | Jinja2模板语法 |

## 七、最佳实践

### 7.1 模板设计

1. **明确目标**：每个模板应有明确的分析目标
2. **结构化输出**：要求AI输出JSON格式便于解析
3. **验证机制**：使用条件语法处理数据缺失情况
4. **版本管理**：重要变更时创建新版本

### 7.2 占位符使用

1. **优先使用内置占位符**：减少手动数据准备
2. **设置合理默认值**：提高模板易用性
3. **添加描述信息**：帮助用户理解占位符含义

### 7.3 成本优化

1. **控制输出长度**：设置合理的 `max_tokens`
2. **调整温度参数**：简单任务用较低温度
3. **使用链式调用**：复杂任务拆分可降低成本

## 八、扩展开发

### 8.1 添加自定义模板

```python
# 方式一：通过前端界面
访问 /prompt/manage/ → 新建模板

# 方式二：通过 Django Shell
python manage.py shell

from apps.prompt.domain.entities import PromptTemplate, PlaceholderDef, PlaceholderType, PromptCategory
from apps.prompt.infrastructure.repositories import DjangoPromptRepository

template = PromptTemplate(
    id=None,
    name="my_custom_template",
    category=PromptCategory.DATA_ANALYSIS,
    version="1.0",
    template_content="分析{{INDICATOR}}的最新值：{{VALUE}}",
    placeholders=[
        PlaceholderDef(
            name="INDICATOR",
            type=PlaceholderType.SIMPLE,
            description="指标名称",
            required=True
        )
    ],
    description="我的自定义模板"
)

repository = DjangoPromptRepository()
repository.create_template(template)
```

### 8.2 添加自定义数据适配器

编辑 `apps/prompt/infrastructure/adapters/macro_adapter.py`：

```python
def resolve_placeholder(self, placeholder_name: str) -> Any:
    if placeholder_name == "CUSTOM_DATA":
        return get_my_custom_data()  # 自定义数据获取逻辑
    # ... 其他占位符
```

## 九、常见问题

**Q: 如何查看执行历史？**
A: 访问 `/prompt/manage/` → "执行日志" 标签页

**Q: 如何调试模板？**
A: 使用"测试执行"标签页，选择模板并填写参数后测试

**Q: 如何批量生成报告？**
A: 使用链配置或编写脚本调用 API

**Q: 如何备份模板？**
A: 模板存储在数据库中，使用 Django 的 dumpdata 命令备份

## 十、相关文档

- [AI Prompt 系统设计文档](ai_prompt_system.md)
- [项目结构文档](../architecture/project_structure.md)
- [Regime 判定模块](../business/AgomTradePro_V3.4.md)

---

*最后更新：2024-12-30*
