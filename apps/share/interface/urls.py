"""Share page URL configuration."""
from django.urls import path

from apps.share.interface.views import (
    PublicSharePageView,
    refresh_share_link_page,
    revoke_share_link_page,
    share_disclaimer_manage_page,
    share_manage_page,
)

app_name = "share"

urlpatterns = [
    path("share/manage/", share_manage_page, name="manage"),
    path("share/manage/disclaimer/", share_disclaimer_manage_page, name="manage_disclaimer"),
    path("share/manage/<int:share_link_id>/edit/", share_manage_page, name="edit"),
    path("share/manage/<int:share_link_id>/revoke/", revoke_share_link_page, name="revoke"),
    path("share/manage/<int:share_link_id>/refresh/", refresh_share_link_page, name="refresh"),
    path(
        "share/<str:short_code>/",
        PublicSharePageView.as_view(),
        name="public_share",
    ),
]
