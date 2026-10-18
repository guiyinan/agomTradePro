# D｜DATA-02 四类 Publication 的容差值

决策编号 `OWNER-20261018-D`；状态：待签批。`governance/data02_numeric_tolerance_policies.json` 当前为 awaiting_owner_approval，policies 为空；本页不写入该运行政策。

**比较对象必须先固定：** 相同 provider、资产、观测时点/报告期、原件与合法 canonical 单位下，验证 source → fact → publication 的确定性对账。跨 provider 的采样时差/口径差异另行判断，不能以宽泛百分比把不同时点或单位误差接受为一致。

| 选项 | 数值与适用性 |
| --- | --- |
| D1（推荐首批） | 已定义精确规范化的字段，absolute=0、relative=0；身份/源时间/单位/成员范围必须完全一致 |
| D2 | 每个明确 metric/字段根据真实原件精度单独批准非零绝对/相对容差；未列字段仍阻断 |
| D3 | 四类一律按 1% 放行，不推荐：会混淆 failover 检查与 publication 精确对账 |

**推荐首批值：** D1，先对一个有界生产批次作确定性对账。若真实原件证明存在合法舍入，再按 D2 附单逐字段批准，不自动推导新默认容差。

| Publication | absolute | relative | 不能用数值容差放行的字段 |
| --- | --- | --- | --- |
| quote | 0 | 0 | provider/资产/源时间/币种/报价身份/完整范围 |
| price | 0 | 0 | 交易日/复权口径/证券/单位/成交量口径 |
| valuation | 0 | 0 | 指标代码/估值日期/市值币种/PE-PB 的定义及缺失值 |
| financial | 0 | 0 | 指标/报告期/公告及可用时点/修订行 identity/单位/原件绑定 |

**限定：** 比较前的缩放与量化必须来自已批准 catalog/rule，且原始值可追溯；缺值不等于零。此处批准 0/0 也必须列出实际字段名、canonical unit、policy version/hash、候选 SHA 和比较分母，不能只有数据集名。源相同而合法舍入规则未定义的字段先报 blocked，不提前塞入空矩阵。`publication_policies.json` 的覆盖率门与容差是两种规则，不因本页改变。

**风险：** 零容差可能阻断有合法舍入差异的数据；需显式规则解决，不能通过默认 1% 掩盖。D2 可减少误阻断但增加字段口径错配风险。

**回滚：** 追加停用或 successor tolerance policy；失败候选不切 current pointer，保留原件与 mismatch 证据，禁止改旧 policy hash 或历史事实来凑对账。

**签批栏：** 选择 ___；字段/单位矩阵附件 ___；候选/政策版本与适用范围 ___；Owner 签署及日期 ___。
