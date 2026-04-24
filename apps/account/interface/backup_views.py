from io import BytesIO

from django.http import FileResponse, Http404, HttpResponseBadRequest
from django.views.decorators.http import require_GET

from apps.account.application.interface_services import build_backup_download_payload


@require_GET
def admin_db_backup_download_view(request, token: str):
    try:
        archive = build_backup_download_payload(token)
    except LookupError as exc:
        raise Http404("备份链接无效或已过期") from exc
    except ValueError:
        return HttpResponseBadRequest("数据库备份邮件功能未启用")

    return FileResponse(
        BytesIO(archive["content"]),
        as_attachment=True,
        filename=archive["filename"],
        content_type=archive["content_type"],
    )
