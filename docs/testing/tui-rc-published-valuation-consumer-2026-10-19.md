# Published valuation consumer — 2026-10-19

The valuation endpoint previously returned blocked even when the preliminary
publication gates were usable. Published mode now calls the real valuation
UseCase through a typed input port. Data Center acquires the financial, price and
valuation boundaries before reading their gates and exact selected-member facts,
using one shared monotonic lock deadline. The existing stock-pool default remains
one valuation row; analysis requests an explicitly bounded history, at most 5,000.
Missing/stale/invalid publications and unavailable valuation history fail closed
with original reasons and null decision outputs. Historical-mode behavior remains.

Repository mapping preserves selected member PKs, requested asset identity and
source clocks: `observed_at` supplies `source_updated_at`; `fetched_at` remains
`updated_at`. A newer unselected valuation revision cannot override the current
member. Existing valuation formulas and financial completeness rules are unchanged.

The consumer API fixture supplies all seven required financial metrics rather than
weakening the mapper. Each fact has explicit synthetic source bytes, a hash and a
publication member. Its helper preserves the existing single-revenue default.
These are controlled consumer inputs: the financial helper constructs synthetic
publication state and does not establish formal publisher, activation, provider,
capacity, production or UAT authority.

The corrected composed source passed 128 unit/API/legacy research-consumer cases,
including real selected-member reads, a newer decoy revision, source/fetch clocks,
missing-member blocking, existing missing-gate cases and the old default financial
fixture. Source and pristine baseline hashes were unchanged. This rerun supersedes
the earlier 120-case source identity after formatting/import repair; the first
member fixture's one-pass/one-fail result is retained rather than called green.
The actual shared source then passed the same 128 cases, Black/isort/Ruff,
incremental mypy on ten production files (zero regression/legacy errors), full
production debt (zero errors), freshness contracts (89 surfaces) and official
module-map build/check. Final same-SHA RC/S6 checks remain required separately.

The 128-case run and companion real PostgreSQL lock checks are archived locally at
`C:/Users/muku/.codex/evidence-archives/agomTradePro/2026-10-19/typed-combined128-and-native-pg4/`,
index SHA-256
`384c9b324767d02ae0a0923c11db9e70f2558627135064a0b05c36a3e7c7a785`.
The shared-source run, final type/style checks and official projections are in
`C:/Users/muku/.codex/evidence-archives/agomTradePro/2026-10-19/typed-shared128-and-final-types/`,
index SHA-256
`e6a3d47c51c293d97c323297edd91e23b6efada9882e06462e125f1e1b8e0e15`.
Both archives are local only. Full M5 browser acceptance is pending the separately
guarded test adapter. Nothing in this batch was deployed.
