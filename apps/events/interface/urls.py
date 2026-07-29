"""Events page URL configuration.

This module intentionally exposes no page-level compatibility routes.
Canonical event bus access is under /api/events/.
"""

from django.urls import URLPattern, URLResolver

app_name = "events"

urlpatterns: list[URLPattern | URLResolver] = []
