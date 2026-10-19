# ASH03 automatic ledger evidence

See `evidence.json` for snapshot scope and `raw-files.json` for byte-preserving copies. Counts overlap and are not added. Captured command/inputs/result paths intentionally retain their original locations; `raw-files.json` maps copies. Final generated OpenAPI outputs retain unrelated historical drift only in this evidence directory; delivered schemas use the bounded endpoint closure.

Four metadata JSON files use `digest_map_records_v1`: explicit path/digest records avoid treating public content hashes as API credentials. Their wrappers retain the original digest and JSON serialization settings. Decode records to mappings, serialize with those settings and verify `original_raw_sha256` to reproduce the exact original bytes. The raw index marks these four representations; other logs and JUnit remain unchanged. Original metadata is retained locally. Scanner rules and allowlists are unchanged.

The candidate Git object binds source checks, not a delivered commit or CI result. Final local security and new-commit remote CI are recorded after admission. No production or live-trading acceptance is implied.

Exact raw log/JUnit files listed in `raw-whitespace-preservation.json` retain process-generated trailing spaces and final blank lines through narrowly scoped Git whitespace attributes. They remain visible in diffs and secret scans. Source, tests, documents and other metadata keep normal whitespace checks; original data bytes/hashes are unchanged.
