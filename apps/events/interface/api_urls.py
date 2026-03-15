"""Events API URL configuration."""

from django.urls import path
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.events.interface import views

app_name = "events_api"


class EventsApiRootView(APIView):
    def get(self, request):
        return Response(
            {
                "endpoints": {
                    "publish": "/api/events/publish/",
                    "query": "/api/events/query/",
                    "metrics": "/api/events/metrics/",
                    "status": "/api/events/status/",
                    "replay": "/api/events/replay/",
                }
            }
        )


urlpatterns = [
    path("", EventsApiRootView.as_view(), name="api-root"),
    path("publish/", views.EventPublishView.as_view(), name="publish"),
    path("query/", views.EventQueryView.as_view(), name="query"),
    path("metrics/", views.EventMetricsView.as_view(), name="metrics"),
    path("status/", views.EventBusStatusView.as_view(), name="status"),
    path("replay/", views.EventReplayView.as_view(), name="replay"),
]
