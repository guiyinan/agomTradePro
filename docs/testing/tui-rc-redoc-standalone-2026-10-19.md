# TUI RC ReDoc standalone compatibility repair — 2026-10-19

ReDoc previously returned HTML 200 but loaded the moving `redoc@latest` ESM bundle as a classic script. The browser reported `Cannot use import.meta outside a module`, rendered no documentation and never requested the schema. Pinning the compatible standalone `redoc@2.5.4` bundle fixes the existing template without a route or dependency change.

The isolated Phase 2 preview is `ed032a79bb015e1ddf1619f8b33cb77bc416e1d6` plus the seven overlays recorded in the archived `source/qa-source-v2.json`. The shared source is bound separately by raw hash and clean Git blob in `source-binding.json`; this is scoped preview evidence, not final-candidate release evidence.

The existing ReDoc browser surface case passed under repository `pytest.ini`; the existing HTML contract passed with an assertion for the pinned bundle URL. Captured script and schema requests returned 200, the page contained one `redoc-wrap` and 601,706 body characters, and no page error or request failure was reported. The schema response is YAML; its `json_parseable=false` diagnostic is expected. Black, isort, Ruff, settings incremental mypy and the unchanged mypy debt ceiling passed. The whole test file's formatter-only changes preserve its AST. The independent static review and original logs are included.

The earlier invocation with the nonstandard `-c pyproject.toml` failed and is retained as exploratory evidence; its failure is not assigned to a single cause. Original failing journey results are retained as historical context. This patch does not establish full RC/S6, repair calendar availability, start observation T0, close TUI-02 or authorize deployment. The moving CDN remains an external dependency; this repair pins its runtime version.

Raw logs, JUnit, screenshots, original failure records and source snapshots are preserved in an independently verified local-machine archive. The compact index `tui-rc-redoc-evidence-2026-10-19.json` records its exact path, SHA-256, input identity and check results. It has not been uploaded remotely; this source commit contains no raw evidence package.
