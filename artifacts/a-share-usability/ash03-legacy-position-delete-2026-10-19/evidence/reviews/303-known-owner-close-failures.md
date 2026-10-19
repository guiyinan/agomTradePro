# ASH03 close-test static review

Read-only review of the two failures reported by native run 302. No tests, project imports, QA, database, or Git commands were run.

Both fixtures create only a legacy `account.PositionModel` for an active owner portfolio. Its 1,000 shares, average cost 10.50, current price 12.00, market value 12,000, and `is_closed=False` are explicit. Neither fixture creates a simulated account/position, migration map, trade, or sellable-balance evidence. Each owner-close test POSTs the legacy position ID to `/api/account/positions/{id}/close/` and asserts HTTP 200 plus `success=True`.

The request follows the ordinary open-source path. `_resolve_position_context` checks for a unified position, then reads the legacy position, authorizes its owner, and calls `_ensure_portfolio_ledger_synced`; the closed-source branch is guarded by `legacy_projection.is_closed` and cannot apply to these fixtures. Adoption carries the legacy total quantity and cost, but `DjangoLegacyPositionAdoptionRepository` creates the unified position with numeric `available_quantity=0` and `available_quantity_known=False`. `UnifiedPositionService.close_position` rejects that state with `BusinessLogicError(code="SELLABLE_BALANCE_UNKNOWN")` before creating a SELL trade or changing the position. The common DRF exception handler gives that business error its default 422 status.

Thus the old HTTP-200 expectation is incompatible with the current fail-closed rule when an unqualified legacy holding is first adopted during close. `shares=1000` and a price do not prove how many shares are sellable. The two failures are duplicates in substance; the fixtures differ only in owner username construction and grant creation style.

These requests do not use the closed-source lookup or source-deletion logic added for the 286 race fix: the legacy source is open, and rejection happens before the close result, legacy projection update, or mapping deletion. The common open-ledger synchronization/adoption path is used, so the pure-ed03 baseline reproduction remains useful to establish when this behavior entered the test baseline; it is not evidence that 286's closed/delete branch caused it.

Keep production behavior fail-closed. After the baseline comparison, either preserve these as authorization-only tests and assert the explicit unknown-sellable response with unchanged trade/position state, or give a separate execution-success fixture an explicitly known unified sellable balance and the required account/mapping context. Do not infer `available_quantity=shares` from the legacy row to restore the old 200 response.

Reviewed source SHA-256 values:

- `tests/integration/account/test_observer_permission.py`: `dd9a0c6f13eb43db790256f6adfc91a4443500e58f4201ba02913aa97980a276`
- `tests/integration/test_portfolio_observer_access.py`: `fd14dd7121d5e9da4a4a338f45ee14ddfe0d33c44a04835198a6c836371430a4`
- `apps/account/application/portfolio_api_services.py`: `f77f4a0ddb2b6718ee2b8ce854867d8b9fb433bff1f081658528023d3e509c7c`
- `apps/account/interface/portfolio_api_views.py`: `29add58bc0516e0652825e9422aa37cb333a8981f05ff527e92424d07a564f97`
- `apps/simulated_trading/application/unified_position_service.py`: `dbf7511a24c957527fd6ade3e090550926d5763c08989c2e5dcc0d1307655c79`
- `apps/simulated_trading/infrastructure/legacy_position_adoption_repository.py`: `402b546e9d540f90204953ffc1a4622a7d73d5e501199f02314f2686bba341b0`
