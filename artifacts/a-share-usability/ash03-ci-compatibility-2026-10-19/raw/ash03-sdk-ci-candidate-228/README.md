# ASH03 SDK CI assertion correction

This private test-only candidate updates two commit-argument expectations in `sdk/tests/test_mcp/test_confirmation_commit_argument_bindings.py`. The real owner-governed MCP handler receives a caller-owned stable `idempotency_key` at preview and preserves that same value in the confirmed commit call. The existing assertions still require the commit to use only the account IDs frozen by preview, even if another account appears before confirmation.

The production SDK/runtime contract is correct to carry the key: omitting it would break the backend idempotency contract. The CI failures are stale exact-dictionary expectations, not a production regression.

`manifest.json` records raw-byte SHA-256 values for the full preimage, full candidate, and patch. CI logs were inspected read-only. No tests, imports, DB, QA, or Git operations were run while preparing this packet.
