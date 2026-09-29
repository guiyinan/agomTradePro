# 指数温度分析能力开发计划（2026-09-28）

> 状态：评审修订完成，待实施；数据源实测、模型验证和生产验收尚未开展。
> 本次修订：修正数据源、全收益、历史窗口、发布隔离和迁移假设；增加交付切片与工期。
> 本文是实施与验收计划，不表示已获得数据权限或已验证投资有效性。

## 1. 目标与交付边界

首个标的为中证红利（000922），提供 0–100 的指数温度、组成解释、源观测时间和可用性。
用户在 `/tui/` 完成“判断当前指数冷热、查看依据和历史变化”这一主任务。
基础版与完整版分别验收；辅助能力可后交付，但不能把基础版称为原始全范围完成。

| 交付层级 | 包含能力 | 完成边界 |
| --- | --- | --- |
| 基础版 R1 | DY/PE/PB、股息利差、5 年/10 年分位、估值与利差温度、解释、可用历史折线、近 12 个月表、signal 证伪闭环 | 不含 ETF 拥挤度的评分使用独立模型版本与名称 |
| 完整版 R2 | ETF 份额及估算净申赎、日终折溢价、40 交易日超额收益、拥挤度合成、行业权重与环比、官方全收益、PE–DY 散点与必要的双轴图 | 完成原始全范围；缺数据的增强项保持未完成 |
| 本期不做 | 成分股除息再投资的精确全收益重建、自动下单、任意指数通用建模平台 | 另立需求与估算 |

数据采集、标准化事实和派生指标复用 `data_center`；温度计算复用既有框架，不新建 App。
Domain 保存纯算法，Application 通过 Protocol 编排，Infrastructure 完成外部 I/O。
signal 通过公开 Application 查询消费温度与阻断状态，不复制合成逻辑、不导入中台 Infrastructure。
指标、单位、权重、阈值及 ETF 清单入库并提供管理入口；全局运行开关归 `config_center`。

基础展示为“低温 / 中性 / 高温”，边界分别为 `[0,20)`、`[20,80)`、`[80,100]`。
加仓/持有/减仓的行动解释仅在通过决策门时呈现；温度不直接决定组合仓位或绕过风险规则。

## 2. 已核对事实与待验证假设

### 2.1 仓库能力与限制

| 能力 | 代码证据 | 本期限制或必改点 |
| --- | --- | --- |
| 温度加权 | `apps/data_center/application/market_thermometer_calculate.py` | 组件固定、按有效组件重新归一；不能照搬为指数缺失策略 |
| 分位与分档 | `apps/data_center/domain/rules.py` | 旧分位缺值返回 50，并列规则与本计划不同；旧逻辑不变，指数新增版本化规则；旧分档为五档 |
| 配置、覆盖、快照 | `apps/data_center/infrastructure/fact_and_operational_models.py` | Config 强制保存为 pk=1，Override 为用户一对一，Snapshot 日期唯一 |
| 温度 Repository | `apps/data_center/infrastructure/market_thermometer_repositories.py` | 无标的范围；历史截止依赖当前日期，须支持显式历史区间 |
| 估值同步与发布 | `apps/data_center/application/sync_valuation_sector_use_cases.py`、`apps/data_center/application/valuation_publication.py` | 可复用同步结构；发布器固定为 equity.valuation.fact/current，不能直接用于指数 |
| 代码归一化 | `apps/data_center/domain/rules.py` | 裸 000922 在股票规则下会变成 .SZ；指数必须走主数据和来源别名 |
| 国债、指数行情 | `apps/data_center/infrastructure/macro_sources/fetchers/high_frequency_fetchers.py`、`apps/data_center/infrastructure/akshare_model_market_source.py` | 有 CN_BOND_10Y 和指数日线接口，不证明 000922/H00922 的实际覆盖 |
| 指数权重、ETF | `apps/data_center/infrastructure/tushare_model_market_source.py`、`apps/data_center/infrastructure/_provider_adapter_tushare.py` | 已封装 index_weight、etf_share_size；已有规模差分是代理值，不是净申赎 |
| 信号证伪 | `apps/signal/domain/invalidation.py`、`apps/signal/application/use_cases.py` | 可复用完整性校验，另补指数语义与幂等关联 |
| TUI 图表 | `apps/terminal/application/tui_workbench_collection_result_models.py` | kind=chart 与 chart_type 分离；点为 label/value，通用投影最多 240 行 |

### 2.2 供应商依据（2026-09-28 文档核对）

- [Tushare index_dailybasic](https://tushare.pro/document/2?doc_id=128) 有 PE/PB，但没有股息率字段，支持范围未承诺包含中证红利。不能列为确定的完整主源。
- [Tushare etf_share_size](https://tushare.pro/document/2?doc_id=408) 有份额、规模和可选 nav/close，可作为日终折溢价候选；单位为万份/万元。上一交易日数据通常次日更新，权限、字段和历史覆盖须实测。
- [AKShare 基金接口](https://github.com/akfamily/akshare/blob/main/docs/data/fund/fund_public.md) 的 fund_etf_spot_em 有 IOPV/折价率，但实时截面不证明历史折溢价可回填。
- [中证红利历史 factsheet](https://csi-web-dev.oss-cn-shanghai-finance-1-pub.aliyuncs.com/static/html/csindex/public/uploads/indices/detail/files/zh_CN/000922factsheet.pdf) 佐证全收益代码 H00922；该材料为 2024 年快照，仅作身份参考，不用于当前数值验收。

估值候选源包括中证官方资料、AKShare 对应中证/指数估值接口及已有授权服务，各字段分别核实。
不同接口可能共享同一上游，不能算独立交叉验证。本文不声明候选源已经连通或满足十年历史。

## 3. M0：数据可行性与实施入口

先做可重复的只读取样工具和报告，不先重构温度计。保存脱敏原始响应、哈希、参数、
provider/实际来源、解析版本、源观测/可用时间、采集时间和复现命令，不记录凭据。

| 数据项 | 必须验证 | 不满足时 |
| --- | --- | --- |
| 指数 DY/PE/PB | 身份、PE/PE TTM、股息分母与区间、单位、历史起止、分段完整性、修订、主备同口径重叠 | 缺 R1 必需字段或无可验证切源路径，R1 保持研究候选，暂停正式评分上线 |
| 国债和价格 | 10Y 单位与发布时间；000922/沪深300 的日历、价格口径及历史范围 | 相应派生量阻断，不用计算时间填源时间 |
| ETF | 跟踪指数身份与有效期、成立日、份额/NAV/close 覆盖、拆分、更新时间、备用源 | 只影响 R2；成立前及缺失期间不填零 |
| H00922 | 官方身份、可取接口、真实历史、全收益/净收益区别、主备与参考点 | 全收益增强项未完成，不自动启用均摊股息合成 |
| 行业 | 中证一级分类版本、成分与分类的生效区间、历史来源和使用条件 | 可做当前截面；无历史证据不声称支持历史环比 |

报告有效样本数、预期交易日数、覆盖率、最大缺口、重复/异常值与跨源差异。
至少取最近完成交易日、较早历史段、跨年及调样附近样本；核实分页、上限、权限与限流。
频率、日历、发布时间及延迟预算写入版本化配置，不把此次取样结果硬编码为业务规则。

M0 出口逐项标记 `ready / blocked / research_only`，冻结来源矩阵与可交付历史起点。
阻塞列明缺口及恢复条件，不无限尝试同一不可用接口；外部等待单列。
M0 后收窄工期，M1 后冻结模型；不满足条件的增强项保留原范围和未完成状态。

## 4. M1：计算与时间契约

### 4.1 股息利差与血缘

名称使用“股息利差”，定义为指数股息率减中国十年期国债收益率，不无条件称为一般 ERP。
建议指标代码 `CN_DIVIDEND_SPREAD_CSI_DIV`，登记前检查冲突；单位为百分点：
5.0% − 2.0% = 3.0 个百分点。DY 的 TTM/上一年度/供应商算法由 M0 确定并标注，不能只改字段名。

若发布 `CN_DIVIDEND_YIELD_CSI_DIV` 宏观投影，种子和估值事实投影必须同时实现；
否则直接引用估值事实身份，不把未实现的宏观代码列为上游。
IndicatorCatalog、IndicatorUnitRule、macro fact 沿用现有真源与种子流程。
Domain 计算，Application 按已发布事实编排，Infrastructure 取数和落库；
不要求通用派生引擎，也不把金融公式与数据库编排混入 provider fetcher。

### 4.2 时间、窗口和样本

- 区分 as_of_date、源 observed_at、available_at、fetched_at 与计算时间。派生记录保留每个输入的时间和版本；可用时间不得早于任一输入。
- 历史决策重放只读知识截止点前可获得的版本；无历史可用时间的数据可做事后研究，标记 research_only，不宣称严格 PIT、不用于信号重放。
- 分位使用截至 t 向后 5/10 个日历年的滚动窗口，交易日历确定预期样本。HP 滤波的扩张窗口要求不套用到分位计算。
- 指数分位采用中位秩：`100 × (小于当前值数量 + 0.5 × 等于当前值数量) / N`，包含当期值，全部相等时为 50。缺失、非有限值、非法 PE/PB 不变成零。
- 完整 5/10 年窗口候选门槛：覆盖率至少 95%，有效样本至少 1000/2000，并满足完整时间跨度。M1 用 M0 数据检验后冻结为 DB 参数；样本不足输出 None 和原因，不以 50 掩盖。
- 预热期可展示实际跨度的研究分位，明确不足 5/10 年并阻断正式温度，不能以短窗口替代完整窗口。
- 过去十年的每个点都具备完整十年分位，通常需要约二十年上游数据。实际历史是必需组件可用区间交集；R2 可短于 R1，不能拼成同模型曲线。
- 国债和估值按知识截止点向后匹配，保留各日期与允许延迟，禁止向未来匹配。40 日、ETF 5/20 日指交易日；月/年变化取对应日之前最近有效点并公开比较日期。

### 4.3 评分候选与缺失处理

以下参数用于实施估算，不代表投资有效性已验证。M1 必须完成独立复算、贡献拆分、
敏感性分析后冻结。参数变化创建新模型/配置版本与哈希，不在同一版本改写历史。

设 `Q(x) = 0.5 × P5(x) + 0.5 × P10(x)`：

| 项目 | 候选规则 |
| --- | --- |
| 估值分 V | `(Q(PE TTM) + Q(PB) + 100 − Q(DY)) / 3` |
| 股息利差分 S | `100 − Q(股息利差)` |
| R1 温度 | `0.7 × V + 0.3 × S`，名称“估值与利差温度” |
| 拥挤度分 C | 40 日超额、ETF 流量强度、日终溢价率的升序分位等权平均 |
| R2 温度 | `0.5 × V + 0.2 × S + 0.3 × C`，名称“综合指数温度” |

DY 同时进入 V 和 S，M1 必须检验重复贡献，不能声称提供独立信息。
R2 拥挤度分位候选窗口为向后 3 个日历年、95% 覆盖、至少 600 个样本，同样在 M1 冻结。
每个模型的全部评分组件均为必需；缺失、过期、样本不足或来源冲突时，正式 score/band 为 None，
发布 must_not_use_for_decision 与稳定 blocked_reason，不自动归一剩余权重、不伪造低温。
可以展示组件原值和带日期的末次有效温度；读取时重新评估 freshness。
market 旧语义不变，指数契约须支持可空输出；同一 R1/R2 不因历史缺组件而切配方。

候选阻断原因：INDEX_SOURCE_UNAVAILABLE、INDEX_SOURCE_STALE、INDEX_SOURCE_CONFLICT、
INDEX_HISTORY_INSUFFICIENT、INDEX_AVAILABILITY_UNKNOWN、INDEX_MODEL_NOT_READY；M1 统一冻结。

### 4.4 ETF、超额收益与信号

- 净份额变化为经拆分一致性调整的 Δ份额；估算净申赎金额为 Δ份额 × 同日单位净值，分别汇总 5/20 日并标记估算。规模差分不是净申赎；拆分无法解释或 NAV 缺失则阻断。
- 多 ETF 按当时有效的跟踪清单聚合，保留逐基金覆盖；流量强度候选为 20 日估算净申赎合计 / 前一期合计规模。分母非正或必需成员缺失时不可用，不临时缩小集合。
- 日终溢价率为 `(close / nav − 1) × 100%`，聚合采用前一期规模权重。实时 IOPV 为另一指标，不混入日终历史；供应商折价率的正负号在边界标准化。
- 40 日超额为 000922 价格收益率减沪深300价格收益率，需要 41 个对齐收盘点，命名“价格超额收益”。改为全收益比较须双方一起切换并创建新版本。
- signal 候选为研究持有论断：连续两个交易日均有有效观测，且温度 >=80、股息利差 <=0 个百分点时证伪；参数入库。中间交易日缺数据打断连续性，状态为“不可评估”，不能跳过缺日或自动视作证伪/恢复。
- signal 绑定模型、输入快照与规则版本并去重，不触发下单；模型切换显式处理存量论断，不把 R1 和 R2 连成连续证伪窗口。

M1 出口包含参数快照、例题、边界用例、基准日期、信号语义和历史覆盖结论。
M0 数据不支持候选规则时显式修订本节，不在实现中悄悄放宽门槛。

## 5. 架构与迁移

### 5.1 身份、能力和发布隔离

- 用 AssetMaster/alias 区分指数与股票，按来源映射代码，不对所有指数套 .SH 或裸代码股票规则。测试同数字不同资产类型及 H 前缀。
- fetch_index_valuations 采用精确 DTO/Protocol。可复用 VALUATION 大类，但另声明指数、字段、历史能力；不支持要显式报告，不用空列表冒充正常无数据。
- 审计 ValuationFact/表自然键、revision 与元数据承载能力，再决定复用表或最小迁移；不能仅凭字符串 asset_code 承诺不改表。
- 指数使用独立 dataset 和 publication scope（候选 index.valuation.fact 与 canonical asset 对应的键）；同步枚举、policy、contract、publisher、query 和 evidence。不得复用股票 current 指针或加入 A 股冻结分母。
- 同步批次只写事实/审计，完整范围通过一致性、freshness、hash/revision 校验后原子发布；历史回填不推进 current，已发布事实追加修订、不覆盖。
- failover 核对同身份、日期、单位和统计口径；缺参考、超限或 stale 按契约继续备用并最终失败关闭。默认相对容差 1% 不放宽；零附近有符号利差/溢价另配置绝对误差基点规则，不混用 1% 相对差和 1 个百分点。
- current/latest 从首次接入就登记新鲜度契约，不等最终温度上线才登记。

### 5.2 多标的温度计

| 范围 | 必改项 |
| --- | --- |
| Config | 唯一 thermometer key，解除强制 pk=1；旧行保留 market；参数/版本可复现 |
| UserOverride | 改为 (user, thermometer_key) 唯一，存量回填 market；若 R1 不开放用户阈值，则显式拒绝指数覆盖，不能误用 market 参数 |
| Snapshot | 替换单日期唯一约束，以 (thermometer_key, model_version, as_of_date, revision) 隔离并定义 current 选择；保留输入/参数哈希 |
| Entity/Protocol/Repository | 范围、版本、显式起止日期全链路传递；旧公开入口默认 market；读写删与用户覆盖都隔离 |
| 计算与查询 | 注册组件算法类型，具体指标/权重/阈值入库；market 六组件五档保持，指数三档且可空 |
| 消费者 | API、Admin、TUI、signal、缓存、锁、定时任务完整盘点；共享标识包含范围，旧入口不能选到指数快照 |

先固定 market 数值、状态、用户覆盖、历史与 API 回归，再做迁移；不借此重写全部旧规则。
指数算法不修改旧分位函数历史语义，新增 Admin 遵循 TypedModelAdmin/TypedModelForm。
统一明确官方模型 band 与用户展示 override 的差别；信号只消费其绑定的规则版本。
存量 market 快照标记为 legacy 版本，保留原值；缺失的历史配置/输入证据如实记录，不补造哈希或声称可完整重放。

### 5.3 刷新、回填和任务

上游同步 → 完整性/发布时间校验 → 原子发布 → 派生评分 → 快照 → signal；
失败停止依赖步骤。beat 按来源实际延迟设置，不能假设收盘即齐全。
任务入口校验 key、日期、版本、范围、数量；发布 outcome 与 requested/succeeded/failed/stored，
区分对象和事实行计数，零写入有原因。
回填分区间、带 checkpoint/幂等键/限流/有界重试，同范围同版本互斥；
历史中断可续跑，不逐历史日反复请求整段数据。
登记 invalid_input/all_success/partial_failure/complete_failure/zero_output/blocked 六类证据，
Task Monitor 读取业务 outcome。

## 6. R2 增强项

### 6.1 行业权重

成分权重与中证一级行业映射均保存有效区间、可用时间、分类版本、来源与修订。
行业权重为同历史截面内成分权重按行业求和；总和采用经 M0 核实的舍入容差。
未知行业进入“未分类”并告警，不丢弃/均摊；环比比较相同分类口径的真实快照并展示日期。
缺历史映射时不以当前分类回写历史；初始化、维护、审计入口同切片交付。

### 6.2 官方全收益

验证 H00922 后作为独立指数资产落库；年度收益取上年末和当年末最后有效交易日点位，
未结束年度标注 YTD。缺端点不凑整年，与官方同期间同全收益口径参考点对账。
不以“价格收益 + 股息率/252”兜底，不承诺未经验证的几十 bp 误差。
后续若做估算，另设序列身份与模型版本，仅作研究；官方值不能覆盖估算审计轨迹。

### 6.3 TUI 与通用图表

R1 一个主任务 screen，同步 IA/metadata/runtime/发布配置，声明 primary_task、
primary_outcome、default_action_key 和 empty/error/stale 提示。
首屏展示温度/分区、模型名称、源日期、可用于决策状态及阻断原因；
组成、历史折线和月表为同屏辅助区，月/年比较缺点显示暂无并公开比较日期，不把空值画成零。

R2 保持 kind=chart，扩展 chart_type=scatter 的数值 x/y 契约，
以及 line 的轴身份、单位与范围；仅同时显示不同量纲时启用双轴。
同步 schema、双端 validator、compiler、host projection、通用 runtime 与测试。
实现修改维护源 `frontend/tui-workbench/src/`、`frontend/agomtui-runtime/` 等对应模块，
经 npm run build:tui 生成 bundle，不只改 static/js/tui-workbench.js；同步静态资源版本。
不在通用渲染器写业务 screen/action 特判。

十年走势与散点明示采样规则、240 行上限、首末点保留、sampled/source_row_count；
图上抽样不用于评分/分位计算。散点附完整数据统计摘要，不把抽样密度当总体分布。

## 7. 实施切片、依赖与工作量

估算口径：1 名熟悉仓库的工程师配合代码助手，1 人日约 6 小时有效开发/验证。
含实现、必要测试、专项文档和切片自验，不含采购/供应商等待、生产部署或实盘观察。
S0 对应 M0，S1 对应 M1；后续 S 编号替代旧版 M2–M6 的混合安排。
按依赖执行，行序不强制串行；本次仅规划，不启动代理并行实施。

| 切片 | 交付与验收出口 | 依赖 | 人日 | commit 组 |
| --- | --- | --- | --- | --- |
| S0 数据实测 | 可复现工具、来源/字段矩阵、历史与阻塞报告，逐项 ready/blocked/research_only | 无 | 1–2 | data evidence / docs |
| S1 模型冻结 | §4 例题、参数版本、时间/PIT、缺失/证伪契约、独立复算基准 | S0 | 1–2 | domain contract / docs |
| S2 身份与发布 | 指数主数据/alias、dataset/policy、事实键审计；股票 current 不变、无串标的 | S0 | 2–3 | data_center identity / publication |
| S3 估值接入 | 主备 provider、DTO/Repository、sync/query、原始证据和幂等回填；三字段真实样本可查 | S2 | 3–5 | data_center ingestion / API |
| S4 分位与利差 | Domain 规则、派生、单位种子和 R1 计算，固定输入逐值复算无未来数据 | S1、S3 | 2–3 | data_center domain / derivation |
| S5 兼容迁移 | Config/Override/Snapshot、Protocol/Repository/查询及迁移；market 数值语义不变 | S1、S2 | 3–5 | data_center refactor / migration |
| S6 刷新与历史 | Celery、限流/续跑/锁、版本快照、freshness；中断重跑与部分失败可解释 | S4、S5 | 2–3 | data_center orchestration |
| S7 R1 TUI | P0 温度、解释、line、月表、恢复提示；真实浏览器完成主任务 | S6 | 2–3 | terminal/tui |
| S8 signal | 精确阈值、绑定/去重、失效/不可评估区分；可查看证伪依据 | S1、S6 | 1–2 | signal |
| S9 R1 验收 | 真实对账、PostgreSQL 隔离/迁移、浏览器 UAT、回归及回滚演练，R1 结论 | S7、S8 | 2–3 | tests / governance/docs |
| S10 ETF 与 R2 | 份额/调整/净申赎/溢价、40 日超额、拥挤度与独立 R2；历史覆盖/缺失可解释 | S0 的 ETF ready、S1、S6 | 4–6 | data_center ETF / scoring |
| S11 行业与全收益 | 两个独立子切片：行业时点映射/权重；官方 H00922/年度与 YTD；分别对账 | S0 对应数据 ready、S2、S3 | 3–5 | data_center sector / total return |
| S12 通用图表 | scatter/双轴与全契约同步、R2 同屏接入；其他图表不回归 | S7；最终接入依赖 S10/S11 | 2–4 | terminal/tui renderer / schema |
| S13 R2 验收 | 综合温度、行业、官方收益和图表全链路；版本曲线与信号重放核验 | S10–S12 | 2–3 | tests / governance/docs |

日常开发在 `dev/next-development`，不为每个切片新建分支。
每片可有多个独立 commit；数据接入、架构迁移、TUI、signal、部署不混成大提交。
必需门禁登记随代码提交，最终证据整理可独立提交，不能全部延后到 S9/S13。
每片记录目标、产出、剩余、测试、风险和回滚点；连续扩边时更新本计划。
S11 内再分 S11a 行业时点映射（1–2 人日）与 S11b 官方全收益（2–3 人日），分别验收和提交；一项阻塞不阻止另一项交付。

### 7.1 工期结论

| 交付 | 基础工作量 | 加约 20% 集成/返工缓冲 | 单人每周 5 个有效工作日 |
| --- | --- | --- | --- |
| R1（S0–S9） | 19–31 人日 | 23–38 人日 | 约 5–8 周 |
| R2 增量（S10–S13） | 11–18 人日 | 14–22 人日 | 再约 3–5 周 |
| 原始完整范围（S0–S13） | 30–49 人日 | 36–59 人日 | 约 8–12 周 |

缓冲按各行独立向上取整，分阶段区间端点不要求与总计完全相加。
这是规划区间，不是日期承诺；不能整日投入时按实际投入比例折算。
主要不确定性是历史/授权、发布时间证据、canonical publication 扩展、多标的 DB 迁移。
采购、供应商修复、精确全收益重建、部署与真实观察不在上述工作量中，发生时单列。
不能靠取消来源一致性、放宽时间语义或降低验收维持原估算。

### 7.2 推进与并行边界

1. 先投入 S0–S1 的 2–4 人日，确认数据与模型可做，再收窄剩余估算。
2. R1 主依赖为 S2 → S3 → S4，与 S5 汇合后到 S6；S7/S8 完成后由 S9 收口。
3. 若以后两人分工，S3/S4 与 S5 可在共享 Protocol 冻结后并行，S7/S8 可并行；共享模型、migration、publisher 由单一责任人串行整合。
4. R2 的 ETF、行业/全收益、通用图表可按依赖分工；不能简单把工期减半，M0/M1 和集成仍是共同关口。
5. 生产打包、部署、观察单列 deploy/vps 切片，执行前读取对应规范并另估算。

## 8. 验收、治理与完成标准

### 8.1 最低证据

| 范围 | 必须覆盖 |
| --- | --- |
| 来源 | 错资产、缺字段、单位、跨源超限/零附近误差、空响应、stale 后继续 failover、未知 available_at |
| 数值/时间 | 窗口边界、并列值、非法 PE/PB、样本不足、交易日历、ETF 次日可用、未来修订隔离、月/年端点 |
| 发布/隔离 | 指数不修改股票 current/分母；同日 market/指数并存；跨版本/用户、并发与重复任务隔离 |
| 迁移 | market 六组件逐值一致、五档/用户覆盖不变；PostgreSQL 正向迁移、唯一约束与回滚演练 |
| 任务 | 六类 outcome 场景、checkpoint 重入、互斥、限流、零写入原因 |
| TUI | 用户/管理员权限，正常/空/过期/冲突/恢复，首屏 P0、真实日期、零意外浏览器错误、旧图表无回归 |
| signal | 80 与零利差边界、连续交易日、缺失不可评估、模型切换、去重、阻断无可执行建议 |

官方估值/全收益对账保留同口径参考日期和精度；自定义利差、分位、温度通过独立参考实现或人工例题复算，
不声称官方存在同一温度。界面能显示不能代替决策可用验收。

### 8.2 治理路由与检查

- 实施激活时按 `governance/active_plan_registry.json` 现行结构登记，本次仅修订计划，不伪造激活/完成。
- 新数据面同步 current_data_contracts.json，遵循 `docs/development/data-freshness-contract-guard.md`；任务遵循 `docs/development/celery-task-contract-guard.md`，登记精确测试函数。
- 模块变化遵循 `docs/architecture/MODULE_MAP.md`；API 遵循 `docs/development/outsourcing-work-guidelines.md`，与较新 AGENTS 冲突时以 AGENTS 为准。
- TUI 同步 `docs/development/tui-user-facing-design-standard.md`、`docs/development/tui-workbench.md`、IA、schema/compiler/runtime；涉及 Web 迁移归属时同步迁移矩阵/配置，不新增 Classic 业务页。
- 每片更新本计划证据；正式纳入导航时同步 docs/INDEX.md、docs/plans/README.md，不改无关状态文档。

按切片执行适用检查，Python 使用 agomtradepro 环境：

```bash
python scripts/check_mypy_regression.py <changed-production-python-files>
python scripts/check_mypy_debt_ceiling.py
python scripts/check_celery_task_contracts.py
python scripts/check_current_data_contracts.py
python scripts/build_module_map.py
python scripts/check_module_map.py
python scripts/web_template_migration_inventory.py --check
pytest tests/unit/data_center/test_market_thermometer_tasks.py -q
pytest tests/unit/test_tui_workbench.py -q
pytest tests/unit/test_terminal_agent_service.py -q
npm run build:tui
npm run check:tui
npm run test:tui-js
```

另补本片 Domain/Repository/API Content-Type、状态码、权限测试，以及架构、格式与增量静态检查。
影响 SDK/MCP/内部访问时再运行 sdk/tests/test_sdk/test_client.py、
tests/unit/test_internal_ssl_redirect.py 等回归；不能运行的检查说明原因和影响。
SQLite 不替代 PostgreSQL 迁移/锁验证，metadata 校验不替代浏览器主任务验收。

### 8.3 完成判定

- **R1 完成**：S0–S9 出口通过，真实数据支持冻结 R1；用户可查看当前温度、依据、实际可用历史及证伪。不足十年如实标注，不伪造历史。
- **R2 完成**：S10–S13 通过，ETF 三件套与拥挤度、行业及环比、官方全收益、散点/所需双轴全部交付，缺项明确列为完整版未完成。
- **共同条件**：market 无回归、发布无污染、stale/缺失阻断贯穿 signal/TUI、适用门禁通过、迁移及关闭新能力的演练有证据。
- 开发验收与生产可用分开记录，未部署及无真实观察证据不称生产上线完成。

## 9. 风险与回滚

| 风险 | 处理与回滚点 |
| --- | --- |
| 来源不满足历史/口径 | M0 阻塞对应交付，保留样本；不用估算或其他指数替换 |
| 迁移破坏旧行为 | 备份并在 PostgreSQL 演练；分加字段/回填、兼容代码、约束切换、启用指数四步，各步验证 |
| 逆迁移唯一约束冲突 | 多标的/多修订写入后不直接逆迁移；优先关闭指数入口/任务/信号，保留兼容 schema 和 market。退旧 schema 另做数据保全及恢复演练，不删指数行凑约束 |
| 参数造成历史漂移 | 新参数/模型版本，保留旧快照与 signal 绑定，按版本切回，不覆盖 |
| ETF/回填缺失 | 保留 checkpoint，独立 R1 可继续；R2 阻断，不同名静默降级 |
| 图表回归 | 回退相应前端源和构建物，保留 R1 line/datagrid；R2 图表保持未完成 |
| 生产窗口不具备 | 保留候选、测试、回滚证据，部署与观察另行安排 |

## 10. 本次修订记录

- 已完成：静态代码/供应商文档核对、方案纠错、分层交付、参数候选、隔离迁移/验收设计、S0–S13 切片与工期。
- 未完成：数据实测、模型验证、实现、迁移、自动化回归、浏览器 UAT、部署与观察。
- 本次文档修改仅核对内容、引用路径及格式，不把规划测试写成已通过。
