# ED-03 isolation candidate shipping review

## Decision

This one-file, test-only isolation change can be submitted as an independent commit and validated by the normal Linux CI matrix while the local full 241-target run remains pending. Treat it as accepted only after the affected Linux CI jobs pass. It changes no production source and leaves the migration test body and its assertions intact.

The 291 candidate adds the existing `preserve_account_authority_generation` fixture import to `tests/critical/test_agent_and_recovery_safety.py` and changes only the existing transaction marker to `django_db(transaction=True, serialized_rollback=True)`. The target test body and signature are unchanged. The fixture import is part of the change: it keeps the authority-generation singleton present during this module's flush lifecycle. The existing review in `ash-ed03-isolation-static-review-292.md` explains why this preserves the other tables, content types, and triggers while aligning this interleaver with migration tests' serialized-rollback lifecycle.

## Evidence

The current 300 input snapshot (`.tmp/ash-ci-formatted-full-green-300/inputs.json`, SHA-256 `f58f6c198e3ea7fb01a92e6e389ed7be7bd7ab2fc3921710eacbe6fb7c6b8508`) binds `tests/critical/test_agent_and_recovery_safety.py` at SHA-256 `269e86fb7b8abb41048b2e2a558d963e7f5a85deba52cf8153824b3bd5e4cc45`. I read the exact test file in the recorded source export and confirmed that hash. Its logical diff against the 291 preimage contains the fixture import and serialized-rollback marker only.

The ordered 293 RED ran three nodes: the strategy-allocation migration passed, the critical interleaver passed, and the following AI capability migration failed during pytest setup while deserializing `django_content_type`, with a uniqueness error. The captured 300 `green.log` lines 143–145 show those same three nodes in the same order all passing. This is the specific regression evidence for the test change.

The 300 full-run log was still being written when inspected: its tail had reached about 75%, with no final result receipt or JUnit XML present. I make no claim that all 241 targets passed. The Linux 3.11/3.13 CI jobs remain the required acceptance check.

## Residual limit

`serialized_rollback=True` restores the test database baseline during setup and suppresses teardown `post_migrate` for this test. The critical test does not assert post-migrate behavior. As the 292 review records, the fixture's before/after flush check does not prove authority-generation monotonicity across serialized baseline restoration. That is a stated test-isolation boundary, not a production behavior change.

## Pointers

- 291 candidate manifest: `.tmp/ash-ed03-isolation-tests-291/manifest.json`, SHA-256 `603cfa1a3cc9dab3b392ea3f8eb9ad34a2887598eb54d5f3517318cf9f98dd2b`
- 291 candidate postimage: SHA-256 `288974ec6f90cae1c7605af625941334f8eff0f8bdd5e0263c2e6e2255d136cd`
- 292 static review: `.tmp/ash-ed03-isolation-static-review-292.md`, SHA-256 `cf9835cb0473c861740425efeeff9208ae5e1290be0c00840cb0455767b24000`
- 293 RED result: `.tmp/ash-ci-red-293/red.result.json`, SHA-256 `05da7ea3c1a8ad133016d0fc60bce800a8a56d45c5eba95010d8c67d3bacb57d`

No tests, QA, project imports, database, or Git commands were run for this review. The 300 log was read only for the three named outcomes and current progress; it was not copied or modified.
