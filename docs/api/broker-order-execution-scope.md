# 具体订单的复核、签认与撤回

实盘账户所有者使用自己的 Django 会话，通过带 CSRF 令牌的 JSON POST 操作。服务器核对当前账户归属、Broker 审批角色、计划中的具体订单、Portfolio 基准，以及本人对该账户 Research 材料的读取权限。隔离演练开关和订单执行检查另行生效。

以下路径均相对于 `/api/broker-execution/orders/{client_order_id}/execution-scope/`。

| 操作 | 路径 | 请求字段 |
| --- | --- | --- |
| 查看待签订单和材料 | `preview/` | `account_id`，可附 `research_material` |
| 签认同一份复核结果 | `sign/` | `account_id`、`expected_review_hash`，如预览指定了材料，提交相同的 `research_material` |
| 撤回既有签认 | `revoke/` | `account_id`、原签认的 `expected_scope_hash` |

1. 指定已有 Research 材料时，提供 `owner`、`artifact_type`、`artifact_id`、`artifact_version`、`content_hash` 和 `envelope_content_hash` 六个字段。材料的来源链必须包含这笔订单、它的确切计划或计划审批凭据之一，所有者、类型、版本与哈希均须匹配。省略选择器时，服务器仅尝试读取该订单专属的既有材料。
2. 在预览结果核对账户、代理、标的、买卖方向、数量、价格、预计金额和截止时间，再核对计划版本及订单序号、基准批准件、Research 材料的适用范围、样本、阻断原因与关联来源。Research 的权限为 `display_only`，单笔授权由账户所有者签认。预览返回的 `expected_review_hash` 同时覆盖经济项、账户、材料及有效期。
3. 签认成功后留存 `execution_scope_id`、`execution_scope_version`、`execution_scope_hash` 及 `valid_until`。若返回 409，请重新预览并核对当前材料。四个订单节点重新读取初次签认的精确材料和当前权限。撤回使用原签认的哈希，可在上游材料已到期时操作。

格式错误返回 400，会话或权限不足返回 403，材料无法验证、内容已变更或签发关闭返回 409。错误响应不会给出其他账户的订单或材料内容。


### 追溯签认订单

按账户与 `client_order_id` 查询执行审计。创建、审批、领取与提交确认的记录包含状态机版本、服务器记录时间和同一组 `authority_pin`。其中 `order_version` 是签认经济项的版本。券商回报按事件 ID 重放，成交另存券商成交编号。无法取得券商源时间时，`broker_source_at` 保留为空，`clock_source` 标明实际来源。

`order_reconciled` 记录同一订单与 Agent 快照逐项核对后的结果，包括快照来源、成交清单、状态版本、签发引用及对账运行号。`scope=order_and_fills` 表示核对该笔订单与成交。账户级结果应读取 `run_status` 和对应运行的现金、持仓等差异；真实账户现金依据不足时仍需复核。
