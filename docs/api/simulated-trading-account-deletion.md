# Simulated Trading Account Deletion API

## Overview

This module now supports single-account deletion, batch deletion, and MCP access for simulated trading accounts.

## HTTP API

Base path: `/api/simulated-trading`

### Delete one account

`DELETE /api/simulated-trading/accounts/<int:account_id>/`

Response:

```json
{
  "success": true,
  "account_id": 366,
  "account_name": "admin_模拟仓",
  "deleted_positions": 3,
  "deleted_trades": 3,
  "deleted_reports": 0,
  "message": "账户 admin_模拟仓 已删除"
}
```

### Batch delete accounts

`POST /api/simulated-trading/accounts/batch-delete/`

Request:

```json
{
  "account_ids": [366, 368, 370]
}
```

Response:

```json
{
  "success": true,
  "requested_count": 3,
  "deleted_count": 3,
  "deleted_account_ids": [366, 368, 370],
  "deleted_account_names": ["admin_模拟仓", "codex_verify_模拟仓", "codex_verify2_模拟仓"],
  "failed": [],
  "message": "已删除 3 个账户"
}
```

## Permission Rules

- Must be authenticated.
- User can only delete accounts they own.
- Superusers can delete any account.

## Frontend

Page: `/simulated-trading/my-accounts/`

- Single delete button on each account card
- Multi-select checkboxes
- Select all
- Batch delete action bar

## MCP Tools

The following MCP tools are registered through `sdk/agomtradepro_mcp/tools/simulated_trading_tools.py`:

- `delete_simulated_account(account_id)`
- `batch_delete_simulated_accounts(account_ids)`

These call the same backend API through the AgomTradePro SDK.
