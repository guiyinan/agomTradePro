# AgomTradePro Git 工作流规范

> **最后更新**: 2026-03-23
> **适用范围**: 所有日常开发、修复、重构、文档更新

---

## 目标

AgomTradePro 已公开发布，后续开发默认遵循：

- `main` 保持相对稳定，可随时展示、拉取、部署
- 所有日常开发先在分支完成，再合并回 `main`
- 分支名和提交信息必须能直接表达工作内容

---

## 分支规则

### 主分支

- `main`
  - 只接受已经完成自测、可合并的内容
  - 不建议直接在 `main` 上开发

### 开发分支前缀

统一使用 `dev/` 前缀，不再使用 `codex/` 作为仓库开发分支命名。

格式：

```text
dev/<type>-<scope>-<short-description>
```

推荐类型：

- `dev/feat-...` 新功能
- `dev/fix-...` 缺陷修复
- `dev/refactor-...` 重构
- `dev/docs-...` 文档更新
- `dev/test-...` 测试补强
- `dev/chore-...` 非业务杂项

示例：

```text
dev/feat-terminal-routing
dev/fix-mcp-tool-toggle
dev/refactor-decision-workflow
dev/docs-readme-public-polish
dev/test-regime-api-contract
```

### 命名要求

- 全部使用小写字母
- 使用短横线 `-` 分隔单词
- 名称要能表达“改什么”
- 一个分支只承载一类核心工作

不推荐：

```text
dev/update
dev/test
dev/fix-bug
dev/tmp
```

---

## 标准流程

### 1. 从 main 拉取最新代码

```bash
git checkout main
git pull origin main
```

### 2. 创建开发分支

```bash
git checkout -b dev/feat-terminal-routing
```

### 3. 开发与自测

至少完成与改动范围匹配的验证，例如：

```bash
pytest tests/ -v
ruff check .
```

### 4. 提交

```bash
git add .
git commit -m "feat: improve terminal command routing"
```

### 5. 推送分支

```bash
git push origin dev/feat-terminal-routing
```

### 6. 合并回 main

可选择：

- 通过 GitHub Pull Request 合并
- 本地验证后合并，再推送 `main`

本地合并示例：

```bash
git checkout main
git pull origin main
git merge dev/feat-terminal-routing
git push origin main
```

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
- 涉及跨模块改动时，分支名称应优先体现核心影响面

---

## 推荐习惯

- 小改动也尽量走分支
- 功能开发与文档更新可以同分支提交，但应保证主题一致
- 一个分支完成后尽快合并，避免长期漂移
- 合并前先同步最新 `main`，减少冲突

---

## 一句话总结

> **`main` 负责稳定展示，`dev/*` 负责日常开发；提交信息要能让人一眼看懂你改了什么。**
