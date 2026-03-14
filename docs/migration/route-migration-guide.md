# API 路由迁移指南

> **版本**: V3.5
> **发布日期**: 2026-03-04
> **状态**: 正式发布
> **适用范围**: 所有 API 客户端（Python SDK、JavaScript SDK、第三方集成）

---

## 概述

从 V3.5 版本开始，AgomSAAF 采用统一的 API 路由规范：`/api/{module}/{resource}/`

本次迁移旨在：
1. 统一 API 路由结构，提升 RESTful 规范性
2. 简化路由层级，便于理解和维护
3. 保持向后兼容，平滑过渡

### 迁移原则

- **双轨运行**: 新旧路由同时提供服务
- **渐进式迁移**: 分阶段引导客户端迁移
- **充分通知**: 提前公告，明确时间表
- **向后兼容**: 保留旧路由直到迁移完成

---

## 路由对照表

### 核心模块

| 模块 | 旧路由格式 | 新路由格式 | 状态 |
|------|-----------|-----------|------|
| **account** | `/account/api/portfolios/` | `/api/account/portfolios/` | 兼容别名 |
| **account** | `/account/api/positions/` | `/api/account/positions/` | 兼容别名 |
| **regime** | `/api/regime/api/` | `/api/regime/` | 已废弃 |
| **regime** | `/api/regime/api/current/` | `/api/regime/current/` | 已废弃 |
| **signal** | `/api/signal/api/` | `/api/signal/` | 双轨 |
| **signal** | `/api/signal/api/health/` | `/api/signal/health/` | 双轨 |
| **macro** | `/macro/api/supported-indicators/` | `/api/macro/supported-indicators/` | 兼容别名 |
| **macro** | `/macro/api/indicator-data/` | `/api/macro/indicator-data/` | 兼容别名 |
| **policy** | `/policy/api/events/` | `/api/policy/events/` | 双轨 |
| **realtime** | `/api/realtime/api/prices/` | `/api/realtime/prices/` | 双轨 |

### Alpha 与智能模块

| 模块 | 旧路由格式 | 新路由格式 | 状态 |
|------|-----------|-----------|------|
| **alpha** | `/api/alpha/scores/` | `/api/alpha/scores/` | 无需迁移 |
| **alpha** | `/api/alpha/coverage/` | `/api/alpha/coverage/` | 无需迁移 |
| **factor** | `/factor/api/` | `/api/factor/` | 双轨 |
| **rotation** | `/rotation/api/` | `/api/rotation/` | 双轨 |
| **hedge** | `/hedge/api/` | `/api/hedge/` | 双轨 |

### 决策与策略模块

| 模块 | 旧路由格式 | 新路由格式 | 状态 |
|------|-----------|-----------|------|
| **strategy** | `/strategy/api/` | `/api/strategy/` | 兼容别名 |
| **simulated_trading** | `/simulated-trading/api/` | `/api/simulated-trading/` | 兼容别名 |
| **decision_rhythm** | `/api/decision-rhythm/api/` | `/api/decision-rhythm/` | 双轨 |
| **decision_workflow** | `/api/decision-workflow/api/` | `/api/decision-workflow/` | 双轨 |

### 分析模块

| 模块 | 旧路由格式 | 新路由格式 | 状态 |
|------|-----------|-----------|------|
| **equity** | `/equity/api/` | `/api/equity/` | 双轨 |
| **fund** | `/fund/api/` | `/api/fund/` | 双轨 |
| **sector** | `/sector/api/` | `/api/sector/` | 双轨 |
| **sentiment** | `/api/sentiment/api/analyze/` | `/api/sentiment/analyze/` | 双轨 |

### 工具模块

| 模块 | 旧路由格式 | 新路由格式 | 状态 |
|------|-----------|-----------|------|
| **backtest** | `/backtest/api/` | `/api/backtest/` | 兼容别名 |
| **audit** | `/audit/api/` | `/api/audit/` | 双轨，canonical 为 `/api/audit/` |
| **filter** | `/filter/api/` | `/api/filter/` | 兼容别名 |
| **dashboard** | `/dashboard/api/v1/` | `/api/dashboard/v1/` | 双轨 |

---

## 迁移时间表

| 阶段 | 日期 | 状态 | 说明 |
|------|------|------|------|
| **Phase 1** | 2026-03-04 | 已完成 | 发布新路由，旧路由添加 Deprecation Header |
| **Phase 2** | 2026-03-04 ~ 2026-04-01 | 进行中 | 客户端迁移，旧路由正常服务 |
| **Phase 3** | 2026-04-01 ~ 2026-05-01 | 计划中 | 旧路由进入只读模式（仅支持 GET） |
| **Phase 4** | 2026-06-01 | 计划中 | 移除旧路由支持 |

### Phase 1: 新路由发布 (2026-03-04)

- 发布统一规范的新路由
- 旧路由添加 Deprecation HTTP Header
- SDK 同步更新（向后兼容）
- 文档更新完成

### Phase 2: 客户端迁移期 (2026-03-04 ~ 2026-04-01)

- 所有客户端更新到新路由
- 旧路由继续正常服务
- 每周监控迁移进度

### Phase 3: 只读模式 (2026-04-01 ~ 2026-05-01)

- 旧路由限制为只读（仅 GET 请求）
- POST/PUT/PATCH/DELETE 请求将返回 410 Gone
- 强制剩余客户端迁移

### Phase 4: 移除旧路由 (2026-06-01)

- 完全移除旧路由支持
- 返回 404 Not Found

---

## Deprecation Header 说明

使用旧路由的请求将收到以下响应头：

```
X-Deprecated: true
X-Deprecation-Message: This endpoint is deprecated. Use /api/{module}/{resource}/ instead.
X-Sunset: 2026-06-01
Link: </api/{module}/{resource}/>; rel="alternate"
```

### 示例

```bash
# 使用旧路由请求
curl -H "Authorization: Token xxx" \
     http://api.example.com/api/regime/current/

# 响应头
HTTP/1.1 200 OK
Content-Type: application/json
X-Deprecated: true
X-Deprecation-Message: This endpoint is deprecated. Use /api/regime/current/ instead.
X-Sunset: 2026-06-01
Link: </api/regime/current/>; rel="alternate"
```

---

## SDK 升级说明

### Python SDK

#### 安装新版本

```bash
pip install --upgrade agomsaaf-sdk
```

#### 代码变更

**无需修改代码！** 新版 SDK 保持向后兼容：

```python
# 旧版本（仍然有效）
from agomsaaf import AgomSAAFClient

client = AgomSAAFClient(
    base_url="http://api.example.com",
    api_token="your_token"
)

# 所有 API 调用自动使用新路由
regime = client.regime.get_current()
signals = client.signal.list()
```

SDK 内部已更新为使用新路由，同时保留对旧路由的降级支持。

#### 配置文件

如果使用配置文件 (`.agomsaaf.json`)，无需修改：

```json
{
  "base_url": "http://api.example.com",
  "api_token": "your_token"
}
```

#### 环境变量

如果使用环境变量，无需修改：

```bash
export AGOMSAAF_BASE_URL="http://api.example.com"
export AGOMSAAF_API_TOKEN="your_token"
```

### JavaScript SDK

#### 安装新版本

```bash
npm install @agomsaaf/sdk@latest
# 或
yarn upgrade @agomsaaf/sdk
```

#### 代码变更

**无需修改代码！** 新版 SDK 保持向后兼容：

```javascript
// 旧版本（仍然有效）
import { AgomSAAF } from '@agomsaaf/sdk';

const client = new AgomSAAF({
  baseUrl: 'http://api.example.com',
  apiToken: 'your_token'
});

// 所有 API 调用自动使用新路由
const regime = await client.regime.getCurrent();
const signals = await client.signal.list();
```

### MCP Server

MCP Server 无需升级，自动使用新路由。

如果使用环境变量配置，无需修改：

```bash
export AGOMSAAF_BASE_URL="http://api.example.com"
export AGOMSAAF_API_TOKEN="your_token"
agomsaaf-mcp
```

---

## 直接 HTTP 调用迁移指南

如果您的代码直接调用 API（不使用 SDK），请按以下方式迁移：

### Python (requests)

```python
import requests

# 旧路由（已废弃）
response = requests.get(
    "http://api.example.com/api/regime/current/",
    headers={"Authorization": "Token xxx"}
)

# 新路由（推荐）
response = requests.get(
    "http://api.example.com/api/regime/current/",
    headers={"Authorization": "Token xxx"}
)
```

### JavaScript (fetch)

```javascript
// 旧路由（已废弃）
fetch('http://api.example.com/api/regime/current/', {
  headers: { 'Authorization': 'Token xxx' }
})
.then(r => r.json())
.then(data => console.log(data));

// 新路由（推荐）
fetch('http://api.example.com/api/regime/current/', {
  headers: { 'Authorization': 'Token xxx' }
})
.then(r => r.json())
.then(data => console.log(data));
```

### cURL

```bash
# 旧路由（已废弃）
curl -H "Authorization: Token xxx" \
     http://api.example.com/api/regime/current/

# 新路由（推荐）
curl -H "Authorization: Token xxx" \
     http://api.example.com/api/regime/current/
```

---

## 路由模式说明

### 新路由格式（推荐）

```
/api/{module}/{resource}/
```

- 统一的 `/api/` 前缀
- 简洁的模块路径
- RESTful 资源命名

### 旧路由格式（已废弃）

1. **双层 API 路径**: `/api/{module}/api/{resource}/`
   - 示例: `/regime/api/` 或 `/api/regime/api/` → `/api/regime/`

2. **模块级 API 路径**: `/{module}/api/{resource}/`
   - 示例: `/rotation/api/` → `/api/rotation/`

---

## 迁移检查清单

### 开发人员

- [ ] 更新 SDK 到最新版本
- [ ] 检查直接 HTTP 调用，更新为新路由
- [ ] 运行测试套件验证功能正常
- [ ] 监控日志中的 Deprecation 警告

### 集成方

- [ ] 查阅本迁移指南
- [ ] 更新 API 调用代码
- [ ] 在测试环境验证
- [ ] 部署到生产环境

### 运维人员

- [ ] 更新 API 文档
- [ ] 配置监控告警（监控旧路由调用）
- [ ] 跟踪迁移进度
- [ ] 关注 Phase 3 只读模式通知

---

## FAQ

### Q: 旧路由什么时候会停止服务？

**A**: 2026-06-01 将完全移除旧路由支持。在此之前，旧路由会持续提供服务，但会收到 Deprecation Header。

### Q: 我必须立即迁移吗？

**A**: 不必立即迁移。建议在 2026-04-01 前完成迁移，以避免只读模式限制。

### Q: SDK 会自动使用新路由吗？

**A**: 是的，SDK v1.2.0+ 自动使用新路由，无需修改代码。

### Q: 如何检测我的代码是否使用了旧路由？

**A**: 监控 HTTP 响应头中的 `X-Deprecated` 字段，或检查 SDK 日志。

### Q: 迁移后 API 行为会变化吗？

**A**: 不会。路由迁移仅改变 URL 路径，API 请求和响应格式完全相同。

### Q: 如果迁移后出现问题怎么办？

**A**: 可以临时回退到旧路由（在 2026-06-01 前）。同时提交问题报告。

### Q: 新路由支持版本控制吗？

**A**: 当前使用隐式 v1。未来计划支持 `/api/v1/{module}/` 格式以支持多版本并存。

---

## 技术细节

### 路由实现

新路由通过 Django URL 配置实现：

```python
# core/urls.py

# 新路由（推荐）
path('api/regime/', include('apps.regime.interface.api_urls')),
path('api/signal/', include('apps.signal.interface.api_urls')),

# 旧路由（兼容，已标记 deprecated）
path('regime/api/', include('apps.regime.interface.legacy_urls')),
path('signal/api/', include('apps.signal.interface.legacy_urls')),
```

### Deprecation Middleware

```python
# core/middleware.py

class DeprecationMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # 检测旧路由
        if self.is_legacy_route(request.path):
            response['X-Deprecated'] = 'true'
            response['X-Deprecation-Message'] = (
                f'This endpoint is deprecated. '
                f'Use {self.get_new_route(request.path)} instead.'
            )
            response['X-Sunset'] = '2026-06-01'

        return response
```

---

## 相关文档

- [API 路由命名规范](../architecture/routing_naming_convention.md)
- [API 路由一致性分析](../development/api-route-consistency.md)
- [SDK 文档](../../sdk/README.md)
- [API 参考文档](../testing/api/API_REFERENCE.md)

---

## 更新日志

| 日期 | 版本 | 变更说明 |
|------|------|---------|
| 2026-03-04 | V3.5 | 初始版本，发布路由迁移指南 |
| 2026-02-20 | V3.4 | 完成路由一致性整改 |
| 2026-02-18 | V3.3 | 制定路由命名规范 |

---

**文档维护**: AgomSAAF Team
**最后更新**: 2026-03-04
**联系方式**: support@agomsaaf.com
