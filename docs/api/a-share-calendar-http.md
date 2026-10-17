# A 股日历 HTTP 操作合同

本文描述四个 JSON API 的请求与响应合同，供客户端实现对齐。视图、序列化器、presenter、服务端 composition 和 Data Center URLconf 已完成本地独立验收，含真实 SessionAuthentication/CSRF HTTP 组件测试；源码、完整门禁与原始失败记录见[阶段检查点](../testing/a-share-usability-calendar-http-2026-10-17.json)。浏览器/TUI、真实供应商与生产验收仍未完成。

## 路由

| 方法 | 本地路径 | 用途 | 权限 |
| --- | --- | --- | --- |
| `POST` | `/api/data-center/exchange-calendars/snapshots/capture/` | 从已配置来源采集并保存一个完整日历快照 | 已认证 Django session，且当前用户有 `data_center.publish_exchange_calendar` |
| `POST` | `/api/data-center/exchange-calendars/publication-preview/` | 对一个精确快照生成不落库的发布预览 | 同上 |
| `POST` | `/api/data-center/exchange-calendars/publications/` | 确认并正式发布预览回显 | 同上 |
| `GET` | `/api/data-center/exchange-calendars/current/?dataset_key=…&exchange=…` | 读取精确范围的 current 日历 | 已认证 Django session；不要求发布权限 |

这些路径已接入 `apps/data_center/interface/api_urls.py`，并由 `tests/unit/data_center/test_calendar_publication_routes.py` 检查 resolver/name/view 对应关系。该本地路由测试不证明真实 SessionAuthentication、CSRF 或生产部署已通过验收。

四个视图只接受 DRF `SessionAuthentication` 和 `IsAuthenticated`，使用 `JSONParser`/`JSONRenderer`。POST 仍受 Django SessionAuthentication 的 CSRF 校验。发布步骤还会从真实 request 的成功认证器、Django 用户及数据库 session 中取身份，并在 `default` alias 上锁内重核 session、用户和精确 permission witness。`staff`、`superuser`、账户角色、租户 owner、body 中的 `user_id` 都不能代替 `data_center.publish_exchange_calendar`。

采集、预览和确认是三个独立 HTTP 请求；每个请求分别由自己的 authority context 拥有唯一外层事务，并非跨步骤共享事务。内部 capture 仓储可以创建嵌套 `atomic()` savepoint，但不得换 alias。服务端只有在该请求的 authority context 正常退出并完成最终权限/事务检查后，才把成功结果交给 view。采集成功返回后快照已独立持久化；之后预览或确认失败不会回滚先前已提交的采集。当前读取由 composition 自己开启一个 `default` 外层事务，HTTP view 仍要求用户已认证，但读取不要求发布权。

请求体和 query 均为封闭 JSON 形状：未知字段、缺字段、重复 query 参数、字符串/数字类型强制转换、非 canonical UUID/hash/date/time 和部分填写的 pointer CAS 都会拒绝。客户端不能选择 actor、数据库 alias、clock、凭据或 seal，也不能自行设置或覆盖 TTL；确认请求必须逐字回传服务端预览中的 `expected_identity.calendar_response_max_age_seconds`。所有成功和错误响应都使用 JSON；POST 只接受 `application/json`。

## 采集 → 预览 → 确认

### 1. 采集一个明确日期范围

请求体仅含交易所和完整日期范围：

```json
{
  "exchange": "SSE",
  "coverage_start": "2026-10-01",
  "coverage_end": "2026-10-31"
}
```

日期必须是 `YYYY-MM-DD`，起始日不得晚于结束日。`exchange` 是必填原样字符串；没有默认交易所或默认日期。成功时返回 `201 Created`，`data.publication_status` 为 `unpublished`，其中 `snapshot_reference` 是后续预览需要的完整 source/RawPayload 引用。`data.preview_intent` 已包含可供下一步原样回传的 `{ "snapshot_reference": ... }`。

响应共同声明：

```json
{
  "must_not_execute": true,
  "must_not_use_for_decision": true,
  "blocked_reason": "exchange_calendar_reference_only",
  "freshness": {
    "source_observed_at": null,
    "source_available_at": null,
    "source_time_status": "not_provided"
  }
}
```

`first_seen_at`/`recorded_at` 是本地响应完成与入库知识时间，不是交易所发布时间或源观测时间。上游未提供的 source clock 保持 `null`。采集执行时会调用既有已配置的 Tushare `trade_cal` capture 路径；本文没有新增 Provider RPC、Provider 配置或请求，也没有执行真实供应商调用。执行前的目录、binding、TTL、ProviderConfig 和秘密快照前置条件见[日历采集配置合同](a-share-calendar-capture-configuration.md)。采集只保存未发布快照，不移动 current pointer，也不会新建授权或授予权限。

### 2. 对保存的精确快照生成预览

把采集响应中的 `data.preview_intent` 对象原样作为下一次 POST 的 JSON body。其唯一字段 `snapshot_reference` 必须完整包含：

```json
{
  "snapshot_id": "<capture 返回的 UUID>",
  "exchange": "SSE",
  "coverage_start": "2026-10-01",
  "coverage_end": "2026-10-31",
  "content_hash": "sha256:<64 位小写十六进制>",
  "record_digest": "sha256:<64 位小写十六进制>",
  "raw_payload_id": "<capture 返回的 UUID>",
  "raw_payload_hash": "sha256:<64 位小写十六进制>",
  "raw_record_digest": "sha256:<64 位小写十六进制>"
}
```

这只是字段形状示意；实际请求必须使用上一步返回的值，不能填写占位符。服务端按精确引用重新读取并验证快照、原始 payload、目录、TTL 和 current pointer，不会用 `latest` 替代，也不接受客户端提交 seal。

成功返回 `200 OK`，`data.publication_status` 为 `preview`。服务端返回目录身份 `identity`、响应过期时刻、完整 pointer CAS 预期和 `confirmation_intent`。客户端应把整个 `confirmation_intent` 对象原样保存并回传；不要挑字段、重建 hash、改时间或自行生成 activation ID。

### 3. 原样确认预览

POST body 必须是预览响应中的 `data.confirmation_intent` 本身，字段为：

```json
{
  "snapshot_reference": { "...": "完整精确 source reference" },
  "expected_identity": {
    "dataset_key": "<preview 返回值>",
    "contract_version": "<preview 返回值>",
    "schema_version": "<preview 返回值>",
    "policy_identity": "<preview 返回值>",
    "policy_version": "<preview 返回值>",
    "calendar_response_max_age_seconds": 3600
  },
  "expected_pointer": {
    "dataset_key": "<preview 返回值>",
    "publication_key": "<preview 返回值>",
    "pointer_id": null,
    "publication_id": null,
    "publication_hash": null,
    "activation_id": null,
    "updated_at": null
  },
  "activation_id": "<preview 返回值>",
  "expected_publication_hash": "<preview 返回的 64 位小写十六进制>",
  "preview_hash": "<preview 返回的 64 位小写十六进制>"
}
```

以上代码只示意字段形状；所有占位值都必须使用服务端原响应，`3600` 只表示该字段是 JSON 整数，不是默认或配置值。上例的 absent pointer 只适用于首次发布。若预览返回现有 current，`expected_pointer` 必须完整 echo 其中的 pointer 行 ID、publication ID/hash、activation ID 和 UTC `updated_at`；不能把 present pointer 改为空或只传部分字段。服务器会在确认时重新读取精确来源、目录、TTL、pointer 和权限。任何竞态、目录变化、过期或不一致都会阻断，不会按客户端快照强制写入。

`preview_hash` 是不带密钥的内容校验值，用来检测回显是否变化；它不是签名、权限凭据、预览历史证明或可单独使用的确认 token。新发布响应为 `201 Created`；forward 发布和精确当前赢家重试为 `200 OK`。成功返回 `data.publication_status: "published"`、transition 与有限发布元数据，不返回 seal、原始响应正文或 Audit 对象。

确认只支持首次发布、同范围 forward 和精确当前赢家重试。首次发布要求 pointer 与历史均为空；forward 必须提交完整旧 pointer CAS 并保持其行 ID，发布时间严格向前。精确重试只接受同一当前赢家及原 actor 当前仍有效的发布权限，返回原 publication 身份/时钟而不追加或修复 Audit。已 supersede 的旧版本不能作为历史查询、回滚目标或重新激活目标；本接口没有历史 rollback/reinstate 路径。

## 读取当前日历

GET 仅带两个 query 参数：

```text
?dataset_key=<精确 dataset key>&exchange=SSE
```

`dataset_key` 和 `exchange` 必须是唯一、非空且不带空白填充的字符串。重复参数、额外 `as_of`/`using`/`database_alias`/actor/TTL 参数都会拒绝。knowledge cutoff 来自服务器 UTC clock，不接受客户端历史时点。

存在精确 current 时返回 `200 OK`，包含当前 publication 的有限元信息、服务端 `as_of` 和 `calendar_days`。没有 current 时返回 `404` 和 `CALENDAR_CURRENT_PUBLICATION_NOT_FOUND`。读取只核验 exact current pointer、对应发布记录及正式 Audit 完整性；它不查询 `latest`、其他 scope 或 superseded 历史，也不要求当前读者拥有发布权或仍是原发布者。HTTP 层要求已认证 session；本地 view 与路由接线已存在。

响应仍声明 `must_not_execute=true`、`must_not_use_for_decision=true` 和 `exchange_calendar_reference_only`。它只提供交易所开闭日参考，不证明交易时段/阶段、证券状态、停牌、价格限制、账户可交易权限、T+1 可卖量或券商执行条件。

## 状态码与验收边界

视图/OpenAPI 合同中的成功状态为：采集 `201`，预览 `200`，确认首次发布 `201`、forward/精确重试 `200`，current 读取 `200` 或缺失 `404`。标准 JSON 错误 envelope 使用 `error` 和稳定 `code`。预期错误包括：输入/未知字段 `400`、认证 proof 无法与数据库身份绑定 `401`、未认证或无发布权 `403`、错误方法 `405`、不接受 JSON 响应 `406`、写入媒体类型错误 `415`、typed 业务校验失败 `422`、CAS/目录或时钟冲突 `409`、来源或精确证据不可用 `503`。真实 HTTP 组件已确认匿名 Session 请求返回 `403`；`401` 是身份 proof 无法绑定时的业务异常合同，两者应区别处理。

最新定向 Native 结果为 **81 项：75 项 serializer/presenter/view 等直接单元测试，另有 6 项通过 Django APIClient 执行的真实 SessionAuthentication、CSRF 与 API 组件旅程**。这 6 项验证 capture/preview/confirm/current 的 HTTP 边界，不是浏览器或 TUI 测试；response stream closed 断言只针对响应对象，不代表客户端 session pool 已关闭。独立暂存源码导出另有 485 passed / 27 PostgreSQL-only skipped；这些组合重叠，不能累计为唯一用例。类型、风格、覆盖、架构与生成投影门禁已通过，完整证据见阶段检查点。生产部署验收仍 pending。本文未执行真实 Provider 请求、权限授予、catalog seed、生产发布、部署或实盘验证。

## 工作台的服务端预览交接

新增工作台入口复用上述真实 Session、CSRF 和发布 owner，不要求用户回填底层 snapshot/CAS JSON。四个新路径均以 `/api/data-center/exchange-calendars/workbench/` 为前缀：

| 方法与后缀 | 输入 | 结果 |
| --- | --- | --- |
| GET `scope/` | 不接受 query | 唯一配置概览，或稳定 blocked reason；秘密和 Provider runtime 明确未检查 |
| GET `current/` | 仅一个显式 exchange | 按唯一配置 dataset 读取 exact current，或配置 blocked / current not_found |
| POST `prepare/` | exchange、coverage_start、coverage_end | 采集和预览成功返回 201；安全可见摘要与专用机器交接分开 |
| POST `confirm/` | 仅 confirmation_token | owner 重验原源/权限/窗口/CAS；首次 201，forward 或 exact retry 200 |

prepare 中采集和预览分别由既有 owner 拥有自己的 default 事务，不构成跨步骤原子事务；采集后预览或密钥不可用仍可能保留源快照。响应专用顶层 continuation 包含 action_key=data-center.calendar-workbench-confirm、input.confirmation_token 与 expires_at，不能放入可见表格、调试区、审计结果、URL 或持久浏览器存储。该交接不代表授权或一次性消费，确认仍由当前 Session 与发布权限重验。服务端令牌绑定 actor/session、完整原 intent、first_seen 与原合同 TTL，不因重试续期。密钥更换须清缓存或重启，旧令牌失效后须重新准备。

GET current 不要求发布权限，只接受一个 exchange，拒绝重复值及客户端指定 dataset、actor、alias 或 as_of。配置 selector 与 exact-current owner 分别拥有外层事务，不宣称两次读取是同一跨读快照。新配置 TTL 不重算旧 publication 的 response_expires_at；缺 current 不读取旧 history 冒充 current。上游观测时间未知仍为 null，所有成功日历参考仍不可用于交易或投资决策。原显式 dataset current 路径保持可用。

这些是 HTTP 合同；通用 TUI 交接、专用 screen 接线、实际浏览器完成主任务和真实供应商须各自验收，不能从路由可解析推导已完成。
