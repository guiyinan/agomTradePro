# CI 基础设施有限修复

> 历史验收原件已迁出 Git；原路径、逐文件哈希和恢复方式见[归档索引](evidence-archive-2026-10-19.md)。历史结论与当时失败记录保持不变。

## npm 下载源

旧 RC `39176939034` 在 npmmirror 下载 Playwright tarball 时实际504失败。独立修复只将锁文件30个resolved URL的origin切到registry.npmjs.org；版本、integrity、其他值、依赖图与package.json完全相同。TUX私有新cache/config、正常生命周期的Windows npm ci成功且锁文件未变；Root重新深比较并通过bundle一致性与171项Node测试。该本地安装为Windows Node24/npm11，不是Linux Node22。

[原件](evidence-archive-2026-10-19.md#原件定位 "原件：artifacts/a-share-usability/ci-infrastructure-npm-2026-10-19/evidence.json")绑定候选、命令与源码；新SHA Linux CI另据实际登记，旧RC仍失败。本批不改Python、测试门限或发布资格。


## pytest 临时目录父路径

旧RC的critical-postgres实际16项通过、2项在tmp_path准备阶段报错，因为独立checkout没有.tmp父目录。此独立修复只在nightly、critical-postgres和RC journey的checkout之后各添加mkdir -p .tmp，共3步；pytest仍自行管理.tmp/pytest。未改变pytest.ini、fixture、marker、测试命令、超时或预算。nightly/journey旧运行未到pytest阶段，不将其描述为已复现同一异常。

Root验证两份YAML解析、逐字移除3步后恢复原文件，以及checkout→mkdir→pytest顺序。actionlint本机不可用，未声称执行；新SHA的Linux原生PostgreSQL critical与journey尚待实际验证。本批不运行或重置生产/源数据库。证据见[原件](evidence-archive-2026-10-19.md#原件定位 "原件：artifacts/a-share-usability/ci-infrastructure-pytest-parent-2026-10-19/evidence.json")。完整RC其他已知失败与S6/Owner门禁继续单列。
