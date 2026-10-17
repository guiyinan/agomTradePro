# Calendar preview token read-only review

Review scope: `apps/data_center/application/calendar_preview_token.py`,
`apps/data_center/infrastructure/calendar_preview_token.py`,
`shared/config/secrets.py`, `shared/infrastructure/crypto.py`,
`apps/data_center/application/calendar_publication_operations.py`, and
`tests/unit/data_center/test_calendar_preview_token.py`.

## Concrete finding: expiry is not independently bound to the source window

`CalendarPublicationPreview` retains `first_seen_at`, the contract TTL, and the
derived `response_expires_at` (`apps/data_center/application/calendar_publication_operations.py`,
around lines 375-430 and 822-881). The token content retains only
`previewed_at` and `response_expires_at`; its validation checks that expiry is
after preview time (`apps/data_center/application/calendar_preview_token.py`,
around lines 38-106). The encrypted payload carries the claimed expiry, and
decode only checks that the current time precedes that value
(`apps/data_center/infrastructure/calendar_preview_token.py`, around lines
270-284 and 220-237). There is no standalone check that the expiry equals the
original source-window expiry derived from `first_seen_at + configured TTL`.

The read-only reproduction starts with the unit fixture's 3,600-second
calendar-response TTL and 15-minute token expiry, replaces the expiry with two
days after preview, encodes it, and successfully decodes it one day later. The
successful command and raw output are in
`calendar-preview-token-review-ttl-repro-success.txt`; script:
`.tmp/calendar_preview_token_ttl_repro.py`. The first invocation log,
`calendar-preview-token-review-ttl-repro.txt`, records an import-path setup
failure before Django setup completed; the rerun supplied explicit `PYTHONPATH`
and produced the successful reproduction.

This is a pre-integration contract gap, not a demonstrated publication bypass:
the token codec has no production caller elsewhere in the current tree, and the
confirmation use case fresh-loads the source and recalculates the TTL before
publishing. Before wiring the codec, construct token content from the complete
server `CalendarPublicationPreview` and do not accept a client-supplied expiry.
Alternatively include the original `first_seen_at` and enough immutable
identity to recompute and validate the expiry. Preserve the separate token
shortening behavior if desired; it must never extend the source window.

## Other reviewed boundaries

- The decoder rejects missing/unsupported encryption prefixes before decrypt,
  so `FieldEncryptionService.decrypt`'s legacy unprefixed-plaintext behavior is
  not reachable through this codec.
- `_encryption_service()` calls `get_secrets(require_tushare_token=False)` and
  passes the returned key explicitly to `FieldEncryptionService`. That
  `get_secrets` branch returns environment secrets without database loading or
  settings fallback. Missing/invalid key handling is typed and fail-closed.
- The codec enforces exact nested key sets, duplicate-key rejection, strict
  primitive types, canonical dates/UTC timestamps, and plaintext/ciphertext
  size bounds. Unit tests cover present and absent CAS pointers plus actor,
  session, and alias binding.
- `get_secrets` is LRU-cached. The key-rotation test explicitly clears its
  cache; no production caller of `clear_secrets_cache()` was found. Rotation
  therefore depends on process restart or explicit cache clearing, and rolling
  workers can temporarily have different accepted keys. This is an operational
  compatibility property, not a bypass found in this review.
- No production call site for `CalendarPreviewTokenCodec` was found outside its
  own application/infrastructure modules and tests. Actor/session/alias inputs
  must come from future server-verified composition; the token itself is not
  authority.

## Verification limits

The targeted pytest invocation was started but stalled during project setup and
was interrupted; no pytest pass is claimed. The TTL reproduction is a standalone
Python process using `django.setup()` only to import project DTOs and codec. It
does not invoke ORM/repositories and makes no database query. No production
source was modified.
