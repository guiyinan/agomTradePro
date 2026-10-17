# Calendar preview key secrets candidate review

Review date: 2026-10-17
Scope: read-only review of the unstaged `shared/config/secrets.py` and
`tests/unit/shared/config/test_preview_key_secrets.py` candidate, plus actual
call sites. No production/test source, index, database, or governance files were
modified. No pytest suite was started.

## Verified behavior

- `get_secrets()` keeps `require_tushare_token=True` as its default. That path
  still calls the registered database loader first, falls back to environment
  values, and raises `OSError` if neither has a Tushare token
  (`shared/config/secrets.py:84-118,127-168`). Existing production callers found
  by search use the no-argument form; the new calendar preview-token caller is
  the only production call found with `require_tushare_token=False`
  (`apps/data_center/infrastructure/calendar_preview_token.py:248`).
- `require_tushare_token=False` returns `_load_from_env()` before the database
  branch. Its test registers a loader that raises, removes `TUSHARE_TOKEN`, and
  confirms the preview key is returned with an empty provider token
  (`shared/config/secrets.py:127-151`,
  `tests/unit/shared/config/test_preview_key_secrets.py:25-42`). This is a
  direct no-database-loader test, not just a missing-token assertion.
- The option requires `type(value) is bool`; the tests cover `0`, `1`, `None`,
  and a string (`shared/config/secrets.py:144-145`,
  `tests/unit/shared/config/test_preview_key_secrets.py:97-104`).
- The new `AppSecrets.field_encryption_key` is appended with default `None`,
  `repr=False`, and `compare=False` (`shared/config/secrets.py:33-39`). The
  constructor signature probe confirms the original first three positional
  fields remain in place. The test also checks equality with/without the new
  key and frozen-instance behavior (`tests/unit/shared/config/test_preview_key_secrets.py:81-94`).
- Default database precedence, environment fallback behavior already present
  in the legacy test suite, and the missing-token error remain represented by
  tests (`tests/unit/shared/config/test_preview_key_secrets.py:45-79`,
  `tests/unit/test_secrets_registry.py:44-97`).

## Review findings and integration risks

1. The added preview key is hidden from `AppSecrets` repr, but the nested
   provider credentials are not. `DataSourceSecrets` remains a normal
   dataclass with `tushare_token` and API-key fields and no `repr=False`
   (`shared/config/secrets.py:21-30`); `AppSecrets` repr includes that nested
   object. A one-process probe with synthetic values returned
   `repr exposes provider tokens: True, preview key: False`. The new test only
   asserts that `do-not-print` (the new preview key) is absent. This is
   pre-existing behavior, not introduced by this candidate. If the intended
   contract is that *all* secret values are absent from `repr(AppSecrets)`,
   that contract is not met and needs a separate scoped change.

2. Cache rotation is explicit, not automatic. The new test proves that after
   changing `AGOMTRADEPRO_ENCRYPTION_KEY`, the env-only mode continues returning
   the cached old key until `clear_secrets_cache()` is called; clear removes
   both cached entries (`shared/config/secrets.py:127,170-172`,
   `tests/unit/shared/config/test_preview_key_secrets.py:106-128`). Search found
   no production call to `clear_secrets_cache`; it is only defined here and
   used by tests. `register_database_secrets_loader()` also does not invalidate
   the cache (`shared/config/secrets.py:49-60`). Thus provider-secret or
   preview-key changes take effect after explicit cache clearing or process
   restart. The preview-token codec says it resolves the current secret “per
   call” (`apps/data_center/infrastructure/calendar_preview_token.py:108-113`),
   but `get_secrets(False)` is cached, so that wording should be understood as
   a getter call, not an uncached rotation check. The codec has no old-key ring;
   after rotation, old tokens cannot be decrypted once the new key is active.

3. Cache keys are call-shape-sensitive. `lru_cache(maxsize=2, typed=True)` gives
   `get_secrets()` and `get_secrets(require_tushare_token=True)` separate keys,
   even though both request the same logical default mode. A short isolated
   probe with synthetic env values showed: optional + implicit default gives
   `misses=2, currsize=2`; adding explicit `True` gives `misses=3`; requesting
   optional again gives `misses=4`, because the two-slot LRU evicted it. The
   current production search found no explicit-`True` caller, so this is a
   future integration hazard rather than a present caller failure. The new
   cache test covers optional and implicit default modes, but not this mixed
   call form (`tests/unit/shared/config/test_preview_key_secrets.py:106-128`).

## Conclusion

The env-only preview-key path, strict bool validation, legacy default behavior,
and backward-compatible `AppSecrets` constructor shape are supported by the
implementation and candidate tests. No current production call site was found
that explicitly passes `True`. The actionable review notes are the existing
nested-secret repr exposure, the need to clear/restart for key rotation, and
call-shape-sensitive cache entries if an explicit-`True` caller is added. No
runtime or pytest verification was performed for this read-only review.
