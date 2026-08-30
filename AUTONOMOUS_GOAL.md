# AgomTradePro 自主收口 Goal

> 本文件是长期运行的调度合同，不是计划状态真源，也不是 Codex 自动加载的配置文件。
> 当前状态、依赖、执行模式和唯一仓库焦点始终读取
> `governance/active_plan_registry.json`；面向人的排期解释读取
> `docs/plans/README.md`。本入口由该计划索引反向链接，任务状态不得回写到本文件形成
> 第二真源。
> 启动、换 worktree、恢复和日常控制方法见
> `docs/development/codex-autonomous-goal-usage.md`。

## 启动方式

在模型选择为 `gpt-5.6-sol` 的 Codex 任务中设置：

```text
/goal 按照 AUTONOMOUS_GOAL.md 自主推进 AgomTradePro canonical closure backlog。持续工作并在一个 closure unit 达到真实 exit gate 后自动调度下一个符合依赖和执行锁的 unit；由 Sol 负责规划、审查、验收和状态晋级，优先调用 gpt-5.6-luna 完成有界且互不重叠的实现、测试、调查和文档切片。直到不存在无需新增授权即可安全推进的 eligible work，或全部 canonical closure units 达到真实终态才停止。不得伪造证据、放宽 fail-closed 门禁或把外部阻塞解释为完成。
```

文件本身不会切换当前任务的主模型。启动 Goal 前必须在 Codex 中选择 Sol；Sol
创建子代理时显式选择 `gpt-5.6-luna`。

## 唯一目标

持续推进注册表中的 canonical closure backlog，同时始终保持一个且仅一个
`repository` unit 扩展代码边界。完成当前 `execution_focus.unit_id` 后，只有在其真实
exit gate、验证和状态同步全部成立时，才自动选择下一个依赖已满足的 unit。

“持续推进”不代表无限创建工作。它只允许处理注册表中已经存在、依赖明确、验收条件
明确的 closure unit；禁止把历史 checklist、临时发现或松散建议直接升级成新主线。

## 个人项目单一所有者模式

本仓库是个人项目，当前唯一真人项目所有者的生效授权记录为
`docs/deployment/personal-project-single-owner-authorization-2026-08-30-80ea002b.json`；
它已取代候选 `36b72d2f` 的首份授权记录。
该记录生效期间，owner、business owner、operations owner、root approver、reviewer 等治理角色
可以由同一项目所有者承担，不再要求为了形式上的职责分离寻找第二个自然人；历史计划中的
“独立 reviewer”“双签”按“同一真实所有者在对应技术证据形成后确认”解释。

该简化只取消多人签字和重复泛化审批，不取消技术事实。零行 authority、缺失业务定义、未部署
环境、未发生的模型/券商结果、未留存的监控历史和未自然经过的观察时间仍必须保持 unavailable、
DEFER 或 fail-closed，自动化不得补造。所有者已经授权仓库内有界整改，以及在精确 preflight、
停止线和回滚点齐全且技术依赖通过后执行对应生产整改；同一候选和同一 action envelope 内不再
重复索要人工批准。删除生产数据、database restore、destructive rollback、实盘交易和付费外部
模型调用仍须单独的精确动作包。

当已确认的真实阻塞需要新增一个有界 repository unit，且用户明确授权修改计划时，可以把该
unit 登记进机器注册表并设为唯一 focus；这不允许从松散建议无限扩展 backlog。

## 开始前的真源审计

Sol 在第一次派工和每次焦点晋级前必须重新读取：

1. `AGENTS.md` 以及本次文件范围内更深层的代理说明。
2. `governance/active_plan_registry.json`。
3. `docs/plans/README.md` 的维护规则、当前执行焦点和滚动执行排期。
4. 当前 unit 登记的 primary plan，以及 AGENTS.md 按改动类型要求的专项规范。
5. `git status --short --branch`、当前 diff、最近提交和相关实现/测试。

发现文档、旧 Prompt 或历史提交与机器注册表冲突时，以注册表作为动态状态真源，先收敛
冲突再实施。不得因历史上下文继续已经 completed 的 unit，也不得覆盖用户或其他代理的
未提交修改。

恢复一个已经运行过的 Goal 时，不依赖聊天摘要猜测进度。Sol 必须从当前 focus unit 的
primary plan 最新实施记录、注册表 `status/next_gate/depends_on`、已有证据 artifact 和工作树
diff 重建：已完成 checkpoint、已验证命令、未满足 exit gate、精确下一步和权限阻塞。

## Sol 调度职责

Sol 是唯一调度者和验收者，负责：

- 从当前 unit 的 exit gate 反推最小可验证切片，并维护简短的内部执行计划。
- 判断哪些工作适合交给 Luna，给每个 worker 明确文件边界、交付物、禁止事项和验证命令。
- 审查 Luna 的完整 diff 与证据；必要时由 Sol 修正架构、契约和跨模块问题。
- 运行最终的聚焦回归、架构、类型、治理和专项门禁。
- 只有真实 exit gate 成立后，才同步 primary plan、`docs/plans/README.md` 和
  `governance/active_plan_registry.json`，随后选择下一个 unit。
- 处理跨 App 架构决策、生产权限判断、候选晋级、回滚判断和最终完成声明；这些判断不得
  委托给 Luna。

## Luna worker 合同

Sol 默认复用一个 `gpt-5.6-luna` worker，reasoning effort 使用 `medium`。只有两个任务
文件范围互不重叠、验收互不依赖且并行确实缩短关键路径时，才允许同时运行第二个 Luna；
不得为了“保持忙碌”制造并行任务。

适合交给 Luna 的任务包括：

- 搜索调用链、核对实体定义、盘点缺失合同。
- 在明确边界内补测试和最小实现。
- 执行聚焦测试、静态检查或只读证据整理。
- 更新与该实现切片直接对应的计划证据。

每个 Luna 任务必须满足：

- 只处理 Sol 指定的一个 bounded subtask，不自行扩展 backlog。
- 不再创建子代理。
- 不修改分配范围以外的文件，不接触已存在的无关工作树改动。
- 不 commit、不 push、不部署、不执行生产写入、不发起付费调用、不代替人工审批。
- 返回修改文件、关键判断、执行过的验证、未验证风险和剩余问题。

Luna 完成后，Sol 必须先审查和验证结果，再使用 follow-up 继续派发下一个切片。未经审查
不得连续叠加多个 worker diff。

## 自动选取下一任务

Sol 按以下规则选择工作，不凭提交数量或主观新鲜感排期：

1. 当前 `execution_focus.unit_id` 永远优先，且是唯一允许扩展 repository scope 的 unit。
2. 当前 unit 未满足 exit gate 时保持焦点；测试通过、代码存在或文档写完都不能单独触发晋级。
3. 当前 unit 完成后，从注册表中选择依赖全部完成、执行模式为 `repository`，并且符合
   `docs/plans/README.md` 滚动排期的下一 unit。
4. 如果高优先级 unit 的生产依赖尚未满足，只能选择排期明确给出的 fallback；不得擅自
   把其他 planned unit 激活。
5. `production`、`external` 和 `governance` unit 只有在
   `execution_focus.allowed_parallel_execution_modes` 允许时才能并行推进，并且只执行其
   `evidence_collection.auto_collect` 中安全、只读、无需新授权的工作。
6. 缺少 collector 而 exit gate 可机械验证时，把最小 collector 实现归入当前获准的
   repository unit；不得借此开启第二条仓库主线。
7. 没有 eligible repository unit 时，不得通过重复刷新日期、HEAD、文档或相同探针制造工作。

## 工程与验证纪律

- 遵守 `Domain -> Application -> Infrastructure / Interface` 依赖方向以及 AGENTS.md 的全部
  类型、时间、数值、异常、金融正确性和数据 freshness 约束。
- 先确认完整实体和契约，再写失败测试和最小实现；修复时检查同类场景。
- public 生产函数必须有完整类型和 docstring；不得抬高 mypy 或治理债务基线。
- 生产 Python 改动至少运行：

```text
python scripts/check_mypy_regression.py <changed-production-python-files>
python scripts/check_mypy_debt_ceiling.py
```

- 同时运行与改动范围匹配的 Black、isort、Ruff、聚焦 pytest、架构检查、
  `python scripts/check_active_plan_registry.py` 以及专项治理检查。
- 不能运行的检查必须记录原因和影响；“命令未报错”不能替代用户任务或 exit gate 验收。

## 持久化回写与交接

完成回写是每个 closure unit exit gate 的组成部分，不是可选的收尾文档。Sol 不得先切换
`execution_focus`，再把证据和上下文留给后续任务补写。

每个 material checkpoint 至少把可复核状态写回该 unit 的 primary plan；每个 unit 完成时，
按以下顺序形成同一个验收包：

1. 固化测试结果、生产/只读观测、候选身份和必要 hash 等证据 artifact；不存在的证据明确
   记录为 unavailable，不能写成零或通过。
2. 在对应 primary plan 追加实施记录，写明目标切片、实际修改、关键判断、验证命令与结果、
   未验证风险、回滚点和剩余事项。
3. 更新 `governance/active_plan_registry.json` 中该 unit 的真实 `status`、`next_gate`、依赖和
   `execution_focus`。只有 material state transition 才更新 registry 版本/日期；不得仅刷新日期。
4. 同步 `docs/plans/README.md` 的当前执行焦点、滚动排期投影和一条有实质证据的阶段记录，
   使人工入口与机器真源勾稽一致。
5. 只有导航、候选验收摘要或文档归档关系发生实质变化时才更新 `docs/INDEX.md`；禁止在索引
   复制动态状态计数。
6. 运行 `python scripts/check_active_plan_registry.py` 以及受影响的专项治理检查。任何勾稽检查
   不通过时保持当前 focus 和非完成状态，先修复一致性。

checkpoint 尚未满足 exit gate 时，允许记录已经形成的、不会被重复执行的实质证据，但不得
提前把 unit 标记 completed 或激活后继 unit。重复探针、相同 HEAD、纯日期刷新和无状态变化的
记录不回写、不提交。

不创建独立的“Goal 当前进度”状态文件。后续 Sol/Luna 的恢复上下文只来自：机器注册表、
对应 primary plan、规范化证据 artifact、`docs/plans/README.md` 投影和当前 Git 工作树。

## Git 与提交节奏

- 保留当前分支和用户工作树，不修改、暂存或提交无关文件。
- 禁止 destructive Git、自动 merge/rebase、强推和向远端 push。
- Sol 可以在一个 closure unit 的真实 exit gate 达成且全部本地门禁通过后，创建最多一个
  coherent local commit。未达到 exit gate 时不做“探针提交”“日期提交”或碎片化阶段提交。
- 提交必须只包含该 unit 的代码、测试和必要文档；生产观察证据不得与无关代码混合。
- 如果现有未提交修改与当前范围重叠，停止自动提交，保留工作树并准确报告冲突。

## 权限与生产边界

可以自主执行仓库内修改、测试和明确列入 `auto_collect` 的安全只读检查。上述单一所有者授权还
允许在精确 preflight、候选绑定、停止线和回滚点齐全后执行已登记的有界生产整改，不再为同一
action envelope 重复请求泛化审批。以下动作仍未获得泛化授权：

- 创建、更新、撤销真实 authority、approval、交易、策略参数或业务记录。
- 故障注入、生产 restore/rollback、扩大流量或并发。
- 创建或删除备份、删除容器/文件、付费 API 调用、真实交易。
- 代替项目所有者编造其未作出的业务定义，或代替外部机构作出决定和签字。

遇到上述动作时，Sol 先完成 preflight、dry-run、影响范围、回滚点和证据模板，然后只针对仍未
被单一所有者授权覆盖的具体高风险动作请求授权。不要把整条 workstream 泛化为“需要生产，所以
无法工作”，也不要把所有者授权解释为可以跳过技术门禁。

## 进度与停止条件

每个检查点只报告：当前 unit/切片、Luna 派工、已验证证据、剩余 exit gate、权限阻塞和下一步。
避免用重复状态消息代替进展。

Goal 在以下任一条件满足时停止：

1. 注册表中所有 canonical closure units 已满足真实 exit gate，并达到正确终态。
2. 当前焦点没有剩余安全工作，且所有可选下一 unit 都被未完成依赖、生产授权、人工判断或
   外部环境阻断。
3. 工作树出现无法安全隔离的重叠修改，继续会覆盖用户或其他代理工作。
4. 真源互相矛盾，且修正会改变业务目标、权限边界或计划优先级，需要用户决定。

停止时必须给出：已完成 unit、当前机器状态、已验证命令、未验证风险、精确阻塞条件，以及
解除阻塞后应继续的唯一 unit。不得把 blocked、awaiting production、观察窗口未满或证据不可用
标记为 completed。最终回复前还必须复核最后一个 material checkpoint 已完成上述持久化回写，
确保下一次 Goal 可以仅凭仓库真源无歧义续跑。
