# ASH03 CI compatibility evidence

Exact-source local RED and GREEN outputs, official generator receipts and independent static reviews. `evidence.json` binds raw originals and final source files. Remote CI failures are preserved as precise excerpts with complete-log digests. No production Python changed. Full NoDB and MCP checks overlap and are not summed as unique coverage.

The exact `.log`/`.xml`/two raw `.patch` attributes preserve immutable output whitespace only; source checks, diff visibility, scanner rules and budgets remain unchanged. New SHA CI, release and external acceptance are separate.

Post-commit blob verification caught CRLF conversion in one of the two raw candidate patches. A separate evidence-only commit explicitly restages that exact path with `git add --renormalize`; `git-archive-preservation.json` records both prior and original digests. The other patch already matches. Source and tests are unchanged.
