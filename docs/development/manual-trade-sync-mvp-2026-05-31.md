# Manual Trade Sync MVP

> Updated: 2026-05-31

This MVP keeps real broker execution manual. AgomTradePro imports broker trade files,
syncs the internal account ledger, links actual actions to system recommendations,
and runs branch-level decision replay backtests for review.

## Import API

- `POST /api/account/broker-trades/preview/`
- `POST /api/account/broker-trades/import/`

Both endpoints accept `multipart/form-data`:

- `portfolio_id`
- `broker_name`
- `file`

Supported file formats are CSV and Excel files readable by the configured parser.

Required columns:

- `traded_at`
- `action`
- `asset_code`
- `shares`
- `price`

Optional columns:

- `commission`
- `stamp_duty`
- `transfer_fee`
- `external_trade_id`
- `notes`

Each valid row receives a deterministic `broker_trade_key`. Existing keys are skipped
so re-importing the same file does not create duplicate transactions.

## Ledger Sync

Confirmed imports write `account.TransactionModel` and update the unified position
ledger through `UnifiedPositionService`.

- Buy rows merge into existing positions and recalculate average cost.
- Sell rows reduce or close positions.
- Legacy `account.PositionModel` projections are updated for compatibility with
existing account APIs and pages.

## Recommendation Matching

After a transaction is imported, the system searches nearby unified recommendations
by account, security code, side, and time window.

- Matched recommendations are marked `ADOPTED`.
- A `decision_execution_link` row records the transaction/recommendation link.
- Unmatched transactions are recorded as `manual_only`.

## Decision Replay Backtest

`POST /api/backtest/decision-replay/` creates a `BacktestResultModel` for one branch:

- `actual`: replay imported manual executions.
- `no_action`: skip imported executions and keep cash/positions unchanged.
- `system_plan`: use matched recommendation quantity and entry/target price when available.
- `delayed_1d`: replay imported executions one day later.

The replay uses imported execution prices and recommendation snapshots only. It does not
infer missing market history and should be read as a trading-discipline review, not as a
future sell-point guarantee.

## SDK / MCP Alignment

SDK canonical methods:

- `client.account.preview_broker_trades_file(...)`
- `client.account.import_broker_trades_file(...)`
- `client.account.preview_broker_trades_csv(...)`
- `client.account.import_broker_trades_csv(...)`
- `client.backtest.run_decision_replay(...)`

MCP canonical tools:

- `preview_broker_trades_csv`
- `import_broker_trades_csv`
- `preview_broker_trades_json`
- `import_broker_trades_json`
- `run_decision_replay_backtest`

Older MCP helpers such as `import_transactions_csv/json` remain compatibility tools
for raw transaction CRUD. New manual trade sync workflows should use the broker trade
tools above because they trigger deduplication, ledger sync, position updates, and
recommendation matching.

## Review Page

`/audit/manual-trades/` lists recent import batches and imported transactions for the
current user.
