# Qlib Local Upload User Isolation

## Goal

- Local Qlib inference results can be uploaded to VPS.
- Personal uploads are visible to the uploader and admins.
- Admin uploads can be stored as system-level defaults.
- Read priority is personal cache first, then system cache.

## Implemented

- `AlphaScoreCacheModel` adds nullable `user` FK.
- Cache uniqueness includes `user`.
- `GET /api/alpha/scores/` reads personal cache first and supports admin `user_id`.
- `POST /api/alpha/scores/upload/` supports `scope=user|system`.
- SDK adds `alpha.upload_scores(...)`.
- `tools/qlib_uploader.py` uses the SDK and does not depend on Django.
- MCP adds `get_alpha_stock_scores(..., user_id=...)` and `upload_alpha_scores(...)`.

## Validation

- `python manage.py makemigrations alpha --check --dry-run`
- `python manage.py check`
- `pytest tests/unit/test_alpha_upload.py -v --create-db`
