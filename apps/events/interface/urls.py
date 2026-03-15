"""Events URL Configuration."""

from django.urls import include, path
from django.views.generic import RedirectView

app_name = 'events'

urlpatterns = [
    # 向后兼容重定向 (旧路由重定向到新路由)
    path('publish/', RedirectView.as_view(url='/api/events/publish/', permanent=False)),
    path('query/', RedirectView.as_view(url='/api/events/query/', permanent=False)),
    path('metrics/', RedirectView.as_view(url='/api/events/metrics/', permanent=False)),
    path('status/', RedirectView.as_view(url='/api/events/status/', permanent=False)),
    path('replay/', RedirectView.as_view(url='/api/events/replay/', permanent=False)),
    # Legacy API compatibility under /events/api/*
    path('api/', include(('apps.events.interface.api_urls', 'events_api'), namespace='legacy_events_api')),
]
