# -*- coding: utf-8 -*-
import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings.development')
django.setup()

from apps.macro.infrastructure.models import MacroIndicator

print("=" * 60)
print("Checking macro data units")
print("=" * 60)

# Get unique codes
codes = MacroIndicator.objects.values('code').distinct().order_by('code')
print(f"\nTotal indicators: {codes.count()}")

for item in codes:
    code = item['code']
    latest = MacroIndicator.objects.filter(code=code).order_by('-reporting_period').first()
    if latest:
        print(f"\n{code}:")
        print(f"  Value: {latest.value}")
        print(f"  Unit: {latest.unit}")
        print(f"  Original Unit: {latest.original_unit}")
        print(f"  Period: {latest.reporting_period}")
