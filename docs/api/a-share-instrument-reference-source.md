# 证券名录来源与精确审计合同

本入口保留供应商证券身份及上市生命周期原文，用于后续不可变事实与正式发布建设。它不更新 AssetMaster，不迁移旧消费者，也不提供当前可交易性判断。

## 显式来源范围

`InstrumentReferenceProviderContract` 要求调用方给出合同身份、版本、供应商、dataset、字段顺序、交易所范围和上市状态范围。当前协议明确请求 `stock_basic` 的 `ts_code/name/exchange/market/list_status/list_date/delist_date` 七个字段，每个 exchange × list_status 组合分别调用一次。响应的字段结构、行范围、完整代码后缀及日期均须校验。

交易所与代码后缀使用调用方提供的版本化 `InstrumentReferenceExchangeSuffixCrosswalk`。完整代码参与匹配，不靠代码前缀推断交易所，也不把供应商 market 标签自动转换成执行规则的 board。合同及 crosswalk 分别保留规范化内容摘要；测试里的范围和映射仅是显式夹具，没有初始化生产业务配置。

Tushare 捕获按精确 ProviderConfig 读取 `extra_config.tushare_request_mode` 并传给统一运行设置 resolver。显式受支持模式优先于全局模式；未配置或空白值保留 resolver 的既有全局回退，显式不支持的值或非字符串值在创建客户端前拒绝，不会偷偷切到全局合法模式。该项只决定请求传输路径，不改变 Provider 身份或配置/凭据存储。

[Tushare 股票列表文档](https://tushare.pro/document/2?doc_id=25) 中的上市状态是名录维度；它不能证明盘中停牌、涨跌停、ST、可买卖股份或实时可成交性。[历史备用列表](https://tushare.pro/document/2?doc_id=262) 是另一个 endpoint，当前 `stock_basic` 来源合同不据此宣称具备历史全量证券主数据或 PIT 能力。

## 每次响应的证据

源适配器只解析实际 HTTP 捕获后留存的 RawPayload，读取时验证精确 payload 身份、摘要、请求参数、响应 schema 和范围。返回的 DataFrame 内容不能代替原件。脱敏规则及 body hash 含义沿用[供应商响应留档合同](a-share-provider-response-retention.md)。

调用方须传入所属任务真实的 `run_id` 和 `ingested_run_id`，不能让适配器生成 UUID 冒充所属任务。适配器为每次实际调用生成单独 occurrence UUID，用于关联这一请求与响应。

Fenced capture 的内存响应暂存和正式 RawPayload 留存均传递不可变 capture request 的 `run_id`，新写入后的回读必须保留该身份。已有空 run 的历史进度凭据可继续读取；非空 run 必须等于当前请求所属 run。不能因为原件自身摘要一致就接受另一运行的凭据，也不能把新留存退化为空 run。此绑定不改写旧原件、不授予来源资格，也不把采集运行身份解释为供应商时钟。

`DjangoInstrumentReferenceRawAuditOccurrenceWriter` 经既有 RawAudit repository 写入，再按数据库生成的精确主键回读，核对内容摘要、请求、run、原件及 occurrence 范围。当前只接受显式 `django:default` repository；不把一个默认库的审计声称为其他 alias 的证据。RawAudit 使用既有合法状态 `ok`，不新增审计表。

相同 body 可以重复出现，RawPayload 去重不代表请求发生了同一次。每次实际调用仍有不同 RawAudit ID；不按“最新相同 body”寻找审计。候选要求 occurrence ID 和 RawAudit ID 唯一、范围恰好完整，并逐 occurrence 核对记录数。零行响应仍可记录原始调用证据；这不放宽通用正式 publication manifest 的非空成员要求。

## 时间与读取边界

`response_completed_at` 仅表示本系统收到完整响应的 UTC 时间。上市与退市日期保留原字符串及 `date` 解释，不转换为供应商披露时刻。`stock_basic` 没有上游观测或披露时间字段，因此 candidate 和 record 的 `source_observed_at/source_available_at` 均为 None。

候选固定返回：

```text
must_not_use_for_decision = true
must_not_execute         = true
blocked_reason           = INSTRUMENT_REFERENCE_SOURCE_ONLY_NOT_DECISION_READY
```

后续仍需不可变证券事实、独立知识时点、规范化身份与板块映射、正式发布及真实 dataset/exchange 权限。名录来源合同的通过不能替代这些验收，也不能用本地抓取时刻补造上游时钟。

## 独立 Owner 主数据维护

`maintain_asset_active_scope` 是独立的显式维护命令，来源采集本身仍不更新主数据。
它只接受一个外部 SHA-256 固定的五行计划：完整证券代码、主键、当前退市日期、
`updated_at`、全部保留字段的摘要，以及 SSE×D、SZSE×D 两次既有 RawAudit/RawPayload
的精确身份。计划不含自己的文件哈希；`--plan-sha256` 固定实际 UTF-8 文件字节。
代码不会根据 L 名录缺行推断退市，也不自动停用其他证券。

命令通过 `--owner` 与 `--password-fd` 对真实 Django 用户认证；密码只从编号至少为 3
的管道或 socket 读取，不接受命令行密码、环境变量密码或普通密码文件。用户须具有
`data_center.change_assetmastermodel`，并通过现有 DATA-02 审计权限预检及提交前重验。
这次操作固定起始的真实权限快照，后续任何快照变化均阻断；既有长期任务的等价续期规则不变。

在默认 PostgreSQL 库的单个外层事务中，命令按主键顺序锁定五行、重放两份原文并核对
完整前像，只改变 `is_active=False`、来源声称的 `delist_date` 和本地维护 `updated_at`。
事务必须为 READ COMMITTED，以便后续重验能读取新提交的权限撤销；其他隔离级别在 DML 前拒绝。
同一事务写入 USER/SystemAudit 系统操作事件及 Outbox；任何验证或审计失败均回滚。
重复执行仅在原事件、Outbox、来源、权限和当前五行状态全部精确匹配时返回 `noop`。

`is_active=False` 会影响所有按活跃状态过滤主数据的消费者。名称、别名、上市日期、
行业、币种、股本、扩展字段、持仓与历史数据均不在维护范围。该操作记录 Owner 的
活跃范围维护，不授予法律退市、时点证券事实或可交易性资格；来源的未知上游时钟、
`must_not_use_for_decision`、`must_not_execute` 保持原义。

本命令不执行迁移或供应商请求。实际执行前仍需其自身精确代码版本的开发/CI检查、
旧生产 schema 隔离演练、有效备份和真实权限；应用发布候选的 S6、部署与退出门另行完成。
