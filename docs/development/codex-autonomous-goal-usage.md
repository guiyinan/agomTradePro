# Codex 自主 Goal 使用备忘

> 用途：由一个开发会话负责完整事项，按授权使用 Luna 或独立复核；状态、证据和交接分别回写既有真源。

## 1. 相关文件

- 自主调度合同：[`AUTONOMOUS_GOAL.md`](../../AUTONOMOUS_GOAL.md)
- 活跃计划人工索引：[`docs/plans/README.md`](../plans/README.md)
- 动态状态机器真源：[`governance/active_plan_registry.json`](../../governance/active_plan_registry.json)
- 仓库代理规则：[`AGENTS.md`](../../AGENTS.md)

`AUTONOMOUS_GOAL.md` 只定义调度和权限合同，不保存当前任务状态。当前 focus、依赖、状态和
下一门禁始终以机器注册表为准；实施细节和证据写入对应 closure unit 的 primary plan。

## 2. 最短启动方法

在已经打开 AgomTradePro 仓库的 Codex 任务中：

1. 模型沿用当前任务设置；默认单开发会话，明确要求的 worker 分工沿用用户指定模型与 effort。
2. 确认当前 worktree 能看到上述四个文件。
3. 输入：

```text
/goal 执行 AUTONOMOUS_GOAL.md 的本阶段目标：当前开发会话负责完整事项，优先完成 DATA-02 有界修复、回填与真实对账，推进获准且不冲突的 TUI-02/AUD-03 事项，精确列出 Evidence/策略/TAR 输入缺口；遵守阶段完成条件、真实证据、共享整合焦点与生产串行规则，不重复 completed 单元，不把 QMT 纳入本阶段完成条件；仅按用户另行明确要求派 worker。
```

之后可以不持续盯守。主代理应从机器注册表重建本阶段 eligible work set：当前
`execution_focus.unit_id` 是唯一 repository 写入通道，但获准的 production/external/governance
只读取证、观察和 preflight 可以在无冲突时并行。一个 unit 达到真实 exit gate 并完成回写后，
再按本阶段边界判断该通道的下一步，不自动扩展到阶段外的 unit。

已经运行的 Goal 不应依赖旧聊天上下文猜测合同变化。修改合同后，在获准协调范围内向受影响的任务
一次性提供变更小节与文件版本，由其读取差异及必要前置约束，无须回执或全文重读；不清除已有证据。
另一 worktree 必须先取得同一文档版本；文件修改不自动更新应用 Goal 或正在运行的会话上下文。

## 3. 三种使用场景

### 当前 Codex 工作区

如果 Goal 文件和仓库位于当前共享工作区，直接使用上面的 `/goal` 命令即可，不需要重新上传
文件。未提交文件在当前 worktree 中仍可读取，但可能不会出现在另一个独立 worktree 中。

### 新任务、新 worktree 或另一台机器

先把以下文件以 coherent documentation commit 提交到当前开发分支并同步到目标环境：

- `AUTONOMOUS_GOAL.md`
- `docs/development/codex-autonomous-goal-usage.md`
- `docs/plans/README.md` 中的 Goal 入口
- `docs/INDEX.md` 中的本备忘入口

然后在包含这些提交的 worktree 中启动 Goal。不要只复制 Goal 文件而遗漏仓库计划、注册表、
代码和测试上下文。

### 普通 ChatGPT 对话

只把 `AUTONOMOUS_GOAL.md` 当作附件交给无法访问仓库和开发工具的普通对话，不足以执行此
流程。它可以解释文件，但无法读取计划真源、修改代码、运行测试或完成回写。应在已打开完整
仓库的 Codex 任务中运行。

## 4. 运行时会发生什么

- 主代理按 AGENTS 路由读取当前事项必要的规则、registry 字段、plan 小节、源码定义和测试。
- 启动、事项结束或调度输入变化时，按合同核验四类通道；同一事项内不随工具返回重复全量扫描。
- 一个开发会话负责完整事项，worker/独立复核按授权和实际需要参与；按合同复用 worker，不常驻陪跑。
- Luna 完成搜索、实现、测试或文档切片，不 commit、不 push、不执行生产写入。
- 主代理审查完整 diff 和证据，按 Git 工作流核验并复用有效运行；缺失、变化、失败或过期时补跑适用门禁，判断 exit gate 是否真实满足。
- worker 不并行编辑共享真源；主代理将实质状态变化写 registry，短交接写既有 plan，验证详情写同一事项证据索引；导航只在入口变化时更新。
- 勾稽或验证失败时保持当前 focus，不得提前激活下一 unit。

## 5. Goal 控制命令

修改仓库文件不会自动修改当前应用 Goal。若当前会话工具不能改写已有 objective，
不要把未完成的旧目标标为 completed，也不要直接改应用内部存储；在任务输入框清除旧 Goal
后，使用本文件第 2 节指令建立新 Goal，并读回核验 objective/status。普通消息仍可指导当前
工作继续，但不能据此声称应用 Goal 的持久化设置已改变。

```text
/goal
```

查看当前 Goal 和状态。

```text
/goal pause
/goal resume
```

临时暂停或继续。

```text
/goal clear
```

确认工作已经完成、需要改方向，或准备换用新的 Goal 时清除。

## 6. 完成后的回写检查

每个 closure unit 完成后至少确认：

- 对应 primary plan 有最新实施记录和验证结果。
- 规范化 evidence artifact 保留来源时间、候选身份和必要 hash。
- `active_plan_registry.json` 的 status、next gate、依赖和下一 focus 与真实结果一致。
- 导航发生变化时同步 `docs/plans/README.md`，不复制状态或阶段记录。
- `python scripts/check_active_plan_registry.py` 通过。
- 未满足的生产授权、人工审批、观察窗口和外部环境没有被标记为 completed。

Goal 或聊天上下文被压缩、任务重启时，新的主代理必须从这些仓库真源恢复，不依赖聊天记忆，
也不另建第二份 Goal 进度表。

## 7. Git 与权限提醒

- 按完整业务事项通过适用开发门禁后创建 coherent local commit，不等待整单元生产关闭；
  禁止自动 push、merge、rebase 和碎片化探针提交，独立授权的 Git 操作按其范围执行。
- 保留用户已有未提交修改；范围重叠时停止自动提交并报告。
- 部署、生产写入、故障注入、备份创建/删除、付费调用、真实交易和人工签字应逐项核对既有授权；
  只对尚未覆盖的具体动作请求授权，不重复索要已授予的权限。

## 8. 官方参考

- [OpenAI：Follow a goal](https://learn.chatgpt.com/use-cases/follow-goals)
- [OpenAI：GPT-5.6 model guidance](https://developers.openai.com/api/docs/guides/latest-model)

官方 Goal 指南建议给 Codex 一个可验证的停止条件，明确必须先读取的文件、证明进展的命令或
artifact，并按 checkpoint 保存简短进度。GPT-5.6 指南将 Sol 定位为旗舰能力模型，将 Luna
定位为高吞吐执行模型，并建议为多步骤工作明确授权边界和停止条件。
