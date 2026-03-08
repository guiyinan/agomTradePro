# AgomSAAF MCP Server 部署指南

本文档说明如何部署和配置 AgomSAAF MCP (Model Context Protocol) Server，以便与 Claude Desktop 或其他 MCP 客户端集成。

## 目录

1. [环境要求](#环境要求)
2. [本地调试](#本地调试)
3. [Claude Desktop 配置](#claude-desktop-配置)
4. [Claude Code 配置](#claude-code-配置)
5. [RBAC 权限配置](#rbac-权限配置)
6. [常见故障排查](#常见故障排查)

---

## 环境要求

- Python 3.11+
- AgomSAAF API 服务运行中
- API Token（从 AgomSAAF 管理后台获取）

### 依赖安装

```bash
cd sdk
pip install -e .
```

或手动安装依赖：

```bash
pip install mcp
```

---

## 本地调试

### 1. 设置环境变量

#### Linux/macOS (bash)

```bash
export AGOMSAAF_API_BASE_URL="http://127.0.0.1:8000"
export AGOMSAAF_API_TOKEN="your-api-token"
export AGOMSAAF_MCP_ROLE="admin"  # 可选: viewer, analyst, admin
export AGOMSAAF_DEFAULT_PORTFOLIO_ID="1"  # 可选
```

#### Windows PowerShell

```powershell
$env:AGOMSAAF_API_BASE_URL="http://127.0.0.1:8000"
$env:AGOMSAAF_API_TOKEN="your-api-token"
$env:AGOMSAAF_MCP_ROLE="admin"
```

### 2. 启动 MCP Server

```bash
# 方式一：使用模块入口
cd sdk
python -m agomsaaf_mcp

# 方式二：直接运行
python sdk/agomsaaf_mcp/__main__.py
```

### 3. 测试工具列表

使用 MCP Inspector 测试：

```bash
npx @modelcontextprotocol/inspector python -m agomsaaf_mcp
```

然后在浏览器打开 `http://localhost:5173` 查看可用工具和资源。

---

## Claude Desktop 配置

### 1. 找到配置文件位置

- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
- **Linux**: `~/.config/Claude/claude_desktop_config.json`

### 2. 复制模板

将 `sdk/.mcp/claude-desktop-config.json` 的内容复制到上述配置文件中。

### 3. 修改配置

```json
{
  "mcpServers": {
    "agomsaaf": {
      "command": "python",
      "args": ["-m", "agomsaaf_mcp"],
      "cwd": "/absolute/path/to/agomSAAF/sdk",
      "env": {
        "AGOMSAAF_API_BASE_URL": "http://127.0.0.1:8000",
        "AGOMSAAF_API_TOKEN": "your-actual-token",
        "AGOMSAAF_MCP_ROLE": "viewer",
        "PYTHONPATH": "/absolute/path/to/agomSAAF/sdk"
      }
    }
  }
}
```

### 4. 重启 Claude Desktop

保存配置后，完全退出并重新启动 Claude Desktop。

### 5. 验证连接

在 Claude Desktop 中，你应该能看到 AgomSAAF 的工具图标。尝试提问：

```
请获取当前宏观环境状态
```

---

## Claude Code 配置

### 方法一：使用 MCP 配置

在项目根目录创建 `.claude/mcp.json`：

```json
{
  "servers": {
    "agomsaaf": {
      "command": "python",
      "args": ["-m", "agomsaaf_mcp"],
      "cwd": "${workspaceFolder}/sdk",
      "env": {
        "AGOMSAAF_API_BASE_URL": "http://127.0.0.1:8000",
        "AGOMSAAF_API_TOKEN": "${AGOMSAAF_API_TOKEN}",
        "AGOMSAAF_MCP_ROLE": "analyst"
      }
    }
  }
}
```

### 方法二：直接调用 SDK

在 Claude Code 会话中：

```python
# 直接使用 Python SDK
from agomsaaf import AgomSAAFClient

client = AgomSAAFClient(
    base_url="http://127.0.0.1:8000",
    api_token="your-token"
)

# 获取当前 Regime
regime = client.regime.get_current()
print(f"当前宏观象限: {regime.dominant_regime}")
```

---

## RBAC 权限配置

MCP Server 支持基于角色的访问控制 (RBAC)。通过 `AGOMSAAF_MCP_ROLE` 环境变量设置。

### 可用角色

| 角色 | 权限范围 |
|------|---------|
| `viewer` | 只读访问：查询 Regime、Policy、资产信息 |
| `analyst` | 分析操作：运行回测、生成报告 |
| `admin` | 完全访问：创建/修改信号、管理账户 |

### 权限矩阵

| 工具/资源 | viewer | analyst | admin |
|----------|--------|---------|-------|
| `get_current_regime` | ✅ | ✅ | ✅ |
| `get_policy_status` | ✅ | ✅ | ✅ |
| `run_backtest` | ❌ | ✅ | ✅ |
| `create_signal` | ❌ | ❌ | ✅ |
| `execute_trade` | ❌ | ❌ | ✅ |

### 自定义 RBAC 配置

编辑 `sdk/agomsaaf_mcp/rbac.py` 来自定义权限规则：

```python
# 示例：添加自定义角色
ROLE_PERMISSIONS = {
    "viewer": {...},
    "analyst": {...},
    "admin": {...},
    "trader": {  # 新角色
        "tools": ["execute_trade", "get_positions"],
        "resources": ["account/positions"],
    }
}
```

---

## 常见故障排查

### 问题 1：连接被拒绝

**症状**：
```
Connection refused: [Errno 111] Connection refused
```

**解决方案**：
1. 确认 AgomSAAF API 服务正在运行
2. 检查 `AGOMSAAF_API_BASE_URL` 是否正确
3. 验证端口是否被占用

```bash
# 检查服务状态
curl http://127.0.0.1:8000/api/health/
```

```bash
# Linux/macOS: 检查端口占用
lsof -i :8000
```

```powershell
# Windows: 检查端口占用
netstat -ano | findstr :8000
```

### 问题 2：认证失败

**症状**：
```
401 Unauthorized
```

**解决方案**：
1. 确认 API Token 有效
2. 检查 Token 是否有正确的权限
3. 重新生成 Token

```bash
# 从 Django 管理后台生成 Token
python manage.py drf_create_token <username>
```

### 问题 3：模块找不到

**症状**：
```
ModuleNotFoundError: No module named 'agomsaaf_mcp'
```

**解决方案**：
1. 确认 `cwd` 路径正确
2. 设置 `PYTHONPATH`
3. 使用绝对路径

```json
{
  "env": {
    "PYTHONPATH": "/absolute/path/to/agomSAAF/sdk"
  }
}
```

### 问题 4：权限不足

**症状**：
```
Permission denied for tool: run_backtest
```

**解决方案**：
1. 检查 `AGOMSAAF_MCP_ROLE` 设置
2. 确认角色有对应工具的权限
3. 联系管理员升级权限

### 问题 5：超时错误

**症状**：
```
Timeout waiting for MCP server response
```

**解决方案**：
1. 检查网络连接
2. 增加客户端超时设置
3. 检查 API 服务是否响应缓慢

```bash
# 测试 API 响应时间
curl -w "@curl-format.txt" -o /dev/null -s http://127.0.0.1:8000/api/regime/current/
```

### 问题 6：Windows 路径问题

**症状**：
```
The system cannot find the path specified
```

**解决方案**：
1. 使用正斜杠 `/` 或双反斜杠 `\\`
2. 确保路径不包含空格
3. 使用绝对路径

```json
{
  "cwd": "C:/Users/YourName/projects/agomSAAF/sdk"
}
```

---

## 日志调试

启用详细日志：

#### Linux/macOS (bash)

```bash
export AGOMSAAF_MCP_LOG_LEVEL=DEBUG
python -m agomsaaf_mcp
```

#### Windows PowerShell

```powershell
$env:AGOMSAAF_MCP_LOG_LEVEL="DEBUG"
python -m agomsaaf_mcp
```

日志输出位置：
- 标准错误流 (stderr)
- 或设置 `AGOMSAAF_MCP_LOG_FILE` 指定日志文件

---

## 附录

### 环境变量完整列表

| 变量名 | 必需 | 默认值 | 说明 |
|--------|------|--------|------|
| `AGOMSAAF_API_BASE_URL` | 是 | `http://127.0.0.1:8000` | API 服务地址 |
| `AGOMSAAF_API_TOKEN` | 是 | - | 认证 Token |
| `AGOMSAAF_MCP_ROLE` | 否 | `viewer` | RBAC 角色 |
| `AGOMSAAF_DEFAULT_PORTFOLIO_ID` | 否 | - | 默认组合 ID |
| `AGOMSAAF_RHIZOME_PATH` | 否 | - | 知识库路径 |
| `AGOMSAAF_MCP_LOG_LEVEL` | 否 | `INFO` | 日志级别 |
| `AGOMSAAF_MCP_LOG_FILE` | 否 | - | 日志文件路径 |

### 可用工具列表

- `get_current_regime` - 获取当前宏观象限
- `get_policy_status` - 获取政策档位状态
- `run_backtest` - 运行回测
- `check_signal_eligibility` - 检查信号准入
- `get_portfolio_summary` - 获取组合摘要
- ... 更多工具请参考 `sdk/agomsaaf_mcp/tools/`

### 可用资源列表

- `agomsaaf://regime/current` - 当前宏观状态
- `agomsaaf://policy/status` - 政策状态
- `agomsaaf://account/summary` - 账户摘要
- `agomsaaf://account/positions` - 持仓快照
- `agomsaaf://account/recent-transactions` - 最近交易
