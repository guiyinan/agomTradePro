# Terminal 模块指南

> **模块版本**: 1.0
> **创建日期**: 2026-03-17
> **依赖模块**: prompt（AI 能力、数据模型）

---

## 概述

Terminal 模块提供终端风格的 AI 交互界面，支持可配置命令系统。用户可以通过命令行方式与 AI 进行交互，执行预定义的命令。

## 架构设计

### 四层架构

```
apps/terminal/
├── domain/                    # 领域层
│   ├── entities.py           # 命令实体定义
│   └── interfaces.py         # 仓储接口协议
├── application/              # 应用层
│   ├── use_cases.py          # 业务用例
│   └── services.py           # 命令执行服务
├── infrastructure/           # 基础设施层
│   ├── models.py             # ORM 模型（重导出）
│   └── repositories.py       # 仓储实现
└── interface/                # 接口层
    ├── views.py              # 页面视图
    ├── api_views.py          # API 视图
    ├── serializers.py        # 序列化器
    ├── urls.py               # 页面路由
    └── api_urls.py           # API 路由
```

### 与 prompt 模块的关系

```
terminal (上层交互界面)
    │
    ├── 依赖 prompt 的数据模型 (TerminalCommandORM)
    ├── 依赖 prompt 的 AI 客户端 (AIClientFactory)
    └── 可选依赖 prompt 的模板 (PromptTemplateORM)
```

## 核心概念

### 命令类型 (CommandType)

| 类型 | 说明 | 执行方式 |
|------|------|----------|
| `PROMPT` | Prompt 模板调用 | 通过 AI 生成响应 |
| `API` | API 端点调用 | 直接调用系统 API |

### 命令实体 (TerminalCommand)

```python
@dataclass
class TerminalCommand:
    id: str
    name: str                          # 命令名称（如 analyze, report）
    description: str                   # 命令描述
    command_type: CommandType          # 命令类型
    
    # Prompt 类型配置
    prompt_template_id: Optional[str]  # 关联的 Prompt 模板 ID
    system_prompt: Optional[str]       # 系统提示词
    user_prompt_template: str          # 用户提示词模板
    
    # API 类型配置
    api_endpoint: Optional[str]        # API 端点路径
    api_method: str                    # HTTP 方法（GET/POST）
    response_jq_filter: Optional[str]  # JQ 过滤器
    
    # 参数定义
    parameters: list[CommandParameter] # 交互式参数
    
    # 执行配置
    timeout: int                       # 超时时间（秒）
    provider_name: Optional[str]       # 指定 AI 提供商
    model_name: Optional[str]          # 指定模型
```

### 参数定义 (CommandParameter)

```python
@dataclass
class CommandParameter:
    name: str                    # 参数名
    param_type: ParameterType    # 类型：text/number/select/date/boolean
    description: str             # 描述
    required: bool               # 是否必需
    default: Any                 # 默认值
    options: list[str]           # 选项（select 类型）
    prompt: str                  # 交互提示文本
```

## API 端点

### 命令管理 API

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/terminal/commands/` | 获取命令列表 |
| GET | `/api/terminal/commands/{id}/` | 获取命令详情 |
| POST | `/api/terminal/commands/` | 创建命令 |
| PUT | `/api/terminal/commands/{id}/` | 更新命令 |
| DELETE | `/api/terminal/commands/{id}/` | 删除命令 |

### 命令执行 API

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/terminal/commands/{id}/execute/` | 按 ID 执行命令 |
| POST | `/api/terminal/commands/execute_by_name/` | 按名称执行命令 |
| GET | `/api/terminal/commands/available/` | 获取可用命令列表 |
| GET | `/api/terminal/commands/by_category/` | 按分类获取命令 |

### 会话管理 API

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/terminal/session/` | 创建新会话 |

## 使用示例

### 执行命令（按名称）

```bash
curl -X POST /api/terminal/commands/execute_by_name/ \
  -H "Content-Type: application/json" \
  -d '{
    "name": "analyze",
    "params": {
      "symbol": "AAPL",
      "period": "1m"
    },
    "session_id": "abc123"
  }'
```

### 响应格式

```json
{
  "success": true,
  "output": "分析结果...",
  "metadata": {
    "provider": "openai",
    "model": "gpt-4",
    "tokens": 1500,
    "session_id": "abc123"
  },
  "error": null,
  "command": {
    "id": "1",
    "name": "analyze",
    "type": "prompt",
    ...
  }
}
```

### 创建命令

```bash
curl -X POST /api/terminal/commands/ \
  -H "Content-Type: application/json" \
  -d '{
    "name": "stock_analysis",
    "description": "股票分析命令",
    "command_type": "prompt",
    "user_prompt_template": "请分析股票 {symbol} 的投资价值",
    "parameters": [
      {
        "name": "symbol",
        "type": "text",
        "description": "股票代码",
        "required": true
      }
    ],
    "category": "analysis"
  }'
```

## 页面路由

| 路由 | 说明 |
|------|------|
| `/terminal/` | 终端主页面 |
| `/terminal/config/` | 命令配置管理页面 |

## 数据模型

TerminalCommandORM 定义在 `apps/prompt/infrastructure/models.py`：

```python
class TerminalCommandORM(models.Model):
    name = models.CharField(max_length=50, unique=True)
    command_type = models.CharField(choices=[('prompt', 'Prompt模板调用'), ('api', 'API端点调用')])
    
    # Prompt 配置
    prompt_template = models.ForeignKey(PromptTemplateORM, on_delete=models.SET_NULL, null=True)
    system_prompt_override = models.TextField(blank=True)
    
    # API 配置
    api_endpoint = models.CharField(max_length=255, blank=True)
    api_method = models.CharField(max_length=10, default='GET')
    api_payload_template = models.JSONField(default=dict)
    response_jq_filter = models.CharField(max_length=255, blank=True)
    
    # 参数定义
    parameters = models.JSONField(default=list)
    
    # 状态
    is_active = models.BooleanField(default=True)
    category = models.CharField(max_length=50, default='general')
```

## 配置示例

### Prompt 类型命令

```json
{
  "name": "market_analysis",
  "description": "市场分析",
  "command_type": "prompt",
  "user_prompt_template": "请分析当前市场环境：\n- Regime: {regime}\n- 关注板块: {sectors}",
  "parameters": [
    {"name": "regime", "type": "select", "options": ["Recovery", "Overheat", "Stagflation", "Deflation"]},
    {"name": "sectors", "type": "text", "description": "关注板块，逗号分隔"}
  ]
}
```

### API 类型命令

```json
{
  "name": "get_regime",
  "description": "获取当前 Regime",
  "command_type": "api",
  "api_endpoint": "/api/regime/current/",
  "api_method": "GET",
  "response_jq_filter": ".dominant_regime"
}
```

## 最佳实践

1. **命令命名**: 使用简短、有意义的名称（如 `analyze`, `report`, `signal`）
2. **参数设计**: 尽量提供默认值，减少用户输入
3. **错误处理**: 提供清晰的错误提示
4. **超时设置**: 根据命令复杂度设置合理的超时时间

## 相关文档

- [Prompt 模块指南](../ai/prompt_templates_guide.md)
- [AI 服务商管理](../ai/ai_provider_requirements.md)
- [API 结构指南](../development/api_structure_guide.md)
