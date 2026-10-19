# Alpha 运维概览入口权限对齐

两项 Alpha 运维概览的后端仅接受 staff，原 TUI 却向普通用户展示，进入后返回 403。此次将这两个 action 的 audience 调整为 admin，并精确检查 staff 身份，避免仅有 RBAC/profile admin 或非 staff superuser 的用户看到无权读取的入口；其他 Alpha action 和后端权限不变。

测试保留普通用户入口隐藏及后端 403，staff-only 和 staff-superuser 入口可见及读取 200，并验证实际发布元数据中的 admin 标记、catalog/screen 一致性与角色反例。首次测试把内部 audience 误当成公开 action DTO 字段，出现 1 failed / 1 passed；原件保留。修订后的实际验收、格式、官方投影检查和类型结果详见[证据索引](tui-rc-alpha-audience-evidence-2026-10-19.json)。

迁移矩阵只改两个 audience 单元格，官方 telemetry catalog 只更新 source SHA；117 条 Classic 路由、471 个 catalog task key、100 个可比较 task key 均保持。官方 TUI build/check 同步 runtime manifest；私有构建的三个 JS 仅从归档 CRLF 变为原 Git LF 字节，内容已逐一核对，不纳入本批提交。未重写旧 cutover evidence 或观察资格。原件在本机仓库外持久归档，未上传远端。本批不代表最终候选 RC/S6 通过，本轮不部署。
