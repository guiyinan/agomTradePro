# VPS 全市场行情和 Alpha 恢复

状态：数据补齐与代码修复已部署；持续自动发布尚被审计身份阻断，六份账户手动推理全部验收完成，下一自然周期未验收。

## 根因与修复

- 原有效范围 5,533 只中 5,196 只缺未复权参考；原定时行情仅覆盖两个探针。增加独立全市场任务，冻结范围、按批写事实、全部成功才发布，财报仍独立校验。
- 主数据遗漏 31 只新上市股票，并错误停用 302132.SZ。按真实 stock_basic 恢复为 5,565 只；同步器保留合法交易所后缀，未知裸代码从主数据解析，不猜测新板块规则。
- 腾讯快照主板/北交所以手、科创板以股返回，统一复用数据库单位规则。两只北交所差异由真实大宗交易对账解释，未放宽 1% 校验。
- 全市场历史改为真实交易日历逐日批取，最多 4 个并发请求链；检测截断、日期与重复因子，保留逐股 failover 和一致性校验。
- 构建成功后原子记录绑定日期/完整范围的停牌证据，只排除已验证停牌。共享 Qlib 目录增加跨进程读写锁，避免推理读取半写入特征。
- 审计快照原来对含 secret reference 的完整 projection 求哈希，却仅持久化公开 projection。改为对持久化内容求哈希；完整 revision 哈希保留。生产只新增 v17，不改旧快照或授权。
- Alpha 页面独立显示全市场发布失败；新评分成功不能清除发布错误。

## 数据结果

目标日 2026-09-18，不以周六请求时间替换观测时间。

| 项目 | 结果 |
| --- | --- |
| 有效股票全集 | 5,565 |
| 当日报价 / 估值 | 各 5,565 |
| 当日可交易日线 / 特征 | 5,553 |
| 源记录证实全天停牌 | 12 |
| 特征文件缺失 / 异常复权因子 | 0 / 0 |
| 三类 Publication 成员合计 | 16,695 |

停牌：000016.SZ、002731.SZ、301139.SZ、600301.SH、600825.SH、601059.SH、601198.SH、601238.SH、601995.SH、603400.SH、605303.SH、688496.SH。保留真实末次交易日 08-28 至 09-14。

09-19 12:07:18 UTC 全集发布，精确成员和源内容哈希校验通过：

- 报价：3eaed0e5-a907-5c82-b641-8d0d2b712c87
- 日线：51023424-e9b0-590b-9d93-1606be338887
- 估值：fc52e7dc-5254-5445-9a81-3d287fe33111

周末报价仍按配置 4 小时过期；全市场日线 gate 保留最旧停牌成员的 stale；单股读取已修复为独立评估自身时效，并继续验证全 Publication 完整性；财报精确 available_at 与覆盖尚未修复。因此不能标记全部决策数据可用或所有推荐可执行。

## 推理与自动计划

- 通用 CSI300 297 个有限评分已验证，目标/实际日期均 09-18，无 fallback；任务 f6656f01-bda0-4feb-814a-642ef99e3737。
- 全市场特征原 5,533 与新增 32 均构建完成，并写入完整范围停牌证据。
- 账户手动父任务 03a684b0-24cc-43f7-9bf3-ab79b028807b 的 6 个真实子任务已全部验收成功，每个 scope 5,565 只、可推理 5,553 只；缓存、有限评分、真实日期、无 fallback 和 12 个停牌 metadata 均已核验。
- 工作日 16:30 Asia/Shanghai 的 full-market-current-publications 已配置 enabled；17:30 通用、17:40 账户、18:00–18:50 恢复计划保留。无有效审计身份时零写入返回 blocked。
- 下次自然周期 2026-09-21。heartbeat alpha 回查自然父子任务和源日期；手动恢复不作自然执行证据。

## 未完成与所需输入

1. v17 哈希已验证，但 audit mode=off、outbox=false、authority selector 缺失。临时管理员授权均不适用于长期任务。已询问用户服务账号及账户/租户范围；未获绑定信息前不伪造权限、延长旧身份或使用空 writer。
2. 下一自然周期尚未发生，需生产回执验收。
3. 财报精确时间/覆盖、候选可执行性仍是独立未完成项；全局日线 gate 的 stale 是全集真实状态，不能替代单股时效。

## 验证与部署

- 模型历史/批取/停牌/Publication/builder 回归通过；最新 27 个锁与预测范围、13 个页面提示、20 个发布任务、12 个配置控制平面、4 个计划、7 个全集归一测试通过。
- 增量 mypy、全量 mypy 零债务门禁、Ruff、Celery 92 任务契约、current 62 数据面契约、Web→TUI inventory 通过。
- hot-update code-only，无整库恢复或依赖更换。核心 11 文件在 web/worker/beat SHA-256 一致并重启；后续提示/计划入口/全集归一单独同步，活动预测期间不重启 worker。
- 核心备份 /opt/agomtradepro/manual-file-backups/20260919201557；提示/计划 20260919202438；全集归一 20260919202935。web 重启后 HTTPS health=200，容器均 running。
- Linux 锁实测：共享读取可共存；读取期间独占构建被阻止，释放后可独占。

## 证据与回滚

本轮主要代码文件：

- `apps/data_center/application/{tasks,market_publication_refresh,model_market_data,query_services}.py`
- `apps/data_center/domain/model_market_data.py`、`apps/data_center/composition.py`
- `apps/data_center/infrastructure/{tushare_model_market_source,a_share_universe_sync}.py`、`apps/data_center/infrastructure/gateways/tencent_gateway.py`
- `apps/data_center/management/commands/setup_full_market_publications.py`
- `apps/alpha/infrastructure/{qlib_builder,qlib_prediction_runtime,qlib_scope_evidence,qlib_runtime_lock}.py`
- `apps/config_center/application/runtime_config.py`、`apps/dashboard/application/alpha_refresh_notice.py`

本轮 Python 热更以 SHA-256 校验 release 与容器副本；模板/static marker 不适用本轮新增修复。

生产 /app/data/backups/alpha-unit-repair-20260919 保存原始数据、修复前 gzip、上市/停牌、构建、发布与任务证据。本地 backups/vps-postgres/market-recovery-evidence-20260919/verified-manifest.json 记录下载 SHA-256。

代码按 manual-file-backups 回退，数据按 ingestion UUID/归档追溯，禁止整库覆盖用户新数据。既有数据库/Qlib 备份保留。首轮 Tencent append-only 424 标的后因 HTTP 501 停止，主动停止退出 143 未计成功。

## 最后核验补充

- 首个账户子任务 c865d514-f938-4de0-aa0a-87d7e820909b 于 12:39:58 UTC 写入 available 缓存：30 个有限评分，日期 09-18，无 fallback，requested=5565/eligible=5553，12 只停牌 metadata 完整。其余 5 个尚未验收。
- 全市场发布任务还加入目标日原始日线刷新与逐股校验，禁止仅更新快照后重新发布旧日线；缺日线的新股票先补数据再做最终 Publication 完整性校验。代码备份 20260919203843，已同步三容器。
- 12:40 后已对 worker 请求 warm shutdown；当时第二个账户子任务 622acfd3-c989-4a4b-b06c-561119602921 运行中。等待其完成后由 Docker unless-stopped 重启加载最后代码，必须后续确认重启与剩余队列执行，不强制中断。
- heartbeat alpha 暂每 30 分钟核验这些后台结果，六个手动子任务完成后恢复工作日 18:55 的自然周期核验。

- 真实同步执行发布入口并连接 Task Monitor 后，任务 7deeb017-3140-46d4-9c81-c149961562b1 发布 audit_runtime_disabled、stored=0；Alpha 读取持久化记录并渲染“行情自动发布异常”提示已验证。

- 单股日线时效与全局完整性新增回归共 22 个通过；增量 mypy、全量零债务门禁通过。测试同时证明正常股不受他股停牌日期拖累、停牌股自身 stale、缺失成员阻断、任何成员哈希被改则全体阻断。

- 单股时效补丁备份 20260919205112，web/worker/beat 文件哈希一致，HTTPS health=200。VPS 实读 300750.SZ 成交量 38,071,300 股、688012.SH 为 20,605,046 股、302132.SZ 为 6,178,849 股，均 fresh 且未被单股日线 gate 阻断；000016.SZ 仍 canonical_publication_stale、零返回行。单次完整发布校验约 1.6–2.7 秒。整批 30 个候选实际 context 路径已验证：30/30 有成交量，30/30 因财报 publication_policy_changed 保持决策阻断；冷读耗时 141.12 秒，批量读取性能仍需优化。

- 第二个账户子任务 622acfd3-c989-4a4b-b06c-561119602921 于 12:59:31 UTC 成功写入 30 个有限评分，实际/目标日均 09-18，无 fallback；两份缓存均保留 5,553/5,565 与 12 个停牌证据。其余 4 份仍需后台验收。

- Worker 已于 12:59:37 UTC 完成自动重启（restart count=1，running），随后继续实际子任务 a1e6e12e-0c79-4e0f-bd7f-24f4d58e8b0b。最后日线发布/单股时效补丁均已同步，核心配置及查询由重启后进程加载。


## 根因扩展修复（本轮最新结论）

- 批量读取根因：旧股票上下文对每只股票、每个数据集都重新验证全市场成员和事实哈希，
  且将全部成员主键重复传入单股查询。新增 Data Center 批量公开入口，每个数据集在一个
  一致性快照内全量核验一次，再按股票限定成员主键。证明不跨调用缓存；任何非请求股票
  的成员篡改仍阻断全部返回；停牌 freshness 不影响正常股票。
- VPS 相同 30 个候选的真实 Dashboard context 读取从 141.12 秒降至 9.06 秒；
  返回 30/30，成交量可用 30/30，财报规则不匹配仍阻断 30/30。证据为
  `full-market-alpha-context-batch-optimized.json`，修复前证据保持不变。
- 主数据同步原来用只有代码和名称的新 AssetMaster 覆盖已有字段。现在只更新名称、
  启用状态及来源标记，保留上市日期、行业、股本及既有来源证据，避免下次同步再丢失。
- Alpha 根据具体 publication gate 区分行情、财报、估值错误，即使成交量正常也显示
  财报阻断；未知错误使用安全文案，不向页面透传原始异常。
- 财报只读盘点：AKShare 487,624 行、5,535 个标的，105,606 行有旧 available_at，
  announced_at 有值为 0。现存 financial publication 只有 80 个成员，旧规则为
  `1.0:1.0`，活动规则要求真实来源时间及响应证据。因此不能把旧 available_at 当作
  已恢复的来源证明，也不能改 policy_version 冒充通过。证据为
  `full-market-financial-root-causes.json`。
- 定向回归 51 项通过；页面分类提示新增后 17 项页面/流动性回归通过。
  增量 mypy、全量零债务门禁、Ruff、Black、current 62 数据面契约通过。
- 五个批量/主数据文件 hot-update code-only 备份 `20260919211855`；web 已重启，
  HTTPS health=200，web/worker/beat 五文件 SHA-256 一致。对 worker 再次请求
  warm shutdown，活动任务为 `2d09331b-c878-45ac-a2d1-2fea56402e71`，需其结束后
  确认重启；不强制终止推理。
- 三个账户 142、141、139 已成功写入 available 缓存，各 30 个有限评分，目标/实际
  日期均 09-18。其余三份不能计作成功；Celery backend 的 PENDING 不代表任务未运行，
  应结合 Task Monitor 和 worker active 确认。证据为 `full-market-scoped-compact.json`。

未完成项保持明确：长期审计服务身份及账户/租户范围尚无用户绑定输入；财报没有真实精确
来源证据；剩余账户任务及 09-21 自然周期仍需生产回执。上述性能与提示修复不代表这些
独立阻断已恢复。


页面分类提示另行备份 `20260919212409`，web 重启后 HTTPS health=200；包含该提示的
六个文件已在 web/worker/beat 完成 SHA-256 一致性校验。最终增量 mypy 与全量门禁为
0 新增错误、0 存量错误；本次仅热更新代码，数据库未做整库恢复。

VPS 当前候选上下文的提示路径也已实测：300750.SZ 成交量可用，阻断码为
`publication_policy_changed`，用户文案为“财报发布规则已变更，需重新校验并发布，当前候选仅供研究。”
证据 `full-market-financial-visible-notice.json`。历史详情的仅名称读取不用于当前候选验收。


## 定时回查（2026-09-19 14:01 UTC / 北京时间 22:01）

- 手动恢复账户 142、141、140、139 四份已同时满足 Celery SUCCESS、Task Monitor
  success、业务 outcome=success、available 缓存；每份 30 个有限评分，目标/实际日期
  均为 2026-09-18，未调整交易日、未降级复用。四份缓存均保留 requested=5565、
  eligible=5553、12 个停牌标的及其真实末次交易日。
- 新完成账户 140 的任务 `2d09331b-c878-45ac-a2d1-2fea56402e71` 于
  13:41:50 UTC 成功。Worker 随后于 13:41:56.004 UTC 自动重启，restart count=2、
  running；六个本轮修复文件在 web/worker/beat 的 SHA-256 均与本地一致。
- 账户 135 的任务 `d6c99b9b-2608-4770-995f-5d70f69bb60f` 于 13:42:15 UTC
  开始，Task Monitor=started 且 worker active 确认；账户 138 的任务
  `2b3883c0-6bd8-49d4-ad7a-0c8a4c085ebd` 位于 worker reserved。
  两者尚无目标日缓存，不计为成功。
- 手动全市场发布验证任务 `09e717e4-ecb0-4833-b6d8-c59a78c89cc4` 同时仍在
  reserved，尚未发生执行回执；本次未重发任务、未重启容器、未更改生产数据或授权。
- 已更新 `full-market-scoped-compact.json`，新增 `full-market-heartbeat-runtime.json`，
  下载证据时校验远端/本地 SHA-256，并更新 verified-manifest.json。
- 继续每 30 分钟核验；未满足六份终态条件，尚不切换到工作日 18:55。
  09-21 自然周期仍未发生；先前明确的审计身份和财报来源证据阻断未被改为恢复。


## 手动恢复最终验收（2026-09-19 14:35 UTC / 北京时间 22:35）

六个账户 142、141、140、139、138、135 均已完成：Celery SUCCESS、Task Monitor
success、业务 outcome=success、available 缓存四项一致。每份 30 个有限评分，共 180 条
账户评分记录，目标/实际日期均为 2026-09-18；无 scope fallback、无交易日调整。
每份证据均包含 requested=5565、eligible=5553，以及 12 个停牌代码和真实末次交易日。
最终归档脚本逐项断言通过，产物 `full-market-manual-inference-final.json` 明确标记
origin=manual_recovery、natural_cycle_verified=false。

最后两份结果：账户 135 于 14:01:45 UTC 完成；账户 138 于 14:24:00 UTC 完成。
14:34 UTC 回查 worker active/reserved 均为空，容器保持 running，最后重启时间仍为
13:41:56 UTC、restart count=2。没有为了验收追加预测、强制重启或修改生产授权。

先前排队的真实全市场发布验证任务 `09e717e4-ecb0-4833-b6d8-c59a78c89cc4` 也已执行，
但业务结果为 blocked、stored=0、system_audit_audit_runtime_disabled。
Celery 自身 SUCCESS 不计作发布成功。Alpha 页面仍显示“行情自动发布异常”，
告警内容与 role=alert 渲染均通过；这是既知审计配置阻断的真实异步回执。
证据为 `full-market-audit-queued-task-verification.json`。

六份手动任务的终态条件已满足，heartbeat alpha 已改为工作日北京时间 18:55，
下一次为 2026-09-21，核验自然发布、通用/账户推理及恢复周期。若自然任务到时仍在运行，
继续安排临时后续回查，不能将运行或排队当作成功。审计身份、财报来源证据及自然周期
验收仍未完成；本节只确认手动恢复，不改变全链路未恢复的结论。

本次回查只更新证据与文档；四份新增/更新证据下载均校验远端与本地 SHA-256，
verified-manifest.json 一并更新。没有生产代码变更，因此未重复执行代码回归测试。

## 自然周期核验（2026-09-21 19:23 北京时间）

- 16:30 全市场发布任务 `9660c46d-da00-4837-9613-81f0edad3cfa` 已进入终态，
  Task Monitor=failed，业务 outcome=blocked，`blocked_reason=system_audit_audit_runtime_disabled`，
  requested/succeeded/failed/stored 均为 0；因此没有把行情发布标记为已恢复。
- 17:30 通用 Alpha 父任务 `5a8750e6-7658-4c27-9f35-fba4b083562f` 与子任务
  `f86ac18b-a055-431c-96b4-d48354625c91` 均成功，`csi300` 的 09-21 缓存有 30 个有限评分。
- 17:40 账户父任务 `9f168f61-29d3-42a8-9816-b96b987b4707` 刷新目标日为 09-21，
  scope=6、全集 5,565、可推理 5,553、已证实停牌 12；六个子任务中账户 142、141 已成功写入
  30 个有限评分缓存，账户 140 仍由 Celery active 执行，账户 135、139、138 仍在 reserved。
  active/reserved 仅记录运行状态，不能计为成功；当前仅 3/6 账户缓存可验收。
- 本次自然周期仍未满足全市场发布、六个账户子任务和缓存证据的联合终态，
  `natural_cycle_verified` 保持 `false`。审计运行时身份阻断和财报来源证据缺口继续保留。

本次只读回查证据为 `backups/vps-postgres/market-recovery-evidence-20260919/full-market-natural-cycle-20260921.json`；
其 SHA-256 为 `4ff887eb7e13f5b05b1691c74e6cb3cc6313ee70eae821b0f3b1521d8cc12bd0`，
已加入 `verified-manifest.json`。未触发任务、重启容器、修改授权或写入生产数据。

## 自然周期核验（2026-09-22 19:09 北京时间）

- 16:30 全市场发布任务 `cb184cb2-d2d0-40a7-b58a-1d346b1ba65f` 已进入终态，
  Task Monitor=failed，业务 outcome=blocked，`blocked_reason=system_audit_audit_runtime_disabled`，
  requested/succeeded/failed/stored 均为 0；审计运行时阻断仍未恢复。
- 17:30 通用 Alpha 父任务 `f5ef6ebb-d3ba-4ac4-b7bc-bb6721f977aa` 与子任务
  `78a5793b-81f8-4736-a11c-bbdd9f4d69ed` 均成功，`csi300` 的 2026-09-22 缓存有
  30 个有限评分，目标日与实际日一致。
- 17:40 账户父任务连续三次终止为业务阻断：`aea06dd7-ec8d-467a-ad14-f3358ea85829`
  为 `model_market_adjustment_incompatible`，`41caa177-d584-4d53-9000-0011788af871`
  为 `tushare_daily_quota_exhausted`，`f49a7915-dff7-484c-a03f-a4c7e12bf405` 为
  `model_market_invalid`；每次均为 6 个 scope、全集 5,565、成功/写入为 0。
  随后重试 `344f348f-d04f-4ab3-9c44-bc7a899b36bb` 在回查时仍为 Celery active，不能计为成功，
  2026-09-22 没有账户 scope 缓存。
- 同时记录到三条配置路由的真实失败：DataHubCo RDS 出现 `TUSHARE_HTTP_502`/
  `MODEL_MARKET_INVALID`，Tushare Pro 出现 `TUSHARE_DAILY_QUOTA_EXHAUSTED`/连接超时，
  AKShare Public 出现 `MODEL_MARKET_ADJUSTMENT_INCOMPATIBLE`/连接错误；当前没有
  `equity.price.bar` 出口规则或可用 egress endpoint，因此不能把路由不可用误标为数据已恢复。

本次自然周期仍未满足全市场发布、通用 Alpha、六个账户子任务和缓存证据的联合终态；
`natural_cycle_verified` 保持 `false`，并保留审计身份及财报来源证据缺口。只读证据为
`backups/vps-postgres/market-recovery-evidence-20260919/full-market-natural-cycle-20260922.json`，
其 SHA-256 为 `ee73a8c80b1e0d7dc497bea46ea203965f68c79b89515dad99d256be2a37756b`，
已加入 `verified-manifest.json`。本次未触发任务、重启容器、修改授权或写入生产数据。

### 终态补充（2026-09-23 07:36 北京时间）

- 重试父任务 `344f348f-d04f-4ab3-9c44-bc7a899b36bb` 最终为
  `refresh_result.status=failed`、`error=SoftTimeLimitExceeded()`、`stock_count=5565`，
  但编排层仍将 6 个子任务排队，父任务因此记录为 `outcome=partial`、`success=true`、
  `stored=6`。这 6 个值只代表子任务已入队，不代表有缓存写入。
- 6 个子任务最终全部以 `model_market_scope_incomplete` 阻断，实际 `stored=0`。
  生产 Qlib 的 `scoped_portfolios.txt` 有 5,565 个标的，但最新日期仍为 2026-09-21；
  `build_evidence/2026-09-22.json` 只覆盖 300 个标的，不能证明账户全集在目标日有数据。
- 因此新增的代码整改顺序是：刷新结果只要是 `failed`/不完整就立即阻断，不再排子任务；
  行情源恢复后重新构建 5,565 个标的，并要求目标日、Qlib 特征、instrument 文件和
  build evidence 四者范围一致后才允许发布成功。

终态证据为 `backups/vps-postgres/market-recovery-evidence-20260919/full-market-natural-cycle-20260922-final.json`，
其 SHA-256 为 `101cc0fb3fbfb35d1a91b6ac80ed36453b0f67dfc18ad3fb0a12462c2852a79d`，
已加入 `verified-manifest.json`。

## 自然周期核验（2026-09-23 19:13 北京时间）

- 16:30 全市场发布任务 `ce64f8ae-47d0-41d0-a1ea-fe7f2af77246` 已终态失败，业务 `outcome=blocked`，`blocked_reason=system_audit_audit_runtime_disabled`，`requested/succeeded/failed/stored=0`；仍不能标记行情发布恢复。
- 17:30 通用 Alpha 已成功写入 `csi300` 的 2026-09-23 缓存，30 个有限评分，目标日与实际日一致，来源为 Qlib，无 fallback。
- 17:40 账户推理先后遇到 `model_market_scope_refresh_failed`、`tushare_daily_quota_exhausted` 等阻断；重试任务 `27c55e33-6bec-414f-893a-2d800a750b40` 于 18:59:04 北京时间开始，19:13 回查仍为 Task Monitor=started、Celery active，不能把运行中当作成功；账户 2026-09-23 可用缓存仍为 0。
- Celery Beat 持续发送定时任务，worker、beat、web、PostgreSQL、Redis 均运行；本次未触发任务、未重启容器、未修改授权或生产数据。
- 审计运行时仍为 `mode=off`、`outbox_enabled=false`、selector 缺失。行情 freshness 与市场温度计阻断也仍存在，`valid_component_count=3`。

本次自然周期仍未满足全市场发布、通用 Alpha、六个账户子任务和缓存证据的联合终态，`natural_cycle_verified` 保持 `false`。只读证据为 `backups/vps-postgres/market-recovery-evidence-20260919/full-market-natural-cycle-20260923.json`，SHA-256 为 `1d4f2e2a378aeec6177da0e6d081dbcd056bb26aa191caedd0d44921472cadfb`，已加入 `verified-manifest.json`。当前活动账户任务需临时后续回查，完成后再恢复工作日 18:55 的自然周期核验。
