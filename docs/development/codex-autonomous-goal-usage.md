# Codex 自主 Goal 使用备忘

> 用途：让 Codex 在 AgomTradePro 仓库中由 Sol 负责调度和验收，调用 Luna 持续完成有界
> closure unit，并在完成后把状态、证据和下一任务写回仓库真源。

## 1. 相关文件

- 自主调度合同：[`AUTONOMOUS_GOAL.md`](../../AUTONOMOUS_GOAL.md)
- 活跃计划人工索引：[`docs/plans/README.md`](../plans/README.md)
- 动态状态机器真源：[`governance/active_plan_registry.json`](../../governance/active_plan_registry.json)
- 仓库代理规则：[`AGENTS.md`](../../AGENTS.md)

`AUTONOMOUS_GOAL.md` 只定义调度和权限合同，不保存当前任务状态。当前 focus、依赖、状态和
下一门禁始终以机器注册表为准；实施细节和证据写入对应 closure unit 的 primary plan。

## 2. 最短启动方法

在已经打开 AgomTradePro 仓库的 Codex 任务中：

1. 主模型选择 `gpt-5.6-sol`。
2. 确认当前 worktree 能看到上述四个文件。
3. 输入：

```text
/goal 按照 AUTONOMOUS_GOAL.md 持续自主推进，严格执行其中的 Sol/Luna 调度、单 repository 执行锁、计划回写、验证、权限和停止规则。
```

之后可以不持续盯守。Sol 应从机器注册表当前 `execution_focus.unit_id` 开始，审查并验收 Luna
完成的有界切片；一个 unit 达到真实 exit gate 并完成回写后，再自动调度下一 eligible unit。

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

- Sol 读取 AGENTS、机器注册表、plans 索引、当前 unit primary plan、代码和测试。
- Sol 默认复用一个 `gpt-5.6-luna` worker；仅在文件范围和验收互不依赖时并行第二个 worker。
- Luna 完成搜索、实现、测试或文档切片，不 commit、不 push、不执行生产写入。
- Sol 审查完整 diff，运行最终门禁，并判断 exit gate 是否真实满足。
- 每个 material checkpoint 回写 primary plan；unit 完成时同步证据 artifact、registry、plans
  人工投影和必要的文档索引。
- 勾稽或验证失败时保持当前 focus，不得提前激活下一 unit。

## 5. Goal 控制命令

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
- `docs/plans/README.md` 的人工投影与机器注册表一致。
- `python scripts/check_active_plan_registry.py` 通过。
- 未满足的生产授权、人工审批、观察窗口和外部环境没有被标记为 completed。

Goal 或聊天上下文被压缩、任务重启时，新的 Sol 必须从这些仓库真源恢复，不依赖聊天记忆，
也不另建第二份 Goal 进度表。

## 7. Git 与权限提醒

- 当前 Goal 合同只允许 Sol 在一个 unit 真实完成且门禁全绿后创建最多一个 coherent local
  commit；禁止自动 push、merge、rebase 和碎片化探针提交。
- 保留用户已有未提交修改；范围重叠时停止自动提交并报告。
- 部署、生产写入、故障注入、备份创建/删除、付费调用、真实交易和人工签字仍需要单独授权。

## 8. 官方参考

- [OpenAI：Follow a goal](https://learn.chatgpt.com/use-cases/follow-goals)
- [OpenAI：GPT-5.6 model guidance](https://developers.openai.com/api/docs/guides/latest-model)

官方 Goal 指南建议给 Codex 一个可验证的停止条件，明确必须先读取的文件、证明进展的命令或
artifact，并按 checkpoint 保存简短进度。GPT-5.6 指南将 Sol 定位为旗舰能力模型，将 Luna
定位为高吞吐执行模型，并建议为多步骤工作明确授权边界和停止条件。
