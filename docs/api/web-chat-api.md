# Shared Web Chat API 文档

> **模块**: Homepage Chat / `AgomChatWidget` / AI Capability Routing  
> **版本**: V1.0  
> **最后更新**: 2026-03-20  
> **主入口**: `POST /api/chat/web/`

---

## 1. 概述

Shared Web Chat API 是网页端统一聊天入口，供以下前端复用：

1. 首页右侧 AI 聊天窗口
2. `AgomChatWidget` 组件
3. 未来其他页面内嵌 AI 助手

该接口复用系统级 AI Capability Routing，不再让首页或组件直接依赖旧的 `/api/prompt/chat` 作为主调用链。

---

## 2. 设计目标

该接口需要同时满足以下目标：

1. 支持普通对话与 capability routing 共存
2. 支持 Markdown / Mermaid / answer chain / metadata 展示
3. 支持网页端 suggestion card 交互
4. 支持结构化“执行建议动作”，而不是依赖自然语言 prompt 猜测
5. 保持对多页面、多组件复用友好

---

## 3. 认证与权限

### 3.1 认证要求

所有请求需要登录态。

推荐请求头：

```http
Content-Type: application/json
X-CSRFToken: <csrf_token>
```

### 3.2 权限差异

1. 所有已登录用户可调用 `POST /api/chat/web/`
2. `answer_chain` 对非 staff/admin 用户默认做技术细节脱敏
3. staff/admin 可看到未脱敏的 answer chain 技术细节

---

## 4. API 总览

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/chat/web/` | POST | 网页端统一聊天入口 |
| `/api/prompt/chat/providers` | GET | 获取 provider 列表 |
| `/api/prompt/chat/models?provider=<name>` | GET | 获取指定 provider 的模型列表 |

---

## 5. 主接口：网页聊天

### 5.1 端点

```http
POST /api/chat/web/
```

### 5.2 请求体

```json
{
  "message": "当前系统是什么状态",
  "session_id": "optional-session-id",
  "provider_name": "openai-main",
  "model": "gpt-4.1",
  "context": {
    "history": [
      {"role": "user", "content": "你好"},
      {"role": "assistant", "content": "你好，我可以帮你做什么？"}
    ]
  }
}
```

### 5.3 请求字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `message` | string | 是 | 当前用户输入 |
| `session_id` | string \| null | 否 | 会话 ID；不传则后端生成 |
| `provider_name` | string \| null | 否 | 指定 AI provider |
| `model` | string \| null | 否 | 指定模型 |
| `context` | object | 否 | 扩展上下文 |
| `context.history` | array | 否 | 历史消息列表 |

### 5.4 默认行为

后端调用 routing facade 时固定使用：

1. `entrypoint="web"`
2. `mcp_enabled=true`
3. `answer_chain_enabled=true`

---

## 6. 普通聊天响应

### 6.1 示例

```json
{
  "reply": "当前系统运行正常，可以继续查看宏观环境或投资组合状态。",
  "session_id": "f2c70f3f-5711-4c28-a8de-7a2d7f2abcb8",
  "metadata": {
    "provider": "openai-main",
    "model": "gpt-4.1",
    "tokens": 821,
    "answer_chain": {
      "label": "View answer chain",
      "visibility": "masked",
      "steps": [
        {
          "title": "Intent recognition",
          "summary": "Recognized the request as a general web chat question.",
          "source": "capability-router"
        }
      ]
    }
  },
  "route_confirmation_required": false,
  "suggested_command": null,
  "suggested_intent": null,
  "suggestion_prompt": null,
  "suggested_action": null
}
```

### 6.2 响应字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `reply` | string | AI 回复正文，允许 Markdown |
| `session_id` | string | 会话 ID |
| `metadata.provider` | string | 响应来源 provider |
| `metadata.model` | string | 响应来源模型 |
| `metadata.tokens` | integer | token 数，未知时可为 `0` |
| `metadata.answer_chain` | object \| null | answer chain 数据 |
| `route_confirmation_required` | boolean | 是否需要展示建议执行卡片 |
| `suggested_command` | string \| null | 建议命令 |
| `suggested_intent` | string \| null | 建议意图 |
| `suggestion_prompt` | string \| null | 建议提示文本 |
| `suggested_action` | object \| null | 结构化建议动作 |

---

## 7. 建议执行响应

当命中 capability 且需要网页端显式确认时，接口返回 suggestion card 所需字段。

### 7.1 示例

```json
{
  "reply": "检测到你可能想执行系统状态检查。",
  "session_id": "f2c70f3f-5711-4c28-a8de-7a2d7f2abcb8",
  "metadata": {
    "provider": "capability-router",
    "model": "router",
    "tokens": 0,
    "answer_chain": {
      "label": "View answer chain",
      "visibility": "masked",
      "steps": [
        {
          "title": "Capability selection",
          "summary": "Matched the request to a system status capability.",
          "source": "capability-router"
        }
      ]
    }
  },
  "route_confirmation_required": true,
  "suggested_command": "/status",
  "suggested_intent": "system_status",
  "suggestion_prompt": "检测到你可能想执行 /status。",
  "suggested_action": {
    "action_type": "execute_capability",
    "capability_key": "builtin.system_status",
    "command": "/status",
    "intent": "system_status",
    "label": "执行系统状态检查",
    "description": "读取当前系统健康状态并返回摘要",
    "payload": {}
  }
}
```

### 7.2 `suggested_action` 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `action_type` | string | 当前固定为 `execute_capability` |
| `capability_key` | string | 要执行的 capability key |
| `command` | string | 建议展示给用户的命令 |
| `intent` | string | 检测到的意图 |
| `label` | string | 卡片主按钮标题 |
| `description` | string | 卡片说明 |
| `payload` | object | 保留扩展字段 |

---

## 8. 显式执行建议动作

网页端点击 suggestion card 的 `Execute` 按钮时，继续调用同一个接口：

```http
POST /api/chat/web/
```

### 8.1 推荐请求结构

```json
{
  "message": "/status",
  "session_id": "f2c70f3f-5711-4c28-a8de-7a2d7f2abcb8",
  "provider_name": "openai-main",
  "model": "gpt-4.1",
  "context": {
    "history": [
      {"role": "user", "content": "当前系统是什么状态"}
    ],
    "execute_action": {
      "action_type": "execute_capability",
      "capability_key": "builtin.system_status",
      "command": "/status",
      "intent": "system_status"
    }
  }
}
```

### 8.2 兼容请求结构

首页当前也兼容以下旧格式：

```json
{
  "message": "/status",
  "session_id": "f2c70f3f-5711-4c28-a8de-7a2d7f2abcb8",
  "context": {
    "execute_capability": "builtin.system_status",
    "action_type": "execute_capability"
  }
}
```

### 8.3 行为说明

1. 后端优先识别结构化执行字段
2. 一旦识别到 `execute_capability`，按指定 capability 直接执行
3. 不再重复走“建议执行”确认提示
4. 响应继续沿用统一聊天返回结构

---

## 9. `metadata.answer_chain` 结构

### 9.1 示例

```json
{
  "label": "View answer chain",
  "visibility": "masked",
  "steps": [
    {
      "title": "Capability selection",
      "summary": "Matched the request to a system capability.",
      "source": "capability-router"
    }
  ]
}
```

### 9.2 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `label` | string | 前端折叠按钮文本 |
| `visibility` | string | `masked` / `technical` |
| `steps` | array | 推理步骤列表 |
| `steps[].title` | string | 步骤标题 |
| `steps[].summary` | string | 步骤摘要 |
| `steps[].source` | string | 来源说明 |
| `steps[].technical_details` | array | 仅在技术可见时返回 |

### 9.3 可见性规则

1. 非 staff/admin：`technical_details` 被移除
2. staff/admin：保留完整 answer chain

---

## 10. Provider / Model 辅助接口

Shared Web Chat 本身不提供 provider/model 目录，而是复用 prompt 模块现有接口。

### 10.1 获取 provider 列表

```http
GET /api/prompt/chat/providers
```

示例响应：

```json
{
  "providers": [
    {
      "name": "openai-main",
      "display_label": "OpenAI Main",
      "default_model": "gpt-4.1"
    }
  ],
  "default_provider": "openai-main"
}
```

### 10.2 获取模型列表

```http
GET /api/prompt/chat/models?provider=openai-main
```

示例响应：

```json
{
  "models": ["gpt-4.1", "gpt-4.1-mini"]
}
```

---

## 11. 前端接入要求

### 11.1 首页聊天

首页聊天调用链要求：

1. 主接口使用 `/api/chat/web/`
2. `Execute` 按钮继续调用 `/api/chat/web/`
3. 使用 `AgomSharedChatRenderer`
4. 必须加载：
   - `js/marked.min.js`
   - `js/mermaid.min.js`
   - `js/shared/shared-chat-renderer.js`

### 11.2 `AgomChatWidget`

组件接入要求：

1. 默认 `useSharedApi: true`
2. 支持 `showAnswerChain`
3. 支持 `showSuggestionCard`
4. 点击 suggestion card 时发结构化 `execute_action`

### 11.3 Markdown / Mermaid

`reply` 允许包含：

1. 标题、列表、代码块、表格
2. ` ```mermaid ` 代码块

前端约束：

1. Mermaid 渲染失败时降级显示源码块
2. answer chain 默认折叠
3. `hidden` 状态必须真正隐藏面板

---

## 12. 错误响应

### 12.1 500 示例

```json
{
  "error": "Capability not found: builtin.unknown",
  "reply": "聊天请求处理失败: Capability not found: builtin.unknown"
}
```

### 12.2 常见错误场景

| 场景 | 说明 |
|------|------|
| capability 不存在 | `execute_capability` 指向无效 key |
| provider/model 无效 | 底层 provider 无法调用 |
| routing 失败 | capability routing facade 抛异常 |
| 网络错误 | 前端 fetch 失败 |

---

## 13. 典型调用流程

### 13.1 普通问答

1. 前端发送用户消息到 `/api/chat/web/`
2. 后端执行 capability routing
3. 若未命中明确 capability，则返回普通聊天回复
4. 前端渲染 Markdown + metadata + answer chain

### 13.2 建议执行

1. 用户发送“当前系统是什么状态”
2. 后端识别为 `builtin.system_status`
3. 返回 `route_confirmation_required=true`
4. 前端渲染 suggestion card
5. 用户点击 `Execute`
6. 前端带 `execute_action` 再次调用 `/api/chat/web/`
7. 后端直接执行 capability 并返回最终结果

---

## 14. 当前实现文件

主要实现位置：

1. [api_views.py](/D:/githv/agomSAAF/apps/ai_capability/interface/api_views.py)
2. [serializers.py](/D:/githv/agomSAAF/apps/ai_capability/interface/serializers.py)
3. [facade.py](/D:/githv/agomSAAF/apps/ai_capability/application/facade.py)
4. [shared-chat-renderer.js](/D:/githv/agomSAAF/core/static/js/shared/shared-chat-renderer.js)
5. [chat-widget.js](/D:/githv/agomSAAF/core/static/js/components/chat-widget.js)
6. [index.html](/D:/githv/agomSAAF/core/templates/dashboard/index.html)

---

## 15. 兼容性说明

1. 旧的 `/api/prompt/chat` 仍可保留给历史调用方
2. 首页和 `AgomChatWidget` 的主链路应使用 `/api/chat/web/`
3. `execute_action` 是推荐执行格式
4. `execute_capability + action_type` 作为兼容格式暂时保留

