# ADR-0004：实验登记与研究晋级门禁

状态：Accepted（2026-07-22）

## 决策

`research` 登记完整 trial family。trial 启动后参数、PIT manifest、切分、代码与运行环境证据不可修改。晋级必须核验真实 verified manifest、匹配的 completed `pit_verified` backtest、样本外和 walk-forward 切分、完整 family、BH-FDR 与 Deflated Sharpe。失败和中止 trial 计入 family，不允许只登记最佳参数。

## 后果

策略参数在研究门禁 flag 开启后只能引用 approved `PromotionDecision`。历史和 exploratory 回测只能展示，不能激活参数。

