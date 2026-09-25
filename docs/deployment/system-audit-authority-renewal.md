# System Audit authority renewal

The production scheduler may remain enabled while protected tasks are blocked.
Every Data Center writer performs a current actor/scope preflight before a
provider call or database write.  Renewal must therefore create a new,
append-only actor source and owner/tenant authority successor before the Audit
runtime can be enabled.

The renewal command is now connected to a fifteen-minute Celery guard:
`apps.audit.application.tasks.system_audit_authority_renewal_guard_task`.  The
guard checks the configured lease before protected work reaches the provider.
When the remaining window is within six hours it executes the request at
`AGOM_SYSTEM_AUDIT_RENEWAL_REQUEST_PATH`; the request is still parsed by the
strict command below and is protected by profile/source predecessor hashes.
Without that server-supplied request, or when the runtime is explicitly
`off`, the guard records a critical operational alert and returns `blocked`.
It never extends a row in place or manufactures an approval.

The VPS compose contract passes the request path to both the web process and
the default Celery worker.  Its fail-closed default is
`/app/var/system-audit-authority-renewal.json`, backed by the persistent
`var_data` volume, so a code/image replacement does not silently remove the
configured renewal channel.  A missing file still produces
`renewal_request_not_found`; deployment must place only a reviewed,
non-secret request envelope at that path.

The supported entry point is:

```text
python manage.py renew_system_audit_authority --input <renewal.json>
python manage.py renew_system_audit_authority --input <renewal.json> --execute
```

The command is dry-run by default.  Its JSON envelope contains only
server-issued selectors, hashes, timestamps, the owner/policy scope, and
hash-bound Config Center predecessor values.  It must not contain passwords,
session keys, API tokens, or provider secrets.  The actor capture selectors
must refer to fresh raw authentication, User, and RBAC sources already
published by the authenticated Account authority publisher.

Execution performs the following steps in one PostgreSQL transaction:

1. capture the fresh actor authority source;
2. append the owner/tenant Authority V3 successor with predecessor CAS;
3. revalidate the actor/scope identity and minimum validity window;
4. publish a Config Center successor with `mode=required`, `outbox_enabled=true`,
   and the exact V3 selector.

The active profile and snapshot IDs, versions, and hashes are mandatory for
execution.  A changed predecessor, expired upstream source, missing Evidence
V5, or insufficient validity window returns a stable `blocked` result and
rolls back the authority writes.  Existing authority rows are never extended
or edited in place.

When Evidence V5 itself has expired, use the recovery entry point:

```text
python manage.py recover_system_audit_authority --input <recovery.json>
python manage.py recover_system_audit_authority --input <recovery.json> --execute
```

Recovery is also dry-run by default and uses the renewal envelope plus fresh
receipt, subject, Evidence V5, and Authority V3 identities.  It appends a new
provenance receipt and Evidence V5 successor, issues a fresh Authority V3 root
against that successor, and activates the runtime in the same PostgreSQL
transaction.  Evidence roots keep their original canonical hashes; successors
bind the exact predecessor content hash.  Repository CAS requires both account
and underlying mappings to name the same head, so history cannot be overwritten,
forked, or backfilled.  A failed profile activation rolls the entire recovery
back.

The periodic guard continues to use ordinary Authority V3 renewal while the
Evidence V5 lease is current.  Operators must run recovery only after that
assignment lease has expired; it does not weaken actor, policy, physical-row,
profile, or source-freshness validation.

After a successful execution, run the read-only Audit/Data Center preflight,
then one bounded full-market publication.  Count the run as restored only when
the business outcome is `success`, `stored` is positive, the Audit outbox and
delivery receipts are present, and the Alpha page no longer reports the
authority blocker.  Observe two natural scheduler cycles before promoting the
runtime as recovered.  Financial Publication/source-time blockers remain an
independent gate.
