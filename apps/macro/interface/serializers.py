"""
DRF Serializers for Macro Data API.
"""

from rest_framework import serializers

from apps.macro.infrastructure.models import MacroIndicator


class MacroIndicatorSerializer(serializers.ModelSerializer):
    """Serializer for MacroIndicator"""

    class Meta:
        model = MacroIndicator
        fields = '__all__'
