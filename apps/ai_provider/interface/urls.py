"""URL Configuration for AI Provider Management."""

from django.urls import path

from . import views

app_name = "ai_provider"

urlpatterns = [
    path("", views.page_views.ai_manage_view, name="manage"),
    path("me/", views.page_views.ai_my_providers_view, name="my-providers"),
    path("quotas/", views.page_views.ai_user_quota_manage_view, name="quota-manage"),
    path("logs/", views.page_views.ai_usage_logs_view, name="logs"),
    path("detail/<int:provider_id>/", views.page_views.ai_provider_detail_view, name="detail"),
    path("detail/<int:provider_id>/edit/", views.page_views.ai_provider_edit_view, name="edit"),
]
