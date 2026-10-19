# TUI RC：M5 发布数据夹具与可见结果

本批补齐 M5 正向估值读取所需的受控 published financial/market 成员，并在 RC 的 M5 专用测试配置中显式 opt-in。默认研究夹具的隔离保护不变；新入口只接受 CI、精确 loopback、M5 settings、固定 RUNNER_TEMP SQLite 路径和同一 NAME/TEST/AGOM 数据库，拒绝路径逃逸及符号链接。合成输入只证明消费者读取，不代替生产发布权限、真实用户 UAT 或独立复核。

估值断言改为定位真实 detail grid 的标签及对应值，保留成功状态、实际响应、七项来源和值断言；失败诊断只输出白名单字段并使用当前操作页面。跨本地午夜复验曾因 UTC 日期与 `date.today()` 不同而在 sentiment 夹具前置失败；仅将实际 aware 时钟表示转为系统本地时区，独立日期保护、存储/回读和精确行清理均保留，符合 owner 的现有日期口径。

- 独立静态复核通过。专用数据库保护五项反例/正例及八项发布成员/旧 API 检查此前已通过，相关夹具实现哈希保持一致；格式检查通过。
- 最新定向浏览器测试真实完成 pool 和 valuation：1 passed / 0 failed / 0 errors / 0 skipped；随后另建数据库副本运行原本地 M5+opt-out 集：15 passed / 0 failed / 0 errors / 0 skipped，原有两项 live-AI 排除规则不变。原动作时限、health 180 秒、no-skips 及正式 RC minimum 20 未放宽。
- 两次通过绑定同一 `e786271a5…` HEAD、显式十三路径 adoption lock 和源码指纹 `5f69d07ab093355e7a2536aff387b93a61826ec836c8c329f2a4780298800787`。所有 tracked/untracked 文件、暂存内容及标记不变；ITA `20004000` 保留，迁移基线未变，calendar 临时工件清理，18770 服务关闭。
- 此前一次浏览器主体通过但本地包装器因原始 Git index 缓存变化拒绝，原结果保留。复核确认文件字节、HEAD、状态无变化；后续包装器绑定 staged entries、Git 标记及 ITA，原始缓存只作诊断。新鲜副本重新实跑得到上述结果，没有追认旧失败。

原件仅本机可用：`C:/Users/muku/.codex/evidence-archives/agomTradePro/2026-10-20/m5-owned-fixtures-positive15/`；索引 SHA-256 `1e47fadcb4a452991295d3ecd9335bbfb7eeaf9895cec2148f4d8375a344eccb`。此前 R15/R16 失败仍见各自归档。本轮共享树含明确绑定的其他任务 WIP，结果不构成最终干净候选的 RC/S6 或生产资格。测试 superuser 已获授权但尚未创建，等待最终 RC 及 fresh S6 prepare；没有部署或启动观察 T0。
