# fc20f43 CI correction packets: bounded static review

Review date: 2026-10-19. Read-only static review only. No project imports, tests, mypy, QA, database access, or Git operations were run by this review.

## Scope and receipts

- TEST ONLY fixture packet: `.tmp/ash03-fc20-fixture-correction-01/manifest.json`, SHA-256 `c62048e00d349d51db07906d907e5a020bcf300ea732231005fafde1e1e1fe65`.
- RestrictedPython import candidate: `.tmp/ash03-fc20-restrictedpython-type-candidate-01/manifest.json`, SHA-256 `4a5a2694fa94ed08d7e53e744d0e7b491702cfc4a6a31fb9183731762d72f182`.
- Security evidence index candidate: `.tmp/ash03-security-evidence-shape-98/manifest.json`, scanner comparison `scanner-comparison.json`.

The two fixture and import manifest digests match the supplied values. This review concerns only these candidates and the one evidence index; it does not certify broader ASH03 behavior or CI status.

## Fixture correction

The patch changes only three test-fixture fields:

- `tests/unit/test_auto_trading_engine.py`: the shared SimpleNamespace account fake explicitly has `cash_known=True`. The fixture carries a numeric cash amount and tests a known-cash risk branch; it does not change production behavior or remove a cash-unknown assertion.
- `tests/unit/test_simulated_performance_calculator.py`: the shared synthetic SimulatedTrade sets `fee_amounts_known=True` and `cost_basis_known=True`. This file's helper produces complete numeric executed-trade examples for performance calculations. Existing function arguments, realized PnL values, assertions, and production sources are unchanged.

These values align each positive fixture with the Domain evidence contract. They do not convert missing or unknown production evidence to known. The packet contains no production file, dependency, governance, or budget-baseline change. Root still owns native test execution.

## RestrictedPython import candidate

The source change is one import path: `RestrictedPython.compile_restricted` becomes `RestrictedPython.compile.compile_restricted`. The compiler call and `mode="exec"` stay the same. The candidate retains the existing RestrictedPython compiler and the configured safe builtins, guarded attribute/item access, write guards, sequence unpack guards, and restricted import hook; the patch adds no `TYPE_CHECKING` edge, dynamic import, ignore, policy bypass, or dependency/configuration change.

The private README reports local package evidence for version 8.1. `pyproject.toml` lists `RestrictedPython` without a version constraint, so that local evidence alone does not certify every dependency version allowed by the project. Before admission, Root should run the CI-equivalent incremental mypy check and the existing script-engine sandbox behavior tests in its restored window. No unknown cash/cost checks or baseline values are touched by this import patch.

## Security evidence index shape

The scanner receipt records the same Gitleaks version, binary hash, and config hash for all runs: original source index found 6, candidate found 0, and the synthetic positive control found 1. All six original matches are the index's SHA-256 values for source files, not credential values; the receipt marks each as matching its frozen source and current file. The redacted scanner reports preserve no secret material.

A direct read-only comparison of the preimage and candidate found:

- all top-level keys are equal;
- all values outside `production_inputs` are equal;
- the 110 `production_inputs` path/hash pairs are identical;
- the representation changes from an object mapping paths to digests into an array of objects with explicit `path` and `raw_sha256` fields.

Therefore this is an **index representation/schema correction**, not a whitespace-only formatting change. It preserves the underlying evidence but changes its JSON shape. A bounded `rg` across `scripts/`, `apps/`, `tests/`, `governance/`, `docs/` and the ASH03 source receipts found no code consumer of the `production_inputs` field; the documentation links to the index without parsing it. The checked-in index at `artifacts/a-share-usability/ash03-broker-facts/evidence.json` still uses the old object representation. If Root admits the new shape, the final evidence index and its producing workflow should be described/synchronized as this shape change. No module map, data dictionary, dependency projection, or governance baseline is changed by the private packet.

## Review disposition

The fixture packet is safe as TEST ONLY alignment. The RestrictedPython candidate is a narrow static typing fix that preserves the sandbox configuration, pending Root's targeted CI verification. The evidence index candidate preserves every path/hash pair and has a successful scanner control, but its manifest/description must say “representation/schema correction,” never “format-only.” I found no in-repository parser that depends on the old object shape. No conclusion here represents a production test pass or broader ASH03 acceptance.

