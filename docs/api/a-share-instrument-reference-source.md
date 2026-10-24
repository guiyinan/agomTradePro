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
