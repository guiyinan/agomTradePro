"""
URL configuration for Signal app.
"""
from django.urls import path
from . import views


app_name = 'signal'


urlpatterns = [
    path('manage/', views.signal_manage_view, name='manage'),
]
