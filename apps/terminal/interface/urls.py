"""
Terminal Page URL Configuration.

页面路由配置。
"""

from django.urls import path

from .views import terminal_config_view, terminal_view

app_name = 'terminal'


urlpatterns = [
    path('', terminal_view, name='terminal'),
    path('config/', terminal_config_view, name='terminal-config'),
]
