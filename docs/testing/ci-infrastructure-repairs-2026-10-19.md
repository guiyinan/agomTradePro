# CI 基础设施有限修复

## npm 下载源

旧 RC `39176939034` 在 npmmirror 下载 Playwright tarball 时实际504失败。独立修复只将锁文件30个resolved URL的origin切到registry.npmjs.org；版本、integrity、其他值、依赖图与package.json完全相同。TUX私有新cache/config、正常生命周期的Windows npm ci成功且锁文件未变；Root重新深比较并通过bundle一致性与171项Node测试。该本地安装为Windows Node24/npm11，不是Linux Node22。

[原件](../../artifacts/a-share-usability/ci-infrastructure-npm-2026-10-19/evidence.json)绑定候选、命令与源码；新SHA Linux CI另据实际登记，旧RC仍失败。本批不改Python、测试门限或发布资格。
