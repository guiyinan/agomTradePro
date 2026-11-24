# Portfolio 基准审批

### 发布日结估值

1. 账户所有者在首次估值截止前，通过已登录的会话向 `/api/portfolio/benchmark-valuations/epochs/` 发起 POST，提交 `account_namespace`、`account_id`、已激活的 `definition_id` 和 `policy_id`。切换估值期时还需提交前一期的 `previous_epoch`。
2. 按基准约定的收盘时点准备两份独立原件。托管日结原账载明账户、币种、现金、逐券持仓及当日流水覆盖。QMT Agent 通过已认证的快照接口独立上报实际账户、可用及冻结现金、逐券数量、市值与采集时点。
3. 向 `/api/portfolio/benchmark-valuations/epochs/{epoch_id}/close/` 发起 multipart POST。字段为 `broker_snapshot_id`、`certify_complete=true` 和文件 `statement`。ZIP 上限为 2,000,000 字节，内含托管原文 `source.csv` 和逐行引用原文哈希及行号的 `day.csv`。服务器核对两份原件、官方收盘行情和估值规则后返回 `valuation_id`、`version`、`content_hash` 和观测时间。
4. 从第二个估值日起，ZIP 还须包含 `action-coverage.json`。已批准的方法引用锁定来源版本、公钥及内容哈希。来源以 Ed25519 签名明确证明该证券从前次截止至本次截止的期间内生效事件数为零。必须提供完整覆盖、来源签发时间及修订标识。缺证、换钥、换券或期间不匹配会返回 409。
5. 发现托管原文应撤回时，账户所有者向 `/api/portfolio/benchmark-valuations/epochs/{epoch_id}/statements/revoke/` 提交 `observation_date` 和 `original_hash`。`original_hash` 取首次上传的完整 ZIP 字节的 SHA-256。依赖该原件的估值与审批在重读时失效，撤回事件保留在账本。

本入口支持人民币单只股票、权重 100% 的基准。费用取自批准的方法，按其舍入规则核对。遇到超出此范围的持仓、外汇折算、非零公司行动或缺失行情，日结停止，操作员可根据响应核查原件。

### 双人审批与撤销

正式审批使用已登录工作人员的 Django 会话，所有 POST 均校验 CSRF。操作员须为有效实盘账户所有者或有该账户管理权限的超级管理员，同时满足已批准、有效 staff 和策略写入角色。提交人与批准人必须是两个不同的真实用户。

| 操作 | 路径 | JSON 请求字段 |
| --- | --- | --- |
| 提交 | `POST /api/portfolio/benchmark-approvals/` | `request_id`、`valuation_id`、`valuation_version` |
| 复核来源 | `GET /api/portfolio/benchmark-approvals/{request_id}/` | 无 |
| 独立批准 | `POST /api/portfolio/benchmark-approvals/{request_id}/approve/` | `expected_content_hash` 为复核结果的 `submission_hash` |
| 撤销 | `POST /api/portfolio/benchmark-approvals/{request_id}/revoke/` | `expected_content_hash` 为已批准事件的 `content_hash` |

日结发布成功后，提交者将返回的估值 ID 及版本作为选择器，并为本次申请生成 UUID。独立批准人打开复核路径，核对 `source.valuation` 内的估值内容哈希、观察日、生效时段、定义、方法激活和计划策略激活，以及 `source` 中的 Account 身份与所有权策略。确认状态为 `pending` 后，使用该次复核的提交哈希批准。响应包含申请 UUID、审批版本、审批内容哈希和有效截止时间。

授权消费者可按完整账户、所有者和租户范围选取当前审批。重验时须同时精确匹配原审批 UUID、版本和内容哈希。撤销或更新批准后，原审批不能回退为有效。只提交新的草案时，现有审批仍须通过实时源、签发人权限和有效期复核。
