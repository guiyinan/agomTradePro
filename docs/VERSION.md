# AgomTradePro 版本号管理规范

> **当前版本**: `0.7.0`
> **Build 日期**: `2026-03-23`
> **完整版本号**: `0.7.0-build.20260323`
> **开发文档快照**: `2026-05-08`

---

## 版本号格式

采用**语义化版本**（Semantic Versioning）+ **Build 日期**组合：

```
主版本号.次版本号.修订号-build.日期

示例：0.7.0-build.20260323
```

### 版本号组成

| 组成部分 | 说明 | 变更时机 |
|---------|------|---------|
| **主版本号** | 架构级变更 | 不兼容的 API 变更、重大架构重构 |
| **次版本号** | 功能级变更 | 新增功能模块、重要功能改进 |
| **修订号** | 修复级变更 | Bug 修复、小优化 |
| **Build 日期** | 构建日期 | 每次发布时更新，格式 `YYYYMMDD` |

---

## 当前版本信息

```
版本: 0.7.0
代号: AgomTradePro
状态: 开发中
Build: 2026-03-23
文档快照: 2026-05-08
```

> 当前公开版本号仍为 `0.7.0`。2026-03-23 之后的功能收口、界面整合与架构修复仍记入 `Unreleased` / 开发快照，尚未单独切出新发布版本号。

## 0.7.0 之后的开发快照（截至 2026-05-08）

- `2026-05-10` Dashboard / Decision Workspace 的退出链路 deep link 已补齐锚点定位与高亮提示；首页“退出链路入口”现在会自动收起已采纳 / 已忽略项，避免重复提醒；Workspace 侧也已改为复用统一 `dashboard_detail_url`，并新增模板 guardrail 防止回退到手拼链接；Alpha Trigger → Workspace 的旧参数桥接也已兼容收口到 `security_code/action/step`；Dashboard / Equity 的 Workspace 入口现在统一走 canonical URL builder，`进入 Step 4 / 去 Step 5` 链接已与真实 step 参数对齐；Decision Workspace 的 `user_action_label` 也已改为后端单源下发，前端不再独立维护一套显示口径；主页 query / API / SDK / MCP 暴露的退出项也已收口到同一套 canonical Workspace URL 与 processed 状态字段，减少前后端各自补丁造成的漂移
- `2026-05-08` 本地 Alpha ETF fallback 已补入 seed data，Fund / Dashboard 相关 smoke contract 也已对齐当前页面行为；离线回归与降级路径的可重复性更稳
- `2026-05-07` 宏观治理与 Dashboard 数据流继续收口；累计类宏观输入现在不会再误入 Regime / Pulse 的实时语义链路
- `2026-05-07` `task_monitor` 载荷口径已标准化，VPS SQLite 启动任务的序列化问题已修复，任务可见性与远端启动排障更稳定
- `2026-05-06` 宏观指标治理 seeds 与 CI / 测试基线已对齐当前实现，治理 guardrail 与 smoke contract 误报继续减少
- `2026-05-05` Dashboard Alpha 新增完整排名入口；Data Center governance 与宏观页面探索能力继续扩展
- `2026-05-04` 基金研究工作流、宏观同步覆盖面与 `DR007` 同步链路继续扩展 / 修复；MCP 文档快照已更新到 `326`

- 宏观数据中心页面已在前端显式把 Data Center 倒序返回的时间序列标准化为“过去 → 现在”，修复图表时间轴左右颠倒、切换指标后最新值取错的问题
- 宏观数据中心页面现在会显式区分“未同步”和“未接入”：前者表示该指标已接入自动同步但当前库里暂无事实数据，后者表示目录有定义但尚未接入自动抓取链路；页面头部也新增“全部刷新可抓取指标”按钮，仅对已接入自动同步的指标批量补抓
- 宏观治理白名单已按 `2026-05-04` 的真实抓取冒烟结果扩到 53 个可自动同步指标；新增放开的包括 PMI/非制造业 PMI、SHIBOR、LPR、RRR、DR007、新增信贷、人民币存贷款、国债收益率、运价指数、PMI 分项等，页面“全部刷新可抓取指标”会覆盖这批已验证可回数的序列
- `CN_DR007` 已切换到按区间调用 `repo_rate_hist(start_date, end_date)` 并显式读取 `FDR007` 列，不再依赖无参数默认返回的 2020 年旧样本；该指标现已重新纳入自动同步
- 宏观页图表展示现在额外在前端做时间序列强制正序兜底：无论首屏 SSR 注入数据还是切换指标后的 API 返回数据，最终都统一按 `past -> now` 排序再渲染，避免 `CN_IMPORT_YOY` 一类序列出现 x 轴左右反转
- 宏观序列顺序职责已进一步固化：Data Center `macro/series` API 继续明确提供“最新优先”的倒序数据，宏观页面与 UI helper 则统一在展示层转成 `past -> now`；相关仓储、用例与模板回归测试已补齐，避免不同指标或不同入口出现顺序规则漂移
- 登录页与注册页已切换到轻量认证基座，不再默认加载全站导航、浮动告警中心和多组无关前端依赖；匿名认证页首屏负担已明显收敛
- `core.context_processors.get_market_visuals` 现对匿名 `/account/login/` 与 `/account/register/` 做默认值短路，不再为认证页额外触发运行时配置摘要读取
- Data Center 与 Macro 页面已补齐 GDP 语义修正：`CN_GDP` 明确标记为“国内生产总值累计值”，并通过元数据暴露 `series_semantics` / `paired_indicator_code`，避免把季度累计额误读成单季值或同比
- 宏观页默认展示逻辑已支持语义优先级；当 `CN_GDP` 与 `CN_GDP_YOY` 同时存在时，会优先落到同比增速，季度标签也统一显示为 `YYYY-Qn`
- 宏观图表治理已进一步从“页面规则”下沉到指标元数据：`IndicatorCatalog.extra.chart_policy` 现统一由语义规则驱动落库，当前标准化为 `continuous_line` / `period_bar` / `yearly_reset_bar` 三类；对累计值类指标还会同步落库 `chart_reset_frequency` / `chart_segment_basis`，宏观页据此统一复用 reset-stack 图表逻辑，避免再按指标代码写展示特判
- reset-stack 类累计值图表现统一隐藏图例，直接依赖柱内颜色分段与 tooltip 展示周期位次，减少 `CN_GDP`、固投、工业利润等图表的纵向占用
- active 宏观指标现已补齐显式 `series_semantics`，包括累计值、当期流量、余额、指数、利率、同比/环比与 compat alias 口径；`python manage.py init_macro_indicator_governance --strict` 可幂等修复这套治理元数据并作为新环境初始化护栏
- `python manage.py sync_macro_data` 已修复 GDP / 月度指标将 `PeriodType` 枚举误写入 JSON 的问题，`CN_GDP_YOY` 可正常回填入库
- 宏观口径治理已扩展到 M2、CPI、PPI、社零、固投、工业增加值、外储、社融、进出口等高风险指标；`IndicatorCatalog` 现在会显式标注 level / index_level / yoy_rate / cumulative_level / balance_level 等语义
- AKShare 采集链已校正 `CN_RETAIL_SALES` 与 `CN_FX_RESERVES` 的 code-to-column / code-to-unit 对应关系，避免把社零同比误当总额、把外储亿美元误写成万亿美元口径
- Data Center 新增宏观数据治理台 `/data-center/governance/`，集中审计 legacy source 别名、catalog-only 缺口、可自动补同步缺口和配对序列缺失，并提供一键修复入口
- 固定资产投资、社会融资规模、进出口口径已进一步治理：`CN_FIXED_INVESTMENT/CN_FAI_YOY` 与 `CN_SOCIAL_FINANCING/CN_SOCIAL_FINANCING_YOY` 已接入并完成回填；`CN_EXPORTS/CN_IMPORTS` 已纠正为金额口径，`CN_EXPORT_YOY/CN_IMPORT_YOY` 单独承载同比口径
- 宏观运行配置已开始从代码常量下沉到 `IndicatorCatalog.extra`：调度频率、发布时间 lag、季度发布时间窗口、period override 现可通过运行时 metadata 暴露给页面、SDK 与 MCP
- `sync_macro_data` 现直接读取 catalog runtime metadata 解析 period_type；季度调度判定也已补齐，不再出现 `quarterly` 配置存在但运行时永远不触发的问题
- 宏观 fetcher 层的单位解析已开始优先读取 runtime metadata / unit rule，本地 `INDICATOR_UNITS` 退化为 fallback，不再作为抓取链的主要口径真源
- 宏观治理台的巡检范围与自动补数范围也已下沉到 `IndicatorCatalog.extra`；治理台不再依赖页面层硬编码指标列表
- legacy source 统一逻辑现优先读取 `data_center_macro_fact.extra.source_type`，再结合 `ProviderConfig.name -> source_type` 推断 canonical source，页面层不再维护独立 alias 常量表
- Data Center 全部事实表后续新增写入已统一使用 canonical `source_type`；provider display name 仅保留在 `extra.provider_name` 与审计链路
- `apps/data_center/migrations/0017_canonicalize_fact_sources.py` 已完成存量事实表 `source` 规范化整改，覆盖 macro/price/quote/fund/financial/valuation/sector/news/capital flow
- 宏观调度、publication lag、period override 的本地治理 fallback 表已移除，运行时统一以 `IndicatorCatalog.extra` 元数据为准
- `apps/data_center/migrations/0018_seed_macro_compat_alias_catalog.py` 已将剩余 legacy code alias 下沉为 catalog-managed 兼容别名，`apps/macro/application/indicator_service.py` 不再维护本地 `LEGACY_CODE_ALIASES`
- `tests/guardrails/test_logic_guardrails.py` 已新增宏观治理防回归护栏：禁止重新引入本地 fallback 常量，并要求最小健康基线数据下治理摘要保持全绿；该 guardrail 会被核心 CI 持续执行

- `main` 已拉齐到最新通过 CI 的开发主线，当前公开主线包含宏观单位治理、Alpha/Qlib 运维台和异步任务可见性修复
- `/equity/screen/` 的“系统自动推荐”按钮现已改为真正触发 `/api/dashboard/alpha/refresh/` 后再回读推荐结果，并对当前推荐股票顺手同步 `/api/equity/valuation-data/sync/` 与 `/api/equity/financial-data/sync/` 真源数据；不再只是重复读取旧的 `/api/dashboard/alpha/stocks/` 缓存视图，页面摘要也会显式展示最新评分日，便于识别像 `2026-05-06` 收盘后仍停留在 `2026-04-30` 这类新鲜度问题
- `/equity/screen/` 读取 `/api/dashboard/alpha/stocks/` 时现已显式附加时间戳并使用 `cache: 'no-store'`，避免浏览器继续复用更早的 `2026-04-24` JSON 响应而掩盖服务端其实已经切到 `2026-04-30` 的情况
- Alpha / Qlib 的收盘后自动链路已补齐三处修复：`qlib_predict_scores` 在刷新本地日线后会强制清空单进程 qlib 初始化状态，避免首个任务明明把数据刷到 `2026-05-06` 却仍按旧的 `2026-04-30` calendar 继续推理并落旧 `asof_date`
- `qlib_daily_scoped_inference` 现改为按“最近一个已收盘交易日”而不是裸 `localdate()` 决定目标交易日，并对已有 `asof_date == intended_trade_date` 的 scoped qlib cache 做幂等跳过；午夜到次日收盘前的恢复任务会继续补前一交易日，不会误切到尚未收盘的“今天”
- Celery 现显式声明 `celery / qlib_infer / qlib_train` 队列，并新增 `qlib-post-close-scoped-inference-recovery` 收盘后恢复调度；即使 beat 晚于 `17:40` 启动，后续 `18:00-23:50` 的恢复窗口仍会自动补跑缺失 scoped inference，不再依赖页面手点触发
- `/equity/screen/` 新增直达 `/dashboard/alpha/ranking/` 的“查看完整排名”入口，并沿用当前 URL 中的 `portfolio_id / pool_mode / alpha_scope`；财务与估值展示继续坚持单一真源优先，未同步时保持空值而不是混源 fallback
- `/equity/screen/` / Dashboard Alpha 上下文中的财务与估值字段现已明确只读取 `data_center` canonical fact tables；旧 `equity_financial_data` / `equity_valuation` 镜像表不再参与页面展示兜底，避免 Alpha 股票池看到“有旧本地值但不是真源”的混源结果
- `DjangoStockRepository.list_active_stock_codes()` 的默认 universe 已从仅 `equity_stock_info.is_active=True` 扩到“legacy active + Data Center 当前 `price_covered` canonical stock”，财务同步、估值同步与估值质量校验的默认覆盖面已从本地 10 只扩大到当前实际可见的 49 只，避免后台定时任务继续只围着旧 active 清单打转
- `/api/dashboard/alpha/stocks/` 现已通过 `never_cache` 返回 `Cache-Control: no-store`，避免 Dashboard / Equity Screen / 浏览器 fetch 在同一登录态下继续复用陈旧 Alpha JSON
- Alpha ops、Dashboard Alpha refresh、Policy RSS 抓取和 Data Center decision reliability repair 现在都会在返回 `task_id` 后立即向 `task_monitor` 写入 `pending` 记录
- `provider_filter` 单点探测失败不再误报全局 `provider_unavailable`，Alpha 运维告警语义与 Dashboard fast-path/fallback 语义已对齐
- 新增回归脚本 `python scripts/run_alpha_ops_regression.py`，当前覆盖 Alpha ops、Dashboard、Policy RSS 和 Data Center decision reliability repair 的关键回归点

- Alpha / Qlib 运维台 V1 已落地：新增 staff 可读、superuser 可执行的推理管理与基础数据管理页面，方便统一查看激活模型、缓存、任务、告警与本地 Qlib 数据状态
- 这轮运维台与 Nightly 修复没有变更 MCP 外部契约：SDK/MCP 的 tool 名称、参数 schema、canonical API 路径与 RBAC 语义保持不变
- `tests/integration/test_alpha_stress.py` 已切到默认离线 ETF fallback mock，避免 GitHub Actions 上偶发落到 `akshare` 远端请求；最新 push CI 与 Nightly 已重新全绿
- Dashboard / SDK / MCP 的 Alpha 候选读取链已统一支持 `pool_mode` 和共享 `contract` 元数据，明确区分研究排序、异步刷新与真实可行动推荐
- Alpha 账户驱动股票池补齐价格覆盖同步与资产主数据回填，账户池稳定性、可解释性和跨入口一致性进一步提升
- Pulse 重算前会先刷新上游宏观输入；当当前 Regime 只能解析到 `Unknown` 时，系统会保留最近有效的 Pulse 快照而不是覆盖成未知状态
- Alpha cache 读取已回收至 repository 边界，Architecture Layer Guard 与整条 Nightly 主回归重新恢复绿色
- Domain / Application 层一批静默 `except Exception:` 已改成显式日志分支，架构治理时可以保留降级行为，同时不再无痕吞错
- Strategy 外部 provider 已移除对 macro / asset_analysis / signal / equity / fund ORM model 的跨 App 直连，统一改走 Application Service / Repository Provider / Facade 边界
- Asset name resolution 桥接已回收到 equity / fund / rotation / asset_analysis 各自应用层公开入口，`asset_analysis` 与 `core/integration` 不再跨过去直接访问这些模块的 ORM
- Asset pool screening 桥接已改为调用 equity / fund 各自 application facade，`core/integration` 不再自行组装 scorer + repository
- asset_analysis 跨 App 市场协作已升级为 shared technical registry；equity / fund / rotation 在启动时注册 repository / screener / name-resolver，旧 `core/integration/asset_analysis_market_sources.py` 已移除且未引入新循环依赖
- `tests/unit` 缺失的测试包入口已补齐，Nightly 全量 pytest 收集不再因重复测试文件名触发 `import file mismatch`
- 多个 Application provider 入口已改回按调用时解析 concrete implementation，并补回 Alpha / StopLoss 旧测试契约兼容层，Nightly 可继续暴露真实单测失败而不是被 patch 断点卡住
- Nightly integration 步骤已从 `pytest-xdist` 并行改为串行执行，并补充 `faulthandler` / per-test timeout，优先保证 GitHub hosted runner 上的稳定性与可诊断性
- Strategy 执行在 investable asset pool 尚未预热时会回退读取 asset_analysis 最新评分缓存；Decision Workspace AI 证伪草稿接口已切到新的 `generate_chat_completion` 参数签名
- 统一账户 API、SDK 与 MCP 契约进一步收口，统一到账户绩效、估值与 canonical 路径
- Equity Detail 补齐技术图表、分时数据 fallback 与更完整的市场上下文展示
- Equity Detail 在本地股票主数据或估值缓存缺失时，支持基础信息回退与部分加载，避免详情页整体阻塞
- Equity Detail 日线/Regime 相关性在本地缓存缺失时接入 Tushare Gateway 历史行情回退，降低单一 AKShare/EastMoney 失败影响
- Equity Detail 历史行情回退新增 read-through cache，远端成功返回后会幂等写回本地 `equity_stock_daily`
- 系统设置中心、管理员界面、MCP Tools、服务日志与文档管理页统一到共享管理界面
- 财经数据源配置页收口为统一数据源中心，支持 Provider Inventory 与运行时连接测试
- RSS 管理页支持 RSSHub / timeout / retry / proxy 等更完整的源配置
- GitHub Actions 架构与逻辑门禁已跟上这轮界面和数据源收口后的最新代码边界

---

## 版本演进历史

### 0.7.0 (2026-03-23)

**新增模块**:
- `setup_wizard` - 系统初始化向导（首次安装引导）
- `ai_capability` - AI 能力目录与统一路由
- `terminal` - 终端 CLI（AI 交互界面）
- `agent_runtime` - Agent 运行时
- `pulse` - Pulse 脉搏层（战术指标聚合与转折预警）

**功能改进**:
- 网页版安装向导，引导配置管理员密码、AI API、数据源
- 密码强度实时检查
- 已初始化系统需密码验证才能修改配置

**模块数量**: 35 个业务模块

---

### 0.6.0 (2026-03-19)

**新增模块**:
- `ai_capability` - 系统级 AI 能力目录与统一路由

**功能改进**:
- 支持四种能力来源：builtin/terminal_command/mcp_tool/api
- 统一路由 API
- 自动采集全站 API 并进行安全分层

---

### 0.5.0 (2026-03-17)

**新增模块**:
- `terminal` - 终端 CLI（终端风格 AI 交互界面）
- `agent_runtime` - Agent 运行时（Terminal AI 后端）

**功能改进**:
- 支持可配置命令系统（Prompt/API 两种执行类型）
- 任务编排和 Facade 模式

---

## 版本号使用场景

### 1. 文档中引用版本

```markdown
> **版本**: 0.7.0
> **Build**: 2026-03-23
```

### 2. API 响应中返回版本

```json
{
  "version": "0.7.0",
  "build": "20260323",
  "modules": 35
}
```

### 3. 代码中获取版本

```python
# core/version.py
__version__ = "0.7.0"
__build__ = "20260323"

def get_version():
    return __version__

def get_full_version():
    return f"{__version__}-build.{__build__}"
```

### 4. Git 标签

```bash
git tag -a v0.7.0 -m "Release 0.7.0: Setup Wizard + AI Capability"
git push origin v0.7.0
```

---

## 版本发布流程

### 1. 开发阶段
- 在 `develop` 分支开发
- 版本号保持 `-dev` 后缀，如 `0.8.0-dev`

### 2. 测试阶段
- 合并到 `release` 分支
- 版本号改为 `-rc.N`，如 `0.8.0-rc.1`

### 3. 发布阶段
- 合并到 `main` 分支
- 更新 Build 日期
- 创建 Git 标签 `v0.8.0`
- 更新本文档的版本历史

---

## 版本号变更规则

### 主版本号 (0 → 1)
- [ ] 生产环境首次正式部署
- [ ] API 发生不兼容变更
- [ ] 数据库架构重大调整
- [ ] 核心架构重构

### 次版本号 (7 → 8)
- [x] 新增业务模块
- [ ] 重大功能改进
- [ ] 性能大幅优化

### 修订号 (0 → 1)
- [ ] Bug 修复
- [ ] 小功能优化
- [ ] 文档更新

---

## 相关文件

| 文件 | 用途 |
|-----|------|
| `docs/VERSION.md` | 版本号管理规范（本文档）|
| `core/version.py` | 版本号常量定义 |
| `AGENTS.md` | AI Agent 指引（引用版本号）|
| `README.md` | 项目说明（引用版本号）|
| `docs/INDEX.md` | 文档索引（引用版本号）|

---

## 版本号同步检查清单

发布新版本时，需更新以下文件：

- [ ] `core/version.py` - 版本号常量
- [ ] `AGENTS.md` - 项目概述中的版本号
- [ ] `README.md` - 项目说明中的版本号
- [ ] `docs/INDEX.md` - 文档索引中的版本号
- [ ] `docs/VERSION.md` - 版本历史记录
- [ ] `docs/governance/SYSTEM_BASELINE.md` - 系统基线中的版本号
- [ ] `docs/SYSTEM_SPECIFICATION.md` - 系统规格书中的版本号

---

**维护者**: AgomTradePro Team  
**最后更新**: 2026-04-30
