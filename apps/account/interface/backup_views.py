from io import BytesIO

from django.http import FileResponse, Http404, HttpResponseBadRequest
from django.views.decorators.http import require_GET

from apps.account.infrastructure.backup_service import (
    generate_backup_archive,
    validate_download_token,
)
from apps.account.infrastructure.models import SystemSettingsModel


@require_GET
def admin_db_backup_download_view(request, token: str):
    config = SystemSettingsModel.get_settings()
    max_age_seconds = max(config.backup_link_ttl_days, 1) * 86400

    try:
        payload = validate_download_token(token, max_age_seconds=max_age_seconds)
    except Exception as exc:
        raise Http404("备份链接无效或已过期") from exc

    if payload.get("settings_id") != config.pk or payload.get("email") != config.backup_email:
        raise Http404("备份链接无效")

    if not config.backup_enabled:
        return HttpResponseBadRequest("数据库备份邮件功能未启用")

    archive = generate_backup_archive(config)
    return FileResponse(
        BytesIO(archive.content),
        as_attachment=True,
        filename=archive.filename,
        content_type=archive.content_type,
    )
