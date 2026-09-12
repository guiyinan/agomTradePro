# 部署文档与保留证据

本目录纳入 Git，用于共享部署指南、正式验收证据及其校验文件。不要在根目录 `.gitignore` 中忽略整个 `docs/deployment/`。

## 文件归属

| 内容 | 存放位置 | Git 管理 |
| --- | --- | --- |
| 部署指南、环境配置说明、交接说明 | `docs/deployment/` | 保留 |
| 测试、治理清单或验收计划引用的正式证据 | 保留现有路径 | 保留，相关 `.sha256` 一并保留 |
| 新生成的临时预检输出、调试日志、重复运行快照 | `artifacts/deployment/` | 忽略，仅本地保存 |

`artifacts/` 已由根目录 `.gitignore` 忽略。执行部署或预检时，将临时输出参数指向 `artifacts/deployment/`；需要作为正式证据提交时，再选择必要文件放入本目录，并同步引用及校验信息。现有工具有固定输出路径时，应先确认引用关系，再调整工具输出位置。

## 常用指南

- [Docker 部署](DOCKER_DEPLOYMENT.md)
- [VPS 打包部署](VPS_BUNDLE_DEPLOYMENT.md)
- [数据库配置](database_configuration.md)
- [Windows Docker PostgreSQL](postgres_windows_docker.md)
- [Qlib 训练环境](QLIB_TRAIN_RUNTIME_SETUP.md)
- [测试包发布流程](TEST_PACKAGE_RELEASE_WORKFLOW.md)
- [M5 观测绑定](M5_OBSERVATION_BINDING_GUIDE.md)

## 证据保留与整理

JSON 不等于临时文件。部分 JSON 由测试直接读取，或被治理清单、计划文档及其他证据引用；历史证据也不能仅凭日期较旧而移除。

迁移前检查完整路径、文件名及证据间引用，保留正在修改的文件；迁移校验文件时保持原始字节及绑定关系。只有确认没有仓库引用的临时输出，才迁入 `artifacts/deployment/`。被引用的证据如需外置，应先建立可访问的归档和校验记录，并同步所有引用方。

2026-09-10 整理时保留现有部署指南及有引用的证据，仅将四份未发现仓库引用的旧预检输出移入本地 `artifacts/deployment/`。本地迁移清单记录在该目录的 `migration-2026-09-10.json`，包含原路径、新路径及 SHA-256。该本地产物目录不会随 Git 克隆分发；旧文件仍可从整理前的 Git 历史取回。
