"""URL Configuration for AI Prompt Management."""

from django.urls import include, path

from .views import prompt_manage_view

app_name = 'prompt'

# URL模式
urlpatterns = [
    # 页面路由
    path('manage/', prompt_manage_view, name='prompt-manage'),
    # Legacy API compatibility under /prompt/api/*
    path('api/', include(('apps.prompt.interface.api_urls', 'prompt_api'), namespace='legacy_prompt_api')),
]
