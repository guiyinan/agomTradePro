# MCP Hosted Transport 与身份模型备忘录（2026-05-10）

> 目的：记录 AgomTradePro 当前 MCP 接入形态、是否需要从 `stdio` 演进到 streamable HTTP/SSE，以及是否需要从长期 Token 演进到 per-user OAuth。

---

## 1. 结论摘要

### 1.1 是否有必要升级 transport

- 对**本地单用户** MCP 使用场景：**暂不必要**。
- 对**云端 agent、团队共享、统一网关、多租户**场景：**有必要**。

### 1.2 是否有必要升级身份模型

- 对**本地单用户**使用场景：当前用户级 Token 模型可继续使用。
- 对**云端托管、团队共享、代用户执行、合规审计增强**场景：**有必要**，且优先级高于 transport 升级。

### 1.3 推荐顺序

1. 先把**真实用户身份**稳定打透到 Django 审计。
2. 再把 MCP transport 从 `stdio` 扩展为 streamable HTTP/SSE。

不建议先做“共享 HTTP MCP 网关 + 单 service account”。

---

## 2. 当前系统现状

### 2.1 MCP 运行形态

当前 MCP Server 为独立 Python 进程，基于 `FastMCP` 实现，默认通过 `stdio` 运行。

- 参考：
  - `sdk/agomtradepro_mcp/server.py`
  - `sdk/agomtradepro_mcp/__main__.py`
  - `sdk/pyproject.toml`

关键点：

- 服务实例：`FastMCP("agomtradepro")`
- 默认启动方式：`python -m agomtradepro_mcp`
- 当前 transport：`server.run(transport="stdio")`

### 2.2 后端认证形态

当前 SDK/MCP 主要通过 Django DRF Token 访问后端：

- SDK 请求头使用 `Authorization: Token <token>`
- Django 侧有自定义 `MultiTokenAuthentication`
- Token 解析后能恢复为真实 `request.user`

关键点：

- 当前并非只能使用一个共享 service account
- 系统已支持**每个用户独立 Token**
- Token 模型已记录 `user`、`created_by`、`last_used_at`

### 2.3 当前身份能力的真实边界

当前系统已经具备：

- 用户级访问凭证
- `mcp_enabled` 开关
- 从 `/api/account/profile/` 读取 `rbac_role`
- Django 侧按用户落权限与部分审计

当前系统仍然缺少：

- 标准 OAuth/OIDC 登录授权流程
- 短期访问令牌/刷新机制
- 面向 hosted MCP gateway 的用户授权委托模型
- 面向多租户/多客户端的标准 scope 体系

---

## 3. 为什么本地单用户场景不急

如果使用方式仍然是：

- 每个操作者在自己的本机启动 MCP
- MCP 直接连自己的本地或个人环境 Django
- 每个人使用自己的 Token

那么当前 `stdio + per-user token` 方案有几个明显优点：

- 架构简单，故障面小
- 无需额外暴露网关服务
- 本地调试成本低
- 已能满足“谁调用了后端 API”这一层的基础审计

因此，在**本地个人助手**阶段，把 `stdio` 视为缺陷并不准确。它主要是不适合服务化，而不是不适合当前形态。

---

## 4. 为什么云端/团队/多租户场景有必要升级

一旦目标变为以下任一场景：

- 云端托管 MCP gateway
- 多个 agent 共享同一 MCP 服务
- 团队共用统一入口
- 多租户隔离
- 中央化限流、审计、监控和运维

当前模式就会暴露两个问题。

### 4.1 `stdio` 的问题

`stdio` 更适合本地宿主进程拉起，不适合：

- 长连接网关服务
- 团队共享接入
- 统一入口鉴权
- 负载均衡
- 服务级观测与熔断

在这些场景下，streamable HTTP/SSE 或等价的 hosted transport 更合适。

### 4.2 共享 service account 的问题

如果未来出现“一个云端 MCP 服务 + 一个后端共享 Token”的模式，会产生严重审计塌缩：

- Django 只能看到同一个账号
- 无法区分是哪个真人触发的请求
- 审批、执行、风控动作的责任边界会变模糊
- 多人共享环境下，RBAC 实际上会退化成“网关代行权限”

这比 `stdio` 本身更危险。

---

## 5. 判断原则

### 5.1 何时不用急着升级

满足以下条件时，可继续维持当前模式：

- MCP 主要用于本地桌面 agent
- 使用者规模小，且为一人一环境
- 不需要团队共享网关
- 不需要标准第三方授权
- 当前审计只要求能落到具体用户 Token

### 5.2 何时必须进入升级路线

出现以下需求时，应进入升级路线：

- 云端托管 agent
- 多人共用 MCP gateway
- 需要把真人身份稳定打到 Django 审计
- 需要临时授权、撤权、scope 控制
- 需要多租户隔离
- 需要统一入口的限流、日志、WAF、LB、SRE 管控

---

## 6. 推荐架构判断

### 6.1 短期推荐

继续保留：

- 本地 `stdio` MCP
- 当前用户级 Token 模型

并补强以下内容：

- Token 使用日志与 `last_used_at`
- MCP tool 调用审计中的 `user_id`
- 请求链路中的 `request_id` / `session_id`
- tool 名称、目标资源、执行结果摘要

### 6.2 中期推荐

新增一套 hosted MCP gateway，但不要立即废弃本地 `stdio`：

- 本地开发：继续 `stdio`
- 云端共享：新增 HTTP/SSE gateway

这样可以同时覆盖两类场景，而不是强行单轨切换。

### 6.3 长期推荐

如果系统进入团队化、平台化阶段，应演进为：

- gateway 层使用 streamable HTTP/SSE
- 用户通过 OAuth/OIDC 登录
- gateway 持有**用户态**而非共享 service account 的访问能力
- Django 审计落到真实 `user_id`
- 租户、客户端、scope、会话链路都成为一等字段

---

## 7. 升级顺序建议

### Phase 0: 维持现状，但补强审计

目标：

- 不改 transport
- 不引入 OAuth
- 先把当前 Token 模型的审计信息打完整

建议至少补齐：

- `token_id`
- `user_id`
- `client_name` 或 token name
- `request_id`
- `session_id`
- `tool_name`
- `resource_uri`
- `actor_type`（human / agent / automation）

### Phase 1: Hosted MCP gateway 原型

目标：

- 新增 HTTP/SSE MCP 入口
- 保留本地 `stdio`
- 仍可先复用当前用户级 Token

约束：

- 禁止使用单个共享 service account 作为所有请求后端身份

### Phase 2: Per-user OAuth / OIDC

目标：

- 用户在 gateway 上完成登录授权
- gateway 获取用户态短期凭证
- 后端持续识别真实用户

此阶段应解决：

- token 轮换
- refresh
- scope
- 撤权
- 第三方客户端接入

### Phase 3: 多租户与平台治理

目标：

- 租户隔离
- 客户端隔离
- 按租户和用户做限流、审计、策略控制
- 将 MCP 纳入统一平台入口治理

---

## 8. 明确不建议的方案

以下方案不建议采用：

### 8.1 先上共享 HTTP MCP，再用单后端账号

这是最容易“看起来服务化了，实际审计更差”的路线。

问题：

- Django 看不到真实用户
- 审计、责任、RBAC 都会虚化
- 之后再补身份，会牵涉大量回补改造

### 8.2 一步到位替换掉本地 `stdio`

当前本地桌面 agent 场景下，`stdio` 仍然是低成本、低故障面的合理方案。

更稳妥的策略是双轨并存：

- 本地开发/个人使用：`stdio`
- 云端共享/平台化：HTTP/SSE

---

## 9. 最终判断

本次判断结论如下：

- `stdio -> streamable HTTP/SSE` 不是“立即必须修”的问题，而是“服务化后必须具备”的能力。
- `service account -> per-user OAuth` 对团队共享和云端托管场景是更关键的升级项。
- 如果只做一项，优先做**身份模型升级**，不要只做 transport 升级。
- 当前系统并非纯 service account 模式；它已经具备用户级 Token 基础，因此可以采用“先补审计，再做 hosted gateway，再做 OAuth”的渐进路线。

---

## 10. 相关参考

- `sdk/agomtradepro_mcp/server.py`
- `sdk/agomtradepro_mcp/rbac.py`
- `sdk/agomtradepro/client.py`
- `apps/account/interface/authentication.py`
- `apps/account/infrastructure/models.py`
- `apps/account/application/interface_services.py`
- `docs/mcp/mcp_guide.md`

