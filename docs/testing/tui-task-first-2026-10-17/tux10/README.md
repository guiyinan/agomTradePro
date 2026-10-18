# TUX-10 本地仓库验收

已完成默认任务首页、标的研究、今日关注、组合已记录事实，以及专业模式 / 受权诊断、输入保留、键盘可达、深链历史和失败恢复的集成验收。先读 [任务模式使用说明](user-guide.md)。

- 428 项后端、160 项前端、10 项真实 Django 浏览器、1 项全量角色能力盘点、8 项时间边界和 8 项登记测试通过。
- [验收与命令](acceptance.json)、[85 项输入冻结](frozen-inputs.json)、[20 项要求核对](requirements-audit.json)、[全量能力去向](surface-report/capability-placement.md)、[登记最小差异](registry-delta-audit.json)。
- `browser/` 保留原角色 / 视口截图与局部计时、请求记录；`source-artifacts/` 为明确合成来源事实。成功 owner 响应未被替换。元数据清单证明声明 / 角色可见性，不能代替全部动作执行。
- `previous-round/` 保留上一轮实际失败及输出；本轮一次文档检查命令文件名拼错的记录亦保留，正确命令已通过。

五人上手试用尚未执行：[试用协议](human-study-protocol.md)。真实正常外部市场源、原生 PostgreSQL、大组合性能、生产发布和生产回滚演练仍未验证。没有部署、生产写入、付费运行时 AI、QMT 或真实交易。

源码身份由 Fee B 基线、85 项 raw / LF 哈希及包含本证据的 TUX10 本地 commit 共同限定。`reproduce/` 保存当时的隔离 settings、只读 inventory、日期边界与命令记录器；复跑须新建获准的独立 QA 环境并生成新的 HEAD / preflight / freeze，不能复用已结束的共享窗口或把任意 HEAD 的结果拼入本证据。官方 builder 在冻结前运行，后续 check 只验证一致性。

回滚仅回退本批自有变更和匹配生成物，保留 A 股前置、用户文件和业务记录；重新核对官方构建与资源请求，并给 rollback 资源使用新的唯一缓存参数。没有模型迁移或业务数据库回滚。
