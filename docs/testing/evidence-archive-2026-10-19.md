# 历史验收原件归档（2026-10-19）

依据 Owner“代码仓库干净一些”的决定，源码仓库只保留代码、测试、精简验收说明和本索引。完整日志、源码快照、JUnit、运行脚本副本及原始证据 JSON 已按原路径归档。没有删除失败记录、重新认定测试结果或重写 Git 历史。

## 原件定位

- 归档 ID：`source-evidence-3cca76c49622`。
- 位置：本机 Codex 数据目录下 `evidence-archives/agomTradePro/2026-10-19/source-evidence-3cca76c49622/`（本机当前为 `C:/Users/muku/.codex`）。
- 完整原件：`originals.zip`；逐文件原路径、字节数、SHA-256 和归档时 Git blob：`files.json`。
- ZIP SHA-256：`48f8a0363943752e4c643a373a16b5d6e15dd0ed1a96234cb59158bba5dd32aa`。
- 清单 SHA-256：`b442007b22987753a63bc106303693b6fb93ea5f08fcba77d9726e54d71ad0f2`。
- 归档时 HEAD：`68309d6c789f9628914921d9590fff294fdb2506`。归档同时包含当时已准备但未提交的 ASH-04 原件；这不是该 HEAD 验收通过的证明。
- 共 2806 个文件，原始 69216960 字节，ZIP 19389644 字节。全部 ZIP 成员已读回逐项比对 SHA-256，工作区原件在归档时也逐项比对；原件仍保留为 Git 忽略的本地缓存。

**可用性边界：这是已校验的本机持久归档，未上传远端。** 新克隆不会自动获得这些原件；需要历史原件时须同时取得 ZIP 与清单，先校验上述包哈希，再按清单定位和校验成员。历史文档中的原路径（含链接标题）对应 ZIP 内的成员路径；旧结构化证据中的路径和哈希仍描述当时原件，不改写为新一轮通过证据。

## 恢复与后续交付

可将 ZIP 解压到独立审查目录；确需在原仓库复查时，仅恢复所需原路径到 Git 忽略目录，不强制暂存。不要覆盖现有源码、业务数据库或用户改动。完整清单在归档旁保存，不把逐文件大清单再次复制进源码仓库。

新验收摘要应记录实际候选/输入身份、命令和结果、原件位置及哈希。正式发布规定的报告、S6 和资格门继续独立执行；迁出历史原件不表示这些门已通过。QMT 安装包、业务代码、正式测试及必要生成投影不在本次移除范围。

## 归档范围

| 原路径组 | 文件数 | 原始字节数 |
| --- | ---: | ---: |
| `artifacts/a-share-usability/ash01` | 17 | 32828705 |
| `artifacts/a-share-usability/ash02` | 906 | 18224029 |
| `artifacts/a-share-usability/ash03` | 799 | 3124228 |
| `artifacts/a-share-usability/ash03-automatic-ledger-2026-10-19` | 388 | 6258256 |
| `artifacts/a-share-usability/ash03-broker-facts` | 123 | 3000011 |
| `artifacts/a-share-usability/ash03-ci-compatibility-2026-10-19` | 77 | 757621 |
| `artifacts/a-share-usability/ash03-finite-handoff-2026-10-19` | 19 | 34277 |
| `artifacts/a-share-usability/ash03-legacy-position-delete-2026-10-19` | 80 | 273033 |
| `artifacts/a-share-usability/ash03-nullable-fixtures-2026-10-19` | 15 | 42590 |
| `artifacts/a-share-usability/ash03-owner-close-contract-2026-10-19` | 17 | 28335 |
| `artifacts/a-share-usability/ash03-sell-nullable-2026-10-19` | 33 | 2685260 |
| `artifacts/a-share-usability/ash04-financial-partial-read-2026-10-19` | 166 | 1248193 |
| `artifacts/a-share-usability/ci-browser-isolation` | 4 | 12715 |
| `artifacts/a-share-usability/ci-infrastructure-npm-2026-10-19` | 9 | 21905 |
| `artifacts/a-share-usability/ci-infrastructure-pytest-parent-2026-10-19` | 5 | 4044 |
| `artifacts/a-share-usability/ci-repair` | 4 | 39767 |
| `artifacts/a-share-usability/ci-serialized-isolation-2026-10-19` | 16 | 52781 |
| `artifacts/a-share-usability/rc-contract-isolation-2026-10-19` | 45 | 207545 |
| `artifacts/tui-rc/journey-encryption-2026-10-19` | 10 | 8993 |
| `artifacts/tui-rc/m5-fixture-lifecycle-2026-10-19` | 11 | 271191 |
| `docs/reviews/owner-scope-freeze-2026-10-18` | 9 | 5916 |
| `docs/testing/tui-task-first-2026-10-17/tux10` | 24 | 26662 |
| `docs/testing/tui-task-first-2026-10-17/tux10/previous-round` | 29 | 60903 |

机器可读的精简包索引见[JSON](evidence-archive-2026-10-19.json)。
