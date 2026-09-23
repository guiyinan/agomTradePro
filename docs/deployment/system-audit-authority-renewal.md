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

An expired Evidence V5 mapping still requires a fresh owner approval and a
new root issuance.  The guard prevents that state from becoming silent, but it
does not bypass the Evidence V5 first-winner/mapping invariants.

After a successful execution, run the read-only Audit/Data Center preflight,
then one bounded full-market publication.  Count the run as restored only when
the business outcome is `success`, `stored` is positive, the Audit outbox and
delivery receipts are present, and the Alpha page no longer reports the
authority blocker.  Observe two natural scheduler cycles before promoting the
runtime as recovered.  Financial Publication/source-time blockers remain an
independent gate.
