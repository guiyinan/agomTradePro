# ADR-0002：PIT 双时间语义与冻结清单

状态：Accepted（2026-07-22）

## 决策

`data_center` 是 PIT 事实唯一 owner。事实采用追加版本，业务有效时间为 `effective_at/effective_to`，知识时间为公开口径 `available_at` 或系统口径 `ingested_at`；未知发布日期不得标记 verified。回测和研究使用不可变 `PITDatasetManifest`，可信执行的读取器只能访问清单冻结的版本 ID，且查询时间不得超过清单截止时间。

## 后果

后续修订不会改变既有可信结果；历史数据不能可靠回填时保留 unknown/estimated。探索运行仍可执行，但不能进入研究晋级。

