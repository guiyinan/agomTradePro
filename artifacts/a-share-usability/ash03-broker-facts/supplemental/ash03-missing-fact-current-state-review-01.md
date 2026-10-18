# ASH03 missing-fact current-state candidate 88 — static review

Review scope: the frozen private production candidate only, with a bounded read of the current unavailable-fact component test and TUI serializer. No project imports, tests, database access, QA, network, or Git commands were run for this review.

## Identity and size

- Candidate manifest SHA-256: `cfaf7f244715799c239b7ea7f827decbb907189c644e3687e889d32418e6e14c` (verified against the file).
- Candidate patch SHA-256: `3e3b76a6cf6f8f9d155724f5c0c46320106fb0a74f4059fc9875dc515a61a0a0` (verified against the file).
- `manual_trade_sync.py`: preimage `9a73bd4ce93164dad207f0e48d41aed7f0e372c383d6c6a20c00d144a224fdc1`, 884 nonempty lines; candidate `12e58a2c4084a7436cdff5d259bbbb5ce57c23a8fda2b9712ac8d8761a987f8c`, 962 lines (+78).
- `transaction_api_views.py`: preimage `cf2c06b9dc333671972a88aeab277957020721921fa42b0aca18982cef53baf7`, 806 nonempty lines; candidate `42f44081b6768918fceec9c5c6f47e968d02c0ffc52500e2f93a881b5b03be6f`, 828 lines (+22).
- Combined growth is 100 nonempty lines. Both files stay below 1,000 lines. Imports and changed/new functions remain within the existing Application/Interface boundary; the new repository result is narrowed to `BrokerFactRecord` before use.

## Findings

The main repair is coherent: `_resolve_current_fact_states` scopes fallback reads by owner, portfolio, and stable key, then validates transaction ID and all three identity fields. Missing reader, missing row, raised read, or identity mismatch produces `fact_unavailable`; the row drops reconciliation state/reason and projection outcome. `_fact_state_counts` skips unavailable records, so the two Source89 deletion cases should no longer inherit the initial write receipt as pending. `facts_saved_count` deliberately remains the count of successful initial persistence calls, even if a subsequent concurrent deletion makes the final current row unavailable.

The current component test exercises both deletion windows against real ORM rows: deletion after projection abort/before the blocked follow-up, and deletion after persist/before the pending reconciliation read. It asserts the transaction is gone, no other captured account/position/mirror/map state changed, all four reconciliation counts are zero, the row has no reconciliation/projection state, and one stable unavailable error gives recovery guidance. The test does not exercise a repository read exception or identity-mismatched return, though those branches are statically handled.

One counter edge remains in the candidate: after `_fact_state_counts` returns all zeros, the fallback at `manual_trade_sync.py` lines 606–623 counts directly from every `reconciliation.facts` entry. This bypasses both the current-state map and its write-ID filter. A malformed/stale result containing an outcome not represented by a current write could therefore repopulate a ghost count. The repository contract normally returns only the requested IDs, so this is not shown by the two deletion tests; to make the README claim that all counters share the resolved current snapshot invariant, remove this fallback or constrain it to the exact validated current IDs.

The TUI row adapter maps `fact_unavailable` to “成交事实当前状态不可用” and maps the stable code to “成交事实当前状态无法确认，未重建；请重新导入并先核对文件和余额”. It strips the internal code from the TUI error list while retaining the message and row number; the normal API retains the machine-readable code. The user-facing copy is clear. The current unavailable-fact test is Application-level and does not assert this TUI sanitization, so that presentation remains statically reviewed rather than regression-tested.

## Review status

No structural or typing blocker found. The current Source89 evidence is the pre-fix RED; this review did not run or infer a post-candidate GREEN result. The only concrete follow-up is to fence the all-zero raw-result counter fallback; the read-exception and TUI paths are finite coverage gaps if Root wants them included in the same focused regression set.
