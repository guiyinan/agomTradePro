# TUI response optimization — 2026-09-08

## Completed

- Batch Alpha quote aliases through one existing publication read, preserving its
  freshness prohibition, source timestamps, missing values and original-code priority.
- Project visible screen actions once and reuse the result for legacy blocks.
- Load collapsed secondary dashboard panels on first expansion, retaining open state
  after the response. Cancel browser requests when leaving a dashboard and ignore
  detached responses. Browser cancellation does not guarantee server query cancellation.
- Rebuild the workbench bundle and version its template URL for cache invalidation.

## Measurements

Authenticated production Django Client measurements use the same user and default
parameters, with one warm-up and three recorded requests per endpoint. These measure
server processing rather than browser/network latency. Raw results are in
`tui-performance-before-2026-09-08.json` and
`tui-performance-after-2026-09-08.json`.

| Request | Before | After |
| --- | --- | --- |
| Alpha database queries | 234 | 177 |
| Alpha median processing time | 964 ms | 710 ms |
| Alpha individual processing times | 964 / 862 / 966 ms | 710 / 2483 / 651 ms |
| Screen median processing time | 117 ms | 135 ms |
| Screen database queries | 6 | 6 |

The Alpha median improved by about 26%; queries decreased by about 24%. The screen
request did not show a timing improvement. A 2483 ms server outlier remains; an
authenticated external HTTPS Alpha request took 3822 ms. These small samples do not
establish tail latency or guarantee that every interaction is faster.

A second five-request run (`tui-performance-after-repeat-2026-09-08.json`) measured
Alpha at 892 / 1210 / 1286 / 1066 / 902 ms (median 1066 ms), with 179 queries each.
Screen processing was 186 / 199 / 215 / 207 / 1059 ms. Thus the reduction in query
count is reproducible, but a sustained response-time improvement is not established
under the live workload. Candidate count, scoring date and decision blocks matched.

## Validation

- Backend regression: 329 passed across Alpha context, publication gates and TUI.
- `npm run test:tui-js`: 47 passed, including lazy expansion and navigation abort.
- Incremental mypy: zero regressions/errors for the three production Python files.
- Full mypy debt ceiling: zero errors.
- Current-data contract guard: 53 surfaces passed; new batch safety tests registered.
- Ruff, Black/isort, runtime build/check, template migration inventory and diff check passed.
- Live authenticated HTTPS: 200, ten candidates, eight columns, scoring date
  2026-09-04, all rows still prohibited for decisions. TUI location label and new bundle
  version present; served JavaScript matches the local generated bundle.

## Deployment and remaining verification

- Code-only hot update; Web restarted, health endpoint 200, nine containers running.
- Backup: `/opt/agomtradepro/manual-file-backups/20260908102327`.
- Nine selected source/template/bundle/manifest files verified against release hashes.
- No database restore or unrelated working-tree changes were deployed.
- Requested code changes are complete. Live signed-in visual browser acceptance and
  sustained load/tail-latency testing were not performed. Network latency, concurrent
  workload and remaining data reads can still cause slow requests; the observed spikes
  have not been attributed to a specific cause.
