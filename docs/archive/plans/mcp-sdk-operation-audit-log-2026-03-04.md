# MCP/SDK 操作审计日志系统规划（细化版）

## Context（背景与需求）

### 问题陈述
AgomTradePro 通过 MCP (Model Context Protocol) 和 SDK 对外暴露了 65+ 个工具，覆盖信号管理、政策事件、回测执行、模拟交易等核心功能。但当前缺乏统一的操作审计追踪，导致：

1. 无法追溯：不知道谁在什么时候调用了什么工具。
2. 无法复盘：AI 决策链路不透明，难以事后分析。
3. 无法追责：异常操作无法定位到具体来源。
4. 合规风险：金融场景要求完整可检索的操作轨迹。
5. 可用性不足：仅有后端日志，不足以支撑运维/风控/用户自查。

### 当前状态
- MCP 工具：65+，覆盖主要业务域。
- RBAC 角色：7 个（admin, owner, investment_manager, trader, risk, analyst, read_only）。
- `apps/audit/` 现有能力偏投资分析审计，不是操作审计日志。
- 各模块有分散日志（PolicyLog, RegimeLog），没有统一查询视图。

### 目标
建立统一操作审计日志系统，并明确区分两类消费场景：

1. 采集层：记录所有 MCP/SDK 调用上下文（身份、参数、结果、耗时）。
2. 查询层：
   - 管理员审计台（全量可见、统计、导出）。
   - 用户“我的操作”页面（仅可见自己的日志）。
3. 接口层：提供稳定 API（查询、详情、统计、导出、内部写入）。
4. 治理层：最小权限、敏感字段脱敏、保留策略、失败告警。

---

## Architecture Decision（关键决策）

### 决策 1：必须提供前端查询入口
- 结论：需要。
- 原因：仅有后端 API 无法形成可用审计闭环，运营/风控/用户都需要直接可视化查询。

### 决策 2：查询权限按“管理员全量 + 用户仅本人”分层
- 管理员角色：可查询全量、查看统计、执行导出。
- 普通角色：仅查询本人日志，禁止全量导出和全局统计。

### 决策 3：写入接口与查询接口分离
- 内部写入接口（MCP/SDK -> Backend）单独鉴权，不暴露给普通前端 token。
- 查询接口仍基于用户登录态 + RBAC。

### 决策 4：审计失败不阻塞主流程，但必须可观测
- 不影响工具主执行结果。
- 记录告警计数与错误日志，纳入监控。

---

## Implementation Plan（实现方案）

### Phase 1: 数据模型设计（核心）

**新增 Model**: `apps/audit/infrastructure/models.py`

```python
class OperationLogModel(models.Model):
    """MCP/SDK 操作审计日志"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    request_id = models.CharField(max_length=64, db_index=True, help_text="链路追踪ID")

    # 操作者身份
    user_id = models.IntegerField(null=True, db_index=True)
    username = models.CharField(max_length=150, default="anonymous")
    ip_address = models.GenericIPAddressField(null=True)
    user_agent = models.CharField(max_length=500, blank=True)

    # 来源与租户
    source = models.CharField(max_length=20, default="MCP", db_index=True, help_text="MCP/SDK/API")
    client_id = models.CharField(max_length=100, blank=True, db_index=True)

    # 操作描述
    operation_type = models.CharField(max_length=50, db_index=True, help_text="MCP_CALL/API_ACCESS/DATA_MODIFY")
    module = models.CharField(max_length=50, db_index=True, help_text="signal/policy/backtest/...")
    action = models.CharField(max_length=50, help_text="CREATE/READ/UPDATE/DELETE/EXECUTE")
    resource_type = models.CharField(max_length=50, blank=True)
    resource_id = models.CharField(max_length=100, null=True, db_index=True)

    # MCP 特定字段
    mcp_tool_name = models.CharField(max_length=120, null=True, db_index=True)
    mcp_client_id = models.CharField(max_length=100, blank=True)
    mcp_role = models.CharField(max_length=30, blank=True)
    sdk_version = models.CharField(max_length=50, blank=True)

    # 请求详情（params 为脱敏后）
    request_method = models.CharField(max_length=10, default="MCP")
    request_path = models.CharField(max_length=500, blank=True)
    request_params = models.JSONField(default=dict, encoder=DjangoJSONEncoder)
    response_status = models.IntegerField(default=200, db_index=True)
    response_message = models.TextField(blank=True)
    error_code = models.CharField(max_length=50, blank=True)

    # 时间与性能
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    duration_ms = models.IntegerField(null=True)

    # 完整性
    checksum = models.CharField(max_length=64, blank=True, help_text="SHA-256")

    class Meta:
        db_table = "audit_operation_log"
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["user_id", "-timestamp"], name="idx_audit_user_ts"),
            models.Index(fields=["operation_type", "module"], name="idx_audit_type_module"),
            models.Index(fields=["mcp_tool_name", "-timestamp"], name="idx_audit_tool_ts"),
            models.Index(fields=["response_status", "-timestamp"], name="idx_audit_status_ts"),
            models.Index(fields=["source", "-timestamp"], name="idx_audit_source_ts"),
        ]
```

**补充字段说明**
- `source`：统一兼容 MCP/SDK/API 来源。
- `client_id`：用于后续多租户或客户端维度隔离。
- `error_code`：便于统计失败类型。

---

### Phase 2: Domain 层实现

**新增实体**: `apps/audit/domain/entities.py`
- `OperationLog` 实体与 Model 对齐（含 `source/client_id/error_code`）。

**新增 Service**: `apps/audit/domain/services.py`
- `OperationLogFactory.create(...)` 统一构建日志实体。
- `infer_action(tool_name)` 与 `infer_module(tool_name)` 固化规则。
- `mask_sensitive_params(params)` 在 Domain 层执行脱敏。

**脱敏规则（最低要求）**
- key 命中以下关键词时替换为 `***`：
  - `password`, `token`, `secret`, `api_key`, `authorization`, `cookie`, `session`
- 支持嵌套字典和列表递归脱敏。

---

### Phase 3: Application 层 Use Cases

**新增**: `apps/audit/application/use_cases.py`

1. `LogOperationUseCase`
- 输入 `LogOperationRequest`，调用 `OperationLogFactory`，入库。
- 记录 `request_id` 返回给调用方用于链路追踪。

2. `QueryOperationLogsUseCase`
- 管理员可按全条件筛选。
- 普通用户自动追加 `user_id = current_user.id` 限制，禁止越权。

3. `ExportOperationLogsUseCase`
- 仅管理员可导出。
- 导出上限（如 10,000 条）和时间窗限制（如最大 90 天）。

4. `GetOperationStatsUseCase`
- 仅管理员可查看全局统计。
- 普通用户仅允许“我的统计”（可选，首版可不开放）。

---

### Phase 4: MCP/SDK 集成（写入链路）

**修改**: `sdk/agomtradepro_mcp/server.py`
- 在 `apply_tool_rbac_guards()` 中将包装器升级为 `RBAC + Audit`。
- 记录成功、权限拒绝、业务异常三类状态。

**新增**: `sdk/agomtradepro_mcp/audit.py`
- `AuditLogger` 调用后端内部写入端点：
  - `POST /audit/api/internal/operation-logs/`
- 使用服务间鉴权（`X-Audit-Signature` 或内部 API key）。
- 审计失败时：
  - 不抛出给业务调用方；
  - 打本地 warning/error 日志；
  - 增加失败计数指标（Prometheus counter 或等价机制）。

**状态码建议**
- 执行成功：`200`
- RBAC 拒绝：`403`
- 业务异常：`500`
- 客户端参数校验失败：`400`

---

### Phase 5: API 端点（查询与内部写入分离）

**新增**: `apps/audit/interface/views.py`

1. `OperationLogViewSet`（查询）
- `GET /audit/api/operation-logs/`：列表 + 过滤 + 分页
- `GET /audit/api/operation-logs/{id}/`：详情
- 权限：`IsAuthenticated + OperationLogReadPermission`
- 普通用户仅可见本人数据

2. `OperationLogExportView`（导出）
- `GET /audit/api/operation-logs/export/?format=csv`
- 权限：`IsAuthenticated + IsAuditAdmin`
- 限制：最大导出条数 + 最大时间窗

3. `OperationLogStatsView`（统计）
- `GET /audit/api/operation-logs/stats/`
- 权限：`IsAuthenticated + IsAuditAdmin`

4. `OperationLogIngestView`（内部写入）
- `POST /audit/api/internal/operation-logs/`
- 权限：`HasInternalAuditSignature`（非用户登录态）
- 用于 MCP/SDK 写入，不对普通前端开放

**重要修正**
- 原方案里 `ReadOnlyModelViewSet` 与 `POST /operation-logs/` 冲突。
- 本版改为独立 internal ingest endpoint，职责清晰。

---

### Phase 6: 前端查询能力（新增）

#### 6.1 管理员审计台（Audit Admin Console）

**页面目标**
- 支撑运营/风控/审计人员快速检索和复盘。

**核心功能**
1. 全量筛选：
   - 时间范围、模块、动作、工具名、角色、状态码、用户、资源ID。
2. 列表视图：
   - 时间、用户、工具、动作、状态、耗时、request_id。
3. 详情抽屉：
   - 请求参数（脱敏后）、响应信息、客户端、IP、UA。
4. 统计卡片：
   - 总量、错误率、平均耗时、Top 工具/模块。
5. 导出按钮：
   - 仅管理员显示；导出当前筛选结果（受上限保护）。

#### 6.2 用户“我的操作日志”（My Operation Logs）

**页面目标**
- 支撑普通用户自查“我做了什么、是否成功”。

**核心功能**
1. 默认仅显示当前登录用户日志。
2. 默认时间窗 `最近 7 天`（可改 30 天）。
3. 过滤条件精简：
   - 时间范围、工具名、动作、状态。
4. 不提供全局统计和全量导出。

#### 6.3 前端权限与交互约束
- 后端做强制权限裁剪，前端只做显示层控制。
- 非管理员访问管理员审计页返回 `403`，前端落地为无权限页。
- 查询页必须使用后端分页，避免一次拉取超量数据。

---

### Phase 7: 数据保留与清理

**新增管理命令**: `apps/audit/management/commands/cleanup_operation_logs.py`
- 默认保留 90 天。
- 支持 `--days` 与 `--dry-run`。
- 建议定时任务每日执行一次。

**可选增强（数据量上升后）**
- 按月分区表。
- 冷数据归档到对象存储（CSV/Parquet）。

---

## Permission Matrix（权限矩阵）

| 能力 | admin/owner | investment_manager/trader/risk/analyst/read_only |
|------|-------------|---------------------------------------------------|
| 查询全量日志 | Yes | No |
| 查询本人日志 | Yes | Yes |
| 查看日志详情 | Yes | Yes（仅本人） |
| 查看全局统计 | Yes | No |
| 导出日志 | Yes | No |
| 内部写入接口调用 | No（用户态） | No（用户态） |
| MCP/SDK 服务写入 | Yes（服务签名） | Yes（服务签名） |

---

## API Endpoints Summary

| Method | Endpoint | 权限 | 描述 |
|--------|----------|------|------|
| GET | `/audit/api/operation-logs/` | 登录 + 读权限 | 查询日志列表（分页/过滤） |
| GET | `/audit/api/operation-logs/{id}/` | 登录 + 读权限 | 查询单条详情 |
| GET | `/audit/api/operation-logs/export/` | 审计管理员 | 导出日志（CSV/JSON） |
| GET | `/audit/api/operation-logs/stats/` | 审计管理员 | 全局统计 |
| POST | `/audit/api/internal/operation-logs/` | 服务签名 | 内部写入日志 |

### 查询参数
- `operation_type`: MCP_CALL, API_ACCESS, DATA_MODIFY
- `module`: signal, policy, backtest, etc.
- `action`: CREATE, READ, UPDATE, DELETE, EXECUTE
- `mcp_tool_name`: 工具名
- `mcp_role`: 角色
- `user_id`: 用户 ID（普通用户传入也会被后端覆盖为本人）
- `response_status`: 响应状态码
- `start_date`, `end_date`: 时间范围
- `resource_id`: 资源 ID
- `ordering`: `timestamp` / `duration_ms`

---

## Critical Files to Modify/Create

### 新增文件
| 文件路径 | 说明 |
|---------|------|
| `apps/audit/domain/entities.py` | `OperationLog` 实体 |
| `apps/audit/domain/services.py` | 工厂与脱敏逻辑 |
| `apps/audit/application/use_cases.py` | 记录/查询/导出/统计用例 |
| `apps/audit/infrastructure/models.py` | `OperationLogModel` |
| `apps/audit/infrastructure/repositories.py` | 日志仓储实现 |
| `apps/audit/interface/serializers.py` | `OperationLogSerializer` |
| `apps/audit/interface/permissions.py` | `IsAuditAdmin` 等权限类 |
| `apps/audit/interface/views.py` | 查询/导出/统计/internal ingest 视图 |
| `apps/audit/management/commands/cleanup_operation_logs.py` | 清理命令 |
| `sdk/agomtradepro_mcp/audit.py` | MCP 审计客户端 |
| `frontend/.../audit-admin/*` | 管理员审计台页面与组件 |
| `frontend/.../my-operation-logs/*` | 用户自查页面与组件 |

### 修改文件
| 文件路径 | 修改内容 |
|---------|----------|
| `sdk/agomtradepro_mcp/server.py` | RBAC 包装器增加审计钩子 |
| `apps/audit/interface/urls.py` | 注册查询/导出/统计/internal 路由 |
| `core/settings/base.py` | 审计配置（保留天数、导出上限、签名密钥） |
| `frontend` 路由配置文件 | 增加两个页面路由与权限守卫 |

---

## Verification（验证方案）

### 1. 单元测试
```bash
pytest tests/unit/test_audit_domain.py -v
pytest tests/unit/test_audit_permissions.py -v
pytest tests/unit/test_audit_masking.py -v
```

### 2. 集成测试（后端）
```bash
pytest tests/integration/test_audit_api.py -v
pytest tests/integration/test_audit_internal_ingest.py -v
pytest sdk/tests/test_mcp/test_audit.py -v
```

### 3. 端到端测试（前端）
```bash
# 管理员审计页：筛选、详情、导出按钮可见
pytest tests/e2e/test_audit_admin_console.py -v

# 普通用户：仅看到本人日志，访问管理员页返回 403/无权限页
pytest tests/e2e/test_my_operation_logs.py -v
```

### 4. 手动验证
```bash
# 1) 调用 MCP 工具后查看日志
curl -H "Authorization: Token ADMIN_TOKEN" \
  "http://localhost:8000/audit/api/operation-logs/?mcp_tool_name=create_signal"

# 2) 普通用户尝试查他人 user_id，结果应被后端限制为本人
curl -H "Authorization: Token USER_TOKEN" \
  "http://localhost:8000/audit/api/operation-logs/?user_id=1"

# 3) 非管理员访问统计应返回 403
curl -H "Authorization: Token USER_TOKEN" \
  "http://localhost:8000/audit/api/operation-logs/stats/"

# 4) 服务签名写入（示例）
curl -X POST "http://localhost:8000/audit/api/internal/operation-logs/" \
  -H "X-Audit-Signature: <SIGNATURE>" \
  -H "Content-Type: application/json" \
  -d '{"operation_type":"MCP_CALL","module":"signal","action":"CREATE"}'
```

### 5. 数据库验证
```sql
SELECT COUNT(*) FROM audit_operation_log;

SELECT timestamp, username, mcp_tool_name, response_status, duration_ms
FROM audit_operation_log
WHERE operation_type = 'MCP_CALL'
ORDER BY timestamp DESC
LIMIT 20;
```

---

## Estimated Effort（更新）

| Phase | 工作量 |
|-------|--------|
| Phase 1: 数据模型 | 0.5 天 |
| Phase 2: Domain 层 | 0.5 天 |
| Phase 3: Application 层 | 0.5 天 |
| Phase 4: MCP/SDK 集成 | 1 天 |
| Phase 5: API 与权限 | 1 天 |
| Phase 6: 前端查询（管理员+用户） | 1.5 天 |
| Phase 7: 数据保留与清理 | 0.5 天 |
| 测试与文档 | 1 天 |
| **总计** | **6.5 天** |

---

## Risks & Mitigations（细化）

| 风险 | 缓解措施 |
|------|----------|
| 审计写入失败影响主流程 | 审计写入异常不抛出；同时打告警日志与失败指标 |
| 普通用户越权看到全量日志 | 后端 QuerySet 强制 `user_id=self`；权限类二次兜底 |
| 敏感信息泄露 | `request_params` 入库前统一脱敏；导出复用同一脱敏逻辑 |
| 数据量增长导致查询慢 | 索引 + 分页 + 默认时间窗；后续分区/归档 |
| 导出导致性能抖动 | 条数/时间窗上限 + 异步导出（数据量大时升级） |
| internal ingest 被伪造调用 | 服务签名校验、时间戳防重放、密钥轮换 |

---

## Definition of Done（验收标准）

1. MCP/SDK 所有工具调用均能落审计日志（成功/失败/拒绝）。
2. 管理员可在前端按条件检索、查看详情、查看统计、执行导出。
3. 普通用户前端仅可查看“我的操作日志”，无法越权查看他人。
4. 敏感参数在数据库与导出结果中均已脱敏。
5. 日志清理任务可执行并有 dry-run 验证。
6. 单元、集成、E2E 测试覆盖核心路径并通过。
