"""Pulse page views."""

from django.http import HttpRequest, HttpResponseRedirect
from django.shortcuts import redirect
from django.views import View


class PulseIndexView(View):
    """Redirect the page entry to the API root until a dedicated page exists."""

    def get(self, request: HttpRequest) -> HttpResponseRedirect:
        return redirect("/api/pulse/")
