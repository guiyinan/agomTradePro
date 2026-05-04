# 基金研究工作台 UX/UI 刷新记录

> 日期：2026-05-04
> 范围：`core/templates/fund/dashboard.html`、`static/css/fund.css`

## 本次改动

- 将基金页面重构为“研究工作台”结构，按 `筛选 -> 带入研究 -> 风格/业绩/持仓复核` 串联主流程
- 重做顶部信息架构，突出当前 Regime、Policy、Sentiment 与激活信号
- 新增“已选基金”工作台卡片，结果表中的基金可一键带入后续研究工具
- 左侧改为研究流程导航，右侧改为 AI 助手与使用建议，避免三栏内容互相争抢注意力
- 重写 `fund.css`，补齐原页面缺失的布局、表格、表单、卡片和移动端样式

## 修复的交互问题

- 修正前端请求路径，统一改为 `/api/fund/*`
- 修正前端对 API 返回结构的错误假设：
  - `screen` 使用 `fund_codes/fund_names`，并补充二次请求拉取基金详情
  - `rank` 使用 `fund_code/fund_name/total_score/...`
  - `style` 使用 `style_weights/sector_concentration`
  - `performance` 使用嵌套 `performance` 对象
  - `holding` 使用 `holding_ratio/holding_value/holding_amount`
- 将报告期输入从自由文本改为日期输入，降低无效请求概率
- 业绩评估默认填充近一年时间区间，减少空表单操作

## 设计判断

- 本次没有引入新的视觉体系，而是沿用现有 design token 和平台导航样式，避免基金页面与主站割裂
- 优先解决信息层级、路径连贯性和可操作性，而不是只做颜色或排版层面的“美化”
