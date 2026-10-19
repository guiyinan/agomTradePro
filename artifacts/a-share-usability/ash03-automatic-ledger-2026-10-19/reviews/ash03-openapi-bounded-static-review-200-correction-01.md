# Correction to OpenAPI review 200: account-type constraint

This note corrects one follow-up inference; the frozen review 200 memo is unchanged. I initially treated an unknown persisted `account_type` as writable through the real ORM because Django `choices` alone do not enforce a database constraint. That omitted the account's cash-knowledge check constraint.

`SimulatedAccountModel` declares `sim_account_cash_knowledge_ck`: a row must be either `account_type="simulated"` with `cash_known=True` and `cash_reconciliation_status="simulated_ledger"`, or `account_type="real"` with `cash_known=False` and status `unverified` or `quantity_only`. Since `account_type` is non-null, another value fails this constraint. Migration `0032_cash_knowledge.py` installs the same check. Therefore `QuerySet.update(account_type="unknown")` on a database with migration 0032 applied is rejected by the database; the reported real-ORM counterexample does not establish a reachable HTTP 500 on the current migrated schema.

The application guard still maps an unexpected type returned by `get_active_account_models_for_user` to a 500 scope result, and the repository filters by user and `is_active`. But the current model/migration constraint prevents a conforming persisted row from supplying that unknown type. I found no other concrete current-schema ORM path through these rows to that 500 branch. Do not upgrade the prior memo's unproven `AgomTradeProException` 500 caveat into a confirmed defect or add a second 500 schema branch on this evidence. Review 200's conclusion remains: no confirmed P1/P2 projection defect; the generic setup-failure 500 schema matches its explicit response branch, and the separate exception-shape caveat remains unproven.

Source hashes read for this correction:

- `apps/simulated_trading/infrastructure/simulated_account_trade_models.py`: `a6189de5a40a66a00738be399ada43438b03bc192f75fe22e05787ffb06a047f`
- `apps/simulated_trading/migrations/0032_cash_knowledge.py`: `33f70e51043c4b6654532701c585d6753a40cfa2f8c00ae791359b0c1d7249ff`
- `apps/simulated_trading/application/interface_services.py`: `64c7a447f503f05efb14be091a5b41547ab70b9763a82ef6124e4255fce150cf`
- `apps/simulated_trading/infrastructure/account_repository.py`: `017c1ebba56fc98c3db2bdef0d6a629b05a5ea6552dc612c2e23f6f18effc682`

This was a read-only source review. No project import, test, QA, database operation, Git operation, or shared-source edit was performed.
