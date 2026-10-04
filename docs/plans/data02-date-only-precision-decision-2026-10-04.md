# DATA-02 财报 source-time date-only 精度决策记录（2026-10-04 Owner 决策）

> 状态：Owner 已正式拍板接受 date-only 精度。本记录是
> `governance/financial_source_time_match_contracts.json` owner approval 的审批
> receipt 原件；`approval.receipt_sha256` 绑定本文件提交后 git blob 的 SHA-256。
> 本决策只解除“日期粒度是否可登记”的疑问，不代表 DATA-02 生产退出门通过，
> 不晋级任何生产 publication 或决策读取，不授权任何历史回填。

## 1. Owner 决策（2026-10-04）

Owner 正式拍板：**接受 date-only 精度**，规则为：

1. `announced_at` = 公告日 T 00:00 Asia/Shanghai。语义为“公告日历日起点，精度
   date”，是日历日的规范化投影，**不是**供应商披露的精确时刻。
2. `available_at` = T+1 00:00 Asia/Shanghai（= T 16:00 UTC），即公告次日生效。
   系统决策 cutoff 是决策日上海 00:00（见
   `apps/data_center/domain/market_time.py:51-54` 的
   `cn_market_date_start_utc` 与
   `apps/data_center/application/public_published_queries.py:530-548` 的
   `get_financial_facts_for_decision`），因此 T 日公告的财报首次对 T+1 盘前
   决策可见，天然等价 T+1 交易日生效，且不需要交易日历。
3. 历史 441,944 行中已有的合成午夜值保持 degraded 标记，不得借新合约洗白；
   本决策不改写任何历史行。
4. CNINFO 精确时刻增强**明确推迟**到盘中决策端口出现时再评估（见第 3 节）。
5. 备选增强路线记录为 Tushare `anns_d`（见第 4 节）。

## 2. 决策依据与事实基础

- 2026-09-13 本地单标的真实原始响应样本（整改方案第 11 节，
  [封存元数据](../deployment/data02-financial-single-source-raw-sample-2026-09-13.json)）：
  AKShare/EastMoney `RPT_F10_FINANCE_MAINFINADATA` 响应 388,061 字节、SHA-256
  `6a56f4ccbaa203e689f62a1f14033ed8a61a0c0a842afda03a6c27e5b1054578`，122 行
  `SECUCODE` 均为 `000001.SZ`；`NOTICE_DATE` 为 119 个无时区午夜文本加 3 个
  `null`，`REPORT_DATE` 122 个值均为无时区午夜文本；**无行级 record ID**。
  本次工作线在同一台机器上对私有保留原件做了只读复核：字节数与 SHA-256 与封存
  一致；`SECUCODE+REPORT_DATE+NOTICE_DATE` 组合键在 122 行内无重复；3 个
  `NOTICE_DATE=null` 行对应 1990-1992 年报告期。
- 官方文档核验（整改方案第 9 节）：Tushare `fina_indicator` 的 `ann_date`、
  AKShare 该接口的 `NOTICE_DATE` 均为日期粒度，均无日内时间或时区契约。
- CNINFO 官方单文档核验（整改方案第 12 节）：正式公告日期为日期粒度，没有可
  直接映射到 UTC 的精确瞬时。
- 决策消费端已经是 date-only 端口：`get_financial_facts_for_decision` 的知识
  截止为决策日上海 00:00 的精确 UTC 瞬间，并要求 `announced_at`、
  `available_at` 非空且不晚于截止。date-only 推导值与该端口的语义完全对齐：
  T 日公告的 `available_at = T+1 00:00 Asia/Shanghai` 恰好在 T+1 决策 cutoff
  处变为可见（边界相等允许），在 T 日及更早的决策中不可见。

## 3. 推迟 CNINFO 精确时刻增强的决定与理由

决定：CNINFO 精确时刻增强推迟到盘中决策端口出现时再评估。理由：

1. 当前唯一的决策消费端口是日级盘前 cutoff；在其之下，精确到分钟/秒的公告
   时刻与 date-only 推导值产生完全相同的决策可见性，精确时刻的当前边际价值
   为零。
2. 共享 verifier 的同-provider 不变量
   （`apps/data_center/application/financial_source_time_verifier.py:115-118`
   要求 source-time 原件与财务原件同 provider，
   `:169-180` 要求两条 audit link 解析出相同正整数 provider row id）阻挡
   CNINFO 跨源证据链：CNINFO 与财务行 provider（akshare/tushare）不同，
   接入 CNINFO 需要修改该不变量及其全部回归，属于独立治理变更。
3. 整改方案第 12 节已确认：CNINFO 文档句柄与 EastMoney 财务行之间没有共同、
   可验证的 row-level 绑定，公告编号不能单独填充财务行的 `source_record_id`。

## 4. 备选增强路线（记录，不实施）

Tushare `anns_d`：与财务行同属 tushare provider，自带 `rec_time` 精确时刻，
不触动 verifier 同-provider 不变量。整改方案第 28 节已记录其缺口：`anns_d`
公开字段没有财务 `end_date` 关系，在 provider contract 明确字段映射、唯一键、
时区和 availability 语义之前，禁止按 `ts_code+ann_date` 猜测关联。该路线仅在
盘中决策端口出现且完成上述契约核验后再评估。

## 5. 无行级 ID 的诚实处理

AKShare 该接口无行级 record ID（样本复核确认）。本决策批准以
`SECUCODE+REPORT_DATE+NOTICE_DATE` 组合键作为 source row identity 的**显式
推导规则**，在 match contract 中以 `composite:` 前缀声明，不伪装成 provider
原生字段；同一公告日同报告期出现多行（如更正公告）时 matcher 必须
fail-closed（`matched_row_count != 1` 拒绝）。同理，`announced_at` /
`available_at` 不是 provider 字段，在 contract 中以 `derived:` 前缀声明其
推导规则（公告日上海日界起点 / 次日上海日界起点）。

## 6. 本决策不解除的门

- DATA-02 保持 `awaiting_production`：生产回填仍需 current authority、明确
  生产写授权、真实 retained 双原件与 RawAudit、四 Publication 对账。
- 历史 441,944 行的 announced/available/raw 缺口不因本决策修复；既有合成午夜
  值保持 degraded。
- date-only witness 只在新抓取且双原件证据链完整时产生；缺证据范围继续
  `must_not_use_for_decision`。
