"""URL Configuration for AI Prompt Management."""

from django.urls import path

from .views import prompt_manage_view

app_name = 'prompt'

# URL模式
urlpatterns = [
    # 页面路由
    path('manage/', prompt_manage_view, name='prompt-manage'),
]
