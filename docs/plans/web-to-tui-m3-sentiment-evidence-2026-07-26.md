# Web → TUI M3 Sentiment Analysis Wave 证据（2026-07-26）

## 范围与闭环

- Wave：`M3-sentiment-w22`；覆盖文本情绪分析 1 个认证 route template。
- `research.signals` 新增 `sentiment.analyze-text` 与 `sentiment.health` 两个 action。
  分析表单保留最多 5000 字文本和是否使用缓存选项，结果展示情绪评分、置信度、
  分类与关键词。
- 复用既有 `/api/sentiment/analyze/` 和 `/api/sentiment/health/` owner API，
  没有复制 Classic 页内 fetch、loading 和 DOM 拼装脚本。
- 分析可能写入缓存与分析日志，因此 TUI action 明确标为 execute/write 并要求确认；
  服务不可用继续以 503 明确返回，不伪装成中性情绪。
- Classic 页面保持 login-required，发布精确 TUI deep link，并在稳定期保留。

## 验证与风险

- Sentiment API、Classic page component、TUI metadata 与 IA 合计 `17 passed`。
- ruff 通过；新增 metadata 与 registry 增量 mypy 为 `0 regressions`。
- migration inventory 与 TUI static contract 在本 wave 收口命令中复核。
- 真实 live-server 文本输入→缓存开关→AI 结果/503 错误 UAT 尚未执行；Classic 路由
  删除仍受 M5 稳定期、访问量和回滚门槛约束。
