 # AgomSAAF 外包团队系统测试执行方案

  ## 一、方案摘要

  本方案面向 AgomSAAF V3.4 当前代码基线，用于指导外包团队在 本地环境为主 完成一轮完整系统测试，并产出可用于验收、缺陷流转和版本放行的测试证据。

  方案基于仓库现状制定，而不是抽象模板。当前项目已具备以下可复用资产：

  - Django 5.x 主系统，含 27 个业务模块
  - 现有测试分层：unit / integration / api / e2e / playwright / performance / uat / guardrails
  - 已有 UAT、RTM、验收报告模板、守护测试和部分性能测试
  - 本地启动脚本与测试编排脚本已存在，可直接作为外包执行入口

  本次建议的测试策略为：

  - 环境策略：本地环境为主
  - 依赖策略：分层混合
      - 功能回归、批量执行：优先固定测试数据 / mock / 本地依赖
      - 关键链路联调：少量使用真实依赖或准真实依赖
  - 交付形式：执行手册 + 检查清单 + 缺陷报告 + 汇总结论

  ———

  ## 二、测试目标

  本轮系统测试的目标不是“重复开发自测”，而是从第三方执行视角验证以下事项：

  1. 系统主链路可运行，关键页面、关键 API、关键业务流程无阻断性问题。
  2. 核心业务逻辑在跨模块联动时保持正确，尤其是宏观判定、政策档位、信号准入、回测、决策执行、模拟交易、审计复盘。
  3. UI/导航/权限/API 命名/接口契约与当前系统约定一致。
  4. 异步任务、监控、健康检查、日志导出、Prometheus 指标等运维相关能力可用。
  5. 系统在本地标准环境下具备可接受的稳定性和基础性能。
  6. 测试结果可追踪到需求、模块、缺陷和放行结论。

  ———

  ## 三、测试范围

  ### 1. 业务范围

  建议纳入本轮系统测试的业务域：

  - 账户与权限
  - Dashboard / Decision Workspace / Ops Center
  - Macro / Regime / Policy
  - Signal / Filter / Asset Analysis
  - Equity / Fund / Sector
  - Backtest / Audit
  - Strategy / Decision Rhythm / Beta Gate / Alpha Trigger
  - Simulated Trading / Portfolio
  - Realtime / Task Monitor / Monitoring
  - API 文档、路由兼容、健康检查、日志、指标

  ### 2. 测试层级范围

  本轮外包测试应覆盖以下层级：

  - 配置与安装验证
  - 冒烟测试
  - 功能测试
  - 集成测试
  - API 契约测试
  - 端到端流程测试
  - UAT 旅程测试
  - 权限与安全基线测试
  - 稳定性与恢复测试
  - 基础性能测试
  - 发布前验收测试
  - 本地部署后巡检测试

  ### 3. 明确不纳入本轮范围

  除非你后续追加要求，否则先默认不纳入：

  - 生产环境压测
  - 大规模并发压测
  - 灾备切换演练
  - 真资金交易验证
  - 全量外部第三方真实数据源长期稳定性测试
  - 全量 Qlib 深度训练性能评估

  ———

  ## 四、测试对象与现有入口

  ### 1. 本地启动入口

  - 服务启动：scripts/start-dev.ps1
  - 推荐模式：sqlite
  - 支持模式：sqlite / postgres / docker

  ### 2. 自动化执行入口

  - 总编排：run_all_tests.ps1
  - UAT 执行：tests/uat/run_uat.py

  ### 3. 现有测试目录分层

  - tests/unit
  - tests/integration
  - tests/api
  - tests/e2e
  - tests/playwright
  - tests/performance
  - tests/guardrails
  - tests/uat
  - tests/acceptance

  ### 4. 关键系统入口

  - 首页 /
  - API 根 /api/
  - 健康检查 /api/health/
  - 就绪检查 /api/ready/
  - OpenAPI /api/schema/
  - Swagger /api/docs/
  - 指标 /metrics/

  ———

  ## 五、外包团队角色分工

  建议最小团队配置：

  1. 测试负责人（1人）
  2. 功能测试工程师（2人）
  3. API / 集成测试工程师（1人）
  4. 自动化 / Playwright 执行工程师（1人，可兼职）
  5. 缺陷管理员/报告汇总（可由测试负责人兼任）

  职责划分：

  - 测试负责人
      - 维护计划、排期、日报、风险、缺陷优先级、最终汇总
  - 功能测试
      - 页面、流程、权限、异常路径、文案与可用性
  - API / 集成测试
      - 接口契约、状态码、参数校验、跨模块联动
  - 自动化执行
      - 执行现有 pytest / Playwright / UAT 脚本，整理日志、截图、报告

  ———

  ## 六、环境与数据准备规范

  ### 1. 标准执行环境

  建议外包统一使用以下基线：

  - Windows + PowerShell
  - Python 3.11+
  - 本地虚拟环境 agomsaaf
  - Django 开发设置
  - 默认本地端口 8000

  ### 2. 环境准备步骤

  1. 校验虚拟环境存在。
  2. 安装项目依赖。
  3. 准备 .env。
  4. 执行数据库迁移。
  5. 启动本地服务。
  6. 验证 /api/、/api/health/、/api/docs/ 可访问。

  ### 3. 数据策略

  采用三层数据策略：

  1. 固定基线数据
      - 用于回归、截图比对、旅程执行
  2. 合成测试数据
      - 用于边界值、异常输入、权限隔离
  3. 少量真实依赖校验数据
      - 用于关键联动和 failover 验证

  ### 4. 默认依赖策略

  - SQLite 作为默认执行底座
  - 需要 Celery/Redis 的测试项单独标记
  - 需要 Docker/Postgres 的测试项独立分组，不阻塞主回归批次
  - 外部 API 波动不应阻断主验收，需单独归类为“外部依赖验证批次”

  ———

  ## 七、测试批次设计

  建议拆成 7 个执行批次，便于外包排期和验收。

  ### 批次 0：环境与安装验证

  目标：

  - 确认外包执行环境可复现
  - 避免后续缺陷被环境问题污染

  检查项：

  - 虚拟环境存在
  - 依赖安装成功
  - .env 正常
  - manage.py migrate 成功
  - 服务可启动
  - /api/health/ 返回成功
  - /api/docs/ 可打开
  - /metrics/ 有输出

  通过标准：

  - 所有基础检查通过
  - 否则不得进入后续批次

  ### 批次 1：系统冒烟

  目标：

  - 快速判断系统是否达到“可测状态”

  覆盖项：

  - 首页
  - 登录/权限重定向
  - Dashboard
  - Policy / Regime / Signal / Backtest / Simulated Trading / Audit
  - 关键 API 根路径
  - 主导航无 404
  - 核心接口非 500 / 非 501

  通过标准：

  - P0 阻断缺陷为 0
  - 关键入口成功率 100%

  ### 批次 2：主业务功能回归

  目标：

  - 验证各业务模块核心功能可用

  功能组：

  - Macro 数据展示与同步入口
  - Regime 判定与象限展示
  - Policy 档位管理、事件创建/更新/删除
  - Signal 创建、审批、证伪逻辑展示
  - Asset Analysis / Equity / Fund / Sector 筛选与结果展示
  - Backtest 创建、执行、结果查看
  - Audit 报告、归因字段
  - Simulated Trading 账户/持仓/净值/调仓建议
  - Strategy / Execution 评估与编排
  - Realtime 监控页面与接口
  - Ops / 日志 / 配置中心

  通过标准：

  - 各模块核心用例通过率 >= 95%
  - 无 P0 缺陷
  - P1 缺陷可控且有回避路径

  ### 批次 3：跨模块集成与系统链路

  目标：

  - 验证系统不是“单点可用”，而是链路可用

  重点链路：

  1. Macro -> Regime -> Policy -> Signal
  2. Signal -> Strategy -> Decision Execution
  3. Asset Analysis -> Recommendation -> Decision
  4. Backtest -> Audit
  5. Simulated Trading -> Position / Net Value / Notification
  6. Realtime -> Monitoring -> Alert / Metrics
  7. Config Center -> Runtime Capability -> API

  通过标准：

  - 关键链路全部至少执行 1 次正向场景 + 1 次异常场景
  - 链路中断类问题全部记录并复现

  ### 批次 4：UAT 与用户旅程

  目标：

  - 从用户视角验证 A-E 关键旅程可走通

  旅程基线沿用现有定义：

  - Journey A：新用户入门
  - Journey B：研究与选标
  - Journey C：决策与执行
  - Journey D：交易与持仓
  - Journey E：复盘与运营

  验收项：

  - 页面可达
  - 信息结构清晰
  - 关键操作可完成
  - 跳转、权限、文案、状态反馈正常
  - 无严重视觉或交互阻断

  通过标准：

  - 关键旅程通过率 >= 90%
  - 主导航 404 = 0
  - 手工验收评分达到预设门槛

  ### 批次 5：安全/权限/稳定性/异常恢复

  目标：

  - 验证系统在错误输入、权限隔离、部分依赖异常下的行为

  覆盖项：

  - 未登录访问受限页面
  - 不同角色权限隔离
  - 非法参数 / 空参数 / 超长参数
  - 错误状态码映射
  - 历史兼容路由重定向
  - Celery/Redis 不可用时的降级或错误反馈
  - 外部数据源失败时 failover 行为
  - 日志/告警/错误信息是否可追踪
  - 不得出现主链路 501、占位接口、NotImplementedError 暴露

  通过标准：

  - 无高危权限问题
  - 无敏感信息泄露
  - 异常路径具备明确错误反馈
  - 高风险守护项全部通过

  ### 批次 6：基础性能与发布前验收

  目标：

  - 验证系统满足本地验收级性能和最终放行条件

  覆盖项：

  - 核心 API 响应时间
  - 页面首屏可用时间
  - 常见列表页/详情页加载稳定性
  - 连续执行稳定性
  - 现有性能测试脚本执行结果
  - RTM / UAT / 缺陷汇总

  通过标准：

  - 关键 API P95 满足项目设定阈值
  - 页面无明显卡死、超时、白屏
  - 发布前阻断缺陷为 0

  ———

  ## 八、详细测试类型与执行要求

  ## 1. 配置与安装测试

  验证点：

  - 虚拟环境是否齐全
  - 依赖是否完整
  - 启动脚本是否可执行
  - 数据库迁移是否成功
  - 本地服务是否稳定启动
  - OpenAPI/Swagger 是否可访问

  输出物：

  - 环境检查表
  - 安装问题清单
  - 可复现步骤

  ## 2. 功能测试

  按模块建立用例集，每个模块至少覆盖：

  - 正常路径
  - 必填项缺失
  - 非法输入
  - 边界值
  - 无数据场景
  - 失败提示
  - 刷新/重复提交
  - 兼容旧入口或别名路由

  ## 3. API 测试

  重点覆盖：

  - 状态码正确性
  - 请求参数校验
  - 响应 JSON 结构
  - 字段类型
  - 空集 / 缺省值
  - 错误码与错误文案
  - 幂等性
  - 兼容别名路由
  - /api/* 命名规范一致性
  - OpenAPI 文档与真实响应一致

  需重点关注的公开接口类别：

  - account
  - macro
  - regime
  - policy
  - signal
  - strategy
  - simulated-trading
  - backtest
  - audit
  - dashboard
  - system/config-center
  - system/config-capabilities
  - market-data
  - events

  ## 4. 集成测试

  重点验证：

  - 数据在模块间传递是否正确
  - 配置变更是否影响下游
  - 事件/策略/证伪/调仓建议是否联动
  - 审计与回测数据是否一致
  - 监控指标是否跟随系统行为变化

  ## 5. E2E 与 Playwright 测试

  使用现有 tests/playwright 资产进行执行和补充，不要求外包从零搭框架。

  重点检查：

  - 登录/跳转
  - 主导航
  - 关键旅程
  - 表单提交流程
  - 页面可见性
  - 截图证据
  - 视觉一致性抽查

  ## 6. UAT 测试

  沿用现有 tests/uat 的旅程结构与模板。

  UAT 必须包含两类证据：

  - 自动化旅程结果
  - 人工验收记录

  人工验收重点：

  - 信息可理解性
  - 操作路径清晰度
  - 状态标签、按钮、表格一致性
  - 关键术语一致性
  - 错误提示是否可被业务人员理解

  ## 7. 守护测试 / 回归测试

  必须纳入发布前回归的守护项：

  - 主链路无 501
  - 无占位接口
  - 路由基线一致
  - API 命名规范
  - 核心策略和逻辑边界
  - 高风险业务规则回归

  ## 8. 性能测试

  本轮只做基础性能，不做重压。

  建议指标：

  - 核心 API 平均响应时间
  - P95 响应时间
  - 首次打开关键页面响应感受
  - 连续执行稳定性
  - 慢查询或明显阻塞接口

  建议分级：

  - P0 接口：健康检查、关键决策接口、主数据接口
  - P1 接口：列表和详情类
  - P2 接口：后台辅助接口

  ## 9. 安全与权限测试

  至少覆盖：

  - 未授权访问
  - 越权访问
  - 登录后访问边界
  - 管理后台访问控制
  - 敏感日志暴露
  - 输入注入类基础风险
  - 调试信息泄露
  - 文档接口暴露是否符合预期

  ## 10. 监控与运维测试

  至少覆盖：

  - /api/health/
  - /api/ready/
  - /metrics/
  - 日志流导出
  - 服务器日志页面/导出
  - 配置中心快照
  - 能力配置接口
  - 异常发生时是否有可观察证据

  ———

  ## 九、优先级模型

  统一采用四级缺陷优先级：

  - P0
      - 系统不可用、主流程阻断、数据错误、权限绕过、关键接口失效
  - P1
      - 核心功能可用但结果错误或流程严重受限
  - P2
      - 非核心功能异常、交互/文案/局部数据问题
  - P3
      - 低风险体验问题、样式问题、优化建议

  统一采用三档测试优先级：

  - T0
      - 发布阻断项，必须每轮执行
  - T1
      - 核心回归项，版本候选前必须执行
  - T2
      - 扩展项，时间允许执行

  ———

  ## 十、测试执行顺序

  建议外包按以下顺序执行，避免返工：

  1. 环境与安装验证
  2. 冒烟测试
  3. 主业务功能回归
  4. 跨模块集成测试
  5. UAT 与旅程测试
  6. 权限/异常/恢复测试
  7. 基础性能测试
  8. 回归复测
  9. 汇总 RTM、缺陷、截图、日志、结论

  ———

  ## 十一、建议直接使用的现有测试资产

  以下资产应直接纳入外包执行清单：

  ### 1. 基础编排

  - run_all_tests.ps1

  用途：

  - 快速跑 SDK/MCP/集成/逻辑守护相关编排
  - 适合作为环境验证和批量冒烟的入口

  ### 2. UAT 入口

  - tests/uat/run_uat.py

  用途：

  - 执行 Journey A-E
  - 生成验收报告
  - 适合作为 RC 前验收批次入口

  ### 3. 守护测试

  - tests/guardrails/test_logic_guardrails.py
  - tests/guardrails/test_no_501_on_primary_paths.py
  - tests/guardrails/test_security_hardening_guardrails.py

  用途：

  - 发布阻断项回归

  ### 4. 关键集成测试

  - tests/integration/test_complete_investment_flow.py
  - tests/integration/test_backtesting_flow.py
  - tests/integration/test_realtime_monitoring_flow.py
  - tests/integration/test_decision_execution_integration.py
  - tests/integration/test_decision_execution_approval_chain.py
  - tests/integration/test_failover_flow.py
  - tests/integration/test_prometheus_metrics.py

  ### 5. UAT / 合规检查

  - tests/uat/test_api_naming_compliance.py
  - tests/uat/test_route_baseline_consistency.py

  ### 6. Playwright UAT

  - tests/playwright/tests/uat/test_user_journeys.py

  ### 7. 现有追踪矩阵与模板

  - docs/testing/requirements-traceability-matrix-2026-02.md
  - tests/uat/uat_acceptance_checklist.md
  - tests/uat/uat_acceptance_report_template.md
  - tests/uat/final_acceptance_report_template.md

  ———

  ## 十二、外包执行清单模板

  每轮执行必须交付以下清单。

  ### 1. 执行前清单

  - 环境已就绪
  - 依赖安装完成
  - 本地服务已启动
  - 测试账号与权限已准备
  - 基线数据已导入
  - 执行批次与负责人已分配

  ### 2. 执行中清单

  - 每条失败用例都有截图或日志
  - 每个 P0/P1 缺陷都有稳定复现步骤
  - 每日同步执行进度、阻塞项、风险项
  - 真实依赖失败与产品缺陷分开归类

  ### 3. 执行后清单

  - 缺陷台账更新
  - 用例执行结果汇总
  - 自动化日志归档
  - 截图与视频归档
  - 版本结论输出
  - RTM 状态更新
  - 回归建议输出

  ———

  ## 十三、缺陷管理规范

  每个缺陷至少包含：

  - 缺陷编号
  - 标题
  - 模块
  - 环境
  - 前置条件
  - 复现步骤
  - 实际结果
  - 预期结果
  - 严重级别
  - 优先级
  - 截图/日志/接口报文
  - 是否稳定复现
  - 是否阻断验收

  缺陷归类建议：

  - 功能缺陷
  - 接口契约缺陷
  - 权限安全缺陷
  - 数据一致性缺陷
  - 性能缺陷
  - UI/UX 缺陷
  - 兼容性缺陷
  - 环境/依赖问题

  ———

  ## 十四、验收标准

  建议作为本轮外包测试的放行标准：

  ### 必须满足

  - P0 缺陷 = 0
  - 主导航 404 = 0
  - 主链路 501 = 0
  - Journey A-E 关键旅程通过率 >= 90%
  - 核心 API 契约检查通过
  - 健康检查、就绪检查、指标接口可用
  - 关键跨模块链路全部有执行证据
  - 发布阻断守护项全部通过

  ### 可接受范围

  - P1 缺陷 <= 2，且有明确规避方案与修复计划
  - P2/P3 缺陷允许进入观察列表，但不得影响主流程
  - 外部真实依赖波动可单独记录，不直接判定主系统失败，前提是 mock/固定数据链路通过

  ———

  ## 十五、最终交付物要求

  外包团队最终必须提交以下内容：

  1. 《系统测试执行报告》
  2. 《缺陷清单》
  3. 《UAT 验收清单》
  4. 《最终验收报告》
  5. 《自动化执行日志归档》
  6. 《截图/录屏证据包》
  7. 《需求-测试追踪矩阵更新版》
  8. 《风险与遗留问题清单》

  建议报告结构：

  - 测试范围
  - 环境说明
  - 执行批次
  - 用例统计
  - 缺陷统计
  - 关键截图与证据
  - 风险说明
  - 验收结论
  - 放行建议

  ———

  ## 十六、公共接口/类型/输出物变化要求

  本方案不要求修改系统业务 API，但要求外包交付遵守统一输出接口：

  ### 1. 缺陷清单字段标准

  - defect_id
  - title
  - module
  - severity
  - priority
  - environment
  - steps
  - expected_result
  - actual_result
  - attachments
  - status
  - owner

  ### 2. 用例执行结果字段标准

  - case_id
  - batch_id
  - module
  - test_level
  - executor
  - execution_time
  - result
  - evidence_link
  - defect_id

  ### 3. 验收结论字段标准

  - version
  - test_window
  - blocking_defects
  - critical_pass_rate
  - journey_pass_rate
  - api_contract_status
  - ops_check_status
  - final_decision

  ———

  ## 十七、建议排期

  建议按 5 个工作日组织一轮：

  ### Day 1

  - 环境搭建
  - 冒烟测试
  - 基线数据准备
  - 执行批次分工

  ### Day 2

  - 主业务功能回归
  - API 契约检查

  ### Day 3

  - 集成链路
  - UAT 旅程
  - Playwright 执行

  ### Day 4

  - 权限/异常/稳定性/性能
  - 第一轮缺陷复测

  ### Day 5

  - 回归复测
  - 报告汇总
  - 验收结论
  - 风险与遗留问题输出

  ———

  ## 十八、测试用例与场景要求

  每个重点模块至少要有以下场景：

  - 1个正常场景
  - 1个无数据场景
  - 1个边界值场景
  - 1个错误输入场景
  - 1个权限场景
  - 1个异常依赖场景
  - 1个历史兼容/重定向场景（适用时）

  重点系统级场景必须至少覆盖：

  1. 从宏观数据到 Regime 判定再到 Policy/Signal 的全链路
  2. 从策略评估到执行决策的全链路
  3. 从回测到审计查看的全链路
  4. 从模拟交易到账户/持仓/净值更新的全链路
  ———


  本方案基于以下默认值制定：

  - 默认测试版本：当前仓库基线，对应 AgomSAAF V3.4
  - 默认环境：外包团队本地环境
  - 默认数据库：SQLite
  - 默认依赖策略：混合模式
  - 默认不含生产压测与真资金交易
  - 默认以现有自动化资产为主，不要求外包重写测试框架
  - 默认由你方提供测试账号、基础数据和必要环境变量
  - 默认外包团队可访问仓库并执行 PowerShell / pytest / Playwright
  - 默认验收结论以本轮测试报告和缺陷状态为准

  ———

  ## 二十、建议你交给外包的附件包

  建议你把以下内容一起发给外包团队：

  - 本方案
  - 当前版本代码或测试分支
  - 环境搭建说明
  - 测试账号清单
  - 测试数据说明
  - tests/uat 下的清单和模板
  - docs/testing/requirements-traceability-matrix-2026-02.md
  - 缺陷提单模板
  - 每日汇报模板
  - 测试完成标准说明

  如果你要，我下一轮可以把这份方案继续细化成两种直接可发包的版本之一：

  1. “外包测试执行SOW”版

  2. “逐日执行表 + 用例清单Excel字段”版