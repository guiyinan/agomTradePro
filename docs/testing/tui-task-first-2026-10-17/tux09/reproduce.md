# TUX-09 local acceptance reproduction

The JSON phase records contain the exact original command, settings hash, input hashes,
start/end time, exit code and output. Paths and ports refer to the disposable local run.
The copied settings and publication test are the exact bytes used for that run.

Use the repository's `agomtradepro` environment at the feature commit. Copy
`tux09_feature_609ea_settings.py` into a new disposable directory, replace its `QA_ROOT`
with that directory, and put that directory and the repository root on `PYTHONPATH`.
Create a fresh SQLite database there. Changing this location produces a new settings
hash and a new run; it does not recreate the original evidence identity.
Never reuse the concurrent A-share database or a production configuration.

The final backend command is in `backend-final-05.json`; the frontend command is
`node-02.json`. The seven-check HTTP/browser command is in `browser-final-07.json`:
replace only its private publication-test path with the copied
`test_tux09_missing_tasks_red.py` path and use fresh `--basetemp`/cache paths. Set
`TUX09_RUN_LABEL` to a unique name for browser artifacts. `--reuse-db` is safe only
for the disposable database belonging to this reproduction.

The committed browser test uses actual authenticated Django HTTP and real owner
reads with synthetic local business rows. It blocks external network attempts during
the test cases. Market-unavailable recovery is accepted explicitly; a successful normal
market owner response is not claimed. These commands do not authorize provider writes, paid model calls, deployment or trade
submissions. The in-test network guard is not a proof about all Django initialization.

Use official `npm run build:tui`, `npm run check:tui`,
`python scripts/build_module_map.py` and `python scripts/check_module_map.py` for
generated files. The static source-contract amendment is a checker input, not a
runtime-builder input; its reverse JSON comparison is recorded separately.

Earlier failed rounds are retained to explain corrections. Only final check records
listed in `acceptance.json` count toward this slice. Static audit findings have explicit
dispositions there. TUX-10 integrated acceptance and real-user/production studies remain
separate work.

Raw `.log` filenames in private static-audit notes identify the original local stream.
The committed corresponding phase JSON retains that stream in `output`, with its original
raw and UTF-8-roundtrip SHA-256 values. Ignored private log files are not committed.
