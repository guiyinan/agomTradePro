"""Pulse page views."""

from django.shortcuts import redirect
from django.views import View


class PulseIndexView(View):
    """Redirect the page entry to the API root until a dedicated page exists."""

    def get(self, request):
        return redirect("/api/pulse/")
