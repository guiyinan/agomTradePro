# AgomTradePro Git 工作流规范

> **最后更新**: 2026-09-21
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
