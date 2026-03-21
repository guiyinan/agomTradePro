# AgomTradePro SDK & MCP 集成测试计划

> **版本**: 2.0
> **更新日期**: 2026-02-05
> **状态**: 已修订（根据架构评审反馈）

---

## 1. 测试目标

### 1.1 功能性目标
测试 AgomTradePro 系统 SDK 和 MCP (Model Context Protocol) 集成，验证：
- 系统服务器能正常启动（Django + PostgreSQL + Redis + Celery）
- SDK 能正确连接并调用 API
- MCP 服务器能正常工作并提供工具
- 发现潜在 bug 和用户体验问题

### 1.2 非功能性目标
- **性能**: API 响应时间 < 500ms (P95)
- **可靠性**: 错误重试机制正常工作
- **安全性**: 认证/授权机制有效
- **可观测性**: 日志和监控数据完整

### 1.3 测试覆盖目标
| 类型 | 目标覆盖率 | 测试类型 |
|------|-----------|----------|
| SDK 核心模块 | >80% | 单元测试 |
| API 端点 | 100% | 集成测试 |
| MCP 工具 | 100% | 端到端测试 |
| 关键业务流程 | 100% | 场景测试 |

---

## 2. 系统架构概览

---

## 2. 系统架构概览

### 2.1 架构图

```
┌─────────────────────────────────────────────────────────────┐
│                    AI Agent (Claude Code)                    │
└────────────────────────┬────────────────────────────────────┘
                         │ MCP Protocol (stdio)
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                   MCP Server (stdio_server)                  │
│  Location: sdk/agomtradepro_mcp/server.py                       │
└────────────────────────┬────────────────────────────────────┘
                         │ 调用 SDK
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                  Python SDK (AgomTradeProClient)                 │
│  Location: sdk/agomtradepro/client.py                           │
│  - Retry Strategy                                          │
│  - Error Propagation                                       │
│  - Authentication (Bearer Token)                           │
└────────────────────────┬────────────────────────────────────┘
                         │ HTTP REST API
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              AgomTradePro Django Application                     │
│              http://localhost:8000/api/                      │
│  - DRF ViewSets                                            │
│  - Authentication Middleware                               │
│  - Request Validation                                      │
└────────────────────────┬────────────────────────────────────┘
                         │
         ┌───────────────┼───────────────┐
         ▼               ▼               ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│ PostgreSQL   │  │    Redis     │  │   Celery     │
│  :5433       │  │    :6379     │  │ Worker/Beat  │
│              │  │              │  │              │
│ - 主数据存储  │  │ - Celery     │  │ - 异步任务   │
│ - 事务支持    │  │   Broker     │  │ - 定时任务   │
│ - 连接池      │  │ - 会话缓存   │  │              │
└──────────────┘  └──────────────┘  └──────────────┘
```

### 2.2 数据流

```
AI Agent → MCP Server → SDK Client → HTTP Request → Django API → Business Logic → Database
                    ↓                              ↓
               Error Handling              Authentication
                   ↑                              ↑
              Exception ←────────────────── HTTP Error Response
```

### 2.3 错误处理机制

| 层级 | 错误类型 | 处理方式 | 传播方向 |
|------|----------|----------|----------|
| MCP Server | SDK 异常 | 捕获并转换为 MCP 错误响应 | → AI Agent |
| SDK Client | HTTP 错误 | 重试 → 抛出 AgomTradeProAPIError | → MCP Server |
| SDK Client | 网络超时 | 重试（最多3次）→ TimeoutError | → MCP Server |
| Django API | 业务异常 | HTTP 400/404/500 + 错误详情 | → SDK Client |
| Django API | 认证失败 | HTTP 401/403 | → SDK Client |

### 2.4 认证流程

```
1. 环境变量配置
   AGOMTRADEPRO_BASE_URL=http://localhost:8000
   AGOMTRADEPRO_API_TOKEN=<token>

2. SDK Client 初始化
   client = AgomTradeProClient()
   ↓ 读取环境变量
   ↓ 构建请求头: Authorization: Bearer <token>

3. Django API 认证中间件
   验证 Token → 提取用户信息 → 注入 request.user

4. MCP Server 传递
   MCP Server 无状态，每次请求由 SDK 独立认证
```

### 2.5 Redis 角色说明

| 用途 | Redis Key 示例 | TTL | 说明 |
|------|----------------|-----|------|
| Celery Broker | `celery` | - | 任务队列 |
| 会话缓存 | `session:<user_id>` | ��动期+1小时 | Django sessions |
| API 缓存 | `api_cache:<hash>` | 5分钟 | 响应缓存 |

### 2.6 监控与日志

```
日志层级:
├── ERROR: 认证失败、数据库错误、外部服务不可用
├── WARNING: API 调用失败（自动重试）、数据异常
├── INFO: API 请求记录、任务执行记录
└── DEBUG: 详细执行流程（开发环境）

监控指标:
├── API 响应时间 (P50, P95, P99)
├── API 错误率
├── Celery 任务积压数量
├── 数据库连接池使用率
└── Redis 内存使用率
```

### 2.7 扩展性考虑

| 组件 | 扩展方式 | 说明 |
|------|----------|------|
| Django | Gunicorn + 多 worker | 水平扩展 |
| PostgreSQL | 主从复制 | 读写分离 |
| Redis | Cluster / Sentinel | 高可用 |
| Celery | 多 Worker 分布 | 任务分片 |

---

## 4. 测试环境准备

### 4.1 虚拟环境检查

```powershell
# 检查虚拟环境是否存在
Test-Path agomtradepro\Scripts\python.exe

# 如果不存在，创建虚拟环境
python -m venv agomtradepro

# 激活虚拟环境
agomtradepro\Scripts\Activate.ps1
```

### 4.2 安装依赖

```powershell
# 安装项目依赖
pip install -r requirements.txt

# 安装 SDK（开发模式）
cd sdk
pip install -e .
cd ..
```

### 4.3 环境变量配置

> ⚠️ **安全警告**
>
> 以下配置仅用于**开发环境**。生产环境必须：
> 1. 使用强随机 SECRET_KEY（至少 50 字符）
> 2. 更换默认数据库密码
> 3. 使用环境变量或密钥管理服务（如 AWS Secrets Manager）
> 4. 不要将 `.env` 文件提交到版本控制

复制 `.env.example` 到 `.env` 并配置：

```bash
# 必需配置 - **生产环境必须更换这些值**
SECRET_KEY=your-secret-key-here  # ⚠️ 必须更换为强随机字符串
DATABASE_URL=postgresql://agomtradepro:changeme@localhost:5433/agomtradepro  # ⚠️ 更换密码
REDIS_URL=redis://localhost:6379/0

# API 密钥（用于数据获取）
TUSHARE_TOKEN=your_token_here
```

**生成强 SECRET_KEY 的方法：**
```python
import secrets
print(secrets.token_urlsafe(50))
```

### 4.4 创建超级用户（用于管理后台）

```powershell
python manage.py createsuperuser
```

---

## 5. 服务启动测试

### 5.1 方式一：使用启动脚本（推荐）

```powershell
# SQLite 模式（最简单，无需 Docker）
.\scripts\start-dev.ps1 -Mode sqlite

# Docker 模式（完整功能）
.\scripts\start-dev.ps1 -Mode docker
```

### 4.2 方式二：手动启动

**步骤 1：启动 Docker 服务（PostgreSQL + Redis）**
```powershell
docker-compose -f docker-compose-dev.yml up -d

# 验证服务状态
docker ps

# 验证 PostgreSQL
docker exec agomtradepro_postgres_dev pg_isready -U agomtradepro -d agomtradepro

# 验证 Redis
docker exec agomtradepro_redis_dev redis-cli ping
```

**步骤 2：运行数据库迁移**
```powershell
agomtradepro\Scripts\Activate.ps1
python manage.py migrate
```

**步骤 3：启动 Celery Worker（新终端）**
```powershell
agomtradepro\Scripts\Activate.ps1
python -m celery -A core worker -l info --pool=solo
```

**步骤 4：启动 Celery Beat（新终端）**
```powershell
agomtradepro\Scripts\Activate.ps1
python -m celery -A core beat -l info
```

**步骤 5：启动 Django 服务器**
```powershell
agomtradepro\Scripts\Activate.ps1
python manage.py runserver 8000
```

### 4.3 服务验证清单

| 服务 | URL/命令 | 预期结果 | 状态 |
|------|----------|----------|------|
| Django Web | http://127.0.0.1:8000/ | 显示首页 | ☐ |
| Admin Panel | http://127.0.0.1:8000/admin/ | 可登录 | ☐ |
| API Docs | http://127.0.0.1:8000/api/docs/ | 显示文档 | ☐ |
| PostgreSQL | `docker exec agomtradepro_postgres_dev pg_isready` | 返回 accepting connections | ☐ |
| Redis | `docker exec agomtradepro_redis_dev redis-cli ping` | 返回 PONG | ☐ |
| Celery Worker | 查看终端输出 | 显示 ready | ☐ |
| Celery Beat | 查看终端输出 | 显示 Scheduler | ☐ |

---

## 6. SDK 测试场景

### 6.1 SDK 安装测试

```powershell
cd sdk

# 安装 SDK
pip install -e .

# 验证安装
pip show agomtradepro-sdk

# 测试导入
python -c "from agomtradepro import AgomTradeProClient; print('SDK imported successfully')"
```

### 6.2 SDK 基础连接测试

测试脚本已创建：`test_sdk_connection.py`（项目根目录）

**快速运行：**
```powershell
python test_sdk_connection.py
```

**测试内容：**
1. SDK 导入测试
2. 客户端创建测试
3. 获取当前宏观象限
4. 获取政策状态
5. 列出宏观指标
6. 列出投资信号
7. 检查信号准入
8. 获取历史象限
9. 列出回测
10. 获取投资组合

### 6.3 SDK 模块测试清单

| 模块 | 测试方法 | 预期结果 | 状态 |
|------|----------|----------|------|
| Regime | `client.regime.get_current()` | 返回当前象限 | ☐ |
| Regime | `client.regime.history(limit=10)` | 返回历史记录 | ☐ |
| Signal | `client.signal.list()` | 返回信号列表 | ☐ |
| Signal | `client.signal.check_eligibility()` | 返回准入结果 | ☐ |
| Macro | `client.macro.list_indicators()` | 返回指标列表 | ☐ |
| Policy | `client.policy.get_status()` | 返回政策状态 | ☐ |
| Backtest | `client.backtest.list()` | 返回回测列表 | ☐ |
| Account | `client.account.get_portfolios()` | 返回投资组合 | ☐ |
| SimulatedTrading | `client.simulated_trading.list_accounts()` | 返回模拟账户 | ☐ |

---

## 7. MCP 测试场景

### 7.1 MCP 服务器测试

**独立测试脚本：** `test_mcp_server.py`（项目根目录）

**快速运行：**
```powershell
python test_mcp_server.py
```

**测试内容：**
1. MCP 服务器模块导入
2. 服务器实例创建
3. 可用工具列表
4. 资源列表
5. 资源内容读取
6. Prompt 列表
7. Prompt 内容获取
8. 工具模块导入验证
9. SDK 客户端从 MCP 上下文

---

### 6.1.1 MCP 服务器配置（Claude Code 集成）

**步骤 1：配置 MCP 服务器**

编辑 `~/.config/claude-code/mcp_servers.json`：

```json
{
  "mcpServers": {
    "agomtradepro": {
      "command": "python",
      "args": ["-m", "agomtradepro_mcp.server"],
      "cwd": "D:/githv/agomTradePro/sdk",
      "env": {
        "AGOMTRADEPRO_BASE_URL": "http://localhost:8000"
      }
    }
  }
}
```

**步骤 2：手动测试 MCP 服务器启动**

```powershell
cd sdk

# 测试 MCP 服务器启动
python -m agomtradepro_mcp.server

# 预期输出：服务器启动，等待 stdio 输入
```

---

### 7.2 MCP 工具测试清单

在 Claude Code 中测试以下工具调用：

| 工具类别 | 工具名称 | 测试命令 | 预期结果 | 状态 |
|----------|----------|----------|----------|------|
| Regime | `get_current_regime` | "获取当前宏观象限" | 返回象限信息 | ☐ |
| Regime | `calculate_regime` | "计算2024-01-01的象限" | 返回计算结果 | ☐ |
| Regime | `explain_regime` | "解释Recovery象限" | 返回解释文本 | ☐ |
| Signal | `check_signal_eligibility` | "检查000001.SH的准入" | 返回准入结果 | ☐ |
| Signal | `list_signals` | "列出所有信号" | 返回信号列表 | ☐ |
| Macro | `list_macro_indicators` | "列出宏观指标" | 返回指标列表 | ☐ |
| Policy | `get_policy_status` | "获取政策状态" | 返回政策档位 | ☐ |
| Backtest | `list_backtests` | "列出回测" | 返回回测列表 | ☐ |

### 7.3 MCP 资源测试

测试 MCP Resources（自动读取的资源）：

| 资源 URI | 测试方式 | 预期结果 | 状态 |
|----------|----------|----------|------|
| `agomtradepro://regime/current` | 通过 Claude Code 读取 | 返回当前象限文本 | ☐ |
| `agomtradepro://policy/status` | 通过 Claude Code 读取 | 返回政策状态文本 | ☐ |

### 7.4 MCP Prompts 测试

测试内置 Prompt 模板：

| Prompt 名称 | 测试方式 | 预期结果 | 状态 |
|-------------|----------|----------|------|
| `analyze_macro_environment` | 调用 prompt | 返回分析步骤提示 | ☐ |
| `check_signal_eligibility` | 调用 prompt（带参数） | 返回检查步骤提示 | ☐ |

---

## 8. 集成测试场景

集成测试脚本位于 `tests/integration/` 目录：

### 8.1 场景一：完整投资流程

**测试脚本：** `tests/integration/test_complete_investment_flow.py`

**运行方式：**
```powershell
python tests/integration/test_complete_investment_flow.py
# 或
pytest tests/integration/test_complete_investment_flow.py -v
```

**测试步骤：**

1. 通过 SDK 获取当前宏观象限
2. 通过 SDK 获取政策状态
3. 通过 SDK 检查某资产的准入条件
4. 通过 SDK 列出现有信号
5. 通过 SDK 创建投资信号
6. 通过 SDK 验证信号创建
7. 通过 SDK 获取信号详情
8. 验证数据一致性

**预期结果：** 整个流程无错误，数据一致

### 8.2 场景二：回测流程

**测试脚本：** `tests/integration/test_backtesting_flow.py`

**运行方式：**
```powershell
python tests/integration/test_backtesting_flow.py
# 或
pytest tests/integration/test_backtesting_flow.py -v
```

**测试步骤：**

1. 初始化 SDK 客户端
2. 列出现有回测
3. 获取回测详情
4. 获取回测结果
5. 获取净值曲线
6. 获取交易历史
7. 验证回测指标

**预期结果：** 回测数据完整，净值曲线可绘制

### 8.3 场景三：实时数据监控

**测试脚本：** `tests/integration/test_realtime_monitoring_flow.py`

**运行方式：**
```powershell
set AGOMTRADEPRO_RUN_LIVE_REALTIME_TESTS=1
python tests/integration/test_realtime_monitoring_flow.py
# 或
set AGOMTRADEPRO_RUN_LIVE_REALTIME_TESTS=1
pytest tests/integration/test_realtime_monitoring_flow.py -v
```

**运行前提：**
- 该测试依赖 `http://localhost:8000` 上的可用服务。
- 该测试依赖真实实时行情数据。
- 未设置 `AGOMTRADEPRO_RUN_LIVE_REALTIME_TESTS=1` 时应默认跳过，避免 CI 因环境或行情缺失失败。

**测试步骤：**

1. 获取单个资产的实时价格
2. 批量获取多个资产的实时价格
3. 获取市场概况
4. 获取涨幅榜
5. 获取跌幅榜
6. 获取最活跃股票
7. 测试数据一致性

**预期结果：** 数据实时且准确

---

## 9. 高级测试场景

### 9.1 性能测试

**目标**: 验证系统响应时间和吞吐量

| 指标 | 目标值 | 测试方法 |
|------|--------|----------|
| API 响应时间 (P50) | < 200ms | 连续调用 100 次，统计分位数 |
| API 响应时间 (P95) | < 500ms | 连续调用 100 次，统计分位数 |
| API 响应时间 (P99) | < 1000ms | 连续调用 100 次，统计分位数 |
| 并发请求处理 | 支持 10 并发 | 同时发起 10 个请求 |
| MCP 工具调用延迟 | < 100ms | 通过 MCP 调用工具 50 次 |

**性能测试脚本位置**: `tests/performance/`（待创建）

### 9.2 并发测试

**场景**: 多个 AI Agent 同时调用 MCP

**测试步骤**:
1. 启动多个 MCP 客户端进程（模拟多个 AI Agent）
2. 同时调用相同的工具
3. 验证每个请求都获得正确响应
4. 检查数据库连接池状态
5. 验证无竞态条件

**预期结果**: 所有请求成功返回，数据一致性保持

### 9.3 容错测试

| 故障场景 | 测试方法 | 预期行为 |
|----------|----------|----------|
| Django 服务宕机 | 停止 Django 进程后调用 | SDK 返回 ConnectionError，重试 3 次 |
| PostgreSQL 连接断开 | `docker stop agomtradepro_postgres_dev` | 返回明确错误，无崩溃 |
| Redis 连接断开 | `docker stop agomtradepro_redis_dev` | Celery 任务排队，缓存失效 |
| 网络超时 | 模拟网络延迟 30 秒 | SDK 重试后返回 TimeoutError |
| API Token 失效 | 使用过期 Token | 返回 401，明确提示 |

### 9.4 安全测试

| 测试项 | 测试方法 | 预期结果 |
|--------|----------|----------|
| SQL 注入 | 在参数中注入 SQL 语句 | 参数化查询，无 SQL 执行 |
| XSS 攻击 | 在输入中注入脚本 | 输出转义，无脚本执行 |
| 越权访问 | 用普通用户访问管理接口 | 返回 403 Forbidden |
| Token 过期 | 使用过期 Token | 返回 401 Unauthorized |
| 敏感信息泄露 | 检查 API 响应 | 不返回密码、Token 等敏感信息 |

### 9.5 数据边界测试

| 场景 | 测试数据 | 预期结果 |
|------|----------|----------|
| 空数据 | 空列表、空字符串 | 正常处理或明确错误 |
| 大批量数据 | 请求 1000 条记录 | 分页返回或限制数量 |
| 超长字符串 | 10KB 字符串参数 | 拒绝或截断 |
| 特殊字符 | `\n`, `\t`, `\0`, emoji | 正确处理 |
| 非法格式 | 错误的日期格式 | 返回 400 Bad Request |

### 9.6 回归测试策略

**触发条件**:
- 每次 PR 合并到 main 分支
- 每日定时执行（凌晨 2:00）
- 版本发布前

**回归测试内容**:
1. 所有单元测试
2. 所有集成测试
3. 关键业务流程端到端测试
4. 性能基准测试

**CI/CD 集成**: 见第 13 节

---

## 10. 测试数据策略

### 10.1 数据来源

| 测试类型 | 数据来源 | 说明 |
|----------|----------|------|
| 单元测试 | Mock 数据 | 使用 pytest-mock |
| 集成测试 | Fixtures | Django fixtures + factory_boy |
| 性能测试 | 生成数据 | 使用 faker 生成大量数据 |
| 端到端测试 | 测试数据库 | 独立的测试数据库 |

### 10.2 数据初始化

```python
# tests/fixtures.py
import pytest
from django.contrib.auth import get_user_model
from apps.signal.domain.entities import InvestmentSignal

@pytest.fixture
def test_user(db):
    User = get_user_model()
    return User.objects.create_user(
        username='testuser',
        password='testpass123'
    )

@pytest.fixture
def test_signal(db):
    return InvestmentSignal(
        asset_code="000001.SH",
        logic_desc="测试信号",
        signal_type="long"
    )
```

### 10.3 数据清理

**策略**: 每次测试后自动回滚事务

```python
# pytest.ini
[pytest]
django_debug_mode = true
addopts = --reuse-db --nomigrations
```

### 10.4 数据隔离

| 测试模式 | 数据库 | 隔离方式 |
|----------|--------|----------|
| SQLite | 内存数据库 `:memory:` | 每个进程独立 |
| PostgreSQL | `agomtradepro_test` | Schema 隔离 |
| Docker | 独立容器 | 完全隔离 |

---

## 11. 潜在问题和检查点

### 11.1 连接问题

| 问题 | 检查方法 | 解决方案 |
|------|----------|----------|
| 服务器无法启动 | 检查端口占用 | 更改端口或关闭占用进程 |
| PostgreSQL 连接失败 | `docker ps` 检查容器 | 重启 Docker 服务 |
| Redis 连接失败 | `docker exec agomtradepro_redis_dev redis-cli ping` | 检查 Redis 容器状态 |
| SDK 连接超时 | 检查 `AGOMTRADEPRO_BASE_URL` | 确认 URL 正确 |

### 11.2 认证问题

| 问题 | 检查方法 | 解决方案 |
|------|----------|----------|
| 401 Unauthorized | 检查 API Token | 创建有效的 API Token |
| 403 Forbidden | 检查用户权限 | 使用超级用户账号 |

### 11.3 数据问题

| 问题 | 检查方法 | 解决方案 |
|------|----------|----------|
| 宏观数据为空 | `/admin/` 检查数据 | 运行数据同步任务 |
| Regime 计算失败 | 检查指标数据 | 确保数据完整 |

### 11.4 MCP 问题

| 问题 | 检查方法 | 解决方案 |
|------|----------|----------|
| MCP 服务器未启动 | 检查 Claude Code 配置 | 重启 Claude Code |
| 工具调用失败 | 手动测试 MCP 服务器 | 检查 SDK 连接 |

---

## 12. 用户体验检查清单

### 12.1 易用性

- ☐ 启动脚本是否简单明了？
- ☐ 错误提示是否清晰？
- ☐ 配置是否过于复杂？

### 12.2 文档完整性

- ☐ 快速开始指南是否清晰？
- ☐ API 文档是否完整？
- ☐ MCP 配置说明是否准确？

### 12.3 开发体验

- ☐ SDK API 设计是否直观？
- ☐ MCP 工具命名是否合理？
- ☐ 类型提示是否完整？

---

## 13. 测试执行自动化

### 13.1 测试编排脚本

**脚本位置：** `run_all_tests.ps1`（项目根目录）

**快速运行：**
```powershell
# 运行所有测试（完整模式）
.\run_all_tests.ps1

# 快速模式（仅 SDK 和 MCP 基础测试）
.\run_all_tests.ps1 -TestMode quick

# 仅 SDK 测试
.\run_all_tests.ps1 -TestMode sdk-only

# 仅 MCP 测试
.\run_all_tests.ps1 -TestMode mcp-only
```

**测试输出：**
- 所有测试结果保存在 `test-results/` 目录
- 包括每个测试的日志文件
- 测试摘要显示在控制台

**选项：**
- `-TestMode`: quick, full, mcp-only, sdk-only
- `-SkipServerCheck`: 跳过服务器运行检查
- `-NoCoverage`: 跳过代码覆盖率报告
- `-OutputPath`: 指定输出目录（默认：`test-results/`）

---

### 13.2 CI/CD 集成

**自动化测试触发条件**:

| 触发事件 | 执行测试 | 说明 |
|----------|----------|------|
| PR 提交 | 快速测试 (quick) | 仅 SDK + MCP 基础测试，5分钟内完成 |
| PR 合并到 main | 完整测试 (full) | 所有测试，包括性能测试 |
| 定时任务 (每日 2:00) | 回归测试 | 验证主分支稳定性 |
| 发布标签 | 完整测试 + 安全扫描 | 发布前完整验证 |

**GitHub Actions 示例**:

```yaml
# .github/workflows/test.yml
name: Tests

on:
  pull_request:
    branches: [main, develop]
  push:
    branches: [main]
  schedule:
    - cron: '0 2 * * *'  # 每日 2:00

jobs:
  quick-test:
    if: github.event_name == 'pull_request'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          cd sdk && pip install -e .
      - name: Run quick tests
        run: ./run_all_tests.ps1 -TestMode quick

  full-test:
    if: github.event_name == 'push' || github.event_name == 'schedule'
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_DB: agomtradepro_test
          POSTGRES_USER: agomtradepro
          POSTGRES_PASSWORD: test_password
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
        ports:
          - 5433:5432
      redis:
        image: redis:7
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
        ports:
          - 6379:6379
    steps:
      - uses: actions/checkout@v3
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          cd sdk && pip install -e .
      - name: Run full tests
        run: ./run_all_tests.ps1 -TestMode full
        env:
          DATABASE_URL: postgresql://agomtradepro:test_password@localhost:5433/agomtradepro_test
          REDIS_URL: redis://localhost:6379/0
```

---

## 14. Bug 报告模板

发现问题时，使用以下模板记录：

**模板位置：** `docs/testing/bug-report-template.md`

或使用以下快速模板：

```
## Bug #[编号]

### 描述
[简要描述问题]

### 复现步骤
1. [步骤 1]
2. [步骤 2]
3. [步骤 3]

### 预期结果
[应该发生什么]

### 实际结果
[实际发生了什么]

### 环境信息
- OS: [Windows/Linux/Mac]
- Python 版本: [x.x.x]
- 模式: [sqlite/docker/postgres]

### 错误日志
[粘贴相关错误日志]

### 严重程度
- [ ] Critical（阻塞测试）
- [ ] High（影响主要功能）
- [ ] Medium（影响次要功能）
- [ ] Low（不影响功能）
```

---

## 15. 测试结果模板

**模板位置：** `docs/testing/test-results-template.md`

使用该模板记录测试执行结果，包括：
- 各阶段测试通过率
- 发现的 Bug 列表
- 用户体验问题
- 改进建议

---

## 16. 快速开始指南

### 最快速的测试方式

```powershell
# 1. 启动服务器（SQLite 模式，最简单）
.\scripts\start-dev.ps1 -Mode sqlite

# 2. 在新终端运行所有测试
.\run_all_tests.ps1 -TestMode quick
```

### 完整测试流程

```powershell
# 1. 启动完整环境（Docker + PostgreSQL + Redis + Celery）
.\scripts\start-dev.ps1 -Mode docker

# 2. 在新终端运行完整测试套件
.\run_all_tests.ps1 -TestMode full

# 3. 查看测试结果
# 测试结果保存在 test-results/ 目录
```

### 单独运行特定测试

```powershell
# 仅 SDK 测试
python test_sdk_connection.py

# 仅 MCP 测试
python test_mcp_server.py

# 投资流程集成测试
python tests/integration/test_complete_investment_flow.py

# 回测流程集成测试
python tests/integration/test_backtesting_flow.py

# 实时监控集成测试
set AGOMTRADEPRO_RUN_LIVE_REALTIME_TESTS=1
python tests/integration/test_realtime_monitoring_flow.py
```

---

## 17. 测试执行顺序

### 自动化执行（推荐）

使用 `run_all_tests.ps1` 自动执行所有测试阶段。

### 手动执行顺序

1. **Phase 1：环境准备**（15 分钟）
   - 虚拟环境检查
   - 依赖安装
   - 环境变量配置

2. **Phase 2：服务启动**（10 分钟）
   - Docker 服务启动
   - 数据库迁移
   - Celery 启动
   - Django 启动

3. **Phase 3：SDK 测试**（20 分钟）
   - SDK 安装测试
   - 基础连接测试
   - 各模块功能测试

4. **Phase 4：MCP 测试**（20 分钟）
   - MCP 配置测试
   - 工具调用测试
   - 资源和 Prompt 测试

5. **Phase 5：集成测试**（15 分钟）
   - 完整流程测试
   - 数据一致性验证

6. **Phase 6：问题记录**（10 分钟）
   - 汇总发现的问题
   - 记录改进建议

**总计：约 90 分钟（手动执行）**
**自动化执行：约 5-10 分钟**

---

## 18. 关键文件位置

| 用途 | 文件路径 |
|------|----------|
| **测试脚本** | |
| 测试编排脚本 | `run_all_tests.ps1` (项目根目录) |
| **SDK 测试** | |
| SDK 连接测试 | `tests/acceptance/test_sdk_connection.py` |
| SDK 单元测试 | `tests/unit/test_sdk/` |
| **MCP 测试** | |
| MCP 服务器测试 | `tests/acceptance/test_mcp_server.py` |
| MCP 单元测试 | `tests/unit/test_mcp/` |
| **集成测试** | |
| 投资流程测试 | `tests/integration/test_complete_investment_flow.py` |
| 回测流程测试 | `tests/integration/test_backtesting_flow.py` |
| 实时监控测试 | `tests/integration/test_realtime_monitoring_flow.py`（需设置 `AGOMTRADEPRO_RUN_LIVE_REALTIME_TESTS=1`） |
| **性能测试** | |
| 性能基准测试 | `tests/performance/` (待创建) |
| **测试数据** | |
| Fixtures | `tests/fixtures/` |
| 工厂类 | `tests/factories/` |
| **SDK 源码** | |
| SDK 客户端 | `sdk/agomtradepro/client.py` |
| SDK 配置 | `sdk/agomtradepro/config.py` |
| SDK 异常 | `sdk/agomtradepro/exceptions.py` |
| **MCP 源码** | |
| MCP 服务器 | `sdk/agomtradepro_mcp/server.py` |
| MCP 工具目录 | `sdk/agomtradepro_mcp/tools/` |
| **配置文件** | |
| 环境配置 | `.env` |
| 环境配置示例 | `.env.example` |
| **基础设施** | |
| 启动脚本 | `scripts/start-dev.ps1` |
| Docker 配置 | `docker-compose-dev.yml` |
| **文档** | |
| 测试计划 | `docs/testing/sdk-mcp-integration-test-plan.md` |
| Bug 报告模板 | `docs/testing/bug-report-template.md` |
| 测试结果模板 | `docs/testing/test-results-template.md` |
| SDK 文档 | `docs/sdk/` |
| 测试指南 | `tests/README.md` |


