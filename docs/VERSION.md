# AgomTradePro Versioning

> **Current version**: `0.8.0`
> **Build date**: `2026-07-05`
> **Full version**: `0.8.0-build.20260705`
> **Release status**: Formal public release
> **Repository status**: Active development continues on top of the `0.8.0` release line

---

## Current release

`0.8.0` is the first release that closes the long-running post-`0.7.0` snapshot period into one formal version line.

This release freezes three things as official public posture:

1. **Release boundary**
   Local first-run and demo can still use `SQLite + synchronous tasks`, but the formal production recommendation is now `PostgreSQL + Redis + Celery + persisted var/media evidence`.
2. **Operations boundary**
   `task_monitor`, readiness evidence, scheduler proof, and VPS bundle verification are now documented as repeatable acceptance flows instead of ad-hoc operator knowledge.
3. **Architecture boundary**
   TUI runtime metadata no longer depends on one oversized repository file as its single mutation center; runtime patches and injected metadata are split by responsibility.

## 0.8.0 highlights

- Unified public version and build metadata across code, docs, and agent guidance.
- Closed the historical `task_monitor` “unfinished” status in project guidance.
- Standardized readiness acceptance around:
  - local strict acceptance
  - VPS scheduler-clean acceptance
  - evidence files under `var/readiness-evidence/`
  - fixed operator commands and pass/fail conditions
- Locked the formal production database posture to PostgreSQL.
- Kept `core/integration` bridge debt at zero under governance ratchets.
- Reduced `apps/terminal/infrastructure/tui_metadata_repository.py` from a large central runtime file to a smaller repository plus dedicated runtime metadata patch modules.

## Version history

| Version | Date | Status | Summary |
|------|------|------|------|
| `0.8.0` | `2026-07-05` | Released | Release closure, operations hardening, readiness/VPS runbook, TUI metadata refactor |
| `0.7.0` | `2026-03-23` | Released | Setup Wizard, AI Capability Catalog, Terminal CLI, Agent Runtime, Pulse |
| `0.6.0` | `2026-03-19` | Released | AI Capability Catalog initial public release |
| `0.5.0` | `2026-03-17` | Released | Terminal CLI and Agent Runtime initial public release |

## Version format

AgomTradePro uses semantic versioning plus a build date:

```text
major.minor.patch-build.YYYYMMDD
```

Example:

```text
0.8.0-build.20260705
```

### Change rules

- **Major**: incompatible API or architecture boundary change
- **Minor**: new release line with meaningful capability or operations boundary change
- **Patch**: fixes-only release on an existing line
- **Build date**: the release build date

## Release posture

### Local / first-run posture

- Default local path: `SQLite`
- Redis/Celery optional
- Setup Wizard remains the preferred first-run entry

### Formal production posture for 0.8.0

- Primary database: `PostgreSQL`
- Queue/cache: `Redis`
- Async runtime: `Celery worker + Celery beat`
- Persistence expectations:
  - DB persisted outside container lifecycle
  - `var/readiness-evidence/` persisted
  - media/log/audit artifacts persisted

SQLite on VPS is now explicitly treated as a **demo / migration / diagnostic path**, not the formal production recommendation.

## Related files that must stay aligned

| File | Purpose |
|------|------|
| `core/version.py` | Single source of truth for runtime version/build |
| `pyproject.toml` | Package version |
| `AGENTS.md` | Agent-facing project status and architecture guidance |
| `README.md` / `README_EN.md` | Public repo release narrative |
| `docs/INDEX.md` | Doc entrypoint |
| `docs/governance/SYSTEM_BASELINE.md` | Single narrative source for scale and deployment posture |

## Release checklist

When cutting a new formal version:

- [ ] Update `core/version.py`
- [ ] Update `pyproject.toml`
- [ ] Update `AGENTS.md`
- [ ] Update `README.md`
- [ ] Update `README_EN.md`
- [ ] Update `docs/INDEX.md`
- [ ] Update `docs/governance/SYSTEM_BASELINE.md`
- [ ] Update release notes and regression report

---

**Maintainer**: AgomTradePro Team
**Last updated**: `2026-07-05`
