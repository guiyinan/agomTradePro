# 通过 MCP 配置数据出口

数据中台的出口和分流规则可通过默认 MCP 能力入口管理，与 [TUI 配置页](data-egress-tui-configuration.md) 共用后端配置。业务模块仍向数据中台取数。MCP 登记的是应用可访问的 HTTP(S) 代理；FRP 客户端进程、frps 地址和隧道密钥由部署模板管理，不通过这些能力发布。

## 发现与权限

使用 `agom_capability_search` 搜索 `frpc`、`egress` 或“出口”，再用 `agom_capability_schema` 查看选中能力的参数。无需启用 `AGOMTRADEPRO_MCP_ENABLE_LEGACY_TOOLS`，默认统一入口即可调用。

本组能力要求可信运行身份具备 `staff` 权限；后端再次校验管理员权限。沿用现有 MCP 的系统地址和认证配置。路由预览使用 POST，因此认证配置也需要允许对应请求；不应只配置 GET 权限。

`/api/account/profile/` 返回只读 `is_staff` 标志。业务角色为 `owner`、同时具备 Django 管理员权限的账户也可使用本组能力；普通 `owner` 不会因此获得管理员权限。身份标志只来自后端认证资料，不能通过配置参数或资料更新接口写入。

| 操作 | capability_key | 对应 SDK 方法 |
| --- | --- | --- |
| 出口清单 | `data_center.read.egress_endpoints` | `list_egress_endpoints()` |
| 出口详情 | `data_center.read.egress_endpoint` | `get_egress_endpoint(endpoint_id)` |
| 登记出口 | `data_center.create.egress_endpoint` | `create_egress_endpoint(payload)` |
| 修改、启停出口 | `data_center.update.egress_endpoint` | `update_egress_endpoint(endpoint_id, payload)` |
| 测试指定出口 | `data_center.run.egress_endpoint_test` | `test_egress_endpoint(endpoint_id, context)` |
| 规则清单 | `data_center.read.egress_rules` | `list_egress_rules()` |
| 规则详情 | `data_center.read.egress_rule` | `get_egress_rule(rule_id)` |
| 登记规则 | `data_center.create.egress_rule` | `create_egress_rule(payload)` |
| 修改、启停规则 | `data_center.update.egress_rule` | `update_egress_rule(rule_id, payload)` |
| 预览路径 | `data_center.read.egress_route_preview` | `preview_egress_route(context)` |
| 连接诊断 | `data_center.run.egress_diagnostics` | `diagnose_egress_route(context)` |

数据源编号可以从已有 `data_center.read.provider_catalog` 查询，不必猜测 ID。

## 登记、测试和启用

先登记停用出口，再登记停用规则。下面是向 `agom_capability_call` 提供的参数示例；主机和端口须与实际部署一致。

```json
{
  "capability_key": "data_center.create.egress_endpoint",
  "arguments": {
    "name": "境内行情出口",
    "region": "cn",
    "protocol": "http",
    "host": "frpc_egress_visitor",
    "port": 18080,
    "enabled": false,
    "idempotency_key": "register-mainland-exit-001"
  }
}
```

配置写入和联网测试会返回 `confirmation_required`、`preview_result` 与 `confirmation_token`。核对预览后，将 token 和 `approve: true` 交给 `agom_confirmation_resume`；取消则使用 `approve: false`。预览不会保存配置或发起行情请求，确认时由后端校验最终配置和路由约束。每项新操作使用独立 `idempotency_key`；重试同一操作使用相同 key 和参数。

代理认证字段为 `credential_username`、`credential_password`，预览与审计脱敏，SDK 映射到后端写入字段。省略或空字符串保留原值；明确传入 `clear_credentials: true` 才清除认证。不要把凭据放入名称、主机或测试地址。编辑时省略字段表示保留，`enabled: false` 表示停用，规则的 `fixed_egress_id: null` 表示清除绑定。

规则要求数据源、数据集、域名、执行节点区域、策略和优先级。策略可用 `direct`、`fixed`、`direct_fallback`；后两者需要指定出口。测试和诊断的 context 使用具体值，例如：

```json
{
  "provider_id": 3,
  "dataset_key": "equity.price.bar",
  "url": "https://push2his.eastmoney.com/api/qt/stock/kline/get",
  "deployment_region": "overseas"
}
```

此处数据源编号只是示例；区域应是实际执行节点区域。指定出口测试另外提供 `endpoint_id`，目标需要符合已经登记的规则，停用规则也可作为测试许可。实际 HTTP(S) 地址不能含登录凭据或片段，context 不能用通配符。

测试通过后先启用出口，再启用规则；之后预览路径并确认运行诊断。撤销时先停用规则：固定出口规则仍启用而出口停用时，会明确阻断请求。

## 结果与边界

- MCP 外层 `status: completed` 表示能力调用完成。连接是否成功必须看 `result.outcome`：`failed`、`blocked` 不能当作成功；`attempts` 保留每次尝试、耗时和错误码。
- 含查询参数、认证或片段的 URL 在审计中整体脱敏；诊断预览不展示查询参数，实际请求仍保留原查询参数。
- 读清单返回 `result.results` 与 `total_count`；详情、保存和诊断对象位于 `result`。SDK 清单直接返回列表，其他方法返回已解包对象。
- 确认和幂等记录沿用现有 MCP 进程内存机制，不跨重启持久化。进程重启后先查清单核实上次操作是否生效，再决定是否重新提交。
- 部署更新 SDK/MCP 后需重启对应 MCP 服务或客户端连接，才能加载新能力。仅本地提交不会自动更新 VPS 或已有 MCP 进程。
- 本地集成验收以临时 SQLite 和可控网络结果验证全链路；真实 frps/frpc 连通性、实际出口 IP 和东方财富取数仍需部署环境验证。
