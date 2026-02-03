# 浮动小组件系统（Floating Widget System）

## 实施状态：✅ 全部完成

## 概述

浮动小组件系统为 AgomSAAF 的大部分页面添加了浮动帮助小组件，提供页面的功能介绍和计算逻辑说明。

## 已完成的工作

### Phase 1: 核心框架 ✅

1. **CSS 文件** `core/static/css/floating-widget.css`
   - 收起/展开状态样式
   - 位置配置（bottom-right, bottom-left, top-right, top-left）
   - 移动端响应式
   - 动画效果
   - 深色模式支持

2. **JS 组件** `core/static/js/components/floating-widget.js`
   - AgomFloatingWidget 类
   - open() / close() / toggle() 方法
   - ESC 键关闭
   - 点击背景关闭
   - localStorage 状态记忆
   - 自动初始化支持

3. **全局集成** `core/templates/base.html`
   - CSS 和 JS 已添加到 base.html

### Phase 2-4: 配置文件 ✅

所有11个页面的配置文件已创建并集成：

| 优先级 | 页面 | 配置文件 | 状态 |
|--------|------|----------|------|
| P0 | Regime Dashboard | `regime_widget.json` | ✅ 已集成 |
| P1 | Backtest Detail | `backtest_widget.json` | ✅ 已集成 |
| P1 | Equity Screen/Detail | `equity_widget.json` | ✅ 已集成 |
| P2 | Policy Dashboard | `policy_widget.json` | ✅ 已集成 |
| P2 | Dashboard Index | `dashboard_widget.json` | ✅ 已集成 |
| P2 | Strategy Detail | `strategy_widget.json` | ✅ 已集成 |
| P3 | Fund Dashboard | `fund_widget.json` | ✅ 已集成 |
| P3 | Sector Analysis | `sector_widget.json` | ⏸️ 页面待开发 |
| P3 | Filter Dashboard | `filter_widget.json` | ✅ 已集成 |
| P3 | Account Profile | `account_widget.json` | ✅ 已集成 |
| P3 | Simulated Trading | `simulated_trading_widget.json` | ✅ 已集成 |

### 已集成的页面模板（10个）

1. **Regime Dashboard** (`core/templates/regime/dashboard.html`) - 📊
2. **Backtest Detail** (`core/templates/backtest/detail.html`) - 📈
3. **Equity Screen** (`core/templates/equity/screen.html`) - 🔍
4. **Equity Detail** (`core/templates/equity/detail.html`) - 🔍
5. **Policy Dashboard** (`core/templates/policy/dashboard.html`) - 📰
6. **Dashboard Index** (`core/templates/dashboard/index.html`) - 🎯
7. **Strategy Detail** (`core/templates/strategy/detail.html`) - ⚙️
8. **Fund Dashboard** (`core/templates/fund/dashboard.html`) - 💰
9. **Filter Dashboard** (`core/templates/filter/dashboard.html`) - 📉
10. **Account Profile** (`core/templates/account/profile.html`) - 👤
11. **Simulated Trading Dashboard** (`core/templates/simulated_trading/dashboard.html`) - 🎮

## 配置文件格式

```json
{
    "widgetId": "唯一标识符",
    "title": "小组件标题",
    "icon": "图标emoji",
    "position": "bottom-right",
    "sections": [
        {
            "id": "section-id",
            "title": "章节标题",
            "type": "content|accordion",
            "content": "HTML内容（type=content时）",
            "items": [...] // 子项（type=accordion时）
        }
    ],
    "actions": [
        {
            "label": "按钮文字",
            "icon": "图标",
            "action": "函数名|url"
        }
    ]
}
```

## 验证步骤

1. **启动开发服务器**：
   ```bash
   python manage.py runserver
   ```

2. **测试各页面**：
   - 访问对应页面
   - 确认右下角有浮动按钮
   - 点击按钮，确认展开为小组件
   - 确认内容正确显示
   - 测试 ESC 键关闭
   - 测试点击外部关闭

3. **测试移动端**：
   - 缩小浏览器窗口到手机尺寸
   - 确认小组件从底部滑出
   - 确认样式正常

## 设计决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 内容格式 | JSON 配置 | 与代码分离，易于更新，支持 i18n |
| 位置 | 浮动在右下角 | 不干扰主要内容，符合用户习惯 |
| 默认状态 | 收起 | 减少视觉干扰，按需展开 |
| 与教学模态框关系 | 共存 | 小组件=快速参考，模态框=深入学习 |

## 技术特性

1. **响应式设计**: 支持桌面和移动端
2. **无障碍**: 支持键盘导航和屏幕阅读器
3. **状态持久化**: 使用 localStorage 记忆用户偏好
4. **深色模式**: 支持系统级深色模式切换
5. **动画效果**: 平滑的展开/收起动画
6. **可配置**: JSON 配置文件易于维护和更新

## 未来扩展

- AI 驱动的智能问答
- 视频教程嵌入
- 用户反馈和评分
- 使用分析统计
- 全文搜索功能
- 书签功能
