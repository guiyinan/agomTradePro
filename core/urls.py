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


urlpatterns = [
    path('', index_view, name='index'),
    path('admin/', admin.site.urls),
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),

    # Page routes
    path('regime/', include('apps.regime.interface.urls')),
    path('macro/', include('apps.macro.interface.urls')),
    path('signal/', include('apps.signal.interface.urls')),
    path('ai/', include('apps.ai_provider.interface.urls')),

    # API routes (to be added)
    # path('api/regime/', include('apps.regime.interface.urls')),
    # path('api/signal/', include('apps.signal.interface.urls')),
]
