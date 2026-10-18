# 每周 code-only 发布与首次计划要求

依据 OWNER-SCOPE-20261018-01。每 40 分钟进度监控保留，发布改为每周一次；首次周发布窗口由 Owner 确认的具体计划确定，尚未指定的星期/时段不自行假定。本文件不是部署批准，也没有冻结候选 SHA。

## 首次提交给 Owner 的具体计划必须有

1. **候选：** 已验证独立批次、必要依赖、准确 dev/main SHA、拟合并清单和被排除的 WIP；按 `docs/GIT_WORKFLOW.md` 保留 main 现有历史。不能只以“比 main 多 N 提交”判断不准发，也不能直接把整条未验证历史带入发布。
2. **证据与目标：** 适用 CI/类型/架构/生成投影、用户流程、正式发布预检/S6，绑定同一候选；VPS host/目录/镜像及数据库 schema 影响从真实环境核验后脱敏记录，凭据只用环境变量。
3. **数据保护：** PostgreSQL custom-format 备份；远端 `pg_restore --list`、完整 SFTP 下载、大小与本地 SHA-256 比对都通过，才称备份成功。恢复演练在隔离库，不恢复生产。
4. **回滚可用：** 记录当前 release/main SHA、不可变镜像、compose/配置指纹、旧 writer 与新 schema 的兼容证明和回滚指令。只读观测或演练证明可用；若迁移不可逆且旧 writer 不兼容，先解决而不是只写“可回滚”。
5. **部署：** Owner 确认具体计划后，依据 VPS skill 与 `scripts/deploy-vps.ps1` 以 main 的明确 SHA code-only 升级、保留数据卷。排除本地 SQLite、wipe-volumes、生产刷新/回填、自动下单与未经批准的调度变化。每周候选不因不相关开发仍在进行而无限等待。
6. **部署后只读复核：** HTTP/HTTPS、容器、release/image/SHA、数据库 freshness、pyqlib distribution 与 qlib import；真实认证用户查看本目标计划/持仓/成交/可卖量及原有限制，普通读不排写任务。后台 scheduler 自有写入与本次只读核查分别记录。

## M3 与只读发布检查的区别

只读复核可确认 M1 输出及既有 M2 导入结果，没有新的真实成交导入时不能称 M2/M3 全部完成。M3 所需写入是 Owner 提供真实券商成交后在批准范围的显式导入，不能由 heartbeat 自动伪造。

## 触发和失败处理

首次确认前只准备计划。后续依据已批准的周发布窗口及最近一次成功发布证据判断，不每 40 分钟部署；候选未就绪时该周报告具体阻塞，不拼接旧证据。发布失败按已批准代码/配置回滚方案处理，保留日志和业务数据；整库恢复须另取明确授权。

操作依据：[部署技能](../../../.agents/skills/vps-deploy-agomtradepro/SKILL.md)、[PostgreSQL 备份技能](../../../.agents/skills/backup-vps-postgres/SKILL.md)。技能中的旧 SQLite 示例不适用于本目标的正式 PostgreSQL；备份/新鲜度检查以实际数据库为准。
