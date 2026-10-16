# Calendar Workbench Scope Native Component Candidate

This candidate adds one component test file only:

- `tests/component/data_center/test_calendar_workbench_scope.py`
- SHA-256: `FB3B9DDE22114D171437F5AB9F7156DD6C7A9E76F665C5527AF6E3F4B40CDF7D`

The test uses the full Django app registry, an isolated schema for the four configuration tables plus an empty canonical-pointer table, and the real scope composition/repository/selector. It covers safe metadata selection without provider/secret/RPC calls, missing and ambiguous active metadata including an active NULL-TTL version, a missing current pointer, and caller-owned atomic/autocommit rejection before configuration reads. It does not access PostgreSQL, external providers, or secrets. No production file changed.

The final local SQLite command was run with the project venv and explicit non-PostgreSQL skip. It reported `7 skipped in 0.59s`; this is not Native PostgreSQL acceptance. Raw output: `calendar-workbench-scope-native-component-sqlite-skip.txt`.

Black, isort, and Ruff passed against the final test source. Raw outputs are `calendar-workbench-scope-native-component-black-check.txt`, `calendar-workbench-scope-native-component-isort-check.txt`, and `calendar-workbench-scope-native-component-ruff-check.txt`. Isort emits no text on success, so its file is empty with exit status 0.

Before the Native-only skip was added, two SQLite attempts exposed an environment schema mismatch: the existing test database table `data_center_dataset_contract` lacked the current ORM column `execution_freshness_seconds`. Each attempt reported 5 failed and 2 passed; this was fixture database shape, not a business-contract failure. The first run and the `--create-db` reproduction are retained as `calendar-workbench-scope-sqlite-schema-mismatch-red.txt` and `calendar-workbench-scope-sqlite-create-db-schema-mismatch-red.txt`.

Three prior artifacts with colliding names were overwritten before I checked the directory: `calendar-workbench-scope-black-final.txt`, `calendar-workbench-scope-ruff-final.txt`, and `calendar-workbench-scope-sqlite-final-skip.txt`. `git ls-files` found none of those paths tracked, and a filename search found no separate copies, so their prior bytes are unavailable. Current outputs were copied to the unique `calendar-workbench-scope-native-component-*` paths above. The previous `calendar-workbench-scope-isort-final.txt` was also written; both its prior observed size and current size were zero bytes.

Native PostgreSQL execution is reserved for the parent agent. No Native result is claimed here.
