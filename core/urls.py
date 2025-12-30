"""
URL configuration for AgomSAAF project.
"""
from django.contrib import admin
from django.urls import path, include
from django.shortcuts import render
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView


def index_view(request):
    """首页视图"""
    return render(request, 'index.html')


def health_view(request):
    """健康检查"""
    from django.http import JsonResponse
    return JsonResponse({'status': 'healthy'})


def chat_example_view(request):
    """聊天组件示例页面"""
    return render(request, 'components/chat_example.html')


urlpatterns = [
    path('', index_view, name='index'),
    path('health/', health_view, name='health'),
    path('chat-example/', chat_example_view, name='chat-example'),
    path('admin/', admin.site.urls),
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),

    # Page routes
    path('regime/', include('apps.regime.interface.urls')),
    path('macro/', include('apps.macro.interface.urls')),
    path('filter/', include('apps.filter.interface.urls')),
    path('signal/', include('apps.signal.interface.urls')),
    path('ai/', include('apps.ai_provider.interface.urls')),
    path('prompt/', include('apps.prompt.interface.urls')),
]
