# 首页 AI 聊天复用 Terminal 渲染与路由能力外包实施任务书（2026-03-20）

> 生效日期：2026-03-20
> 文档类型：外包实施规格 + 开发任务书 + 验收清单
> 适用团队：外包开发团队、外包测试团队、内部技术验收团队
> 适用范围：首页右侧 AI 聊天窗口、可复用 `AgomChatWidget`、共享聊天 API、共享渲染层、Capability Routing 网页接入层
> 环境边界：仅开发/测试环境实施与验收；禁止修改生产权限策略或新增高风险自动执行链路

---

## 1. 背景与目标

当前系统中存在两套 AI 聊天实现，能力明显分叉：

1. Terminal 聊天已支持较完整的富展示能力：
   - Markdown 渲染
   - Mermaid 渲染
   - answer chain 折叠展示
   - richer metadata 展示
   - capability routing 建议执行
2. 首页右侧 AI 聊天窗口仍是内联脚本，只有最基础的纯文本问答。
3. `AgomChatWidget` 虽然是组件化实现，但仍走旧的 prompt chat 最简接口，不具备 terminal 的富展示与建议执行能力。
4. 当前三者没有共享渲染层，也没有统一网页聊天 API，导致能力持续分叉、维护成本高、行为不一致。

本任务目标是：把首页聊天窗口和 `AgomChatWidget` 升级为一套共享网页聊天实现，复用 terminal 已验证的“富渲染能力 + capability routing 输出”，但不把 CLI/terminal 交互壳直接搬到网页端。

本期必须完成：

1. 新增一个中性的共享网页聊天 API，不让首页直接依赖 `/api/terminal/chat/`。
2. 共享网页聊天 API 底层复用现有 capability routing。
3. 首页右侧聊天窗口接入共享网页聊天 API。
4. `AgomChatWidget` 一并接入共享网页聊天 API。
5. 抽取共享聊天渲染层，统一支持：
   - Markdown
   - Mermaid
   - answer chain 折叠
   - metadata 展示
   - 建议执行卡片
6. 网页端对 route suggestion 采用卡片按钮交互，不使用 terminal 的 `Y/N` 输入确认。
7. 保持首页视觉风格，不把首页改成 terminal 终端风格。

本期明确不做：

1. 将首页聊天改造成 CLI 或 pseudo-terminal。
2. 让首页直接暴露 terminal 动态命令列表。
3. 将 terminal 的命令参数收集状态机搬到首页。
4. 改造 provider/model 管理后台。
5. 引入新的前端框架或大型状态管理库。

---

## 2. 范围与边界

### 2.1 In Scope

1. 首页右侧聊天窗口：
   - 当前位于 `core/templates/dashboard/index.html`
2. 共享聊天组件：
   - 当前位于 `core/static/js/components/chat-widget.js`
   - 当前样式位于 `core/static/css/components/chat-widget.css`
3. Terminal 已有富展示逻辑的抽取与复用：
   - 当前主要位于 `static/js/terminal.js`
4. 新增共享网页聊天 API：
   - 供首页与 `AgomChatWidget` 统一调用
5. capability routing 网页接入层：
   - 允许网页聊天获得 answer chain、建议执行、metadata 等 richer 响应

### 2.2 Out of Scope

1. terminal 的 `/status`、`/regime`、动态命令执行链路重写
2. terminal 模式切换、CLI 参数收集、confirmation token 协议改版
3. 全站其他业务页面的聊天入口全面改造
4. AI provider 数据模型或配置中心改造
5. `prompt` 模块通用聊天的产品定义重做

### 2.3 强边界

1. 首页不得直接调用 `/api/terminal/chat/` 作为长期正式方案。
2. 网页聊天不得照搬 terminal 的输入式 `Y/N` 确认。
3. 首页/组件不得引入 terminal 风格的命令解析、参数收集、mode 状态机。
4. answer chain 普通用户不得暴露技术内部字段。
5. 新增共享层必须以“行为复用”为目标，不允许复制出第三份聊天实现。

---

## 3. 目标态定义

### 3.1 产品目标态

完成后，首页聊天窗口与 `AgomChatWidget` 应具备以下统一能力：

1. 支持 AI 富文本回复展示
2. 支持 Markdown 渲染
3. 支持 Mermaid 图表渲染
4. 支持 answer chain 折叠面板
5. 支持 provider/model/tokens metadata 展示
6. 支持 capability routing 的建议动作卡片
7. 保持网页聊天体验，不出现 terminal CLI 风格操作

### 3.2 路由能力目标态

网页聊天请求必须通过共享网页聊天 API 进入 capability routing，统一得到以下三类结果：

1. `chat`
   - 普通聊天回复
2. `capability`
   - 直接命中某个 capability，返回执行结果
3. `ask_confirmation`
   - 返回建议动作卡片，在网页端由按钮触发二次执行

### 3.3 前端交互目标态

当共享网页聊天 API 返回建议动作时：

1. 首页与组件都必须展示建议卡片
2. 卡片至少包含：
   - 建议动作标题
   - 简短说明
   - 建议命令或建议意图
   - “执行建议”按钮
   - “取消”按钮
3. 点击“执行建议”后，前端再次请求共享网页聊天 API 或专用建议执行接口，完成真正执行
4. 点击“取消”后，仅关闭当前建议卡片，不清空会话历史

### 3.4 answer chain 目标态

1. answer chain 默认折叠
2. 点开后展示步骤列表
3. 普通用户只能看概括性步骤
4. admin/staff 可看技术细节
5. 首页和组件的 answer chain 展示行为必须一致

---

## 4. 现状问题清单

外包团队实施前必须理解以下现状，禁止绕过：

1. 首页右侧聊天窗口当前是模板内联脚本实现，不是共享组件。
2. 首页聊天当前走 `/api/prompt/chat`，只返回：
   - `reply`
   - `session_id`
   - `metadata`
3. 当前 `/api/prompt/chat` 不提供：
   - answer chain
   - route suggestion
   - capability decision 语义
4. `AgomChatWidget` 当前也是独立实现，消息只做 `escapeHtml`，没有 Markdown/Mermaid。
5. Terminal 已经有成熟的富渲染能力，但逻辑散落在 `static/js/terminal.js` 内，不能直接整体复用到网页聊天。
6. Terminal 当前使用 `/api/terminal/chat/`，返回 richer 契约，但接口命名和语义偏 terminal。

---

## 5. 方案冻结项（外包无权自行修改）

以下设计已经冻结，外包团队不得自行改动：

1. 首页和 `AgomChatWidget` 统一复用共享网页聊天 API，不再继续走旧的 `/api/prompt/chat`。
2. 不直接让首页调用 `/api/terminal/chat/`。
3. 新增中性共享聊天 API，由该 API 复用 capability routing。
4. 网页端建议动作采用卡片按钮交互，不采用 `Y/N` 输入确认。
5. 首页保持现有视觉风格，不切换为 terminal 风格。
6. `AgomChatWidget` 必须一并升级，不允许只修首页把组件继续留旧逻辑。
7. provider/model 列表继续复用现有 `/api/prompt/chat/providers` 与 `/api/prompt/chat/models`。

---

## 6. 实施总拆分

建议拆为 6 个任务包，允许并行，但必须按依赖顺序合并。

### WP-01 共享网页聊天 API

目标：新增一个供首页与组件统一使用的中性聊天接口。

任务：

1. 新增共享网页聊天 API 端点。
2. 该接口内部复用 `CapabilityRoutingFacade` / `RouteMessageUseCase`。
3. 输入契约兼容当前网页聊天所需字段：
   - `message`
   - `session_id`
   - `provider_name`
   - `model`
   - `context`
4. 输出契约扩展为 richer 结构，支持：
   - `reply`
   - `session_id`
   - `metadata`
   - `metadata.answer_chain`
   - `route_confirmation_required`
   - `suggested_command`
   - `suggested_intent`
   - `suggestion_prompt`
   - `suggested_action`
5. 对网页端建议执行，提供稳定字段，不要求前端自己拼接 terminal 命令文本。

交付物：

1. 新 API 路径与请求/响应文档
2. Serializer / View / Use Case 接入说明
3. 共享 API 调用示例

验收标准：

1. 网页聊天可通过新接口完成普通聊天
2. capability 命中时可返回 answer chain
3. 建议执行场景可返回建议动作对象
4. 非 admin 不暴露技术字段

### WP-02 共享聊天渲染层

目标：抽取 terminal 已有富渲染能力，形成网页/terminal 都可复用的共享层。

任务：

1. 从 terminal 中抽出共享聊天渲染逻辑，形成独立共享 JS 模块。
2. 至少抽取以下能力：
   - Markdown 渲染
   - Mermaid 渲染
   - answer chain 折叠渲染
   - assistant metadata 渲染
   - typing indicator
3. 抽取结果不得强依赖 terminal prompt、CLI 状态机、dynamic command 逻辑。
4. 对 answer chain 的默认折叠、展开状态、可访问性属性做统一实现。
5. 提供给 terminal 和网页聊天共同调用的清晰接口。

交付物：

1. 共享渲染模块源码
2. 共享模块接口说明
3. terminal 与网页端接入说明

验收标准：

1. terminal 不因抽取共享层而失去现有功能
2. 首页与组件能正确渲染 Markdown/Mermaid
3. answer chain 默认折叠，展开收起正常

### WP-03 首页聊天窗口接入改造

目标：把首页聊天从模板内联脚本升级为使用共享网页聊天能力的正式实现。

任务：

1. 替换首页当前内联 `sendMessage/addMessage` 逻辑。
2. 首页聊天改为调用共享网页聊天 API。
3. assistant 消息展示改为富渲染。
4. metadata 以网页友好方式展示，不暴露 terminal 语义。
5. 保留首页现有欢迎语、快捷提问、输入区域和整体样式结构。
6. 当返回建议动作时，在消息下方渲染建议卡片。

建议卡片最小字段要求：

1. 标题
2. 简要说明
3. 建议命令或意图
4. 执行按钮
5. 取消按钮

交付物：

1. 首页聊天新实现代码
2. 首页 UI 截图/录屏
3. 首页回归说明

验收标准：

1. 首页普通问答正常
2. 首页 Markdown/Mermaid 正常
3. 首页 answer chain 正常
4. 首页建议卡片可展示与交互

### WP-04 AgomChatWidget 升级

目标：把组件层也统一接入共享网页聊天能力，避免继续分叉。

任务：

1. `AgomChatWidget` 改为默认调用共享网页聊天 API。
2. 消息渲染不再使用纯 `escapeHtml` 文本输出。
3. 支持：
   - Markdown
   - Mermaid
   - answer chain
   - metadata
   - 建议动作卡片
4. 保持现有构造参数尽量兼容，不破坏已有调用方式。
5. 若新增配置项，只能增量添加，不得破坏旧接口。

建议新增但不强制暴露的配置能力：

1. 是否显示 answer chain
2. 是否显示 suggestion card
3. 是否启用 provider/model selector

交付物：

1. 升级后的 `AgomChatWidget`
2. 示例页更新
3. 向后兼容说明

验收标准：

1. 示例页可正常使用
2. 现有使用方不因本次升级报错
3. 组件消息展示能力与首页一致

### WP-05 建议动作卡片与二次执行协议

目标：把 capability routing 的 `ask_confirmation` 结果落成网页可操作体验。

任务：

1. 定义网页端建议动作卡片的数据结构。
2. 后端返回可直接消费的建议动作对象。
3. 前端点击“执行建议”后，执行真正调用。
4. 点击“取消”后只关闭卡片，不影响消息历史。
5. 若建议动作已失效、参数不足或权限不足，后端返回明确错误，前端以网页消息方式展示。

建议动作对象至少包含：

1. `action_type`
2. `capability_key`
3. `command`
4. `intent`
5. `label`
6. `description`
7. `payload`

强制要求：

1. 前端不得通过拼接自然语言文本来“猜测执行什么”
2. 建议动作必须基于后端返回的明确结构化字段
3. 不得使用 terminal `Y/N` 输入协议

交付物：

1. 建议动作契约文档
2. 建议动作成功/失败交互说明
3. UI 截图/录屏

验收标准：

1. 建议动作卡片可稳定展示
2. 执行按钮能触发正确后端逻辑
3. 取消按钮行为明确
4. 异常反馈清晰

### WP-06 测试、文档与验收资产

目标：确保交付可复验，不接受“肉眼看起来可以”。

任务：

1. 补齐共享 API 测试
2. 补齐前端渲染测试或最小行为验证
3. 补齐首页集成回归测试
4. 补齐组件示例页回归检查
5. 输出交付说明、接口文档、已知限制与回滚说明

交付物：

1. 自动化测试
2. 回归记录
3. 接口文档
4. 最终交付报告

验收标准：

1. 关键接口与前端行为均有测试或明确回归记录
2. 验收团队能按文档直接复现

---

## 7. 接口契约（外包必须按此执行）

### 7.1 共享网页聊天接口

建议路径：

`POST /api/chat/web/`

请求最小结构：

```json
{
  "message": "当前系统是什么状态",
  "session_id": "optional-session-id",
  "provider_name": "openai-main",
  "model": "gpt-4.1",
  "context": {
    "history": []
  }
}
```

响应最小结构：

```json
{
  "reply": "## System Readiness: `ok`",
  "session_id": "uuid-string",
  "metadata": {
    "provider": "capability-router",
    "model": "router",
    "tokens": 0,
    "answer_chain": {
      "label": "View answer chain",
      "visibility": "masked",
      "steps": []
    }
  },
  "route_confirmation_required": false,
  "suggested_command": null,
  "suggested_intent": null,
  "suggestion_prompt": null,
  "suggested_action": null
}
```

建议执行场景最小结构：

```json
{
  "reply": "检测到你可能想执行系统状态检查。",
  "session_id": "uuid-string",
  "metadata": {
    "provider": "capability-router",
    "model": "router",
    "answer_chain": {
      "label": "View answer chain",
      "visibility": "masked",
      "steps": []
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

### 7.2 建议动作执行

允许两种实现方式，二选一，但必须文档化并保持稳定：

1. 继续调用共享网页聊天 API，并传入结构化建议动作 payload
2. 单独新增建议动作执行接口

无论采用哪种方式，都必须满足：

1. 前端不用拼自然语言猜执行逻辑
2. 后端用结构化 payload 判定真正执行目标
3. 响应继续沿用统一聊天消息返回结构

### 7.3 兼容约束

1. provider/model 列表接口继续复用：
   - `/api/prompt/chat/providers`
   - `/api/prompt/chat/models`
2. 旧的 `/api/prompt/chat` 可保留，但不得继续作为首页与 `AgomChatWidget` 主调用链

---

## 8. 关键实现规则

### 8.1 前端规则

1. 共享渲染层必须和业务页面解耦。
2. 首页与组件必须都通过共享层渲染 assistant 消息。
3. answer chain 默认折叠。
4. `hidden` 状态必须真正生效，不能出现“视觉上展开但逻辑是折叠”的假状态。
5. Mermaid 渲染失败时必须降级显示源码块，不得整条消息报错。
6. suggestion card 的执行/取消按钮必须是明确按钮，不是文本链接伪装。

### 8.2 后端规则

1. 共享网页聊天 API 必须复用 capability routing，不得再复制一套独立路由逻辑。
2. 普通用户 answer chain 不得暴露内部实现字段。
3. 网页端建议动作必须依赖结构化字段，不得依赖 prompt text parsing。
4. API 字段命名不得继续使用 terminal 专属语义作为主字段。
5. 如果底层 capability routing 失败，应返回明确错误，不得 silently fallback 到旧 prompt chat。

### 8.3 复用规则

1. 允许复用 terminal 的成熟渲染逻辑。
2. 不允许把 `terminal.js` 整份复制为网页聊天脚本。
3. 不允许再新建第三套聊天渲染实现。
4. terminal 专属逻辑必须留在 terminal，不得污染共享层：
   - command parsing
   - prompt indicator
   - CLI history
   - pending params
   - `Y/N` 确认

---

## 9. 测试计划（外包必须交付）

### 9.1 后端测试

至少覆盖以下场景：

1. 普通网页聊天请求成功返回 `reply/session_id/metadata`
2. capability 命中时返回 `metadata.answer_chain`
3. 建议执行场景返回 `route_confirmation_required=true`
4. 建议动作对象字段完整且可消费
5. 非 admin 返回的 answer chain 不含技术字段
6. admin/staff 返回的 answer chain 含技术字段
7. provider/model 透传正常

### 9.2 前端渲染测试

至少覆盖以下场景：

1. Markdown 标题/列表/代码块正确渲染
2. 表格正确渲染
3. Mermaid 成功渲染为图
4. Mermaid 失败时正确降级
5. answer chain 默认折叠
6. answer chain 点击展开/收起正常
7. metadata 正确展示 provider/model/tokens
8. suggestion card 渲染正常

### 9.3 首页集成测试

至少覆盖以下场景：

1. 首页发送普通消息成功
2. 首页显示 assistant 富文本回复
3. 首页 suggestion card 点击“执行建议”成功
4. 首页 suggestion card 点击“取消”后卡片关闭
5. 首页欢迎语、快捷提问、滚动行为不回归

### 9.4 组件回归测试

至少覆盖以下场景：

1. `AgomChatWidget` 在示例页可正常使用
2. provider/model selector 正常工作
3. session/history 正常工作
4. 组件渲染能力与首页一致
5. 未提供 answer chain 时不报错

### 9.5 Terminal 回归测试

至少覆盖以下场景：

1. terminal 原有 Markdown/Mermaid 渲染不退化
2. terminal answer chain 仍默认折叠
3. terminal route suggestion 仍保持原有 terminal 交互，不被网页卡片逻辑替换

---

## 10. 强制验收标准（DoD）

以下条目必须全部满足，否则不得验收通过：

1. 首页聊天不再使用旧的最简纯文本实现
2. `AgomChatWidget` 不再停留在纯文本输出
3. 新增共享网页聊天 API 已上线并可用
4. 首页与组件都能展示 Markdown
5. 首页与组件都能展示 Mermaid
6. 首页与组件都支持 answer chain 折叠
7. 首页与组件都支持 suggestion card
8. 网页端 suggestion card 使用按钮交互，不是 `Y/N` 输入
9. 非 admin answer chain 不泄露技术字段
10. terminal 原有能力无回归
11. 自动化测试或完整回归记录已交付

---

## 11. 交付物清单

外包团队最终必须提交：

1. 共享网页聊天 API 源码
2. 共享渲染层源码
3. 首页聊天改造代码
4. `AgomChatWidget` 升级代码
5. 建议动作卡片实现
6. 自动化测试或测试记录
7. 接口文档
8. 回归清单
9. 已知限制说明
10. 回滚说明

---

## 12. 内部验收团队直接检查项

内部验收时按以下顺序检查：

1. 打开首页，发送普通问题，确认 assistant 回复支持 Markdown
2. 发送能触发 capability 的问题，确认可展示 answer chain
3. 发送能触发建议动作的问题，确认 suggestion card 出现
4. 点击“执行建议”，确认返回结果正常
5. 点击“取消”，确认仅关闭卡片
6. 打开 `chat_example` 页面，确认 `AgomChatWidget` 行为一致
7. 打开 terminal，确认原有 Markdown/Mermaid/answer chain 不退化

---

## 13. 明确禁止事项

外包团队不得：

1. 让首页直接依赖 `/api/terminal/chat/`
2. 继续让首页或 `AgomChatWidget` 走旧的 `/api/prompt/chat` 作为正式主链路
3. 把 terminal CLI 状态机整体搬到网页聊天
4. 使用自然语言文本拼接来决定 suggestion card 执行动作
5. 把普通用户 answer chain 技术字段直接返回前端
6. 新建第三套聊天渲染实现
7. 为了赶工只修首页，不升级 `AgomChatWidget`

---

## 14. 建议实施顺序

必须按以下顺序执行：

1. 先建共享网页聊天 API
2. 再抽共享渲染层
3. 再改首页聊天
4. 再升级 `AgomChatWidget`
5. 再补 suggestion card 执行链路
6. 最后补测试和文档

原因：

1. 没有稳定 API，前端改造会反复返工
2. 不先抽共享层，会继续复制逻辑
3. 首页和组件必须建立在同一渲染能力上

---

## 15. 备注

本任务书是“首页 AI 聊天复用 terminal 渲染与路由能力”这批次工作的唯一实施与验收依据。

如外包团队认为存在实现上的更优路径，可在不改变本文行为约束、接口约束、交互约束和验收口径的前提下提交说明，但不得自行改变产品定义或范围边界。
