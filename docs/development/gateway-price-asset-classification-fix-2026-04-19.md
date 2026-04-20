# Gateway Price Asset Classification Fix

## 问题

- `000001.SZ` / `000002.SZ` 这类深市股票代码以 `000` 开头
- 历史价格网关之前只按数字前缀判断，把它们误判成指数
- 结果会去走指数接口，写入错误价格

## 修复

- `TushareGateway.get_historical_prices`
- `AKShareEastMoneyGateway.get_historical_prices`

现在会优先结合交易所后缀判断：

- `000xxx.SH` 视为上证指数
- `399xxx.SZ` 视为深证指数
- `000001.SZ` / `000002.SZ` 这类带 `.SZ` 的代码按股票处理

同时，东方财富历史价格请求增加了轻量重试，降低批量同步时的临时断连影响。
