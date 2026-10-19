# M5 受控读取输入与请求作用域

本批为一次性 CI SQLite 库提供 M5 读取所需的合成日历、Universe 配置和情绪计算输入，并保留既有真实 HTTP/TUI 操作、角色限制、所有权、超时和清理检查。全部输入均须显式 opt-in；准入要求 CI、GitHub Actions、`core.settings.playwright`、字面量 loopback 地址，以及 `RUNNER_TEMP/agomtradepro-rc-playwright.sqlite3` 同时等于 NAME、TEST.NAME 和 `AGOM_PLAYWRIGHT_DB_PATH`。普通环境不安装日历 App 或 middleware。

合成日历只在以下四个 POST action 请求内进入原日历 loader：`data-center.market-thermometer-current`、`operator.governance.data_center_summary`、`task-monitor.readiness`、`dashboard.alpha-ranking`。非名单请求和后台调用保留原来源；嵌套请求及复制的 context 在结束后失效。普通和合成 loader 共用同一 RLock，合成读取的 cache-clear/load/cache-clear 在一个临界区内完成，防止其他请求命中合成缓存。原始 JSON、观测时间和 SHA sidecar 均校验，半写入或篡改保留现场并拒绝使用。

Universe 配置在 worker 内通过真实管理员 PUT/GET 及回读核对，连接在 finally 关闭；该 singleton 保留在一次性克隆库中，不声称恢复旧配置。情绪 fixture 只在股票池 case 执行前调用，使用真实 calculator、repository 和 resolver；拒绝已有当日/未来行，并按本次主键及全部内容、时间戳精确核对后清理。该测试需要独占数据库和无并发情绪写入者。fixture 不创建正式发布、activation、authority 或生产决策资格。

R1 的模块级日历作用域和 R2 的共享缓存竞态分别被静态复核拒绝，冻结原件保留。R3 首轮 33 项单测为 29 passed / 4 failed：测试漏计了过期 context 正确回退原 factory 的调用。修正后在每个阶段核对 3、4、5、6 次原 factory 调用及 2 次合成调用，33 passed，0 failure/error/skip。

完整 M5 模块及实际 fixture opt-out 请求在私有组合副本中执行：15 项中 14 passed / 1 failed，0 error/skip，另 2 项 live AI 按既定 marker 排除；唯一失败为 `equity.valuation-overview`，真实终态为“结果受阻，未形成可用结果”。副本绑定 `1c3d9fb7710a04c201049a25ce677538e8747445` 和 18 个明确 overlay，包含缺失 gate 修复及尚未采用的锁预算辅助代码，不能声称本批干净提交或最终 RC 已通过。原私有源库及 18 份源码哈希未变，日历 artifact 已清理。

原件在本机仓库外 `C:/Users/muku/.codex/evidence-archives/agomTradePro/2026-10-19/m5-run14-and-calendar-scope/`，55 份成员，索引 SHA-256 `885c54c416e5c7f199adba3ec15570effff94187ba036e1841e2cf58daff5349`。归档包含初次失败、修正源码、独立静态审查和实际运行记录；未上传。

共享采用以 `292b595957011d01e52446976797e861cd69d0ee` 为基线，仅采用 14 个测试输入/工作流路径，不采用估值生产核心或锁预算补丁。初次 isort/Ruff 失败已修正，保留失败记录；settings 使用显式基类模块属性，缓存函数使用直接属性访问。最终共享源码的 33 项单测、Black、isort、Ruff、`core/settings/playwright.py` 增量 mypy（0 regression / 0 legacy）、全库类型债务（0 errors）、官方 module map build/check 及限定空白检查均通过，module map 的 Git diff 为空。两项 import 排序只调整顺序，导入绑定及其余 AST 一致。

共享批次原件在本机仓库外 `C:/Users/muku/.codex/evidence-archives/agomTradePro/2026-10-19/m5-controlled-inputs-292-pass/`，45 份成员，索引 SHA-256 `7addcef7763f32ca763e19c76c3a85ebc6d5323e7bda85b36b41d16ef4159cb9`。该归档绑定最终 14 份源码和实际检查结果，未上传。外来五文件、ITA 标记和本任务既有未提交部署计划均保留。

完整 RC 继续执行全部 UAT、health timeout 180 秒、至少 20 项和无跳过门禁。估值正常读取、同一干净候选 RC、独立 Publication PostgreSQL 制品及全新 S6 仍待完成。本批未部署，未创建 S6 测试账号，未开始观察窗口或关闭 TUI-02。
