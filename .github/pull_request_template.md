## Summary

- What changed:
- Why this change is needed:

## Verification

- [ ] Relevant tests were run locally
- [ ] Relevant docs were updated
- [ ] Architecture boundaries in `AGENTS.md` still hold

## Current-data Freshness Checklist

Complete this section when the PR touches a `current` / `latest` / `realtime` / market-summary decision-data surface.

- [ ] Source observation time is preserved; historical data is never stamped with request time
- [ ] Stale provider results continue failover instead of counting as a successful hit
- [ ] Response exposes observation/freshness status and blocks decision use when unreliable
- [ ] `governance/current_data_contracts.json` and its stale/fresh/fallback test evidence were updated
- [ ] `python scripts/check_current_data_contracts.py` passed

## MCP Consolidation Checklist

Complete this section when the PR touches `sdk/agomtradepro_mcp/`, `apps/ai_capability/`, MCP workflows, or MCP governance docs.

- [ ] No new raw `@server.tool()` surface was introduced outside the frozen allowlist
- [ ] Default MCP top-level surface still stays within the governed core-only budget
- [ ] Governed capability manifests, replacement links, and `semantic_key` mappings were updated when MCP behavior changed
- [ ] Local MCP guard scripts were run when relevant:
  - `python scripts/check_mcp_tool_budget.py`
  - `python scripts/check_mcp_manifest_schema.py`
  - `python scripts/check_mcp_no_raw_tools.py`
  - `python scripts/check_mcp_catalog_dedup.py`
  - `python scripts/check_mcp_write_confirmation.py`
