"""URL Configuration for AI Prompt Management."""

from django.urls import path
from django.views.generic import RedirectView

from .views import prompt_manage_view

app_name = 'prompt'

# URL模式
urlpatterns = [
    path("", RedirectView.as_view(url="/prompt/manage/", permanent=False), name="home"),
    # 页面路由
    path('manage/', prompt_manage_view, name='prompt-manage'),
]
