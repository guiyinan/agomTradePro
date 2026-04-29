# AI Capability Catalog 模块指南

> **模块**: `apps/ai_capability/`  
> **版本**: V1.0  
> **创建日期**: 2026-03-19  
> **最后更新**: 2026-03-22
> **状态**: 生产就绪

---

## 1. 模块概述

### 1.1 定位

AI Capability Catalog 是系统级 AI 能力目录与统一路由服务，为 terminal、chat、agent 等多个入口提供统一的 AI 能力检索、决策和执行框架。

### 1.2 核心能力

| 能力 | 说明 |
|------|------|
| **能力目录管理** | 统一管理 builtin、terminal_command、mcp_tool、api 四类能力 |
| **自动采集** | 自动采集全站 API 端点并入库 |
| **安全分层** | 自动识别 unsafe_api，默认不参与路由 |
| **统一路由** | 三阶段路由：Retrieval → Decision → Dispatch |
| **审计追踪** | 记录所有路由决策和执行结果 |

### 1.3 设计原则

1. **系统级能力** - 不属于 terminal 私域，可供多入口复用
2. **代码主导** - 数据库承载，但真实来源仍是代码
3. **安全优先** - 高危接口自动阻断，写操作需确认

---

## 2. 核心概念

### 2.1 能力来源 (Source Type)

| 类型 | 说明 | 示例 |
|------|------|------|
| `builtin` | 内置能力 | system_status, market_regime |
| `terminal_command` | Terminal 命令配置 | 来自 TerminalCommandORM |
| `mcp_tool` | MCP 工具 | data_center_get_macro_series, get_current_regime |
| `api` | 内部 API 端点 | GET /api/regime/, POST /api/signal/ |

### 2.2 路由分组 (Route Group)

| 分组 | 说明 | 默认行为 |
|------|------|----------|
| `builtin` | 内置能力 | 可路由 |
| `tool` | MCP 工具 | 可路由 |
| `read_api` | 只读 API (GET/HEAD/OPTIONS) | 可路由 |
| `write_api` | 写入 API (POST/PUT/PATCH/DELETE) | 可路由，需确认 |
| `unsafe_api` | 高危 API | 不可路由 |

### 2.3 风险等级 (Risk Level)

| 等级 | 说明 | 典型场景 |
|------|------|----------|
| `safe` | 安全 | 只读查询 |
| `low` | 低风险 | 参数化查询 |
| `medium` | 中风险 | 写入操作 |
| `high` | 高风险 | 批量操作 |
| `critical` | 关键 | 管理员操作 |

### 2.4 路由决策 (Decision)

| 决策 | 说明 | 置信度阈值 |
|------|------|------------|
| `capability` | 高置信度匹配，直接执行 | ≥ 0.85 |
| `ask_confirmation` | 中置信度，建议执行 | ≥ 0.60 |
| `chat` | 低置信度，普通聊天 | < 0.60 |

---

## 3. API 接口

### 3.0 网页聊天接口索引

如果你要接入首页聊天、`AgomChatWidget` 或其他页面内嵌 AI 助手，优先查看共享网页聊天接口文档：

- [Shared Web Chat API 文档](/D:/githv/agomTradePro/docs/api/web-chat-api.md)

该文档覆盖：

1. `POST /api/chat/web/` 请求/响应契约
2. suggestion card 的结构化执行方式
3. `answer_chain` / `metadata` 字段说明
4. 首页与 `AgomChatWidget` 的接入约束

### 3.1 统一路由接口

**端点**: `POST /api/ai-capability/route/`

**权限**: 需要登录

**请求体**:

```json
{
  "message": "目前系统是什么状态",
  "entrypoint": "terminal",
  "session_id": "optional-session-id",
  "provider_name": "openai-main",
  "model": "gpt-4.1",
  "context": {
    "user_is_admin": false,
    "mcp_enabled": true,
    "answer_chain_enabled": true,
    "history": []
  }
}
```

**响应 - 高置信度能力匹配**:

```json
{
  "decision": "capability",
  "selected_capability_key": "builtin.system_status",
  "confidence": 0.94,
  "candidate_capabilities": [
    {
      "capability_key": "builtin.system_status",
      "name": "System Status",
      "summary": "Check system health and readiness status",
      "category": "system",
      "risk_level": "safe",
      "requires_confirmation": false
    }
  ],
  "requires_confirmation": false,
  "reply": "## System Readiness: `ok`\n- **Database**: `ok`\n...",
  "session_id": "uuid-string",
  "metadata": {
    "route": "capability",
    "provider": "capability-router",
    "model": "router"
  },
  "answer_chain": {
    "label": "Answer chain",
    "visibility": "masked",
    "steps": [...]
  }
}
```

**响应 - 中置信度建议**:

```json
{
  "decision": "ask_confirmation",
  "selected_capability_key": "builtin.system_status",
  "confidence": 0.67,
  "requires_confirmation": true,
  "reply": "检测到你可能想执行 System Status。建议执行 `/status`。",
  "reason": "Top capability is plausible but below the direct execution threshold.",
  "rejected_candidates": ["builtin.market_regime"],
  "missing_params": [],
  "suggested_command": "/status",
  "suggested_intent": "system_status",
  "suggestion_prompt": "检测到你可能想执行 /status。输入 Y 执行，输入 N 取消，或继续输入其他内容。"
}
```

**响应 - 普通聊天**:

```json
{
  "decision": "chat",
  "selected_capability_key": null,
  "confidence": 0.21,
  "requires_confirmation": false,
  "reply": "普通聊天回答内容...",
  "metadata": {
    "route": "chat",
    "provider": "openai-main",
    "model": "gpt-4.1"
  }
}
```

### 3.2 能力列表接口

**端点**: `GET /api/ai-capability/capabilities/`

**权限**: 需要登录

**可见性规则**:

1. staff/admin 可见完整技术字段，包括 `source_ref`、`input_schema`、`execution_target`
2. 非 admin 仅返回说明性字段，不暴露内部执行目标和技术引用

**查询参数**:

| 参数 | 类型 | 说明 |
|------|------|------|
| `source_type` | string | 过滤来源类型 |
| `route_group` | string | 过滤路由分组 |
| `enabled_only` | boolean | 仅返回启用的能力 (默认 true) |

**响应**:

```json
[
  {
    "capability_key": "builtin.system_status",
    "name": "System Status",
    "summary": "Check system health and readiness status",
    "source_type": "builtin",
    "route_group": "builtin",
    "category": "system",
    "risk_level": "safe",
    "enabled_for_routing": true
  }
]
```

### 3.3 能力详情接口

**端点**: `GET /api/ai-capability/capabilities/<str:capability_key>/`

**权限**: 需要登录

**响应**:

```json
{
  "capability_key": "builtin.system_status",
  "source_type": "builtin",
  "source_ref": "terminal:system_status",
  "name": "System Status",
  "summary": "Check system health and readiness status",
  "description": "Returns current system health including database, Redis, Celery, and critical data status.",
  "route_group": "builtin",
  "category": "system",
  "tags": ["status", "health", "system", "readiness"],
  "when_to_use": [
    "User asks about system status",
    "User wants to check if the system is healthy"
  ],
  "when_not_to_use": [
    "User is asking about market data",
    "User wants to execute trades"
  ],
  "examples": [
    "目前系统是什么状态",
    "系统健康吗",
    "check system status"
  ],
  "input_schema": {},
  "execution_kind": "sync",
  "execution_target": {
    "type": "builtin",
    "handler": "system_status"
  },
  "risk_level": "safe",
  "requires_mcp": false,
  "requires_confirmation": false,
  "enabled_for_routing": true,
  "enabled_for_terminal": true,
  "enabled_for_chat": true,
  "enabled_for_agent": true,
  "visibility": "public",
  "auto_collected": false,
  "review_status": "auto",
  "priority_weight": 10.0
}
```

### 3.4 同步接口

**端点**: `POST /api/ai-capability/sync/`

**权限**: 仅管理员

**请求体**:

```json
{
  "sync_type": "full"
}
```

**响应**:

```json
{
  "sync_type": "full",
  "total_discovered": 2259,
  "created_count": 2213,
  "updated_count": 46,
  "disabled_count": 0,
  "error_count": 0,
  "duration_seconds": 4.63,
  "summary": {
    "builtin": {"created": 2, "updated": 0},
    "terminal_command": {"created": 0, "updated": 0},
    "mcp_tool": {"created": 0, "updated": 0},
    "api": {"created": 2211, "updated": 46}
  }
}
```

### 3.5 统计接口

**端点**: `GET /api/ai-capability/stats/`

**权限**: 需要登录

**响应**:

```json
{
  "total": 2213,
  "enabled": 2023,
  "disabled": 190,
  "by_source": {
    "builtin": 2,
    "terminal_command": 0,
    "mcp_tool": 0,
    "api": 2211
  },
  "by_route_group": {
    "builtin": 2,
    "tool": 0,
    "read_api": 858,
    "write_api": 1163,
    "unsafe_api": 190
  }
}
```

---

## 4. 管理命令

### 4.1 初始化命令

```bash
python manage.py init_ai_capability_catalog
```

**功能**: 全量扫描并初始化能力目录

**输出示例**:

```
Initializing AI capability catalog...

Initialization complete in 4.63s
  Total discovered: 2259
  Created: 2213
  Updated: 46
  Disabled: 0
  Errors: 0

Details by source:
  builtin:
    Created: 2
    Updated: 0
  api:
    Created: 2211
    Updated: 46
```

### 4.2 同步命令

```bash
python manage.py sync_ai_capability_catalog [--type incremental]
```

**参数**:

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--type` | 同步类型: full, incremental | incremental |

### 4.3 审查命令

```bash
python manage.py review_ai_capability_catalog [--format json]
```

**输出示例**:

```
============================================================
AI Capability Catalog Review
============================================================

Total capabilities: 2213
  Enabled: 2023
  Disabled: 190

By Source Type:
  builtin: 2
  terminal_command: 0
  mcp_tool: 0
  api: 2211

By Route Group:
  builtin: 2
  tool: 0
  read_api: 858
  write_api: 1163
  unsafe_api: 190

============================================================

Warning: 190 unsafe API(s) detected

Warnings:
  - No MCP tools found

============================================================
Review complete
```

---

## 5. 数据模型

### 5.1 CapabilityCatalogModel

| 字段 | 类型 | 说明 |
|------|------|------|
| `capability_key` | CharField(255) | 唯一能力标识 |
| `source_type` | CharField(30) | 来源类型 |
| `source_ref` | CharField(255) | 原始来源引用 |
| `name` | CharField(255) | 能力名称 |
| `summary` | TextField | 简短摘要 |
| `description` | TextField | 详细描述 |
| `route_group` | CharField(20) | 路由分组 |
| `category` | CharField(100) | 分类 |
| `tags` | JSONField | 标签列表 |
| `when_to_use` | JSONField | 使用场景 |
| `when_not_to_use` | JSONField | 禁用场景 |
| `examples` | JSONField | 示例查询 |
| `input_schema` | JSONField | 输入 Schema |
| `execution_kind` | CharField(20) | 执行类型 |
| `execution_target` | JSONField | 执行目标 |
| `risk_level` | CharField(20) | 风险等级 |
| `requires_mcp` | BooleanField | 是否需要 MCP |
| `requires_confirmation` | BooleanField | 是否需要确认 |
| `enabled_for_routing` | BooleanField | 是否启用路由 |
| `enabled_for_terminal` | BooleanField | Terminal 可用 |
| `enabled_for_chat` | BooleanField | Chat 可用 |
| `enabled_for_agent` | BooleanField | Agent 可用 |
| `visibility` | CharField(20) | 可见性 |
| `auto_collected` | BooleanField | 自动采集 |
| `review_status` | CharField(20) | 审核状态 |
| `priority_weight` | FloatField | 优先级权重 |

### 5.2 CapabilityRoutingLogModel

| 字段 | 类型 | 说明 |
|------|------|------|
| `entrypoint` | CharField(50) | 入口点 |
| `user` | ForeignKey | 用户 |
| `session_id` | CharField(100) | 会话 ID |
| `raw_message` | TextField | 原始消息 |
| `retrieved_candidates` | JSONField | 候选能力列表 |
| `selected_capability_key` | CharField(255) | 选中的能力 |
| `confidence` | FloatField | 置信度 |
| `decision` | CharField(30) | 决策类型 |
| `fallback_reason` | TextField | 回退原因 |
| `execution_result` | TextField | 执行结果 |
| `created_at` | DateTimeField | 创建时间 |

### 5.3 CapabilitySyncLogModel

| 字段 | 类型 | 说明 |
|------|------|------|
| `sync_type` | CharField(30) | 同步类型 |
| `started_at` | DateTimeField | 开始时间 |
| `finished_at` | DateTimeField | 结束时间 |
| `total_discovered` | IntegerField | 发现总数 |
| `created_count` | IntegerField | 创建数量 |
| `updated_count` | IntegerField | 更新数量 |
| `disabled_count` | IntegerField | 禁用数量 |
| `error_count` | IntegerField | 错误数量 |
| `summary_payload` | JSONField | 详细摘要 |

---

## 6. 使用示例

### 6.1 Terminal 集成

```python
from apps.ai_capability.application.facade import CapabilityRoutingFacade

facade = CapabilityRoutingFacade()

result = facade.route(
    message="目前系统是什么状态",
    entrypoint='terminal',
    user_id=request.user.id,
    user_is_admin=request.user.is_staff,
    mcp_enabled=getattr(request.user, 'mcp_enabled', True),
    provider_name='openai-main',
    model='gpt-4.1',
    context={
        'username': request.user.username,
        'user_role': 'staff',
        'terminal_mode': 'confirm_each',
    },
    answer_chain_enabled=True,
)

if result['decision'] == 'capability':
    return JsonResponse({'reply': result['reply']})
elif result['decision'] == 'ask_confirmation':
    return JsonResponse({
        'reply': result['reply'],
        'suggested_command': result['suggested_command'],
    })
else:
    return JsonResponse({'reply': result['reply']})
```

**当前接入约定**:

1. `apps.terminal.interface.api_views.TerminalChatView` 已切换到 `CapabilityRoutingFacade`
2. terminal 不再直接调用旧的私有 `TerminalChatRouterService`
3. terminal 保留自身响应字段，系统级路由响应会被映射为 `route_confirmation_required`、`suggested_command` 等前端契约

### 6.2 获取能力列表

```python
from apps.ai_capability.application.use_cases import GetCapabilityListUseCase

use_case = GetCapabilityListUseCase()

# 获取所有启用的能力
capabilities = use_case.execute()

# 过滤特定类型
api_capabilities = use_case.execute(source_type='api')

# 过滤特定路由分组
read_apis = use_case.execute(route_group='read_api')
```

### 6.3 手动同步

```python
from apps.ai_capability.application.use_cases import SyncCapabilitiesUseCase

use_case = SyncCapabilitiesUseCase()

result = use_case.execute(sync_type='full')

print(f"Created: {result.created_count}")
print(f"Updated: {result.updated_count}")
print(f"Errors: {result.error_count}")
```

**同步行为说明**:

1. `sync_ai_capability_catalog --source api` 现在会真正只同步指定来源
2. 同步结束后会调用 `disable_missing(...)`，将来源中已消失的 capability 标记为 `enabled_for_routing=false`
3. `disabled_count` 表示本次被禁用的失效记录数量

---

## 7. 安全分层规则

### 7.1 自动分层逻辑

| HTTP 方法 | 默认分组 |
|-----------|----------|
| GET, HEAD, OPTIONS | `read_api` |
| POST, PUT, PATCH, DELETE | `write_api` |

### 7.2 高危识别规则

以下模式会被标记为 `unsafe_api`：

- 路径或名称包含: `delete`, `reset`, `toggle`, `approve`, `execute`
- 管理员接口: `admin`, `token`, `secret`, `credential`
- 系统配置: `bootstrap`, `migrate`, `config-center`, `system-settings`

### 7.3 权限检查

| 路由分组 | enabled_for_routing | requires_confirmation | admin_only |
|----------|---------------------|----------------------|------------|
| builtin | ✅ | ❌ | ❌ |
| tool | ✅ | ❌ | ❌ |
| read_api | ✅ | ❌ | ❌ |
| write_api | ✅ | ✅ | ❌ |
| unsafe_api | ❌ | ✅ | ✅ |

---

## 8. 架构说明

### 8.1 四层架构

```
apps/ai_capability/
├── domain/                      # Domain 层
│   ├── entities.py             # 能力实体、路由上下文、决策结果
│   ├── services.py             # 检索评分、过滤服务
│   └── interfaces.py           # Protocol 接口定义
├── application/                 # Application 层
│   ├── use_cases.py            # 路由用例、同步用例
│   ├── dtos.py                 # 请求/响应 DTO
│   └── facade.py               # 统一门面
├── infrastructure/              # Infrastructure 层
│   ├── models.py               # ORM 模型
│   ├── repositories.py         # 数据仓储
│   └── collectors/             # 采集器
│       └── api_collector.py    # API 自动采集
├── interface/                   # Interface 层
│   ├── api_views.py            # DRF 视图
│   ├── serializers.py          # 序列化器
│   ├── admin.py                # Admin 配置
│   └── api_urls.py             # API 路由
└── management/commands/         # 管理命令
    ├── init_ai_capability_catalog.py
    ├── sync_ai_capability_catalog.py
    └── review_ai_capability_catalog.py
```

### 8.2 路由流程

```
用户消息
    │
    ▼
┌─────────────────────────┐
│  Capability Retrieval   │  ← 从 Catalog 检索 top-k 候选
└─────────────────────────┘
    │
    ▼
┌─────────────────────────┐
│  Capability Decision    │  ← AI 在候选中选择/确认
└─────────────────────────┘
    │
    ▼
┌─────────────────────────┐
│  Execution Dispatch     │  ← 分发到对应执行器
└─────────────────────────┘
    │
    ├── builtin → BuiltinExecutor
    ├── terminal_command → TerminalCommandExecutor
    ├── mcp_tool → McpToolExecutor
    └── api → ApiExecutor
```

---

## 9. 常见问题

### Q1: 如何添加新的 builtin 能力？

在 `domain/services.py` 的 `BuiltinCapabilityRegistry.BUILTIN_CAPABILITIES` 中添加：

```python
{
    'capability_key': 'builtin.new_capability',
    'source_type': SourceType.BUILTIN,
    'source_ref': 'terminal:new_capability',
    'name': 'New Capability',
    'summary': 'Description of new capability',
    'execution_target': {'type': 'builtin', 'handler': 'new_capability'},
    # ... 其他字段
}
```

然后在 `use_cases.py` 中实现 `_execute_builtin` 的对应 handler。

### Q2: 如何标记某个 API 为 unsafe？

API 采集器会自动识别高危模式。如需手动标记，可在 Admin 后台修改：

1. 进入 Admin → AI Capability Catalog
2. 找到对应能力
3. 修改 `route_group` 为 `unsafe_api`
4. 取消勾选 `enabled_for_routing`

### Q3: 如何调试路由决策？

1. 启用 `answer_chain_enabled: true`
2. 查看 `CapabilityRoutingLogModel` 中的记录
3. 检查 `retrieved_candidates` 和 `confidence` 字段

---

## 10. 相关文档

- [架构评估报告](architecture/ai-capability-architecture-review-2026-03-19.md)
- [任务书](plans/system-ai-capability-catalog-outsourcing-task-book-2026-03-19.md)
- [CLAUDE.md - 架构规范](../CLAUDE.md)

---

**维护者**: AgomTradePro Team  
**最后更新**: 2026-03-19
