# ASH03 security normalization static review 208

Reviewed `.tmp/normalize_ash03_evidence_208.py`, `.tmp/ash03-security-normalization-208/receipt.json`, all four artifact wrappers, their original `.tmp` JSON files and preserved copies, the raw-files index, and the outcome-interface test before/current source. This was read-only apart from this memo. No project import, scanner, test, QA, database, or Git command was run.

The four wrapped files decode losslessly with `digest_map_records_v1`. I independently decoded the explicit path/digest records, reconstructed each original JSON serialization from its recorded indentation, ASCII, newline, and trailing-newline settings, and compared the resulting bytes against the preserved originals. All four byte streams and original SHA-256 values match. The top-level original captures and `.tmp/ash03-security-normalization-208` copies are byte-identical:

| Artifact | Original SHA-256 | Wrapper SHA-256 | Digest records |
| --- | --- | --- | ---: |
| `ash03-auto-openapi-183/before.json` | `b9d2caa9b3ab288d0f5ecef22583096c0c55fad85fcc551fc0c164e7af53469a` | `f96ab7e1672bfef9b336bfe2b5c15e3035b69ca0da77753b95add62cc349c9fb` | 3 |
| `ash03-candidate-gates-203/candidate.json` | `7dc9757731ca97b7418f7c2bec93a8da79c9792c99c52f42ebe3240a433e6e63` | `3949cc0bca73e498229945a14bc1e5fe80c23a5a7bd4b96879cd8e4daf117314` | 68 |
| `ash03-candidate-gates-203/inputs.json` | `8e7a82bf42ec54d79b97716cac9386d67fe8c8fc85849d480512c0517f72bd69` | `19c90f9f9d0263ba57b8282a3ea5bae97448b139453c373ab4f6ace836face89` | 73 |
| `ash03-openapi-contract-red-192/inputs.json` | `46f229fb907e4c3989bc35a96dd019d04238057b94f4a3538c8707532ac7c616` | `47a111ba89edc96fe97275a5479e5bab9b9b7d4d19c20f8062e8aa815cce36f1` | 4 |

Each current wrapper hash also matches both its receipt entry and `artifacts/.../raw-files.json`. The index SHA-256 is `1c9c30994ed259ef83328cb57eb16ce9565f0b3ad115a7f0094857c48758fa79`.

The outcome-interface test preimage SHA-256 is `aae58d38af74d45cd4e12be528afd967b0114112fd939a85b3fbf5e10e9a6953`. The receipt postimage can be reconstructed exactly from the preimage by replacing only `outcome-default-scope-001` with `test-run-1` and `outcome-scope-unavailable-001` with `test-run-2`, then applying Windows CRLF newline translation; the reconstructed SHA-256 matches receipt value `86d1fafa8caabe3b8e2aa648e26693342d1de8d29e0ea255bb9f79514f2ac515`. AST comparison of the archived preimage and current test source, after normalizing those two `invocation_key` values, is identical. The assertions and test logic are unchanged. The current file SHA is `27ea725b642924364f7bb360489053265760f1342a1e603680460dabac2698fc`; it differs from the receipt postimage because the current file was later Black-formatted, as noted by Root.

Static review found no P1/P2 issue and no irreversible data loss. The script only writes the four artifact wrappers, their `.tmp` raw copies, artifact metadata/index files, and the two declared test literals; it does not modify scanner configuration, allowlists, or production source. The final scanner result remains for Root's separate verification; this review does not claim a clean rescan.

Review inputs: `.tmp/normalize_ash03_evidence_208.py` SHA-256 `094ab152fe0c4ccc3d349214c499639359efad68dac5dcd2272fefd65af7869f`; receipt SHA-256 `270e2f2a717bb77a6209221ae668587866261440de4018dad5e1b43de995c848`.
