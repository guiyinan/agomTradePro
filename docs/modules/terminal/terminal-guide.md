# Terminal 模块指南

> **模块版本**: 1.1
> **创建日期**: 2026-03-17
> **最后更新**: 2026-07-18
> **依赖模块**: ai_provider（AI 客户端）, prompt（可选模板关联）

---

## 概述

Terminal 模块现在是一个薄入口。用户通过自然语言发起任务，真正的 AI 执行下沉到 `apps/agent_runtime`，由 OpenAI Agents SDK 连接现有 stdio MCP server 完成工具调用、流式输出和审批前置判断。

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
│   ├── models.py             # ORM 模型（TerminalCommandORM）
│   └── repositories.py       # 仓储实现
└── interface/                # 接口层
    ├── views.py              # 页面视图
    ├── api_views.py          # API 视图
    ├── serializers.py        # 序列化器
    ├── urls.py               # 页面路由
    └── api_urls.py           # API 路由
```

### 与 ai_provider / prompt / agent_runtime 模块的关系

```
terminal
    │
    ├── 依赖 agent_runtime 的终端代理服务
    ├── agent_runtime 复用 ai_provider 的 provider / quota / usage 语义
    ├── terminal 仍保留历史 TerminalCommandORM / 审计表
    └── 旧 command API 仅保留 410 兼容壳
```

## 核心概念

### 终端代理入口

- `POST /api/terminal/chat/`
  返回一次性 JSON 应答，适合现有 TUI workbench 同步动作。
- `POST /api/terminal/chat/stream/`
  返回 `text/event-stream`，事件类型固定为 `message_delta`、`tool_called`、`tool_output`、`approval_required`、`final`、`error`。
- `POST /api/terminal/session/`
  生成新的会话标识，供前端保持上下文。
- `GET /api/terminal/audit/`
  保留审计读取。

### 旧命令接口

`/api/terminal/commands/*` 已退出产品主路径，统一返回 `410 Gone`。历史 ORM 表和 migration 仍保留，用于审计和回滚兼容。

## API 端点

### 终端代理 API

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/terminal/chat/` | 非流式自然语言入口 |
| POST | `/api/terminal/chat/stream/` | SSE 流式自然语言入口 |
| POST | `/api/terminal/session/` | 创建新会话 |
| GET | `/api/terminal/audit/` | 读取终端审计 |

## 使用示例

### 非流式聊天

```bash
curl -X POST /api/terminal/chat/ \
  -H "Content-Type: application/json" \
  -d '{
    "message": "总结当前系统状态，并说明是否存在阻断项",
    "session_id": "abc123",
    "provider_name": "personal-openai"
  }'
```

### 响应格式

```json
{
  "reply": "系统当前处于可用状态，未发现新的阻断项。",
  "session_id": "abc123",
  "metadata": {
    "provider": "personal-openai",
    "model": "gpt-4o-mini",
    "provider_scope": "personal",
    "tool_call_count": 1
  }
}
```

### 流式聊天

```bash
curl -N -X POST /api/terminal/chat/stream/ \
  -H "Content-Type: application/json" \
  -d '{
    "message": "读取当前宏观环境，并显示工具执行进度",
    "session_id": "abc123"
  }'
```

## 页面路由

| 路由 | 说明 |
|------|------|
| `/terminal/` | 终端主页面 |
| `/terminal/config/` | 命令配置管理页面 |

### AI 服务商选择器首屏约束

- `/terminal/` 的页面上下文必须直接包含当前可用服务商、默认服务商和模型列表，首屏不得再依赖额外接口请求才能结束 `Loading...` 状态。
- `/api/prompt/chat/providers` 同时返回每个服务商的 `models`，作为无首屏快照时的兼容回退；回退请求必须有超时和明确失败状态。
- Mermaid 运行库体积较大，只能在 AI 回复实际包含 Mermaid 代码块时按需加载，不得阻塞终端初始化、服务商选择器或输入区可用性。

### Agent MCP 工具路由约束

- Agent 只直接调用 MCP 会话实际发布的核心工具，例如 `agom_capability_search`、`agom_capability_schema` 和 `agom_capability_call`。
- `terminal.search.user_actions` 等带点号名称是能力键，不是可直接调用的工具名；内部 `executor_ref` 也不得写入提示词作为工具调用目标。
- 能力检索、Schema 读取和执行必须通过上述核心工具完成，由 MCP dispatcher 再路由到内部执行器。
- Agents SDK 使用 `tool_not_found_behavior="return_error_to_model"`，使旧会话或模型生成的过期工具名能够返回模型纠正，而不是直接终止整轮终端对话。

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
