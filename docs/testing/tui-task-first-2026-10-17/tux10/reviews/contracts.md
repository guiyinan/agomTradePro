# TUX10 final contract review 02

Scope: read-only review of the frozen TUX10 input set and the two bounded
research-fixture repairs. No Django, pytest, browser, network, Git, or source
mutation was performed by this review.

## Findings

- The market fixture change is minimal and source-bound. The current
  tests/support/tui_research/market_consumer_state.py keeps the existing
  local cn_market_session_close_utc import in _normalize_clocks, adds
  cn_market_date_from_observation only inside prepare_market_consumer_state,
  and uses it only for the QuoteSnapshotRepository.get_series(snapshot_date=...)
  lookup. This matches the unapplied repair preimage and does not alter quote
  values, publication calls, owner code, or freshness/readiness rules. Frozen
  raw SHA:
  660c864cd16da8cf0074c925f136546c8a592315c56176674e4148ed62744768.

- The copied UTC/CN boundary candidate is identity-preserved. The frozen
  .tmp/tux10-final-f79b22a4a-02/test_quote_snapshot_market_date_boundary.py
  has raw SHA
  a98a7077ca1864bf04d192d77305efed096765a3AAFBC786AE4626EFDB14B850,
  matching the earlier private candidate. It uses typed repository
  bulk_upsert, date-filtered get_series, and list_publication_candidates; it
  does not insert ORM rows directly or mock an Equity owner response. The two
  fixed aware clocks cover 15:59:59 UTC and 16:00:00 UTC. The candidate
  identity is included in frozen-inputs.json.

- The isolated settings are private and explicit. SHA:
  dcbf84d4140da9bea8367041e2cca3da50e9db0e4369117e283820b7e7955e3d.
  ALLOWED_HOSTS contains six named hosts:
  testserver, localhost, 127.0.0.1, web, demo.agomtrade.pro, and
  web.attacker.example; there is no wildcard. The attacker hostname is
  present only to let the existing SSL RequestFactory case exercise redirect
  behavior rather than fail at host validation. The file is an isolated
  settings module under the private TUX10 directory and is not a production
  settings change. SQLite, LocMem cache, memory broker/backend, console-only
  logging, and the private artifact root are explicitly scoped there.

- Frozen source identity is internally consistent: base_head and head_after
  remain f79b22a4a20397399f0162166d59945a512192ca, source_inputs_unchanged is
  true, and frozen_acceptance_valid is true. The recorded static
  source-contract check reports 407 rules, and the freshness check reports 86
  surfaces. These are recorded outputs, not a claim that production or human
  acceptance passed.

## Limitations

The browser inventory record was still incomplete at this read: its JSON had
a start PID but no exit_code/finished_at, while its log contained six pytest
progress dots. Therefore the final real-browser result remains unverified
from this review. The fixture and settings contracts show no actionable
blocker; parent must use the eventual completed browser record before calling
TUX10 accepted. No production, provider, market-normal-case, human, or
financial-authority conclusion follows from these private records.
