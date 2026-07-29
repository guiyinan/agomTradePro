# TUI Metadata Promotion Guide

> Last updated: 2026-06-21

This guide defines how API, SDK, MCP, and classic template evidence becomes published `/tui/` operation metadata.

User-facing screen rules are defined separately in `docs/development/tui-user-facing-design-standard.md`. Promotion must satisfy both this guide and that design standard.

The runtime rule is fixed: `/tui/` reads published metadata only. It must not parse source files, classic templates, SDK modules, MCP tools, or URL resolver evidence at request time.

The product rule is also fixed: the published workbench is organized by user tasks, not by backend API shape. API endpoints are execution details and should not appear in the ordinary task list.

Repository-level governance counts use `governance/governance_baseline.json` as the machine source of truth. TUI screen, action, smoke, and evidence counts use the current published graph and generated promotion report as their machine sources; this guide does not maintain numeric copies.

Generated evidence is intentionally separate from the generated operation graph:

| Artifact | Purpose |
| --- | --- |
| `config/tui/generated/tui_operation_graph.generated.json` | Compact candidate operation graph for review and validation |
| `config/tui/generated/tui_operation_evidence.generated.json` | Compile-time API/SDK/MCP/template evidence snapshot |
| `config/tui/published/tui_operation_graph.published.json` | Compact reviewed runtime graph |

The compact graph may omit default action values such as `method: GET`, `risk: read`, empty `fields`, empty `view_model`, `raw_debug: true`, and inferable action `module_key`. Runtime and scripts must call `validate_tui_metadata()` before using the graph.

## Schema-First Rule

`config/tui/schema/tui_metadata.schema.v3.json` is the source of truth for the metadata shape. The validator in `apps/terminal/application/tui_metadata.py` applies the same contract before runtime load and before DB publish.

Fixed enums include action risk, HTTP method, view type, dashboard panel kind, field `input_type`, field `value_type`, field `binding`, source prefixes, and task tiers. AI or manual review must not add ad hoc keys. To introduce a new widget, field type, panel kind, visibility rule, editability rule, or confirmation policy, first upgrade the schema, update the validator, and add tests.

Field metadata must be derived from code-owned contracts: Django models, DRF serializers/OpenAPI schema, DDD aggregate roots, SDK method signatures, or MCP typed inputs. Product descriptions and AI interpretation may improve operator copy and screen grouping only; they are not authoritative for fields, units, types, risk, or confirmation behavior.

For Django hosts, compile-time evidence should now be exported explicitly instead of being reconstructed from prose:

```powershell
agomtradepro\Scripts\python.exe manage.py export_tui_django_contracts --output tmp\tui_django_contracts.json
agomtradepro\Scripts\python.exe manage.py spectacular --file tmp\tui_openapi.json
```

`export_tui_django_contracts` emits ORM model contracts plus selected domain dataclass contracts. `spectacular` emits the OpenAPI side of the same compile-time evidence bundle. These two artifacts are the preferred handoff into AgomTUI compiler `skill-request`.

## Evidence Snapshot

The current full compile-time scan writes its evidence to
`config/tui/generated/tui_operation_evidence.generated.json`. Read source totals
from that generated artifact. MCP repository governance totals remain owned by
`governance/governance_baseline.json`.

These numbers are evidence volume, not published menu size. The ordinary TUI surface should stay user-task oriented. Broad coverage belongs in the task-bucketed tool library, not in endpoint-shaped navigation.

## Promotion Rule

Approve an action into `config/tui/published/tui_operation_graph.published.json` only when all of these are true:

- Endpoint is under `/api/`.
- Method is `GET`, or the action is explicitly reviewed as `ai` / `write` and already has a safe backend permission flow.
- Endpoint has no path placeholder such as `<pk>`, `<asset_code>`, or `<str:...>` unless field metadata is explicitly provided.
- Same-process smoke check returns JSON-compatible business data, not an HTML/HTMX fragment.
- Endpoint name does not imply mutation or heavy operation: avoid `refresh`, `fetch_all`, `trigger`, `activate`, `deactivate`, `clear-cache`, `generate`, `import`, `update`, `rerun`, and similar verbs.
- Action has a concrete `screen_key`, `module_key`, `intent`, `view_type`, and operator-facing label.
- Action risk is `read`, `ai`, or confirmed `write` for the ordinary workbench. Confirmed `write` actions must be intentionally approved, grouped as `00 可执行操作`, and protected by the TUI confirmation flow plus backend permission checks.
- Confirmed `write` actions must not use `GET`. Amount, quantity, price, weight, cash, share, quote, count, and portfolio-list fields must declare a fixed `value_type`; numeric write fields must use `integer`, `float`, or `decimal`.
- Business-specific response paths are expressed in `view_model`, not hardcoded in the TUI renderer.
- Operator-facing labels and descriptions explain the user job, not the backend route.
- Workflow replacement screens include `business_context` so the Inspector can show the user's objective, expected decision output, and ordered checkpoints.

Use `source: "approved:api-evidence"` for hand-promoted actions from generated API evidence. Use `source: "api-collector:candidate"` for automatically admitted direct safe-read candidates. Use `django-model:*`, `ddd-aggregate:*`, `openapi:*`, or more specific `classic-template:*` sources when that contract materially shaped the operation semantics. Unsupported source prefixes fail validation.

## First Expanded Batch

The first approved expansion promotes 27 new read actions, bringing the published baseline to 17 screens and 36 actions.

| Screen | Approved actions |
| --- | --- |
| Command Center / Dashboard V1 | Dashboard summary, regime quadrant, equity curve, signal status |
| Macro Regime / Regime Navigator | Navigator state, regime action, transition history |
| Macro Regime / Pulse Monitor | Current pulse, pulse history |
| Policy Workbench | Queue items |
| Research / Alpha Console | Alpha scores, provider state, health |
| Research / Signal Browser | Active signals, signal stats, unified summary |
| Research / Factor Library | Factor definitions |
| Research / Backtest Registry | Backtest statistics, backtest records |
| Execution / Audit Logs and Tasks | Operation logs, decision traces, task monitor dashboard |
| AI Ops / Terminal Commands | Available commands, commands by category |
| AI Ops / Capability and Runtime | AI capability stats, Agent Runtime health, tasks needing attention |

## Safe-Read Coverage Batch

The broad-coverage baseline promotes direct safe-read candidates and field-backed parameterized read candidates into user-task screens after automatic filtering and same-process smoke checks. Dynamic coverage counts are not maintained in this guide; use the generated promotion report from the current run as the single source for screen, action, smoke, and deferred-record totals.

Known HTMX-only fragments, operation-like calculate/check routes, unstable collection routes, and other non-user-facing reads are filtered before publication. Expected degraded Alpha/Celery/task-monitor paths should remain console-clean, stale method variants should be excluded, and session-backed public-share challenges should stay user-visible authorization prompts rather than internal crashes.

System toolbox screens are now fallback buckets rather than the primary organization model:

| Screen | Purpose |
| --- | --- |
| `api-library.runtime` | Health/readiness, Celery, setup, and system runtime status |
| `api-library.data-center` | Data center state, news, market thermometer history, and user thresholds |
| `api-library.config-center` | Admin-only Qlib runtime config, training profiles, and training run controls |

High-value smoke-passing tools are promoted into ordinary business screens:

| Screen | Purpose |
| --- | --- |
| `command-center.decision-flow` | Daily decision steps and decision workspace context |
| `execution.accounts` | Account, portfolio, position, cash flow, sizing, and simulated-trading checks |
| `macro-regime.strategy` | Strategy lists, position rules, assignments, and execution logs |
| `macro-regime.rotation` | Rotation assets, signals, configs, templates, and recommendations |
| `macro-regime.risk-controls` | Decision rhythm, Beta Gate, hedge pairs, alerts, and risk-control views |
| `research.asset-lab` | Asset analysis, funds, sectors, sentiment, and filters |
| `execution.events` | Events, realtime status, and monitoring views |
| `execution.share` | Share links, public snapshots, access logs, and observer support |
| `ai-ops.prompt-workbench` | Prompt templates, chains, model/provider options, and AI logs |
| `api-library.runtime` | Health/readiness, Celery, setup, and system runtime status |
| `api-library.data-center` | Data center state, news, market thermometer history, and user thresholds |

Parameterized read tools now follow the same user-screen promotion rules. For example, account/portfolio detail queries stay in `execution.accounts`, strategy detail queries stay in `macro-regime.strategy`, prompt detail queries stay in `ai-ops.prompt-workbench`, and share/public snapshot queries stay in `execution.share`. The user sees required fields such as account ID, portfolio ID, fund code, or capability key, not the underlying endpoint.

Automatic promotion still rejects path placeholders without generated field controls, debug/docs/TUI internals, HTMX-only fragments without a JSON contract, unstable collection routes, and names that imply mutation, recomputation, export, sync, train, test, trigger, bind, unbind, enable, disable, revoke, resolve, apply-template, check-effectiveness, or other heavy operations. The smoke gate then executes direct actions through `TuiWorkbenchService`; required-field actions are counted as `needs_input`, and remaining failures must be remodeled before they can enter the ordinary published graph.

Reviewed operation actions are added manually after that broad safe-read pass. Current confirmed operations include decision readiness repair, market thermometer recalculation/input sync, quote sync, Alpha batch inference, Qlib runtime data refresh, terminal session/AI interaction flows, and admin-only config-center actions for Qlib runtime settings, training profiles, and training run triggers. These are not inferred from endpoint names at runtime; they are published metadata with explicit fields, risk, grouping, and confirmation behavior.

## Deferred Buckets

Do not delete deferred evidence. Keep it in `tui_operation_evidence.generated.json` until the operation can be modeled safely.

| Bucket | Examples | Required before promotion |
| --- | --- | --- |
| HTML/HTMX responses | `/api/dashboard/attention-items/`, `/api/dashboard/regime-status/` | Add or identify JSON-native API responses. |
| Broken smoke checks | HTML redirect fragments, endpoints with missing field metadata, and backend exceptions | Add fields/defaults or fix backend API, then re-smoke. |
| Remaining path-parameter endpoints | Detail APIs whose placeholders cannot yet be mapped safely | Add field controls, lookup flow, and permission notes. |
| Write-like GET endpoints | `refresh`, `fetch_all`, `activate`, `clear-cache`, `generate` | Convert to write/admin risk with confirmation, or leave hidden. |
| Account/portfolio/private data | Account positions, transactions, grants | Add role-aware UX and explicit selector fields. |
| Debug/system internals | `/api/debug/*`, schema/docs routes | Keep out of ordinary TUI. |

## Metadata Authoring

When adding a screen:

- Edit `config/tui/ia/tui_information_architecture.v1.json`; do not add a second screen map in compiler, runtime, or JavaScript code.
- Keep the canonical groups/modules stable: `daily/daily-decisions`, `research/research-tools`, and admin-only `system/system-governance`.
- Classify legacy inputs explicitly as published `sources` or `runtime_sources`; all aliases must have one canonical target.
- Prefer a small number of task-oriented screens over one screen per endpoint.
- Use `status` for status boards, `detail` for object summaries, and `datagrid` for list/table workflows.
- Use `dashboard_panels` for overview pages that compose multiple approved actions into a single PC tools dashboard.
- Review screen, action, and panel labels as product copy. Endpoint-derived fragments such as `Dashboard`, `System List`, `Password Strength`, `Validate`, `Assignment`, and pluralization artifacts such as `回测s` must be translated into user tasks before publishing.
- Add `default_action_key` for every screen that should act as a replacement for a classic page.
- Add `workflow` and `business_context` for daily-flow screens so the UI explains the business goal, not just the available calls.
- Add `user_experience` for every published screen. This is no longer optional review prose; schema/validator treat it as executable UX metadata.
- A classic replacement screen must not open empty. If the default action needs required fields, provide safe defaults, a selector workflow, or keep the screen out of the replacement path until it can render useful first-screen content.
- Add fields only when the operator should set them. Do not expose raw JSON request bodies.
- Field `input_type` and `value_type` are fixed enums. Do not invent widget names such as `money_input` or `asset-picker` inside generated metadata; add a schema version upgrade first.
- Use `dashboard_panels[].user_priority` and `dashboard_panels[].presentation_semantic` to mark P0/P1/P2 information hierarchy and artifact-specific presentation.
- Set `action_density` in the IA registry. Frontend overflow behavior reads this contract and must not use screen-specific limits.
- Use `actions[].result_semantics` when an action returns copyable token, endpoint, prompt, or other specialized self-service artifacts.
- Use `actions[].fields[].presentation_semantic` for `primary_selector`, `api_token`, `endpoint_url`, and `prompt_text` inputs.
- Add `view_model.rows_path` for list responses whose rows are nested inside a named field.
- Add `view_model.total_path`, `page_path`, and `page_size_path` when the API returns pager metadata.
- Keep raw response available only through the debug drawer with `raw_debug: true`.

When adding an action:

```json
{
  "key": "module.action_name",
  "label": "用户任务名称",
  "method": "GET",
  "endpoint": "/api/example/",
  "intent": "read_example_state",
  "screen_key": "module.screen",
  "module_key": "module",
  "view_type": "datagrid",
  "risk": "read",
  "fields": [],
  "view_model": {
    "rows_path": "results",
    "total_path": "count"
  },
  "description": "Short operator-facing purpose.",
  "source": "approved:api-evidence",
  "raw_debug": true
}
```

Do not add API-specific parsing rules to `TuiWorkbenchService`. The framework can auto-detect simple lists, but durable behavior belongs in `view_model` metadata.
For summary/status payloads, prefer `view_model.kind: "detail"` so nested objects render as readable field groups instead of being mistaken for a list view.

Overview panel example:

```json
{
  "key": "task-monitor",
  "title": "五、任务监控",
  "kind": "detail",
  "action_key": "task_monitor.dashboard",
  "max_rows": 8,
  "layout_area": "tasks"
}
```

Panel `action_key` values must point to already-approved actions. Do not create a panel that directly names an endpoint.

## Verification

Run these checks after changing metadata or the TUI renderer:

```powershell
agomtradepro\Scripts\python.exe manage.py export_tui_django_contracts --output tmp\tui_django_contracts.json
agomtradepro\Scripts\python.exe manage.py spectacular --file tmp\tui_openapi.json
agomtradepro\Scripts\python.exe tui-metadata-compiler\scripts\validate_tui_metadata.py config\tui\published\tui_operation_graph.published.json
agomtradepro\Scripts\python.exe tui-metadata-compiler\scripts\generate_tui_metadata.py --include-safe-api-actions 9999 --include-parameterized-api-actions 9999
agomtradepro\Scripts\python.exe tui-metadata-compiler\scripts\generate_tui_metadata.py --include-safe-api-actions 9999 --include-parameterized-api-actions 9999 --publish-ready --output config\tui\published\tui_operation_graph.published.json
agomtradepro\Scripts\python.exe tui-metadata-compiler\scripts\smoke_tui_actions.py --metadata-path config\tui\published\tui_operation_graph.published.json --json-output tmp_tui_smoke.json --prune-output config\tui\published\tui_operation_graph.published.json
agomtradepro\Scripts\python.exe tui-metadata-compiler\scripts\promote_tui_business_screens.py config\tui\published\tui_operation_graph.published.json
agomtradepro\Scripts\python.exe tui-metadata-compiler\scripts\smoke_tui_actions.py --metadata-path config\tui\published\tui_operation_graph.published.json --json-output tmp_tui_smoke.json --fail-on-error
agomtradepro\Scripts\python.exe tui-metadata-compiler\scripts\validate_tui_metadata.py config\tui\generated\tui_operation_graph.generated.json
agomtradepro\Scripts\python.exe -m pytest tests/unit/test_tui_workbench.py tests/unit/test_tui_metadata_compiler.py -q -p no:cacheprovider
agomtradepro\Scripts\python.exe manage.py check
```

`smoke_tui_actions.py --fail-on-error` is an execution check, not a schema-only check. Run it against
a fully migrated disposable database with a persisted staff user and a same-database localhost
service for MCP actions. A fresh installation without Regime, Pulse, or AI Provider data must return
an explicit empty/setup state. Do not use a stale development database and do not broadly allow
4xx/5xx responses to make the smoke pass.

Publish to the local DB registry only after review:

```powershell
agomtradepro\Scripts\python.exe tui-metadata-compiler\scripts\publish_tui_metadata.py config\tui\published\tui_operation_graph.published.json --approve --generation-source mixed --backend-version "local-dev" --source-evidence-path config\tui\generated\tui_operation_evidence.generated.json --review-note "Reviewed TUI metadata promotion batch"
```

If a published DB row exists, it overrides the repository JSON fallback. Use the publish command when the running local `/tui/` must reflect the reviewed file baseline.

The DB registry stores `schema_version`, `generation_source`, `backend_version`, `source_hash`, `source_evidence_hash`, `changed_fields`, `review_status`, approver, review note, and publish time. This is the rollback and audit trail for TUI-first UI releases.

Verify the active registry without writing:

```powershell
agomtradepro\Scripts\python.exe tui-metadata-compiler\scripts\publish_tui_metadata.py config\tui\published\tui_operation_graph.published.json --check --registry-key default
```

The command canonicalizes the reviewed file through the same validation, IA normalization, runtime injection, and compacting path used by publishing. It exits with code `1` when the active database row is missing or its source hash differs.

### Verified registry backup and restore

Before M5-B cleanup, export the active production registry to a protected path outside the Git
worktree. The command refuses repository-local output and refuses to overwrite an existing artifact.
It writes an atomic JSON bundle plus a `.sha256` sidecar containing the registry generation, graph
hash, schema version, backend version, reviewed payload, runtime build ID, rollback ancestry and
approval metadata.

```powershell
$backupPath = 'E:\agom-backups\tui-registry-pre-cutover.json'
agomtradepro\Scripts\python.exe manage.py backup_tui_registry --registry-key default --output $backupPath
```

Verify recoverability without changing the registry:

```powershell
agomtradepro\Scripts\python.exe manage.py restore_tui_registry_backup --input $backupPath
```

The dry-run verifies the bundle sidecar, registry-record hash, payload hash, runtime build ID and
the same metadata validator used by publishing. After the candidate observation window ends, build
the payload-free repository attestation from that external bundle. The command also requires the
backed-up generation/hash to remain the active production registry and reruns publish preparation as
the restore dry-run:

```powershell
$attestationPath = Join-Path $PWD 'docs\plans\web-to-tui-m5-production-registry-backup-attestation.json'
agomtradepro\Scripts\python.exe manage.py build_tui_registry_backup_evidence `
  --input $backupPath `
  --location 'artifact://agomtradepro/m5/tui-registry-pre-cutover.json' `
  --verified-by '<independent-reviewer>' `
  --retention-until '<YYYY-MM-DD>' `
  --attestation-output $attestationPath
```

The default is a dry run. Add `--write-evidence` only after reviewing the printed generation,
graph hash, bundle SHA-256 and attestation path. It atomically writes a structured attestation with
no registry payload and projects the exact candidate-bound fields into the cutover evidence. The
readiness checker reparses that JSON and rejects narrative files or hand-edited projections. Do not
commit the external bundle or sidecar.

An actual restore requires explicit approval and the source hash observed immediately before the
operation. This prevents overwriting an unexpected newer generation:

```powershell
$activeHash = '<verified-active-source-hash>'
agomtradepro\Scripts\python.exe manage.py restore_tui_registry_backup --input $backupPath --expected-active-source-hash $activeHash --approve
```

The approved restore republishes the validated backup payload through
`PublishedTuiMetadataRepository`, archives the current generation and records it as `rollback_of`.
Run the read-only active-registry check again after restore. Production backup evidence remains
incomplete until the backup and attestation commands have been executed and independently verified
in the production environment.

### Immutable cutover review and approvals

After the stable window, defect snapshot, telemetry snapshot and production registry attestation all
pass, freeze the eight non-approval gates into one review snapshot. The command refuses to write while
any gate fails and clears stale approvals whenever a replacement snapshot is created:

```powershell
$reviewPath = Join-Path $PWD 'docs\plans\web-to-tui-m5-cutover-review.json'
agomtradepro\Scripts\python.exe scripts\build_web_to_tui_review_snapshot.py `
  --as-of '<YYYY-MM-DD>' `
  --snapshot-output $reviewPath `
  --write-evidence
```

The owner and independent reviewer then record separate role-bound attestations. They must use distinct
identities and approve no earlier than the immutable review date:

```powershell
agomtradepro\Scripts\python.exe scripts\record_web_to_tui_cutover_approval.py `
  --role owner `
  --name '<owner-identity>' `
  --approved-at '<YYYY-MM-DD>' `
  --attestation-output 'docs\plans\web-to-tui-m5-owner-approval.json' `
  --write-evidence

agomtradepro\Scripts\python.exe scripts\record_web_to_tui_cutover_approval.py `
  --role reviewer `
  --name '<independent-reviewer-identity>' `
  --approved-at '<YYYY-MM-DD>' `
  --attestation-output 'docs\plans\web-to-tui-m5-reviewer-approval.json' `
  --write-evidence
```

Both tools default to dry-run behavior. The readiness checker reconstructs the current eight-gate
snapshot and exact approval projections; changing the candidate, matrix, production evidence or review
digest invalidates prior signatures. These commands record evidence but do not create or impersonate a
human approval.

### VPS release synchronization

VPS deployment must not call the publisher ad hoc. Both supported deployment paths call:

```sh
sh scripts/publish-tui-release.sh "$RELEASE_TAG"
```

The release helper requires the reviewed JSON to exist, publishes it idempotently, records the optional evidence hash, and immediately runs the read-only active-registry check. The post-deploy verifier repeats that check from the running `web` container. Deployment rollback starts the previous release and republishes that release's reviewed JSON before switching the `current` symlink, because a database registry row overrides repository files even after the application image is rolled back.
