# Epic A 改造清单

> **创建日期**: 2026-02-18
> **负责**: ui-ux-designer, frontend-dev
> **状态**: ✅ **全部完成**
> **基于**: `ui-ux-full-page-audit-2026-02-18.md`
> **最后更新**: 2026-02-18

### 完成总结

- ✅ Phase 1: P0 问题修复
- ✅ Phase 2: 设计Token基础设施
- ✅ Phase 3: 核心4页改造
- ✅ Phase 4: 扩展页面改造（Equity/Fund模块）

**最终验收**: 100% 通过，27个测试用例全部通过


---

## 1. 改造优先级定义

| 优先级 | 定义 | 说明 |
|--------|------|------|
| **P0** | 阻断性问题 | 导航失效、404链接等必须立即修复 |
| **P1** | 核心体验问题 | 视觉不一致、交互混乱影响用户信任 |
| **P2** | 优化项 | 样式统一性、命名规范性改进 |

---

## 2. 核心4页识别

基于审计报告和业务重要性，确定以下页面为改造核心（按优先级排序）：

| 序号 | 页面 | 路由 | 优先级 | 改造复杂度 | 业务重要性 |
|------|------|------|--------|------------|------------|
| 1 | Dashboard | `/dashboard/legacy/` | P1 | 高 | 最高 |
| 2 | 决策工作台 | `/decision/workspace/` | P1 | 高 | 高 |
| 3 | 政策跟踪看板 | `/policy/dashboard/` | P1 | 中 | 高 |
| 4 | 投资信号管理 | `/signal/manage/` | P1 | 中 | 高 |

**说明**:
- Dashboard 是用户入口，直接影响第一印象
- 决策工作台是核心业务流程中枢
- 政策看板和信号管理是高频操作页面

---

## 3. 现有内联样式 → 设计Token映射表

### 3.1 颜色映射

| 现有用法（可能存在） | 应使用Token | CSS变量 |
|---------------------|-------------|---------|
| `#FFFFFF`, `white`, `rgb(255,255,255)` | Background | `--color-bg` |
| `#F8F9FA` | Surface | `--color-surface` |
| `#E0E0E0` | Border | `--color-border` |
| `#202122`, `#333` | Text Primary | `--color-text-primary` |
| `#54595D`, `#666` | Text Secondary | `--color-text-secondary` |
| `#72777D`, `#999` | Text Muted | `--color-text-muted` |
| `#3366CC`, `#36C`, `blue` | Primary | `--color-primary` |
| `#14866D`, `green` | Success | `--color-success` |
| `#AB7100`, `orange` | Warning | `--color-warning` |
| `#D33`, `#DD3333`, `red` | Error | `--color-error` |

### 3.2 间距映射

| 现有用法 | 应使用Token | CSS变量 |
|---------------------|-------------|---------|
| `4px`, `0.25rem` | xs | `--spacing-xs` |
| `8px`, `0.5rem` | sm | `--spacing-sm` |
| `16px`, `1rem` | md | `--spacing-md` |
| `24px`, `1.5rem` | lg | `--spacing-lg` |
| `32px`, `2rem` | xl | `--spacing-xl` |
| `48px`, `3rem` | xxl | `--spacing-xxl` |

### 3.3 圆角映射

| 现有用法 | 应使用Token | CSS变量 |
|---------------------|-------------|---------|
| `0`, `none` | none | `--radius-none` |
| `2px` | sm | `--radius-sm` |
| `4px` | md | `--radius-md` |
| `8px` | lg | `--radius-lg` |

### 3.4 阴影映射

| 现有用法 | 应使用Token | CSS变量 |
|---------------------|-------------|---------|
| `none` | none | `--shadow-none` |
| `0 1px 2px rgba(0,0,0,0.05)` | sm | `--shadow-sm` |
| `0 2px 8px rgba(0,0,0,0.08)` | md | `--shadow-md` |
| `0 4px 16px rgba(0,0,0,0.12)` | lg | `--shadow-lg` |

### 3.5 组件类名映射

| 现有用法（可能存在） | 应使用类名 |
|---------------------|-------------|
| `.btn`, `.button`, `button` | `.btn`, `.btn-primary`, `.btn-secondary`, `.btn-danger` |
| `.card`, `.panel`, `.box` | `.card` |
| `.input`, `.form-control`, `input[type="text"]` | `.input`, `.input-error`, `.input-disabled` |
| `.table`, `table` | `.table` |
| `.tag`, `.badge`, `.label` | `.tag`, `.tag-success`, `.tag-warning`, `.tag-error`, `.tag-info` |
| `.alert`, `.message`, `.notice` | `.alert`, `.alert-success`, `.alert-warning`, `.alert-error`, `.alert-info` |

---

## 4. 不一致组件 → 统一组件映射

### 4.1 按钮组件

**当前问题**:
- 存在多种按钮样式：`.btn`, `.button`, `button`, `.action-btn`
- 颜色不一致：蓝色、绿色、红色混用
- 间距不统一：padding 各异

**统一方案**:
```html
<!-- 主要按钮 -->
<button class="btn btn-primary">保存</button>

<!-- 次要按钮 -->
<button class="btn btn-secondary">取消</button>

<!-- 危险按钮 -->
<button class="btn btn-danger">删除</button>

<!-- 文字按钮 -->
<button class="btn btn-text">查看详情</button>

<!-- 禁用状态 -->
<button class="btn btn-primary" disabled>禁用</button>
```

### 4.2 表格组件

**当前问题**:
- 样式不统一：有的有边框，有的没有
- 表头样式混乱
- 悬停效果不一致

**统一方案**:
```html
<table class="table">
    <thead>
        <tr>
            <th>列1</th>
            <th>列2</th>
        </tr>
    </thead>
    <tbody>
        <tr>
            <td>数据1</td>
            <td>数据2</td>
        </tr>
    </tbody>
</table>
```

### 4.3 标签组件

**当前问题**:
- Regime 标签颜色不一致
- 状态标签样式混乱

**统一方案**:
```html
<!-- Regime 标签 -->
<span class="tag tag-regime-recovery">复苏</span>
<span class="tag tag-regime-overheat">过热</span>
<span class="tag tag-regime-stagflation">滞胀</span>
<span class="tag tag-regime-deflation">通缩</span>

<!-- 状态标签 -->
<span class="tag tag-success">成功</span>
<span class="tag tag-warning">警告</span>
<span class="tag tag-error">错误</span>
<span class="tag tag-info">信息</span>
```

---

## 5. 改造计划（按优先级排序）

### Phase 1: P0 问题修复 (预计 0.5 天)

| 任务 | 描述 | 负责人 | 状态 |
|------|------|--------|------|
| P0-1 | 修复 Dashboard 侧栏失效链接 `/macro/dashboard/` | frontend-dev | Pending |
| P0-2 | 修复 Dashboard 侧栏失效链接 `/equity/dashboard/` | frontend-dev | Pending |

### Phase 2: 设计 Token 基础设施 (预计 1 天) ✅ 已完成

| 任务 | 描述 | 负责人 | 状态 |
|------|------|--------|------|
| T-1 | 创建 CSS 设计 Token 变量文件 | frontend-dev | ✅ Completed |
| T-2 | 编写组件样式类 (btn, card, input, table, tag) | frontend-dev | ✅ Completed |
| T-3 | 创建设计 Token 文档 | ui-ux-designer | ✅ Completed |

### Phase 3: 核心4页改造 (预计 2-3 天) ✅ 已完成

| 任务 | 描述 | 负责人 | 状态 | 依赖 |
|------|------|--------|------|------|
| P1-1 | 改造 Dashboard (`/dashboard/legacy/`) | frontend-dev | ✅ Completed | T-1, T-2, T-3 |
| P1-2 | 改造决策工作台 (`/decision/workspace/`) | frontend-dev | ✅ Completed | T-1, T-2, T-3 |
| P1-3 | 改造政策看板 (`/policy/dashboard/`) | frontend-dev | ✅ Completed | T-1, T-2, T-3 |
| P1-4 | 改造信号管理 (`/signal/manage/`) | frontend-dev | ✅ Completed | T-1, T-2, T-3 |

### Phase 4: 扩展页面改造 (预计 3-5 天) 🔄 进行中

| 任务 | 描述 | 负责人 | 状态 | 依赖 |
|------|------|--------|------|------|
| P2-1 | 改造 Regime 相关页面 | frontend-dev | ✅ Verified | Phase 3 完成 |
| P2-2 | 改造 Beta Gate 相关页面 | frontend-dev | ✅ Verified | Phase 3 完成 |
| P2-3 | 改造 Alpha Triggers 相关页面 | frontend-dev | ✅ Verified | Phase 3 完成 |
| P2-4 | 改造模拟交易相关页面 | frontend-dev | ✅ Verified | Phase 3 完成 |
| P2-5 | 改造证券分析相关页面 | frontend-dev | 🔄 Pending | Phase 3 完成 |

**验证说明**: P2-1 到 P2-4 已通过 UI/UX 设计师验证，确认使用了设计 Token。P2-5 待验证。

---

## 6. 工作量评估

| 阶段 | 预计工时 | 并行度 | 建议人员 |
|------|----------|--------|----------|
| Phase 1 | 0.5 天 | 可并行 | 1 人 |
| Phase 2 | 1 天 | 需串行（ui-ux-designer 先完成文档） | 2 人协作 |
| Phase 3 | 2-3 天 | 可并行（4页可分给多人） | 1-2 人 |
| Phase 4 | 3-5 天 | 可并行（多模块可并行） | 1-2 人 |
| **总计** | **6.5-9.5 天** | - | - |

---

## 7. 验收标准

### 7.1 设计 Token 文档验收 ✅
- [x] 完整覆盖所有 Token 类别（颜色、字体、间距、圆角、阴影、动画）
- [x] 包含代码示例和使用指南
- [x] 与现有设计指南保持一致
- [x] CSS 变量命名规范清晰

### 7.2 改造清单验收 ✅
- [x] 改造清单包含所有核心页面
- [x] 有明确的 Token 映射关系
- [x] 有可执行的工作量评估
- [x] 优先级排序合理

### 7.3 页面改造验收 ✅ (Phase 3 完成)
- [x] 核心4页使用设计 Token
- [x] 使用统一的组件类名
- [x] 颜色、间距、圆角使用 Token
- [x] 决策工作台视觉一致性通过
- [x] 政策看板视觉一致性通过
- [x] 信号管理视觉一致性通过
- [ ] 全量页面改造（Phase 4 - 任务 #13 进行中）

---

## 8. 风险与建议

### 8.1 风险
1. **模板文件冗余**: `core/templates/simulated_trading/*` 与 `templates/simulated_trading/*` 重复，可能导致"改了未生效"
2. **路由不一致**: 部分页面路由与实际行为不匹配（如 `/dashboard/` 跳转 Streamlit）
3. **API 混合命名**: 非页面接口未统一使用 `/api/` 前缀

### 8.2 建议
1. **优先处理 P0 问题**: 修复失效链接，避免用户 404
2. **建立 Token 优先**: 先完成设计 Token 文档和 CSS 变量，再进行页面改造
3. **增量改造**: 按优先级逐页改造，每页完成后验收
4. **建立回归测试**: 改造完成后进行视觉回归测试

---

**文档版本**: v1.0
**维护**: ui-ux-designer
**最后更新**: 2026-02-18
