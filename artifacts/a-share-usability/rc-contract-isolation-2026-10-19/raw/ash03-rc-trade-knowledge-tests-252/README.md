# ASH03 manual trade knowledge contract test candidate

This private test-only candidate updates the exact response field set in the real HTTP-to-UOW manual BUY/SELL contract test and asserts the seven serializer knowledge fields by side. The BUY case requires complete fee and cost-basis knowledge with realized PnL marked not applicable. The seeded SELL position has no cost-basis knowledge, so the response must preserve `cost_basis_known=None`, report realized PnL as unknown, and expose no numeric realized PnL or percentage. Both paths require the UOW-produced fee amounts to be known. Persisted knowledge flags are checked separately.

The existing authenticated actor/account and UOW intent assertions remain unchanged; no unrelated owner response field is added. The candidate retains the exact field-set equality assertion.

The source contract was inspected in `TradeResponseSerializer`, the manual trade view serializer payload, `SimulatedTrade` status properties, and the real settlement repository. The seeded `_position()` fixture leaves `cost_basis_known` at its model default (`None`); SELL may retain numeric internal calculations, while the HTTP contract masks realized values unless cost basis and fees are both known.

Scope is one test file. This packet was generated from the current source bytes recorded in the manifest. No pytest, project imports, database access, QA, or Git operation was run while preparing it.
