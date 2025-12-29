"""
Django Admin for Policy Events.
"""

from django.contrib import admin
from apps.policy.infrastructure.models import PolicyLog


@admin.register(PolicyLog)
class PolicyLogAdmin(admin.ModelAdmin):
    """Admin interface for PolicyLog"""

    list_display = ['event_date', 'level', 'title', 'created_at']
    list_filter = ['level', 'event_date']
    search_fields = ['title', 'description']
    date_hierarchy = 'event_date'
