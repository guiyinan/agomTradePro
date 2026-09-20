# VPS Alpha 自动推理停更：2026-09-19

> 最终状态（2026-09-19 04:53 UTC）：通用 CSI300 数据已推进至 09-18，297 条有限评分成功落库，3 只核验停牌未参与评分；生产排名页已实测显示 297 条、09-18，旧异常提示已清除。账户 5,533 标的大池仍有原始参考缺口，尚未恢复完整推理。下文按排查顺序保留历史状态，最后两节为最新修复与验证。

## 线上证据（只读检查）

- worker、beat 均存活；9 月 18 日 17:30 通用推理、17:40 组合推理及 18:00–18:50 每十分钟的恢复任务均按计划投递（北京时间）。
- 组合批次覆盖 6 个组合、5,533 个去重标的。批量数据刷新遇到 `TUSHARE_DAILY_QUOTA_EXHAUSTED` 后，父任务仍投递 6 个推理任务，每个子任务再次刷新后阻断，形成重复取数。
- 9 月 19 日 09:06 的通用推理请求 09-18 数据，返回 `MODEL_MARKET_SOURCE_CONFLICT`、`outcome=blocked`、`stored=0`。
- Qlib 日历仍停在 09-04；最近评分缓存计划日期 09-08、真实 `asof_date=09-04`、状态 degraded，更新时间 09-09。不是显示层漏刷新。
- 当前模型行情路由依次为 AKShare Public、DataHubCo RDS、Tushare Pro。对单个标的的只读探针中，前两者分别出现连接关闭和 HTTP 400，Tushare Pro 返回截至 09-18 的 268 条行情。此样本仅证明该次小范围请求可用，不证明全市场额度恢复。
- 平安银行 `000001.SZ` 的 2025-08-14 记录：库内腾讯 close=11.604、volume=1,241,041；Tushare 原始 close=12.20、volume=124,104,129。400 天窗口内有 198 个日期价格超过 1% 容差。代码确认腾讯请求 qfq，而 canonical 适配器及 Alpha coverage sync 原先默认保存为 none；历史成交量未将手转为股。这是复权口径和单位混用，不能放宽一致性阈值。

## 代码修复

1. `HistoricalPriceBar` 显式携带 `PriceAdjustment`。腾讯按真实返回的 qfqday/day 区分前复权和原始；东方财富股票/ETF、北交所新浪/东方财富入口保留前复权标记，指数保持原始口径。
2. 腾讯、东方财富历史成交量按手转股/份；新浪英文日线已为股，保持原单位。Tushare daily/fund_daily/index_daily 的手、千元转换成股/份、元，先缩放再转换整数，避免提前截断零股。
3. AKShare/Tushare canonical 适配器和 Alpha coverage sync 传递复权标记，包括 Tushare 失败后走腾讯的情况。去重键加入复权口径；同步只替换同一复权口径的受管记录，不能用前复权覆盖/删除原始参考。
4. 通用与组合定时入口遇到额度耗尽、`MODEL_MARKET_*` 或刷新返回 `status=blocked` 时停止投递，父任务发布稳定原因、`outcome=blocked`、`success=false`、`stored=0` 和决策阻断。普通瞬时异常沿用现有可重试推理路径，成功刷新不改变调度行为。
5. 保留模型行情 1% 一致性、新鲜度及原始参考过滤，不自动信任错误历史，不推进旧数据时间。

## 验证

回归覆盖：定时通用/组合阻断与零投递、前复权/原始区分、手转股/千元转元、fallback 元数据、不同复权记录共存、原始参考保留和模型参考排除前复权。登记在 Celery/current-data 治理清单。

- 核心单元与契约回归：153 passed。
- 数据库存储、Alpha 推理/缓存和 Tushare 完整性回归：39 passed；合计 192 passed。
- 8 个生产 Python 文件增量 mypy：0 errors、0 regressions；全仓 mypy debt ceiling：0 errors，未提高基线。
- Celery 任务契约：91 tasks、21 exemptions、23 governed files，通过。
- 当前数据新鲜度契约：62 surfaces，通过。
- Black、isort、Ruff、git diff --check：通过。

运行环境使用本机可用 Python 3.13 / Django 5.2.12；约定的 agomtradepro 虚拟环境没有可用解释器。生产完整推理和下一次定时周期未验证。

## 首轮代码修复后的待办（已由下方生产处置接续）

- 首轮代码修复时尚未发布；本轮用户追加数据修复要求后的生产处置见下节。
- 旧库错标的历史行不会因新代码自动变正确。应先备份并按资产、日期、来源、复权口径和单位建立修复清单，再从可信原始来源补齐并复核；不能按 source 名称批量改标（同一来源可能含原始指数或其他写入路径）。
- 需要在生产部署修复，处理历史冲突及服务可用性/额度后，执行真实数据构建和评分，验证 `asof_date`、覆盖范围及下一定时周期。尚未证明全市场构建在当前额度和资源预算内完成。
- 回滚可按本次文件 diff 撤回；无数据库迁移，不涉及旧评分数据回滚。

字段依据：[Tushare 日线](https://tushare.pro/document/1?doc_id=27)、[AKShare 股票历史数据](https://akshare.akfamily.xyz/data/stock/stock.html)。

## 生产处置：单位修复与页面错误提示

**历史记录说明：本节是首轮操作记录。腾讯科创板成交量后续发现本身以股计量，首轮乘 100 的处理已由下文 STAR 修正撤销；复权标记修复保留。最终单位结果以下文交叉验证为准。**

用户追加要求后，已备份生产 PostgreSQL，归档为 `/opt/agomtradepro/backups/database/postgres-20260919T024700Z.dump`，本地副本 `backups/vps-postgres/postgres-20260919T024700Z.dump`。大小 157,895,361 bytes，远端/本地 SHA-256 均为 `1ca128865613e59dcd1958ac539ee0e3e72f3cd70e2ea78a459d9d99381c2e18`，远端 `pg_restore --list` 通过。

修复清单为 [vps-alpha-price-repair-2026-09-19.json](vps-alpha-price-repair-2026-09-19.json)，14 个经核对的来源/资产类别/成交额存在性分组，共 2,784,157 条。清单限制抓取时间早于备份、原始 schema=1.0、revision=1、无原始审计标识的日线记录；不会按来源名字无差别处理指数。

证据与规则：

- Tencent 股票/ETF 请求 qfq，旧 volume 为手；股票 2,561,294、ETF 29 行转股并标记 forward。未注册主表的 30 行均为 `000300.SH` 指数，只转股，保留 none。
- AKShare 股票 22,724、ETF 29 行来自旧 qfq 路径（部分为被旧适配器重新标记的腾讯回退），转股并标记 forward；未注册主表的指数记录不参与本次变更。
- EastMoney ETF 30 行转份并标记 forward；41 行指数原本已经是股，保持原样。
- Sina 138,425 行全部为北交所股票，旧网关显式 qfq；只纠正 adjustment，成交量已经是股。
- Tushare 有成交额的 51,576 行为原始价格，量乘 100、成交额乘 1000。资产主表中的 bond/futures/other 组实际代码为交易所 ETF，不改变资产分类。
- Tushare 无成交额的 10,020 行是旧适配器把腾讯 fallback 重标为 tushare 的历史路径：`5492cf23f` 于 2026-08-02 修复了该来源问题。在 9,980 个有腾讯重叠记录的日期上，OHLC 四项完全一致。此组量乘 100、adjustment 改为 forward，不填造缺失成交额。
- 旧代码先将手截断为整数，已丢失的不足一手部分无法从库内恢复。本次恢复单位量级，保留精度限制；将来重新采集使用乘法后取整的新代码。

`repair_legacy_price_units` 默认 dry-run；生产 dry-run 所有分组匹配。写前在持久卷 `/app/data/backups/alpha-unit-repair-20260919` 输出逐行 gzip JSONL 旧值，行锁保护归档与更新，每组事务失败回滚；schema 标记 `legacy-units-20260919-v2` 与 revision=2 防止重复缩放。价格、bar_date、fetched_at 不重写。

页面：通过 task_monitor 公开查询读取最近相关任务的业务 outcome，正确处理 Celery success 但 outcome=blocked、超时、额度耗尽、行情冲突和未知失败。按组合隔离，返回安全文案，不返回原始异常/任务参数/其他账户信息。TUI 完整列表和 P0 概览即使为空或有旧缓存也显示 `business_summary` / `blocking_reason`；Classic 首页 Alpha 表格和完整排名页显示同样提示。成功写入新评分后旧失败提示消失。

发布回滚点：`/opt/agomtradepro/manual-file-backups/20260919111219`，含 release 原文件及 celery_worker/celery_beat 各自旧文件。web、worker、beat 同步代码；静态卷同步，并更新 TUI 脚本 cache key。HTTPS health=200；所有服务 running。

新增验证：Alpha 页面/TUI/数据库修复回归 378 passed；纯提示/运行契约 16 passed；前端全套 66 passed（包含真实浏览器空表、旧缓存和转义）；增量 mypy 5 文件通过，全仓 debt ceiling 0；Celery/current-data/模板迁移门禁通过。浏览器已验证生产 TUI 显示实际错误、09-04 评分日与 09-18 目标日。

数据修复已全部提交：forward 2,732,551 行、none 51,606 行均为 revision=2 / schema=`legacy-units-20260919-v2`；180 行已有正确单位的指数记录保留 schema=1.0。平安银行 2025-08-14 的腾讯成交量恢复为 124,104,100 股，标记 forward；沪深300指数 2026-07-31 腾讯、AKShare、EastMoney 成交量均为 27,924,369,800 股。

逐行回滚档案已打包到 `/opt/agomtradepro/backups/database/alpha-unit-repair-20260919.tar`，本地 `backups/vps-postgres/alpha-unit-repair-20260919.tar`。大小 39,823,360 bytes，SHA-256=`7d1b96364f89c4986470907dfcc4b2609da9d6888508f3a0e8e168bcaa9cb0d0`；下载校验一致，并逐个解压核对 14 个归档、2,784,157 行。

第一轮恢复任务 `796b197e-5f99-403c-b5c6-e37398e59269` 正确阻断为 `model_market_unverified_failover`：去掉错标原始数据后，部分股票缺少原始参考。生产 Classic 完整排名页已现场验证展示该原因及真实 09-04 评分日。

补充恢复使用腾讯明确的未复权 `day` 响应（请求 param 尾部为空）。网关增加显式 NONE 参数，原默认 qfq 行为保持，要求原始行情时绝不接受 qfqday 代替。单股样本 2025-08-14 close=12.200，与独立 Tushare 原始样本 12.20 一致。通过配置中的沪深300指数成分入口取得当前 300 个代码，补录缺失原始参考，不覆盖已有记录；记录独立 ingestion run 与 gzip 证据。随后仍由原模型数据端口执行跨源 1% 一致性、新鲜度及调整因子校验。

原始参考补录结果：run=`684c5763-3b14-4dda-8e36-61d729256b19`，300 个标的均返回有效历史，新增 79,696 条，未覆盖原记录。6 个标的（000963.SZ、601059.SH、601238.SH、601607.SH、601838.SH、601995.SH）来源末日未到 09-18，报告为 partial，保留真实末日。操作脚本及证据保存在本地 `backups/vps-postgres/` 与 VPS `/app/data/backups/alpha-unit-repair-20260919/`。显式原始模式新增 2 个回归用例，Tencent / basis 回归合计 17 passed；追加类型检查通过。

## 最终恢复验证与剩余限制

第二次生产恢复任务 `9343973d-e901-4cc6-8b53-24a12d86339c`（03:36:08–03:37:44 UTC）返回 `outcome=blocked`、`reason=model_market_stale`、`stored=0`，未投递下游预测。已有原始参考后越过了先前的缺参考阻断，但上游行情尚不能满足目标 2026-09-18 的新鲜度。没有放宽 1% 容差，没有补造停牌/滞后行情，也没有把 09-04 的旧评分更新成今天。**单位修复和页面错误提示完成；完整自动推理恢复尚未完成。** 后续需要查明滞后标的的数据可用性/停牌情况，按正式业务规则补足来源或处理不可交易标的。不能仅凭末日缺失推断停牌。

原始参考 gzip 证据另存 `/opt/agomtradepro/backups/database/raw-reference-20260919.jsonl.gz`、本地 `backups/vps-postgres/raw-reference-20260919.jsonl.gz`，摘要文件同目录 `raw-reference-summary-20260919.json`。新增参考属于实际重新采集，保留真实 bar_date，并使用独立 ingestion UUID；与纯单位修复保留原 fetched_at 的策略区分。

最终 Web 18 个文件与本地 SHA 一致，worker / beat 的 8 个相关文件一致；随后追加原始行情可选参数的网关文件亦同步。Qlib 0.9.7 可导入。代码回滚分层目录：初始 `/opt/agomtradepro/manual-file-backups/20260919111219`；Classic 排名初次补丁 `20260919111930`；页面最终补丁 `20260919112527`；显式 raw 网关补丁 `20260919113313`。回滚最初状态应采用最早包含相应文件的备份，不能用最后一次补丁备份假冒原始版本。

最终重启后复核：web healthy，worker、beat running，公开 HTTPS health=200；三个容器的 Tencent 网关 SHA-256 与本地一致。生产 Classic Alpha 排名页已通过浏览器实际刷新，显示“行情数据仍未更新到目标交易日，暂不能生成当期评分”，最近尝试 2026-09-19T03:37:44.480904+00:00，评分日期 2026-09-04，目标日期 2026-09-18。下一定时周期成功生成新评分仍未验证。

新增原始参考证据下载校验：gzip 1,868,631 bytes，SHA-256=`3c72324d8a0c3a087048b331925d7530399b35c21920f1f419b9614a3bb6b62a`；摘要 284 bytes，SHA-256=`11220c441b77fc902d4f10ca1b81d89d1023187f366b514e8798ec13891d5451`。


## 继续恢复：全天停牌证据与推理范围（2026-09-19）

追加排查：原始参考末日滞后的 6 个代码中，000963.SZ、601607.SH、601838.SH 已从配置中的备用模型来源验证取得 09-18 行情；601059.SH 和 601995.SH 最后行情 09-14、601238.SH 最后行情 09-11。DataHubCo RDS 与 Tushare Pro 的 suspend_d 返回一致的逐日全天停牌记录，覆盖后三者所有尾部缺失交易日（无日内 timing）。证据归档在 `/app/data/backups/alpha-unit-repair-20260919/suspensions-DataHubCo-RDS.json` 和 `suspensions-Tushare-Pro.json`。原先将这些已知停牌与未知数据缺失一律视作 stale，导致整个股票池不能推进。

新增可选 ModelSuspensionPort，由数据中台标准化明确的全日 S 记录。模型服务先继续尝试新鲜 failover；仅缺失交易日逐日全覆盖、且原始行情一致性通过时发布专用 MODEL_MARKET_SUSPENDED。没有返回旧记录冒充当期行情，也没有合成停牌 K 线。Qlib builder 单列 suspended_codes/warning_messages，将这些代码的 instrument 终日限制到真实最后观测日，其余股票继续构建；无法核验的 stale、冲突或指数错误仍阻断。预测按实际目标日展开成分，组合显式股票也与当天 all 成分相交。

发布模式 hot-update code-only，备份 `/opt/agomtradepro/manual-file-backups/20260919115817`；7 个文件同步 web/worker/beat。无数据库恢复、无镜像清理、保留数据卷。额外备份完整 Qlib 目录为 `/app/data/backups/alpha-unit-repair-20260919/qlib-before-suspension-recovery.tar.gz`，SHA-256 `6ae470f99960b49c64ac23a05aad4f81777bf546df4355f8896c968b49710164`。

验证：路由/模型构建/运行时回归 64 passed；新增真实目标日/停牌边界聚焦用例 4 passed；ops/outcome/提示/运行时回归 50 passed；7 个生产文件增量 mypy 0，全仓 mypy debt ceiling 0；Ruff/Black/当前数据/Celery 门禁通过。新任务结果另补于下文，不以投递成功代替推理成功。


### 科创板单位差异的追加纠正

恢复任务 60b08575-7291-4975-b4bb-b8ee0926da85 越过停牌阻断，后在 20 个科创板成分的 volume 跨源比较阻断。腾讯 day/qfqday 对主板返回手、对 688/689 科创板返回股；首轮统一乘 100 是本次修复遗漏，不能将此次冲突解释为上游数据未更新。旧库共有 6,001 个腾讯与 Tushare 独立重叠记录，全部满足腾讯首轮修复后 volume 约为 Tushare 的 100 倍，零条满足原来的 1 倍。

已将 294,879 条首轮 Tencent 科创板 forward 记录及本次 raw-reference run 的 5,304 条 none 记录，按严格 schema/revision/ingestion UUID cohort 在一个事务中 volume 除 100；保留价格、复权口径、bar_date、fetched_at，marker=legacy-units-20260919-star-v3，revision 分别为 3 和 2。没有改动正确的 Tushare 科创板记录。写前完整旧行 gzip 已下载校验：star-volume-before-legacy.jsonl.gz 8,617,511 bytes / SHA-256 e63c847cbf9cfc58379ac50fc2eed04e0615463f73057ca406504d93102f7031；star-volume-before-reference.jsonl.gz 163,893 bytes / SHA-256 3fb1cb6e3bcea26187191fbcaac9555ffad2cdd131ad21d750d4d715e8d7bd67。本地 backups/vps-postgres 与远端 /opt/agomtradepro/backups/database 同名文件一致。

转换规则从业务代码移至 Config Center 的 data_center.tencent.history_volume_multipliers，经 configure_tencent_history_units 管理命令显式初始化/修订；规则文件为 tencent-history-volume-rules-2026-09-19.json。缺失或非法配置失败关闭，最长代码前缀匹配，交易所隔离。生产激活 profile 92b739cb-87a6-4005-9fbd-608f03b82fb7；保留其他运行配置值。code-only 补丁回滚目录 /opt/agomtradepro/manual-file-backups/20260919121119。

该轮新增/相关测试 68 passed；3 个生产文件增量 mypy 0。完整恢复重新投递 fd3a20a2-53b1-4725-892b-6c8f2a77d962，结果另行记录。

STAR 修正后交叉验证：包含补录 raw 参考在内，共 8,984 条与独立 Tushare 的重叠记录，全部在 1% 内；仅旧 forward cohort 为 6,001 条。停牌两个来源的完整证据各 14,416 bytes，SHA-256 均为 ed342c14f88d50801d5a553d5bcca6b6a359713fc34aaf114c9e7728e55ad73f，下载副本一致。


### 指数缺失成交量的参考数据修复

第二轮停牌恢复任务 fd3a20a2-53b1-4725-892b-6c8f2a77d962 已验证 297 只可交易股票，随后在沪深300指数参考阻断。旧 akshare:stock_zh_index_daily 有 28 条 close-only 历史记录（2026-02-25–04-03），volume=NULL；model_market_wiring 原先用 `bar.volume or 0.0` 将缺失伪装为 0，产生 28 个 volume 及 3 个 OHLC 冲突。现参考选择排除缺失成交量的记录，实际 0 成交量仍保留并参与比较；不把空参考当校验成功。

独立腾讯原始指数参考新增 238 条，原有 30 条不覆盖，run=d2d8b148-27aa-4a35-99db-fc01d90f0abd。原始 gzip 位于 /app/data/backups/alpha-unit-repair-20260919/raw-index-reference-d2d8b148-27aa-4a35-99db-fc01d90f0abd.jsonl.gz；摘要 raw-index-reference-summary.json。该补丁备份 /opt/agomtradepro/manual-file-backups/20260919122236；34 项行情/路由回归和增量 mypy 通过。

指数追加核验发现腾讯库内 2026-08-21 单条旧成交量 14,937,760,000，与本次重新查询腾讯单日/区间、Sina 和 Tushare 的 17,107,589,100 不同。先归档旧行 index-outlier-before.json 与重取结果 index-outlier-refetched.json、Sina 证据，再按实际腾讯重取值刷新该行，标记 source-refresh-20260919、递增 revision、记录新的 ingestion UUID 和真实 fetched_at；这属于实际重新采集，不是修改历史观测日。该次未改变 bar_date、没有跨来源冒名写入。

完整指数窗口已验证 268 条全部通过；第三次恢复任务 0906990e-b4a5-4746-a195-11278565ef01 进入正式构建。指数 raw 归档下载 SHA-256=7307d2426e0f6f19f4be5eef9ff84c47207977702004a6d013b4973703836b21；旧异常行、重新采集值和 Sina 证据亦已分别下载校验一致。


### Qlib 特征重复复权与溢出修复

第三次完整恢复构建成功将日历由 2026-09-04 推进至 2026-09-18（10 个交易日），首个预测任务 144f56b0-253e-4113-9af2-7078fd89dab5 落库 293 条当期评分。逐个核对剩余标的发现，除 3 只已核验停牌外，002594.SZ、603296.SH、605499.SH、688012.SH 的既有 factor/close 二进制包含 Infinity。根因是 builder 将已有最后一天的 factor 对应到 incoming 第一日 adj_factor，重复刷新不断累乘公司行动。

现改为按相同观测日配对、优先最近重叠日，直接计算复权分母，避免早期 float32 分数经不同日期往返换算引入累积漂移。已有 factor 非有限/非正时在推进共享日历前阻断；待写特征超过 float32 范围时阻断。无匹配复权基准也不猜测缩放。异常发布 MODEL_MARKET_LOCAL_FEATURE_INVALID，Alpha 页提供对应提示。

4 个损坏特征目录先归档、再移动到隔离备份并按可信原始行情重建。归档 corrupt-features-20260919T044706Z.tar.gz 共 70,041 bytes，SHA-256 a73d96d90b95aba702ef7f9b4a562a3121d40537b0b6fc1f9d59744d98768335；容器数据备份、远端数据库备份目录及本地 backups/vps-postgres 副本已校验一致。整个旧 Qlib 目录另有此前完整备份。

真实生产数据连续构建两次，4 只股票共 28 个 bin 的 SHA 完全一致；全体 297 只当期成分的 bin 扫描无 Infinity。最终预测 f6656f01-bda0-4feb-814a-642ef99e3737 随后投递，完成状态见下文。

组合范围另加完整性保护：显式 scope 缺少目标日成分时发布 MODEL_MARKET_SCOPE_INCOMPLETE，不静默裁剪后标记整池成功。任务发布 outcome=blocked / stored=0，禁止在此错误上重用旧缓存，页面显示完整股票池数据不足。此规则优先于前文临时采用的 scope 与 all 交集实现。

代码补丁模式 hot-update code-only；回滚目录 20260919124429（初次因子/范围保护）及 20260919125013（最终因子基准/任务 outcome）。最终四个文件 qlib_builder.py、qlib_prediction_runtime.py、tasks.py、alpha_refresh_notice.py 在 web/worker/beat 的 SHA 与本地一致，三个进程已重启，HTTPS health=200，9 个容器 running。

该轮验证：builder 27 passed；最终小数公司行动幂等/损坏文件/float32 溢出用例 3 passed；运行时与任务 outcome 35 passed；页面提示 11 passed；任务推理链 12 passed。改动生产文件增量 mypy 0，全仓 mypy debt ceiling 0；Black/isort/Ruff/diff-check 与 current-data 62 / Celery 91 门禁通过。

生产数据库定时配置确认：通用 qlib-daily-inference 已启用，工作日北京时间 17:30，csi300/top_n=30，任务默认 refresh_data=True、lookback_days=400；组合任务 17:40，18:00–18:50 每 10 分钟补偿，均启用。最近执行时间为 09-18 对应时刻。没有增加重复调度；下一交易日自然定时触发尚未实际观察。

账户广泛池尚有独立缺口：6 个活动组合的 price_covered scope 每个 5,533 个代码（并集也为 5,533），其中 5,196 个缺少 120 天窗口内可验证的未复权参考；这不等同于 CSI300 恢复。现保护会明确阻断，而不是将 297 只的结果标成完整账户池。尚需补齐这部分独立 raw 参考、核验停牌/退市情况并构建全池后，再完成各账户推理。

### 最终生产结果与页面验证

预测任务 f6656f01-bda0-4feb-814a-642ef99e3737 于 2026-09-19 04:53:29.960506 UTC 完成：outcome=success、requested=1/succeeded=1/failed=0/stored=1，stock_count=297，cache.status=available，asof_date=intended_trade_date=2026-09-18，trade_date_adjusted=false。297 条分数均为有限值，四个重建代码全部在评分中，三个全天停牌代码全部不在评分中；未回填旧评分。工作台推荐刷新 30 条、冲突 0。

生产 Classic 排名页通过真实浏览器请求 top_n=300，实际显示“已加载 297 条 / 来源 qlib / 评分日 2026-09-18”；最新成功结果使 refresh_notice={}，原先自动更新异常横幅已消失。尚未实测下一自然定时周期，也未将账户大池数据缺口宣称为已完成。


### Alpha 信号强度与流动性提示追加修复

用户反馈“信号强度不足；无法获取成交量数据，跳过流动性检查”。线上宁德时代实际 Alpha=0.11408015747041618，按现有 (score+1)/2 映射为 0.5570400787352081，低于策略门槛 0.6；此次不改变模型分数或门槛，显示原始评分、映射强度与实际门槛，并让证伪条件使用同一口径，去除独立硬编码 0.55。

成交量并非原始库没有：09-18 宁德时代 Tencent 为 38,071,300 股，独立 DataHubCo 为 38,071,252 股。页面依赖的行情发布版本因 publication_policy_changed 被阻断，quote/price 上下文未返回可用数值；原代码把缺失变为 0、又把真实 0 变为 None，最终沿用“跳过”警告，且候选没有继承 stock_context 的发布阻断。

修复保留 None 与真实 0 的区别，保留成交量来源和观测时间；缺失或非法成交量明确阻断 Alpha 候选，真实 0 参与流动性不足判定；候选继承行情/基本面发布门禁。完整排名页展示不买原因，规则失效、未发布、过期、缺少成员分别给出可读提示，不用原始行情绕过已发布数据契约。

全市场发布只读预检证据：/app/data/backups/alpha-unit-repair-20260919/current-publications-preview.json。5,533 个有效标的中 price 仅覆盖 337，缺 5,196；quote 覆盖数量完整但观测日期范围为 07-31 至 09-11，不能当作当前行情；valuation 候选缺 observed_at，预检失败。未执行发布、未伪造观测时间。CSI300 推理成功不等于全市场决策行情和基本面发布已恢复。

验证：候选流动性、查询、上下文仓储和更新提示回归共 78 passed；去重提示后专项再跑 14 passed。增量 mypy 0，全仓 mypy debt ceiling 0，Black/isort/Ruff 通过；current-data 62 surfaces 与 Web-to-TUI inventory 门禁通过。补齐旧查询测试的任务历史隔离和 scope.portfolio_id 字段，保留专门的更新失败提示测试。

发布 hot-update code-only：两份 Python 文件和完整排名模板，回滚备份 /opt/agomtradepro/manual-file-backups/20260919160137；最终重复提示去除补丁备份 /opt/agomtradepro/manual-file-backups/20260919160456。web 重启、HTTPS health=200，9 个容器 running；两份 Python 在 web/worker/beat 三容器 SHA 与本地相同，worker/beat 已重启，首次重启前确认 worker 无活动任务。

真实浏览器在 /dashboard/alpha/ranking/?alpha_scope=general&top_n=200 验证“已加载 200 条、评分日 2026-09-18”，第一名显示 0.1141 → 0.5570 < 0.6000 和发布规则失效提示；不再显示跳过流动性检查。线上前三个候选的直接结果断言通过：volume=None、liquidity_check.status=blocked、recommendation_ready=false，发布原因在首条不买理由中。此次未解决全市场发布缺口，下一自然定时周期亦未验证。
