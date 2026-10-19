# TUI RC：非空资产池评分对象适配

M5 的真实非空股票数据触发资产池 502：股票、基金 owner 返回各自评分实体，而公共资产池需要 `AssetScore` 的类型、代码与名称契约。此前空列表没有进入分类分支，未暴露该不兼容。

本批在两个 owner 的池入口完成显式适配，保留各维度评分、排序、配置比例、风险、日期和上下文。通用实体追加可空 typed PE/PB/人民币市值元数据，分类器继续拒绝错误类型；原有 `AssetScore.to_dict()` AST 不变。原始估值不进入 0—100 评分字段，缺失保持 None，非有限值拒绝。基金规模不映射为股票市值；股票市值转换保持 CNY、默认 scale=1。

- 原生产代码配同一组行为测试，两个股票参数及一个基金用例均因实体类型不符而失败：3 failures / 0 errors / 0 skips。
- 六路径候选在独立完整源码、空迁移库的隔离副本运行相关 Domain、owner、池和接口/API 回归：90 passed / 0 failures / 0 errors / 0 skips。API 兼容项 mock owner，不能单独证明元数据穿过 HTTP。
- 共享源码六路径与该通过候选逐字节一致。Black、isort、Ruff、四个生产文件增量 mypy、默认全量债务检查均通过。官方模块地图生成及联合 DataCenter 投影检查通过，生成结果没有变化。迁移基线及本批源码未变。
- 后续真实浏览器单用例的 pool/valuation 主体已通过；其本地包装器因 Git index 缓存指纹变化拒绝验收，所有 tracked/untracked 文件字节、HEAD 和状态路径实测未变。该次包装器失败保留，不作为完整 M5、RC 或 S6 通过证据。

原始日志、JUnit、候选/独立静态复核与源码哈希仅保存在本机 `C:/Users/muku/.codex/evidence-archives/agomTradePro/2026-10-20/pool-owner-adapter-red-green90/`，索引 SHA-256 `fdb7203861b04f0f5bade43ea5daca1836a128e4d51809f570e122f381f1c2c4`。本批不涉及模型、迁移或部署，不改变生产数据或新鲜度门槛。
