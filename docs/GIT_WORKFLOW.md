# AgomTradePro Git 工作流规范

> **最后更新**: 2026-10-25
> **适用范围**: 所有日常开发、修复、重构、文档更新

---

## 目标

AgomTradePro 已公开发布，后续开发默认遵循：

- `main` 保持相对稳定，可随时展示、拉取、部署
- 日常开发统一在 `dev/next-development` 完成，发布时再按授权合并回 `main`
- 提交信息必须能直接表达工作内容

---

## 分支规则

- `main` 保持稳定，只接收已验证并获准发布的变更。
- `dev/next-development` 是唯一长期开发分支，日常工作直接在此分支完成。
- 除非用户另行要求，不再创建其他 `dev/*` 或 `codex/*` 分支。不同事项通过独立 commit 拆分。
- 历史专题分支仅在确认全部提交已进入目标分支，且远端同步成功后删除。

此约定依据 2026-09-21 用户要求，替代此前每项工作创建专题分支的默认流程。

---

## 标准流程

### 1. 检查工作区并同步开发分支

```bash
git status --short
git fetch origin
git switch dev/next-development
git merge --ff-only origin/dev/next-development
```

切换前保留未提交改动，不覆盖其他人的工作。无法快进时先检查分叉原因，不能强推或重置来丢弃提交。

### 2. 开发与自测

在 `dev/next-development` 上直接修改。遵循 `AGENTS.md` 的架构、类型、TDD 和专项治理门禁，
运行与变更风险匹配的检查。生产 Python 改动必须通过增量 mypy 和债务上限检查；
涉及 current/latest 决策数据时同步治理合同并运行对应检查。

单纯快进整合、没有修改生产代码时，核对提交包含关系和已有源码绑定验证证据；
发生冲突或代码变化后，重新运行受影响的回归。

### 3. 分事项提交并推送

自2026-10-25起，重验证和共享采用先遵循下文“VPS QA 与同对象采用”。下面命令是普通已验证事项的简式；需要先固定 SHA 的合批候选使用未发布对象流程，不能验证后重建 SHA。

```bash
git add <changed-files>
git diff --cached --check
git commit -m "fix: describe the concrete change"
git push origin dev/next-development
```

明确暂存本次文件，不顺带提交无关改动。一个 commit 尽量只解决一件事；功能、架构、部署与治理
应按事项拆分，不能因为共用开发分支就混成无边界提交。

### 4. 发布合并

向 `main` 合并仍是独立的发布动作，按当次授权执行，可采用 Pull Request 或获准的本地合并流程。
日常提交或开发分支整合本身不代表发布批准，也不触发生产部署。

### 验收原件与提交范围

- 源码仓库提交代码、测试、必要的生成投影、精简验收结论和证据索引。
- 完整测试/格式化/审计日志、截图、JUnit、运行脚本副本、重复源码快照及大体积证据包保留在 Git 忽略的 `artifacts/` 或仓库外持久归档，不使用 `git add -f` 批量纳入源码提交。
- 索引记录实际候选/输入身份、命令及结果、原件位置和 SHA-256；本机归档必须明确标为本机可用，不能宣称远端已持有。迁出旧原件前逐项校验并更新文档引用，保留失败记录，不重写 Git 历史。
- 正式发布契约要求的结构化报告、清单与资格门保持原要求；归档整理不替代验收，不放宽门禁。

### 控制变更成本

- 独立 commit 的边界是一个完整事项。修复、直接对应的测试、生成投影和专项说明应一起提交；
  不必为了“代码 / docs / chore”标签拆成三个提交。真实生产观测在发生后另行登记，不能提前编造。
- 日常开发只运行适用的本地门禁和增量 CI。多个已验证事项可组成一个发布候选，冻结候选后再
  执行完整发布验证；每个开发 commit 不自动要求独立 S6、部署和生产对账。
- 发布候选冻结后，代码、依赖、运行配置或要求绑定的证据身份变化仍按原发布契约重新验证。
  不能把不同 SHA 的 CI/S6 拼接成通过证据。纯文档若要纳入新的发布 SHA，也须走该 SHA 的发布入口。
- 日常 push/PR 若仅变更 `README.md` 或 `docs/**/*.md`，Fast Feedback 省略无数据库 TDD、
  Python 双版本运行测试和全量 mypy；增量质量 job、Consistency、Architecture、Security 保留。
  JSON 证据、治理配置、Agent 指令、运行时 Markdown、代码删除、未知文件、空 diff 和无法读取的
  diff 均不能获得此简化。手动 Fast Feedback 与 RC 调用始终恢复完整运行验证。
- CI 的 job summary 标明本次范围。文档简化结果不是完整发布验证；冻结候选后使用手动
  Fast Feedback / RC 入口。S6 的环境预检、同镜像部署和生产对账仍以发布真源为准。

上述实现复用 `scripts/select_quality_targets.py --profile runtime-inputs` 和既有 workflow，
不新增审批层、台账或状态真源。只有实际 CI 运行完成后才能报告节省的分钟数。

### 2026-10-22 Owner 批准的交付合批与有界并行

- 一个完整业务事项使用一个验收索引，逐次追加候选/输入、命令、结果和失败原件；交付时合批归档，不为每个小修复复制整套源码、Markdown、JSON 和 ZIP。原始失败及已归档历史不覆盖。
- 唯一 repository 焦点负责共享整合，不代表其他已登记准备工作必须停工。读取 `execution_focus.parallel_preparation`，在隔离工作副本中按不重叠路径准备；不增加长期分支，不共同写共享 index。共享采用、投影生成、提交短占窗口。
- 轻量测试/静态复核可以并行；数据库、缓存、任务通道及端口须隔离。重 QA 按资源预算串行或有界并行，不能多个会话争用同一测试库或缓存。
- 已知候选失败先归因并针对性验证，修齐后冻结下一候选。开发增量证据用于各自改动诊断；完整发布仍绑定同一 SHA 的所有必需检查，不能把历史绿灯算给新 SHA。
- M1 先行只按 A 股主计划 §19.96 的最小真实用户闭环验收，整单元与正式发布退出门保持。批准不等于已有功能或证据。

### 2026-10-25 VPS QA 与同对象采用

- 同一业务事项可合并相互依赖的实现、测试、投影及说明，提交正文列子项与整个 commit 的回滚点。治理、CI 与业务事项若须前后衔接，保留独立提交组成有序候选链，在最终组合 SHA 统一验证；中间对象不单独推送触发已知失败。
- 开发中先复现实际反例、跑受影响模块的快速测试；稳定后集中执行一次适用完整门。失败则保留原件、定向修复后以新身份重验，不对每个中间步骤跑全套，不把父候选结果算给新候选。
- 为让提交前 QA 有精确身份，可在私有副本/独立 `GIT_INDEX_FILE` 中基于明确父提交创建**未发布 commit 对象**，记录父/树/SHA/路径摘要；不移动共享分支、不改共享 Source/index、不推送或增加长期分支。用 bundle 或等价 Git 对象传输送到 VPS 独立 QA clone，核验完整 SHA 与干净受测源码后运行。
- 绿灯是共享采用和推送的前提。取得短 Git 窗口后，核对共享父、外来改动和 index/ITA，仅采用已验证对象的准确字节和同一 commit 链。父或候选字节变化则新建候选重验；禁止 reset/force push、覆盖外来修改或验证后重新 commit 制造另一 SHA。等待验证不占共享窗口。
- VPS 重验证和资源隔离按 quick-reference 的“VPS 独立 QA”执行；统一投影检查进入提交前验证，实际漂移须用官方生成器修正后重新冻结。资金/数据/权限/幂等/回滚、类型/格式/架构/合同/投影、既有性能预算、Domain 90%、M1 §19.96 九项、整单元及 RC/S6 门保持。
- 每事项一份精简索引：最终 SHA/子项，各环境命令/退出码/测试数/覆盖率/耗时/原件，失败摘要，本地/CI 剩余及风险、回滚点。最终结果在提交之外归档，避免为把验收结果写入自身 commit 而反复改 SHA；后续文档记录旧 SHA 结果不充当自身或新业务候选资格。
- 本调整仅授权 QA，不授权部署、生产连接/回填/成交或真实自动下单；候选专属“先不要部署”仍适用。

### 复杂度收敛的后续顺序

以下是尚未实施的工作，不构成模块删除或生产切换：

1. **先减少无效等待**：从 CI 运行记录和 S6 阶段报告分别统计排队、依赖安装、测试、环境失败耗时。
   退出条件是能定位主要耗时，而非维护新的人工日报；后续范围缩减必须有反例测试。
2. **再收敛公开入口**：依据现有 SDK/MCP 清单核对替代入口、调用方与运行期使用证据。
   有替代且已完成兼容迁移的 legacy 分批退役；无替代的先决定保留或实现替代。
   退出条件是调用方迁移与契约回归通过，不能仅凭 legacy 标签批量删除。
3. **按业务职责拆大文件**：使用 `governance/module_map.json` 的依赖关系选择边界清楚、经常修改的
   一个用例，逐步从大服务抽取，保留公开 Facade。先在原 App 内收敛职责，退出条件是原契约不变、
   无新循环依赖、目标文件缩小；不先做跨 App 搬库和大规模改名。
4. **核对重叠语义后再合并模块**：为 signal/strategy/alpha/factor/research 等明确输入、输出及
   数据所有者，只有重复实现与调用方都确认后才合并。每批以删除重复实现及通过回归为完成标准。

---

## Commit 规范

提交信息统一采用：

```text
<type>: <summary>
```

推荐类型：

- `feat`: 新功能
- `fix`: Bug 修复
- `refactor`: 重构
- `docs`: 文档修改
- `test`: 测试新增或修复
- `chore`: 杂项维护
- `perf`: 性能优化

示例：

```text
feat: add setup wizard screenshots to readme
fix: correct terminal mcp route fallback
refactor: simplify decision workflow orchestration
docs: add git workflow and branch naming guide
test: add api contract coverage for regime endpoints
chore: clean up development scripts
```

### 提交要求

- 一个 commit 尽量只做一件事
- 提交主题使用英文，简短、明确
- 不使用无意义信息

不推荐：

```text
update
fix bug
wip
misc
final
```

---

## Pull Request 建议

PR 标题建议与 commit 风格一致：

```text
feat: add terminal routing controls
fix: repair ai capability catalog sync
docs: polish public readme for open-source release
```

PR 描述至少说明：

- 做了什么
- 为什么要改
- 怎么验证
- 是否影响 README / 文档 / API / MCP / SDK

---

## 特别约束

- 不要直接在 `main` 上做大改
- 公开仓库中的展示性改动，也应走分支后再合并
- 涉及 API、SDK、MCP、README 的改动，必须同步检查文档
- 涉及跨模块改动时，使用独立 commit 或阶段计划明确各项影响面

---

## 推荐习惯

- 小改动也统一在 `dev/next-development` 提交
- 功能开发与文档更新可以同分支提交，但应保证主题一致
- 推送后确认本地与远端开发分支身份一致
- 删除历史分支前确认其 tip 是目标分支的祖先，使用安全删除

---

## 一句话总结

> **`main` 负责稳定展示，`dev/next-development` 负责日常开发；提交信息要能让人一眼看懂你改了什么。**
