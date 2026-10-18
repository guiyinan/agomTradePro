# TUX10 frozen-02 shell review

Scope: read-only review of frozen-02 (`frozen-inputs.json` SHA `85c3f216637cf69a9102e7ee14b87e93d6f9fd6180513df2eb3bc799b0fe800d`). No QA, build, Django, DB, or Git command was run and no frozen input was modified.

## Findings

- `frontend/tui-workbench/src/38-task-focus-panels.js` matches the frozen raw SHA `c0f156019c587de030173b28dafb70b80ac7eaa565c430b78f9aa650991b356b`. The dashboard return handler keeps `skipCapture` and `skipRestoreAction`, and adds `preserveAction: true`; it therefore retains the already established `screen`/`action` URL while avoiding workspace snapshot replay.
- `frontend/tui-workbench/src/50-shell.js` matches the frozen raw SHA `f439e21d8afb86198d5a5b143e793a66433fefc672cb1181f4345f1861e41e2a` and remains 1457 lines. The fresh task-home guard runs before task-mode primary selection; professional focused action handling remains after the explicit operator-home check, and completed non-passive focused primaries stop before `nextPrimaryAction()` fallback. F9 task-home/dashboard paths focus visible main controls without un-hiding the professional action panel; only the professional fallback unhides the current action panel.
- `tests/component/test_tui_task_focus_browser.py` matches frozen raw SHA `432545f968bd2ce4ec3da2e9c64ed10f5e9fbf9c8216031415ea90811585d804`. The returned-facts journey records `returned_facts_count` after the intentional source return read (lines 695-696), then asserts no additional `recorded-facts` request after dashboard return (703), Back (707), or Forward (711), while retaining the source action query assertion (702, 710). This directly covers the repaired URL-preservation path and guards against source-read replay.

## Conclusion

No new P1/P2 blocker found in the reviewed JS or browser assertion scope. The remaining full Node/browser/inventory result is owned by the live frozen QA window; this review makes no pass claim for it.
