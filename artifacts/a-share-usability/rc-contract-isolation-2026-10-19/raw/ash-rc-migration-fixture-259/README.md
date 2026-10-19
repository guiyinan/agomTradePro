# RC migration flush fixture candidate

This private candidate changes only `tests/migrations/conftest.py`. It imports the already existing `preserve_account_authority_generation` pytest fixture with the repository's `# noqa: F401` convention. The fixture is defined with `scope="module"` and `autouse=True`, so importing it into this conftest makes pytest discover and apply it to every test module below `tests/migrations/`.

The imported fixture retains its existing behavior: it filters only the authority-generation singleton out of Django's generated flush table list, executes ordinary flush SQL for all other tables (so source-table triggers remain active), and checks the singleton row and nondecreasing generation before/after cleanup. No fixture code, migration, trigger, assertion, or schema is changed.

The support module already documents and enforces isolated PostgreSQL/SQLite test-database checks. The candidate does not add a second protection implementation.

Prepared from the exact preimage in this packet. No project imports, tests, QA, database access, or Git operations were run.
