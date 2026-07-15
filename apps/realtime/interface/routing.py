"""ASGI routes for realtime price delivery."""

from django.urls import path

from apps.realtime.interface.consumers import RealtimePriceConsumer

websocket_urlpatterns = [
    path("ws/realtime/prices/", RealtimePriceConsumer.as_asgi()),
]
