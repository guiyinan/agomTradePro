# 自动化调试日志 API（Codex / Claude Code）

## 目标

为自动化调试工具提供一个**最小可用**的服务端日志读取接口：

- 支持轮询实时日志
- 支持一次性导出日志文本
- 使用 Bearer Token 鉴权
- 默认关闭（避免误暴露）

## 接口

- `GET /api/debug/server-logs/stream/?since=<id>&limit=<n>`
  - 返回 JSON，包含 `entries`、`last_id`、`count`
  - `since`：从该游标之后增量读取（默认 `0`）
  - `limit`：单次条数（默认 `200`，受 `AUTOMATION_DEBUG_API_MAX_LIMIT` 限制）
- `GET /api/debug/server-logs/export/`
  - 返回纯文本日志快照（`text/plain`）

## 鉴权方式

请求头二选一：

- `Authorization: Bearer <token>`（推荐）
- `X-Debug-Token: <token>`

token 由环境变量 `AUTOMATION_DEBUG_API_TOKENS` 配置（支持多个，逗号分隔）。

## 环境变量

在 `.env` 增加：

```env
AUTOMATION_DEBUG_API_ENABLED=True
AUTOMATION_DEBUG_API_TOKENS=replace-with-long-random-token-1,replace-with-long-random-token-2
# 可选：限制来源 IP（反向代理场景下会读取 X-Forwarded-For 首 IP）
AUTOMATION_DEBUG_API_IP_ALLOWLIST=127.0.0.1,::1
# 可选：限制单次拉取上限
AUTOMATION_DEBUG_API_MAX_LIMIT=1000
```

修改后重启 Django 服务。

## 调用示例

### 1) 增量轮询

```bash
curl -H "Authorization: Bearer $DEBUG_API_TOKEN" \
  "http://127.0.0.1:8000/api/debug/server-logs/stream/?since=0&limit=200"
```

### 2) 导出日志

```bash
curl -H "Authorization: Bearer $DEBUG_API_TOKEN" \
  "http://127.0.0.1:8000/api/debug/server-logs/export/" \
  -o server_logs.txt
```

### 3) 一键 E2E 回归（PowerShell）

```powershell
pwsh -File scripts/e2e_debug_log_api.ps1
```

- 默认端口 `8000`
- 默认 token：`agom_local_debug_token_20260217_e2e`（与示例 `.env` 一致）
- 脚本会自动复用已运行的本地服务；若无服务则自动拉起

## 返回示例

```json
{
  "entries": [
    {
      "id": 101,
      "ts": "2026-02-17 20:31:12",
      "level": "INFO",
      "logger": "django.request",
      "message": "INFO 2026-02-17 20:31:12 log 200 GET /health/"
    }
  ],
  "last_id": 101,
  "count": 1
}
```

## 安全建议

- 仅在需要自动化调试时开启 `AUTOMATION_DEBUG_API_ENABLED=True`
- token 使用高熵随机串，定期轮换
- 生产环境建议同时配置 `AUTOMATION_DEBUG_API_IP_ALLOWLIST`
- 如不再使用，立即关闭开关并重启服务

## 说明与限制

- 此 API 基于进程内日志缓冲区，不是持久化日志存储
- 进程重启后缓存会清空
- 多进程部署下，每个 worker 的缓存相互独立
