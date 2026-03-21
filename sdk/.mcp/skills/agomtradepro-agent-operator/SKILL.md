---
name: agomtradepro-agent-operator
description: Use when an AI agent needs to autonomously operate the AgomTradePro system through MCP tools first, then the Python SDK, with docs-backed setup, RBAC-aware execution, read-before-write verification, and direct API fallback only for debugging or unsupported flows.
---

# AgomTradePro Agent Operator

Use this skill when the user wants the agent to operate AgomTradePro directly, not just explain it. This skill is designed around the local MCP server in `sdk/agomtradepro_mcp`, the Python SDK in `sdk/agomtradepro`, and the project docs in `docs/mcp` and `docs/sdk`.

## What to load

- Read `references/setup-and-auth.md` when you need MCP setup, token/auth, local environment variables, Claude Code MCP config, or connection smoke checks.
- Read `references/operation-playbook.md` when you need to choose between MCP and SDK, map a user goal to concrete tools/modules, or execute a safe multi-step workflow.

## Operating policy

1. Prefer MCP tools for interactive agent work.
2. Use the Python SDK when the task needs batching, loops, retries, polling, local data shaping, or a capability not exposed as an MCP tool.
3. Use direct REST only for endpoint debugging, parity checks, or when MCP and SDK both block progress.
4. For any write action, first read current state, then run prechecks, then perform the write, then re-read to verify the final state.
5. Respect RBAC and audit constraints. Do not try to bypass `AGOMTRADEPRO_MCP_ENFORCE_RBAC`.
6. Prefer the unified `/api/{module}/{resource}/` routes. The old routes were deprecated on 2026-03-04, become read-only on 2026-04-01, and are scheduled for removal on 2026-06-01.

## Core workflow

1. Confirm connectivity and auth.
2. Choose MCP-first or SDK-first based on the requested operation.
3. Read baseline state before mutating anything.
4. Run domain prechecks where available.
5. Execute the smallest valid write operation.
6. Verify the resulting state with a fresh read.
7. Report concrete IDs, statuses, and any remaining operator action.

## Source of truth

- MCP server registration: `sdk/agomtradepro_mcp/server.py`
- SDK and route migration notes: `sdk/README.md`
- MCP configuration and RBAC: `docs/mcp/mcp_guide.md`
- SDK initialization and examples: `docs/sdk/quickstart.md`
- SDK method surface: `docs/sdk/api_reference.md`
