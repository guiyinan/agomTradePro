# Scripts、文档与 MCP 存量治理计划

> 2026-10-26 重构衔接：新增的 [数据边界收敛与交付衔接计划](data-boundary-convergence-plan-2026-10-26.md) 作为本工作流支撑计划，REF-01～06 复用当前字典、架构门和运行器；GOV-04/05 优先当前交付的真实失败，GOV-06/07 保持 deferred。不得因重构复制新的审批、台账或按小修生成整套证据包。

> 创建日期：2026-10-14
> 范围：文档导航与状态去重、脚本可靠性与复用审计、legacy MCP 分批收敛。
> 执行状态、依赖和退出门唯一真源：[active_plan_registry.json](../../governance/active_plan_registry.json) 中的 `repository-maintenance-governance` 工作流与 `GOV-03`～`GOV-07`。
> 本文定义工作内容和验收方法；实际进展由机器登记及对应证据表达。

## 1. 问题与目标

本轮治理由三项维护问题触发：脚本层承担越来越多治理与验收职责，文档索引混入历史执行状态，legacy MCP 实现仍需维护。目标是让关键检查可靠、文档状态可追溯、兼容入口有明确退出路径。

不以减少文件数、代码行数或工具数量作为单独完成标准。不能通过删除测试、放宽门禁、移动代码来改变统计口径，或给每个旧工具机械补建新工具来交差。

### 1.1 已核对的事实与待验证假设

| 对象 | 已核对的事实 | 尚不能得出的结论 |
| --- | --- | --- |
| 脚本测试 | `tests/unit/`、`tests/guardrails/` 已有直接导入脚本的测试；`.coveragerc` 与测试质量基线没有将 scripts 单列为覆盖范围 | 不能宣称 scripts 无测试，也不能宣称其关键失败分支已充分覆盖 |
| 文档导航 | 本轮修改前 `docs/INDEX.md` 有 1,411 行；总索引和计划索引同时积累生产检查点、历史焦点和状态表 | 文档日期旧不等于内容失效；历史证据不能按年龄批量删除 |
| 文档一致性 | 原总索引顶部、底部更新时间不同；计划索引仍展示早期治理数量和已被后续事项取代的执行焦点 | 原检查通过不意味着这些文字可以解释为今天的生产状态 |
| MCP 总量 | 静态定义总量、legacy 投影、默认顶层暴露面是不同口径，字段见机器基线 | 总量不能等同模型每次收到的工具数量 |
| MCP 无正式替代项 | 已有 `legacy_dispositions.py` 分类、owner、理由与部分推荐能力；登记完整性见机器基线 | 无正式 replacement 不一定是业务功能缺口；有分类也不等于可以安全删除 |

用户前述 scripts 行数及其与 core/shared 的比例作为审计线索，本轮未重新按统一口径统计。后续审计必须给出扫描范围、候选 SHA、语言、空行/注释与生成文件的排除规则。

### 1.2 成功后的行为

1. 新加入者从总索引进入规范、主计划或证据目录，无需从执行日志判断当前焦点。
2. 治理脚本遇到缺报告、过期候选、损坏输入、失败子进程或未知结果时，输出可诊断的失败并阻断放行。
3. 多入口复用同一规则，CLI 参数、退出码和现有 CI 调用保持可验证的兼容性。
4. 旧 MCP 入口有调用证据、明确处置与退役门，默认发现面不回涨。

## 2. 范围、所有权与执行边界

### 2.1 工作分层

| 主线 | 所有权 | 本轮交付 | 后续交付 |
| --- | --- | --- | --- |
| 文档 | Repository owner / governance maintainer | 总索引、计划索引、导航目录、历史归档、相关口径纠正 | 按专项问题继续清理，不扩大到业务设计重写 |
| 脚本 | 各脚本实际业务或工具 owner | 详细计划、审计字段与检查方法 | 风险清单、失败测试、有限复用与覆盖率治理 |
| MCP | SDK / MCP 与各 capability owner | 详细计划、口径与退役标准 | 调用盘点、处置核验、分批兼容迁移及退役 |

### 2.2 约束

- 本轮是文档与计划登记变更，不执行脚本重构、MCP 删除、生产部署、数据库写入或真实 provider 调用。
- 保留已有 `execution_focus`；文档治理通过允许的 governance mode 进行。脚本/MCP 实现须按机器调度进入唯一 repository 主线，不能以本计划为理由并行扩展实现边界。
- 不修改生产验收单元的状态、候选绑定或停止线；历史候选不能被文档清理晋升为当前生产候选。
- 保留用户未提交代码；本计划的提交仅纳入对应文档和登记文件。
- 正式 JSON 证据、SHA sidecar、固定测试 fixture 和 content-addressed 绑定保留原路径与原始字节。
- 发现业务配置、业务规则或越层调用时先识别 owner，遵守四层依赖及 `shared/` 不依赖 `apps/` 的约束。

## 3. 真源与文档职责

| 信息 | 真源 | 导航/说明应如何表达 |
| --- | --- | --- |
| 版本与 build | [VERSION.md](../VERSION.md)，与 `core/version.py`、`pyproject.toml` 一致性校验 | 总索引仅给版本入口 |
| 依赖 | [pyproject.toml](../../pyproject.toml) | requirements 由同步脚本生成 |
| 模块结构、入口与路由 | [module_map.json](../../governance/module_map.json) | 由 build/check module map 生成和核验 |
| 动态治理规模 | [governance_baseline.json](../../governance/governance_baseline.json) | 不复制当前数字作为第二基线 |
| 测试覆盖率门槛 | [testing_quality_baseline.json](../../governance/testing_quality_baseline.json) | [覆盖率治理说明](../development/ci/coverage-governance.md)解释口径 |
| 工作流、依赖、执行焦点和阶段状态 | [active_plan_registry.json](../../governance/active_plan_registry.json) | 计划索引只导航，不维护另一套状态表 |
| MCP 默认工具契约 | `sdk/agomtradepro_mcp/tools/core_tools.py` 与 `scripts/check_mcp_tool_budget.py` | 区分顶层工具、governed capability 与 legacy 实现 |
| MCP 未正式替代项的处置 | [legacy_dispositions.py](../../sdk/agomtradepro_mcp/legacy_dispositions.py) | 引用 owner、理由和推荐能力，不推定需要一对一替代 |
| 生产事实 | `docs/deployment/` 内绑定候选、环境、观测时间与 hash 的证据 | 按范围解释；不能以最新文件或健康码推断业务验收 |
| 历史过程 | `docs/archive/` 与原始专项 evidence | 标明原时点，链接到当前入口 |

总索引建议控制在 200 行以内，计划索引建议控制在 250 行以内；这是导航预算，不是删证据的理由。专题目录可容纳更完整的文档链接。新增索引条目描述用途，不追加 CI 数字、生产 SHA、观察窗口或“唯一焦点”叙事。

## 4. 阶段与完成标准

| 阶段 / canonical unit | 优先级 | 输入 | 主要产物 | 退出条件 |
| --- | --- | --- | --- | --- |
| D0 / `GOV-03`：计划与导航清理 | P1 | 现有索引、注册表、基线、候选一致性测试 | 本计划、精简索引、专题目录、历史归档、验证记录 | 链接可达、状态真源清晰、候选投影不漂移、旧记录可追溯 |
| S1 / `GOV-04`：脚本审计 | P1 | 脚本、工作流、测试、调用方 | 风险分级清单、调用与测试映射、重复实现候选、首批整改包 | 高风险入口全部有 owner、调用方、失败测试证据或明确缺口 |
| S2 / `GOV-05`：关键脚本可靠性 | P1 | S1 缺口与原契约 | 失败测试、有限修复、独立覆盖报告与 CI 接线 | 选定关键脚本无已知误放行；真实 CLI 退出行为被验证 |
| S3 / `GOV-06`：复用与生命周期 | P2 | S1 重复与退役候选 | 小范围规则提取、兼容包装、归档/删除证据 | 调用方同步、测试通过、规则只有一个实现、无架构回退 |
| M1 / `GOV-07`：MCP 收敛 | P2 | manifest、legacy disposition、SDK/HTTP/运行调用证据 | 全量处置核验、按 owner 的迁移批次、退役证据 | 每项去向明确；有证据的批次完成，无证据的保留项具备复审条件 |

依赖顺序：D0 → S1 → S2 → S3；M1 在 D0 后可先做静态审计，实现与删除仍遵守 repository focus。M1 不依赖完成全部 scripts 重构，也不挤占生产恢复主线。

建议容量预算：D0 一次文档批次；S1 约 1～2 人日；S2/S3 每批 2～5 个入口；M1 每批一个业务 owner 或 3～5 个相近 legacy。预算是排期估算，S1 发现复杂度后重新评估，不承诺按日期完成整个存量。

## 5. D0：本次文档清理方法

1. 改写 `docs/INDEX.md` 为角色入口、真源导航、专题目录、阅读路径和维护规则。
2. 将较完整的文档条目放入 `docs/CATALOG.md`，剥离各条目的当前完成/部署状态；活跃计划指向 `docs/plans/README.md` 与注册表。
3. 精简 `docs/plans/README.md`，移出多轮执行记录、历史焦点、数量快照和重复 backlog 状态；保留工作流与主文档入口、维护纪律及机器字段映射。
4. 将被移出的历史叙事集中保存于 `docs/archive/documentation/`，记录来源与整理日期，重算相对链接；历史“当前”仅按原日期解释。
5. 纠正 `SYSTEM_BASELINE.md` 中“仍有临时大文件 allowance”、覆盖率真源和生产就绪含义等已能从机器规则确认的问题。
6. 给 MCP 历史收口证据增加范围说明，避免把某次验收结果当作永久零 legacy 或今天的默认工具预算。
7. 保留受候选一致性测试约束的 M5 最小投影，并标明它是 canonical cutover 绑定的兼容投影，不能代表今天的 VPS 状态。后续若消除此投影，须连同检查消费方式另开代码批次。
8. 登记本计划和 canonical units，原有生产状态、依赖、focus 与证据字段保持不变。

清理范围仅覆盖此次识别的问题及其导航引用方。业务规范、生产原件和仍在实施的主计划不因日期较旧而移除。

## 6. S1：脚本风险、测试与复用审计

### 6.1 盘点字段与计数口径

清单逐脚本登记：路径、语言、owner、用途、CLI/可导入模块/共享库类别、调用方、读取资源、写入资源、输入 schema、退出码、报告格式、幂等性、授权边界、测试文件、执行证据、风险等级、处置与复审触发条件。

全量盘点包含 Python、PowerShell、Shell、JavaScript 与 SQL；`scripts/debug/`、`scripts/backup/`、生成输出及第三方代码分别标识，不能混入生产工具覆盖率分母。记录总行与非空行；与 core/shared 比较时使用同一排除规则。

调用来源至少覆盖 `.github/workflows/`、部署包、`pyproject.toml`、Git hooks、其他脚本、Python imports、测试动态加载、文档命令与计划/证据引用。静态未引用不等于运行时无人使用。

### 6.2 风险分级

| 风险 | 例子 | 必须核验 |
| --- | --- | --- |
| 高 | release/S6 聚合、候选身份检查、部署、备份恢复、生产 evidence recorder | 缺输入/错误身份/子进程失败时阻断；写入与只读隔离；回滚与幂等 |
| 中 | AST 扫描、契约检查、投影生成、测试选择、覆盖率报告 | 真实违规识别、合法输入不过度拒绝、扫描范围、路径/别名/多行边界 |
| 低 | 开发启动、诊断、演示、一次性历史迁移 | 当前用户、运行依赖、入口兼容、可归档性 |

首批优先检查 `run_release_rehearsal.py`、`validate_release_rehearsal.py`、`rc_gate_report.py`、`check_governance_consistency.py` 与一个生产证据 recorder 的完整调用链。每批边界由 S1 实际发现调整，不因为文件大就优先拆分。

### 6.3 测试证据

- 分别统计“有测试引用”“有行为断言”“有实际运行证据”，不能把 import 计为可靠性覆盖。
- 对参数边界、报告缺失、候选漂移、malformed JSON、子进程 nonzero、超时、部分成功、权限失败与未知结果建立失败用例。
- 校验 CLI 输出、退出码、文件写入与调用次序；高风险条件至少一个真实 CLI/subprocess 测试，不能只测 helper 返回值。
- 检查 happy path 与 false positive；防止治理器为了 fail-closed 而拒绝全部合法结果。
- 测量共用解析器、路径/候选绑定、报告聚合和 evidence 校验的重复实现，先比较行为再决定合并。

S1 报告须给出候选 SHA、分母、排除项、执行命令、原始报告位置，以及下一批 2～5 个入口的整改理由。未运行项目标为 unverified。

## 7. S2 / S3：修复、覆盖率与规则复用

### 7.1 修复顺序

先补能证明误放行或不兼容的测试，再修复规则；保留既有 CLI 参数、退出码、JSON 字段及 CI 引用。若必须破坏兼容，逐一更新引用方和契约测试，不能仅改文档命令。

脚本独立覆盖率报告先观察、再建立实测门槛。不得将 scripts 突然并入全仓覆盖分母导致已有覆盖率下降，或照搬 80%/90% 作为缺少测量的承诺。关键放行分支的故障用例是硬条件；行/分支门槛按选定范围实测后登记在测试质量真源并逐步 ratchet。

测试选择需验证“变更工具脚本是否触发它自己的测试”，不能只由 apps 改动决定是否执行。必要时修改质量目标选择器、Nightly/Consistency 接线及对应说明；仍以复用工作流为准，避免建立另一套发布检查。

### 7.2 复用去向

| 逻辑 | 建议去向 | 判定要求 |
| --- | --- | --- |
| CLI 解析、进程启动与报告写入 | 脚本入口保留薄包装 | 契约清晰，副作用显式 |
| 无业务含义的 AST、路径、JSON 校验等工具 | 先评估现有 `scripts/shared/`；跨运行时需要时再讨论独立工具包 | 有至少两个实际调用方、稳定契约和测试，避免新增大杂烩 |
| 金融规则、发布策略、业务默认值 | 所属 App 的 Domain/Application/Infrastructure 或既有机器配置 | 严守依赖方向，不能塞进 shared 来缩短 scripts |
| 候选绑定与证据校验 | 优先复用既有 owner 的公开契约 | 不产生“脚本版”业务真源或运行时反向依赖 scripts |
| 一次性迁移/诊断 | 经调用审计后归档，或显式冻结为兼容入口 | 保留可恢复来源及必要证据，不按未引用结果直接删除 |

目录、模块、依赖、入口变化须先阅读 MODULE_MAP 规范并重建投影。生产 Python 修改运行双 mypy 门禁及适用架构检查；禁止增加宽泛 ignore 或提高债务上限。

## 8. M1：MCP 分类核验与退役

### 8.1 三个独立分母

1. 默认顶层工具：实际 `server.list_tools()` 与 schema bytes，按工具预算检查。
2. governed capability：manifest/catalog 中用户可发现、可执行的能力及其授权/证据契约。
3. legacy 实现：旧工具定义、compat handlers 与 SDK/外部调用方的维护成本。

当前数值读取 `governance_baseline.json` 并由代码重新测量；本计划不再复制总量。顶层面受控不代表 legacy 无成本；legacy 有替代链接不代表调用方已迁移。

### 8.2 核验矩阵

逐项登记：工具名、owner、现有 disposition、replacement/recommended capability、输入输出兼容性、鉴权与写入性质、内部/外部调用方、使用证据时间窗、客户端版本、迁移步骤、保留理由、退役 gate、回滚路径。

优先复核无正式替代的处置项，再抽查已有 replacement 的高风险写工具。`aggregate` 检查用户主任务能否通过能力组合完成；`internal_only` 检查是否仍公开发现；`legacy_compat` 保留明确客户端需求；`remove/unsupported` 核查停止线、错误返回与历史读路径。

运行日志缺少观测能力时登记 telemetry 缺口，不能写“零调用”。观测窗口按实际客户端使用周期确定并记录，禁止为了删除而任意缩短。外部消费者的退役需满足原兼容承诺，不能仅依据仓库 grep。

### 8.3 分批执行与退出门

- 每批选一个 owner 或一组相近契约，先完成输入/输出、权限、证据与确认流的 parity 测试。
- 保留最小 deprecated wrapper 并给迁移入口；有明确需求的工具可继续保留，登记重新审核触发条件。
- 删除前证明代码与配置调用方均已迁移、运行观测覆盖约定窗口、必要客户端已升级、历史 exact 读取与回滚可用。
- 同步 manifest/catalog、SDK、TUI 引用、治理字段、文档与测试，运行预算、schema、dedup、raw-tool、read/write evidence、confirmation/preview/audit 检查。
- 不降低 write confirmation、owner isolation、read freshness 或 evidence output 的约束来获得 parity。

M1 可以以“全部处置核验完成且当前可安全删除批次已完成”验收；有真实兼容需求的保留项须逐项说明 owner、证据与复审条件，不能要求 legacy 机械归零。

## 9. 验证与证据保留

### 9.1 D0 最小验证包

```bash
python scripts/check_active_plan_registry.py
python scripts/check_governance_consistency.py --baseline governance/governance_baseline.json --format text
python scripts/check_doc_route_sdk_consistency.py
pytest tests/unit/test_web_to_tui_candidate_consistency.py -q
git diff --check
```

另检查所有本次新增/修改 Markdown 的本地文件链接及锚点、旧索引条目的迁移可达性，以及历史归档链接改写后的路径。可用 `python -X utf8` 规避 Windows 控制台编码差异；执行证据记录真实 Python 路径与版本。

### 9.2 后续实现的验证包

- 脚本：所选工具的单元/CLI 故障测试，独立行/分支覆盖报告，质量目标选择与 CI 接线测试。
- Python：增量 mypy、债务上限、Black/isort/Ruff；架构变更增加架构差异、cycle 与 module-map 检查。
- 发布/S6：按 release rehearsal policy 验证必需报告，不用文档检查代替真实候选演练。
- MCP：所选 capability/SDK contract 与全部受影响治理检查；需要时验证普通用户能完成实际主任务。
- 高风险 terminal/runtime/deploy 链路：按 AGENTS.md 选择最小回归包，仓库验证与生产验收分别列明。

临时报告进入 `artifacts/`；成为正式验收依据时选择必要原件放入 `docs/testing/` 或 `docs/deployment/`，保留候选、命令、环境、时间、原始结果与 hash。不要把临时日志继续追加到两个索引。

## 10. 风险、回滚与完成交接

| 风险 | 控制与回滚 |
| --- | --- |
| 清理后证据入口丢失 | 保存历史记录、改写相对链接；逐项核对旧导航链接能从新目录或历史入口到达 |
| 把历史状态误写为当前 | 索引只给机器源；历史归档首屏标记范围；M5 兼容投影说明不代表实时生产 |
| 用户同时修改治理代码 | 不覆盖其改动；以当前工作树执行检查并记录验证范围；本次文件单独审阅 |
| 抽取改变脚本行为 | 先行为契约后提取；小批次提交，保留兼容包装，可单独回退该批次 |
| MCP 删除破坏外部客户端 | 迁移窗口、观测、版本与回滚证据先于删除；没有证据时保留 |
| 治理增加成本但未改善可靠性 | 每批必须关联已证实缺口；不新建重复报告体系；完成后归档对应阶段计划 |

回滚按变更批次恢复对应文档/入口/注册表，使用明确文件差异或独立 revert commit，不重置工作树或覆盖用户文件。文档回滚不改变正式证据字节及生产状态。实现退役回滚保留原客户端行为与授权停止线。

交接必须分别列出：本轮已完成项、仍 planned 的脚本/MCP 工程、实际执行的检查与结果、未验证的生产调用/覆盖率风险。D0 完成不能将整个工作流标记为完成。

## 11. 本轮验证记录（2026-10-14）

执行环境：`C:/ProgramData/anaconda3/python.exe`，Python 3.13.5。指定的 `agomtradepro` 环境在本机 conda 列表中未发现；本轮使用已具备 Django/pytest 的现有环境，没有安装或修改依赖。默认 Windows GBK 输出曾导致文档/API/SDK 检查中断；使用 `python -X utf8` 后该检查通过。

| 验证 | 实际结果 |
| --- | --- |
| `check_active_plan_registry.py` | 零违规；新计划及分阶段 units 均已登记 |
| `check_governance_consistency.py --baseline governance/governance_baseline.json --format text` | 零违规；版本、真源、链接及治理接线检查通过 |
| `check_doc_route_sdk_consistency.py` | PASS；未发现文档/API/SDK 与统一账本引用违规 |
| `pytest tests/unit/test_active_plan_registry.py tests/unit/test_check_doc_route_sdk_consistency.py tests/unit/test_web_to_tui_candidate_consistency.py -q` | 11 passed |
| 本次 Markdown 本地链接与标题锚点扫描 | 10 份文档、1,058 个本地链接、16 个锚点链接，未发现悬空可点击链接 |
| 原有机器状态保全核对 | `execution_focus` 和全部既有 closure unit 的完整记录未变；仅新增治理/审查单元与相关登记 |
| 本次调整的登记测试 Black / isort / Ruff | 通过；仅修改了原测试中的动态数量副本及其直接相关断言 |
| `git diff --check` | 通过 |

清理结果：总索引 99 行，计划索引 207 行，专题目录另行承载完整导航；清理前索引冻结归档，正式证据未移动。系统基线说明已纠正覆盖率真源、临时 allowance 与生产就绪口径；MCP 历史收口记录明确了候选与日期范围。

检查暴露并处理的既有问题：M5 `next_gate` 的过期叙事已归档并改为候选真源引用，候选兼容投影测试通过；登记测试的硬编码数量改为核对机器清单、唯一归属与实际文件。Manager Holdings 原审查期限 2026-10-10 已过且无留存结论，按到期转入明确工作流的规则登记为 `MHD-01` planned governance 审查，没有延期、通过审查或批准 Probe/MVP。

首次整理时发现历史计划索引已有 7 处证据目标缺失，先保留路径并显式标记。用户随后要求补回原件，本轮已按下节恢复全部目标并复验；首次整理的缺失标记已替换为可用链接。脚本独立覆盖率、实际生产 legacy 调用与安全退役条件仍未在本轮验证，属于后续阶段。没有生产 Python 修改，未触发增量 mypy；没有生产操作或 SDK/MCP 行为变更。

本节只保留该文档批次的检查点；后续状态变更写入 canonical units，避免再次积累执行日志。

## 12. 历史缺失证据恢复（2026-10-14）

恢复原件与校验过程见 [恢复记录](../testing/historical-deployment-evidence-recovery-2026-10-14.json)。七份报告均来自本地 stash `f5d213410…` 的未跟踪文件快照 `6ae0954c6…`，不是重新生成生产结果；没有 apply、删除或修改 stash。

- 七份报告已恢复原路径，SHA-256 全部匹配独立历史文档或 content-addressed 文件名；同时恢复五份原 SHA sidecar。
- 为完整核对来源，另恢复 EVID-01、EVID-02、STRAT-01 和 AUD-03 的四份原始 capture。五个 recorder 仅执行离线 dry-run，所得 artifact SHA 全部与恢复文件一致，`written=false`。
- DATA-01 原始报告在 Git 中曾被规范化为 LF；还原原 CRLF 后精确匹配历史 `291178` bytes 和完整 SHA-256。`.gitattributes` 对恢复的 JSON 逐路径禁用文本转换，防止以后提交或跨平台检出改变哈希。
- 恢复了归档中的七处链接，部署目录补充恢复来源与保留规则；现有执行焦点、closure unit 和生产候选绑定不变。
- 最终复验：active-plan registry 与 governance consistency 均零违规；六份受影响导航文档的 670 个本地链接无悬空目标，`git diff --check` 通过。stash parent、部署候选与 deployment/raw restore/canonical restore 三份报告的备份 SHA 和大小一致性均已核对。

本次验证只证明历史字节、来源和离线派生一致，不重新宣称旧部署/恢复演练在今天通过。原来的 zero-seed、DENY、未收集审批和 Audit unavailable section 全部保留；生产接受条件仍按对应候选与时间窗核验。
