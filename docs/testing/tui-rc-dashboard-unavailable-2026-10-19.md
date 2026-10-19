# TUI RC dashboard calendar-unavailable repair — 2026-10-19

The dashboard now handles the specific `MARKET_CALENDAR_UNAVAILABLE` data-fetch condition as an unavailable thermometer. Its score and observation time remain null, `score_available` is false and the no-decision flag stays true. Other data-fetch codes still propagate. The template shows unavailable 5/20-day values and preserves genuine numeric zero.

Fourteen focused unit tests passed. The isolated Phase 2 preview also passed the authenticated dashboard surface, dashboard navigation, main links and sidebar links: four cases in the shared H/I browser JUnit, not four additional cases for each patch. Incremental mypy, the unchanged debt ceiling, format checks, freshness contract and migration inventory passed. The independent revision-3 review and original evidence are included.

Source preview identity and clean Git blobs are recorded in the artifact package. The live data/calendar dependency still reported unavailable; this patch repairs the user-facing fallback, not that dependency. These selected results do not establish full RC/S6 or deployment readiness. No deployment, observation T0 or TUI-02 closure occurred.

Raw logs, JUnit, screenshots, original failure records and source snapshots are preserved in an independently verified local-machine archive. The compact index `tui-rc-dashboard-evidence-2026-10-19.json` records its exact path, SHA-256, input identity and check results. It has not been uploaded remotely; this source commit contains no raw evidence package.
