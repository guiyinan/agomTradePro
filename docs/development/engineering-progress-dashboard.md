# 工程进度 HTML 看板

看板把机器注册表投影为可直接打开的单个 HTML，用于查看当前执行焦点、工作主线、单元状态、依赖、退出门及提交变化。它属于开发工具，不新增 Classic Web 页面、业务 API 或状态真源。

## 打开与自动更新

需要 Git 和 PATH 中的 Node.js 22+，不需要 npm 安装、Django、数据库或网络请求。

Windows 用户直接双击仓库根目录的 [`open-engineering-dashboard.cmd`](../../open-engineering-dashboard.cmd)：脚本先从最新提交重新生成看板，再使用默认浏览器打开。可以从任意工作目录启动；失败时会保留窗口显示错误，不会自动打开旧结果。

```bash
node scripts/engineering-dashboard/build.mjs
node scripts/engineering-dashboard/install-hooks.mjs
```

打开仓库内 `reports/engineering-progress/index.html`。输出目录已被现有 `.gitignore` 忽略；生成 HTML 不进入提交，不产生“为更新提交 SHA 再提交一次”的循环。

安装器为当前 checkout 使用的 hooks 目录增加 `post-commit`、`post-merge`、`post-checkout`。此后提交、合并或切换分支会重新生成 HTML；浏览器中已打开的页面需要刷新。首次 clone 后运行一次安装器。它不修改 `core.hooksPath`；如已配置共享 hooks 目录，安装将作用于该目录。原有 hook 保存为同目录的 `<hook>.before-engineering-dashboard` 并先执行，重复安装不重复包装。移除时仅删除包含 `agom-engineering-dashboard-v1` 标记的包装 hook，再把对应备份恢复原名；没有备份的 hook 直接移除即可。

hook 失败不会撤销已经完成的 Git 操作，会在终端给出警告；旧 HTML 会保留，因此应核对页面顶部 SHA 与当前提交。Node 不在 Git 进程 PATH 时也会明确警告，可手动执行构建命令恢复。

`.github/workflows/engineering-dashboard.yml` 在 `main` / `dev/**` 的 push、PR 和手动运行时生成对应 checkout 的 HTML，保留为 `engineering-progress-<SHA>` Actions 附件 30 天。PR 默认展示 GitHub 测试合并提交。一次 push 的中间提交可通过近期历史或 `--ref` 查看。此流程只生成附件；不发布网站、不写回仓库、不部署 VPS。CI 附件中的文档链接指向该 SHA 的 GitHub 文件，本地输出中的链接指向工作区文件（文件内容可能包含未提交改动）。

## 数据与口径

### 项目管理视图

- **项目总览**：统计卡片、中文主线表、当前执行焦点、待关注事项及分范围完成数量。点击卡片或主线可进入对应任务筛选。
- **任务看板**：待推进、进行中、验收 / 阻塞、已完成、延期 / 归档五列；原始状态仍显示在任务上。支持切换列表以及主线、状态、范围、关键词的组合筛选。未知状态独立进入“待识别状态”，不漏算。
- **任务详情侧栏**：查看完整退出门、所属主线负责人、前置与下游依赖、执行约束及计划文档。可沿依赖逐个打开详情，用 Escape 或关闭按钮返回，保留任务筛选。
- **阶段路线**：从 `closure_backlog.waves` 读取阶段和规则；按 Wave 展示任务，未登记阶段单独保留。阶段不是日期排期，不生成虚构的甘特图。
- **提交动态 / 数据来源**：分别查看单元变更、提交时间线，以及来源 hash、辅助快照提示和治理目录。`#sources`、`#tasks` 等视图链接和 `#unit-ASH-03` 任务链接可直接打开。

“待关注”仅统计未完成且未延期/归档的单元：登记状态为等待依赖、待生产验收、外部阻塞，或其登记前置依赖尚未 completed。它不是新的任务状态，也不表示已授权执行。主线中文名是界面译名，原始标题、owner、退出门继续在详情中保留。任务级负责人、截止日期缺失时明确显示“未登记”，不会把主线 owner 冒充具体任务负责人。

| 来源 | 用途 |
| --- | --- |
| `governance/active_plan_registry.json` | 状态、工作流、执行焦点、依赖、退出门的唯一来源 |
| `governance/governance_baseline.json` | 登记的模块、静态测试规模；不代表本次测试结果 |
| `docs/governance/active-plan-hierarchy.json` | 仅检查辅助快照版本；缺失或版本不同会提示，不覆盖主注册表 |
| Git 第一父提交链 | 默认最近 12 个提交的登记完成数量及当前提交相对父提交的单元变化 |

默认从一个冻结的 Git SHA 读取全部账本，未提交内容不进入提交快照。嵌入来源 SHA-256 便于复核。主注册表损坏、重复单元或缺失依赖导致生成失败；辅助快照缺失不影响主注册表展示。未知状态明确显示为未知，不算完成。历史、特殊归属单元独立展示，不能因没有当前 workstream 而漏算。

完成数量只计 `completed`；`deferred` / `archived` 不计完成，仍保留在比例分母。按 execution_mode 分开显示仓库、生产、外部、治理范围。没有工时或规模权重，因此不声称“整个系统完成百分比”。退出门满足与否由维护账本的既有流程决定，看板不从 commit、测试数量或 Markdown 复选框自动判定。

现有账本足以支持单元级工程看板，但不包含所有 Plan 三级切片、可靠工时、预计完工时间、实时 CI 结果或生产证据有效性判定。看板不补造这些信息。更新节奏是“维护机器账本 → 提交 → 生成只读页面”。

## 手动使用与验证

```bash
# 明确查看未提交草稿，页面带有草稿提示；不覆盖提交快照
node scripts/engineering-dashboard/build.mjs --working-tree --output reports/engineering-progress/draft.html

# 历史提交与历史长度
node scripts/engineering-dashboard/build.mjs --ref HEAD~1 --history 20 --output reports/engineering-progress/previous.html

# 纯 Node 回归，包含隔离临时仓库中的真实提交与 hook 自动更新
node --test scripts/engineering-dashboard/dashboard.test.mjs
```

构建器、样式和渲染代码位于 `scripts/engineering-dashboard/`。源码变化后运行上述回归，并在浏览器验证五个视图、主线下钻、看板/列表结果一致性、组合筛选、详情侧栏、上下游依赖、Escape 关闭、深链接、空结果和窄屏布局。生成结果在打开期间不会联网拉取新状态。
