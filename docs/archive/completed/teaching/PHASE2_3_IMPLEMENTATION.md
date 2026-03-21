# AgomTradePro 教学模块 Phase 2/3 实施文档

> **实施日期**: 2026-02-01
> **实施内容**: Phase 2 & 3 功能增强
> **状态**: 已完成

---

## 一、功能增强总览

### Phase 2 新增功能

| 功能 | 描述 | 文件 |
|------|------|------|
| **Policy 模拟器增强** | 时间线可视化、自定义事件、场景预设 | `policy-simulator-enhanced.js` |
| **历史案例库扩展** | 9个历史案例、搜索筛选、案例对比 | `cases-library.js` |
| **学习进度追踪** | 进度条、成就系统、学习统计 | `learning-progress.js` |

### Phase 3 新增功能

| 功能 | 描述 | 文件 |
|------|------|------|
| **互动式图表** | Regime四象限、配置矩阵、时间线图表 | `interactive-charts.js` |
| **双语支持** | 中英文切换、本地化 | `bilingual-support.js` |

---

## 二、新增文件清单

### Phase 2 文件

| 文件路径 | 说明 | 行数 |
|---------|------|------|
| `core/static/js/teaching/policy-simulator-enhanced.js` | 增强版 Policy 模拟器 | ~450 |
| `core/static/js/teaching/cases-library.js` | 扩展历史案例库 | ~650 |
| `core/static/js/teaching/learning-progress.js` | 学习进度追踪 | ~550 |

### Phase 3 文件

| 文件路径 | 说明 | 行数 |
|---------|------|------|
| `core/static/js/teaching/interactive-charts.js` | 互动式图表组件 | ~350 |
| `core/static/js/teaching/bilingual-support.js` | 双语支持 | ~400 |

---

## 三、详细功能说明

### 3.1 Policy 模拟器增强

#### 时间线可视化
- 实时显示政策事件的时间线
- 累计得分动态更新
- 不同方向事件的颜色区分

#### 预设场景
```
📋 危机应对模式 - 2020年疫情期间政策组合
📋 常规支持模式 - 2019年经济下行期政策组合
📋 抗通胀模式 - 2022年全球通胀时期政策组合
📋 结构调整模式 - 2023年经济结构调整期政策组合
📋 收紧周期模式 - 2017年金融去杠杆时期政策组合
```

#### 自定义事件
- 支持添加自定义政策事件
- 可设置名称、方向、力度、类别
- 可删除自定义事件

### 3.2 历史案例库扩展

#### 新增案例

| 年份 | 标题 | Regime | 难度 |
|------|------|--------|------|
| 2008 | 全球金融危机 | Deflation | 高级 |
| 2015 | 股市大起大落 | Recovery | 高级 |
| 2017 | 金融去杠杆 | Recovery | 中级 |
| 2018 | 贸易摩擦与去杠杆 | Deflation | 高级 |
| 2019 | 科创板与结构性机会 | Recovery | 入门 |
| 2024 | 新质生产力转型 | Deflation | 中级 |

#### 搜索和筛选
- 按分类筛选：危机应对、通胀周期、通缩周期、监管政策等
- 按难度筛选：入门、进阶、高级
- 按年份筛选：2008-2024
- 按 Regime 筛选：Recovery/Overheat/Deflation/Stagflation
- 关键词搜索

#### 案例对比
- 支持多案例对比
- 表格化展示差异
- 一键生成对比报告

### 3.3 学习进度追踪

#### 进度条
- 总体学习进度百分比
- 各章节完成度
- 实时更新

#### 成就系统
```
🎓 初学者 - 完成第一个章节
📚 基础专家 - 完成宏观经济基础章节
🎯 Regime 大师 - 完成 Regime 判定章节
🧮 实践者 - 使用 Regime 计算器
🎮 模拟专家 - 使用 Policy 模拟器
📜 历史研究员 - 阅读3个历史案例
📈 进度过半 - 完成50%的学习内容
🏆 全能专家 - 完成所有学习内容
```

#### 学习统计
- 总进度百分比
- 完成章节数
- 互动工具使用次数
- 已解锁成就数

### 3.4 互动式图表

#### Regime 四象限图表
- 交互式象限展示
- 鼠标悬停显示详情
- 坐标轴说明

#### 资产配置矩阵热力图
- Regime × Policy 二维矩阵
- 颜色编码推荐等级
- 交互提示

#### Regime 时间线图表
- PMI/CPI 历史走势
- 动量变化曲线
- 多指标对比

#### 资产配置饼图
- 目标配置可视化
- 交互式图例
- 百分比显示

### 3.5 双语支持

#### 支持语言
- 🇨🇳 简体中文 (默认)
- 🇺🇸 English

#### 语言切换
- 一键切换中英文
- 所有教学内容同步翻译
- 本地化数字和日期格式

---

## 四、使用方式

### 引入新功能

在 `dashboard/index.html` 中添加新的脚本引用：

```html
<!-- Phase 2 & 3 Enhancements -->
<script src="{% static 'js/teaching/policy-simulator-enhanced.js' %}"></script>
<script src="{% static 'js/teaching/cases-library.js' %}"></script>
<script src="{% static 'js/teaching/learning-progress.js' %}"></script>
<script src="{% static 'js/teaching/interactive-charts.js' %}"></script>
<script src="{% static 'js/teaching/bilingual-support.js' %}"></script>
```

### Policy 模拟器增强使用

```javascript
// 应用预设场景
applyPolicyScenario('crisis_response');

// 添加自定义事件
addCustomPolicyEvent('地方债发行提速', 1, 'fiscal', 'positive');

// 打开自定义事件对话框
openCustomEventDialog();
```

### 案例库使用

```javascript
// 渲染案例库
renderCasesLibrary();

// 按分类筛选
filterByCategory('crisis');

// 对比案例
compareCases(['case2020', 'case2008']);
```

### 学习进度使用

```javascript
// 记录活动
recordCalculatorUse();
recordSimulatorUse();
recordCaseRead('case2020');

// 渲染进度面板
renderLearningProgressPanel();

// 导出/导入进度
exportLearningProgress();
importLearningProgress(file);
```

### 互动图表使用

```html
<!-- 图表容器 -->
<div id="regimeQuadrantChart" style="width:100%;height:400px;"></div>
<div id="allocationMatrixChart" style="width:100%;height:400px;"></div>
```

```javascript
// 初始化图表
initRegimeQuadrantChart('regimeQuadrantChart');
initAllocationMatrixChart('allocationMatrixChart');

// 或批量渲染
renderAllInteractiveCharts();
```

### 双语功能使用

```javascript
// 获取翻译文本
const title = t('modal.title');

// 切换语言
setLanguage('en');
toggleLanguage();

// 获取本地化数据
const sections = getLocalizedSections('en');
const regimes = getLocalizedRegimeData('en');
```

---

## 五、模板更新

### 在 teaching_modal.html 中添加内容

#### 1. 添加学习进度面板

在模态窗中添加进度面板容器：

```html
<div id="learningProgressPanel"></div>
```

#### 2. 添加语言切换器

在模态窗头部添加语言切换器：

```html
<div class="language-switcher-container" id="languageSwitcher"></div>
```

#### 3. 添加互动图表容器

在各章节中添加图表容器：

```html
<!-- Regime 章节 -->
<div id="regimeQuadrantChart" style="width:100%;height:350px;"></div>
<div id="regimeTimelineChart" style="width:100%;height:300px;"></div>

<!-- 资产配置章节 -->
<div id="allocationMatrixChart" style="width:100%;height:350px;"></div>
<div id="allocationPieChart" style="width:100%;height:300px;"></div>

<!-- Regime 计算器 -->
<div id="interactiveRegimeCalc" style="width:100%;height:300px;"></div>
```

#### 4. 添加案例库容器

```html
<div id="casesLibraryContainer"></div>
<div id="caseDetailEnhanced" style="display:none;"></div>
```

#### 5. 增强 Policy 模拟器

```html
<div id="scenarioSelector"></div>
<div id="policyTimelineContainer"></div>
<button onclick="openCustomEventDialog()">+ 添加自定义事件</button>
```

---

## 六、数据持久化

### localStorage 键名

| 键名 | 说明 |
|------|------|
| `teaching_language` | 当前语言设置 |
| `teaching_learning_progress` | 学习进度数据 |
| `teaching_achievements` | 已解锁成就列表 |

### 导入/导出

```javascript
// 导出进度为 JSON 文件
exportLearningProgress();

// 从 JSON 文件导入
<input type="file" accept=".json" onchange="importLearningProgress(this.files[0])">
```

---

## 七、响应式支持

所有新增功能均支持移动端：

- Policy 模拟器：时间线自适应宽度
- 案例库：网格布局自动调整
- 学习进度：统计卡片2列布局
- 互动图表：自动调整尺寸
- 语言切换：移动端只显示图标

---

## 八、浏览器兼容性

| 功能 | Chrome | Firefox | Safari | Edge |
|------|--------|---------|--------|------|
| Policy 模拟器增强 | ✅ | ✅ | ✅ | ✅ |
| 案例库扩展 | ✅ | ✅ | ✅ | ✅ |
| 学习进度追踪 | ✅ | ✅ | ✅ | ✅ |
| 互动图表 (ECharts) | ✅ | ✅ | ✅ | ✅ |
| 双语支持 | ✅ | ✅ | ✅ | ✅ |

---

## 九、性能优化

1. **延迟加载**: 图表在模态窗打开后初始化
2. **事件委托**: 案例列表使用事件委托
3. **localStorage 缓存**: 进度数据本地存储
4. **MutationObserver**: 高效监听 DOM 变化
5. **按需渲染**: 图表仅在可见时渲染

---

## 十、后续优化建议

### 功能增强
- [ ] 添加练习题库和评分系统
- [ ] 支持用户自定义笔记
- [ ] 添加学习计划提醒
- [ ] 支持更多语言（日语、韩语等）

### 内容扩展
- [ ] 添加更多国际案例（美国、欧洲）
- [ ] 添加行业板块案例
- [ ] 添加更多资产类别分析

### 技术优化
- [ ] 后端存储学习进度（支持多设备同步）
- [ ] 添加离线下载功能
- [ ] 优化图表加载性能
- [ ] 添加数据导出功能

---

## 十一、验收清单

### Phase 2 必须达成 ✅

- [x] Policy 模拟器时间线显示正常
- [x] 预设场景可用
- [x] 支持添加自定义事件
- [x] 历史案例库包含9个案例
- [x] 搜索筛选功能正常
- [x] 案例对比功能可用
- [x] 学习进度条显示正确
- [x] 成就系统解锁正常

### Phase 3 必须达成 ✅

- [x] Regime 四象限图表正常
- [x] 资产配置矩阵图表正常
- [x] 时间线图表正常
- [x] 语言切换功能正常
- [x] 所有教学内容支持双语

---

*文档结束*
