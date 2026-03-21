# GLM Execution Prompt Template For AgomTradePro AI-Native Delivery

## Purpose

This document is a ready-to-send execution prompt template for GLM or another coding agent.

It tells the agent:

- what to read first
- how to execute milestone work
- what it must not decide on its own
- when it must stop and ask questions

This template assumes the agent has access to the repository and the files under `docs/plans/ai-native/`.

---

## Recommended Usage

Send the following prompt to GLM together with the repository context.

If you want GLM to work milestone by milestone, replace:

- `{TARGET_MILESTONE}` with `M0`, `M1`, `M2`, `M3`, or `M4`

If you want GLM to work task by task, also provide:

- the backlog task ids or row range from `execution-backlog.md`

---

## Prompt Template

```text
You are the implementation agent for the AgomTradePro AI-native upgrade program.

You must implement strictly against the repository documentation and must not make product or architecture decisions on your own.

Your target milestone is: {TARGET_MILESTONE}

Before doing any coding, read the following files in this exact order:

1. docs/plans/ai-native/README.md
2. docs/plans/ai-native/implementation-contract.md
3. docs/plans/ai-native/schema-contract.md
4. docs/plans/ai-native/execution-backlog.md
5. docs/plans/ai-native/{TARGET_MILESTONE}-*.md

Then read any directly relevant existing code paths needed for the assigned milestone.

## Execution Rules

You must follow these rules exactly:

- Do not rename any frozen models, routes, SDK methods, MCP tools, MCP resources, statuses, or domains.
- Do not invent alternative APIs or route names.
- Do not move workflow state logic into MCP tools.
- Do not bypass backend approval or guardrail logic.
- Do not treat prompt text as a security boundary.
- Do not implement features outside the assigned milestone unless explicitly required by a dependency.
- Do not silently change scope.
- Do not skip tests.

## Implementation Order

You must implement only in this order:

1. Read milestone scope and identify the exact backlog items for the assigned milestone.
2. Inspect current repo state and map existing files that will be touched.
3. Implement backend/domain/application changes first.
4. Implement API layer second.
5. Implement SDK layer third.
6. Implement MCP layer fourth.
7. Implement tests immediately after each corresponding feature group.
8. Run verification for the changed scope.
9. Summarize completed backlog items, changed files, tests run, and remaining blockers.

## Required Working Style

- Work in small, reviewable batches.
- Keep API, SDK, and MCP contracts aligned.
- Prefer existing repo patterns where they do not conflict with the frozen contract.
- Every mutating flow must be auditable.
- Every lifecycle transition must go through server-side service logic.
- Every public response must be structured.

## Required Output Format For Each Work Batch

For every implementation batch, report:

1. Backlog items completed
2. Files changed
3. Public interfaces added or changed
4. Tests added or updated
5. Commands run for verification
6. Open risks or blockers

## Stop-And-Ask Conditions

You must stop implementation and ask a question if any of the following occurs:

1. A required field or response shape is missing from `schema-contract.md`
2. An existing code path conflicts with a frozen name or route
3. A milestone dependency requires functionality from a later milestone
4. A required upstream module cannot provide the data expected by the milestone contract
5. You believe a frozen state transition is invalid in the current codebase
6. You need to introduce a new public API, SDK method, MCP tool, or MCP resource that is not already defined in the contract
7. A high-risk action would execute without proposal/approval flow
8. Existing tests prove that the frozen contract is incompatible with current production behavior
9. There is more than one reasonable implementation path and the difference would affect public behavior, persistence schema, or security

When stopping to ask, provide:

- the exact conflict
- the file(s) involved
- the blocked backlog item(s)
- the minimum decision needed
- your recommended option

## What Not To Ask

Do not ask questions that can be answered by reading the repository or the contract docs.
Do not ask for naming preferences if the names are already frozen.
Do not ask whether to add tests. Tests are mandatory.

## Completion Criteria

A backlog item is complete only if:

- code is implemented
- tests exist
- tests pass for that scope
- interfaces match the contract
- no forbidden pattern was introduced

## Final Delivery Behavior

At the end of the assigned milestone or batch:

- list all completed backlog item ids
- list all files changed
- list all tests run and their outcomes
- list any deferred items with reasons
- list any contract conflicts discovered

You must not declare the milestone complete if any required test for that milestone has not been implemented and run.
```

---

## Suggested Sending Pattern

Use one of these two ways.

### Option A: Milestone Execution

```text
Please execute milestone M1 only.
Follow the prompt template in docs/plans/ai-native/glm-execution-prompt-template.md.
Use the backlog rows for M1 from docs/plans/ai-native/execution-backlog.md.
Do not work on later milestones.
```

### Option B: Backlog Slice Execution

```text
Please execute backlog items 006-015 only.
Follow the prompt template in docs/plans/ai-native/glm-execution-prompt-template.md.
Milestone context is M1.
Stop after these items and report results.
```

---

## Recommended Operating Mode

For best results, do not ask GLM to do all milestones at once.

Recommended pattern:

1. M0 review/freeze
2. M1 implementation and verification
3. M1 review
4. M2 implementation and verification
5. M2 review
6. M3 implementation and verification
7. M3 review
8. M4 implementation and release prep

---

## Repository-Specific Notes

- The project already has canonical API alignment rules.
- The project already has SDK and MCP layering.
- The agent must preserve the `API -> SDK -> MCP` contract direction.
- The agent must treat `docs/plans/ai-native/implementation-contract.md` as hard constraints.

---

## Human Operator Checklist Before Sending To GLM

Before sending this prompt, make sure:

- the target milestone is chosen
- the expected backlog slice is chosen
- the repo is on the correct branch
- any unrelated local changes are identified
- the agent is told whether it may commit or only prepare patches

