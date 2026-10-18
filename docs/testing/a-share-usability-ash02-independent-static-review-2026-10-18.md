# ASH-02 Finite Exit: Final Static Review Supplement

Review date: 2026-10-18
Method: read-only review of the four named JUnit XML files, their run manifests, the actual-caller observation and candidate, and the two type-check manifests. No tests, QA, database, network, or Git operations were run by this reviewer.

## Verification evidence

JUnit counts were read from the XML `testcase` nodes and deduplicated by `classname::name` (the same result holds when deduplicated by test name):

| Run | Nodes | Failures / errors / skips |
| --- | ---: | ---: |
| `calendar-order-green-01.xml` | 16 | 0 / 0 / 0 |
| `actual-caller-05.xml` | 1 | 0 / 0 / 0 |
| `calendar-compat-minimum-01.xml` | 405 | 0 / 0 / 0 |
| `sdk-client-minimum-01.xml` | 23 | 0 / 0 / 0 |
| **Four-file subset** | **445 unique nodes** | **0 / 0 / 0** |

The combined XML contains 445 testcase rows, 445 unique node IDs, and no duplicates. The four run manifests report `passed`, exit code 0, and `source_unchanged=true`. The incremental mypy regression check for `apps/data_center/infrastructure/exchange_calendar_source_evidence.py` and the full mypy debt-ceiling check also report `passed`, exit code 0, and unchanged source manifests.

## Actual-source caller scope

The observation records an actual Sunday wall clock from `2026-10-18T15:20:04Z` to `15:20:13Z` and a controlled Monday scenario cutoff of `2026-10-19T02:00:00Z`. The retained `stock_basic` and `trade_cal` response completion times are Sunday `14:44:22.717022Z` and `14:44:23.653410Z`; the instrument/calendar snapshots, runtime profile, and formal publication were also recorded on Sunday before the scenario cutoff. The helper replays the two previously retained raw responses offline and makes no provider request. The test patches `_ServerUTCClock.now` and `DjangoSystemAuditClock.now` for the Monday path while leaving `timezone.now()` unpatched. It records one System Audit event and one outbox row before the scenario, then asserts both counts remain unchanged.

The instrument evidence preserves `source_observed_at=null`, `source_available_at=null`, `must_not_use_for_decision=true`, and `must_not_execute=true`. The calendar’s `source_published_at` remains null, and its original response reference and completion clock are retained. The observation and test therefore support use of actual retained source bytes with unknown source observation/availability, not a claim that those facts are decision-ready or execution-authorizing.

The caller first sends a real request through the existing manual-trade API view and asserts the Sunday request is blocked with HTTP 400 and no account/position/trade mutation. Its Monday path is limited to the exact production `ManualTradeAPIView` named URL pattern, mounted at its existing `/api/simulated-trading/` prefix in a test URL configuration; unrelated root URL modules are omitted for test-app isolation. The test creates its own rule, fee policy, user/account, and settled 1,000-share position, then checks the Monday open session, next-session T+1 release, BUY, idempotent replay, pending-share SELL rejection, and SELL from that test-owned settled baseline. The submitted price is test input; this run does not test a live quote, real account, broker execution, or production deployment.

The observation explicitly records `production_or_broker_acceptance=false` and `local_rule_fee_and_settled_baseline_are_test_owned=true`. The evidence supports the bounded local ASH-02 caller scenario and the stated test/type-check results. It does not establish production B1, broker acceptance, or live market-price qualification.
