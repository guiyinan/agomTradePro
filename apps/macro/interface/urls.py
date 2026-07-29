"""URL configuration for Macro app."""

from django.http import HttpRequest, HttpResponseRedirect
from django.shortcuts import redirect
from django.urls import path

from . import views

app_name = "macro"


def macro_home_redirect(request: HttpRequest) -> HttpResponseRedirect:
    """Redirect root /macro/ to data page"""
    return redirect("macro:data")


urlpatterns = [
    # Root route - redirect to data page
    path("", macro_home_redirect, name="home"),
    path("data/", views.macro_data_view, name="data"),
    # 统一数据管理器
    path("controller/", views.data_controller_view, name="data_controller"),
]
