## Summary

- What changed:
- Why this change is needed:

## Verification

- [ ] Relevant tests were run locally
- [ ] Relevant docs were updated
- [ ] Architecture boundaries in `AGENTS.md` still hold

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
