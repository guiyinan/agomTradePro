# TUI RC：缺失发布门禁的阻断原因

`screen`、`valuation`、`dcf` 的 published 入口原先用 `None` 同时表示“找到缺失门禁”和“没有找到阻断项”，导致缺失门禁被误报为缺少成员快照。修复按 dataset key 选择首个阻断项，再读取对应门禁；缺失时返回 `canonical_publication_missing`。已有过期门禁仍保留原始原因，空结果与决策禁止字段不放宽。

回归覆盖三个入口分别缺少三个必需门禁的九种组合，核对真实 HTTP 响应、缺失 dataset、空列表或 null、证券身份和 `must_not_use_for_decision=true`，并要求业务用例不被执行。该测试验证缺失输入时的失败关闭，不证明数据已经发布或用户任务可以成功。

历史私有 RED/GREEN 的输入基于 `ed032a79bb015e1ddf1619f8b33cb77bc416e1d6` 加明确 overlay；原实现九项失败，修复后九项通过，均无 error/skip。原件在本机仓库外 `C:/Users/muku/.codex/evidence-archives/agomTradePro/2026-10-19/m5-valuation-gate-red-green/`，索引 SHA-256 `2bf21e8122142cf1a634b5bc8f1b93baf68151bbc2e59a57952366a84aa6d77f`；未声称远端持有。该历史结果不能替代当前提交或最终候选 RC/S6。

本批按 `1c3d9fb7710a04c201049a25ce677538e8747445` 重新组合：保留 A 股在 API 文件内的持久数据快照、缺失 hydration 和 provider identity 修复，仅追加九种缺失门禁用例。治理登记复用 `data_center.publication_only_d4_d5` 合同。

当前共享源码实际验证：新九项 9 passed；同文件全部 published 场景 24 passed / 40 deselected，包含上述九项，不能相加。两轮均为 0 failure/error/skip。Black、isort、Ruff、生产文件增量 mypy（0 regression / 0 legacy）、全库类型债务（0 errors）、新鲜度合同（88 surfaces）及限定 diff 空白检查通过。独立静态复核确认原阻断原因、空输出和既有测试修复保留。所有数据库测试均使用一次性 SQLite 克隆，原私有源库哈希未变；未使用 A 股原生 PostgreSQL。

当前批次原件在本机仓库外 `C:/Users/muku/.codex/evidence-archives/agomTradePro/2026-10-19/missinggate-current1c3-pass/`，20 份成员及其索引逐项绑定源码、命令、结果、JUnit 和独立审查；索引 SHA-256 `a9df00aed1d2745de1c3a6485e13e9121d04fd0382e6902b699c3f4c3d495a24`。未上传该归档。完整候选 CI、全部 UAT 和全新同候选 S6 仍待执行；此批局部验证不能替代它们。

本批不部署、不创建生产身份、不开始观察窗口，不构成 TUI-02 收口或正式发布资格。
