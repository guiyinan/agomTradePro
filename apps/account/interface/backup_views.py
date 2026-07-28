from collections.abc import Mapping
from io import BytesIO
from pathlib import PurePath

from django.http import FileResponse, Http404, HttpRequest, HttpResponseBadRequest
from django.views.decorators.http import require_GET

from apps.account.application.interface_services import build_backup_download_payload

_MAX_BACKUP_TOKEN_LENGTH = 4096
_MAX_BACKUP_FILENAME_LENGTH = 255
_BACKUP_CONTENT_TYPE = "application/octet-stream"


def _valid_backup_token(token: object) -> str | None:
    """Return a bounded printable ASCII token before database or signing work."""

    if not isinstance(token, str) or not 1 <= len(token) <= _MAX_BACKUP_TOKEN_LENGTH:
        return None
    if not token.isascii() or any(character.isspace() for character in token):
        return None
    return token


def _validated_archive_payload(payload: object) -> tuple[bytes, str, str] | None:
    """Narrow the dynamic archive payload before constructing response headers."""

    if not isinstance(payload, Mapping):
        return None
    content = payload.get("content")
    filename = payload.get("filename")
    content_type = payload.get("content_type")
    if not isinstance(content, bytes) or not content:
        return None
    if (
        not isinstance(filename, str)
        or not 1 <= len(filename) <= _MAX_BACKUP_FILENAME_LENGTH
        or PurePath(filename).name != filename
        or "\r" in filename
        or "\n" in filename
    ):
        return None
    if content_type != _BACKUP_CONTENT_TYPE:
        return None
    return content, filename, content_type


@require_GET
def admin_db_backup_download_view(
    request: HttpRequest,
    token: str,
) -> FileResponse | HttpResponseBadRequest:
    normalized_token = _valid_backup_token(token)
    if normalized_token is None:
        raise Http404("备份链接无效或已过期")

    try:
        raw_archive: object = build_backup_download_payload(normalized_token)
    except LookupError as exc:
        raise Http404("备份链接无效或已过期") from exc
    except ValueError:
        return HttpResponseBadRequest("数据库备份邮件功能未启用")

    archive = _validated_archive_payload(raw_archive)
    if archive is None:
        raise Http404("备份文件不可用")
    content, filename, content_type = archive
    return FileResponse(
        BytesIO(content),
        as_attachment=True,
        filename=filename,
        content_type=content_type,
    )
