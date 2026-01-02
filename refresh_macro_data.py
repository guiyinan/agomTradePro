# -*- coding: utf-8 -*-
"""
Temp script to force refresh macro data
"""
import os
import sys
import django

# Fix encoding for Windows console
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings.development')
django.setup()

from apps.macro.infrastructure.models import MacroIndicator
from apps.macro.application.use_cases import SyncMacroDataUseCase, SyncMacroDataRequest
from apps.macro.infrastructure.adapters.akshare_adapter import AKShareAdapter
from apps.macro.infrastructure.repositories import DjangoMacroRepository
from datetime import date, timedelta

def main():
    print("=" * 60)
    print("Force refresh macro data")
    print("=" * 60)

    # 1. Count before deletion
    total_before = MacroIndicator.objects.count()
    codes_count = MacroIndicator.objects.values('code').distinct().count()
    print(f"\nBefore: {total_before} records, {codes_count} indicators")

    # 2. Delete all existing data
    print("\nDeleting existing data...")
    MacroIndicator.objects.all().delete()
    print("[OK] All macro data deleted")

    # 3. Re-sync data
    print("\nStarting re-sync...")

    # Create adapter and repository
    adapter = AKShareAdapter()
    repository = DjangoMacroRepository()
    sync_use_case = SyncMacroDataUseCase(repository, adapters={'akshare': adapter})

    # Set sync parameters (last 5 years)
    end_date = date.today()
    start_date = end_date - timedelta(days=365 * 5)

    # Default indicator list
    indicators = sync_use_case._get_default_indicators()

    print(f"Date range: {start_date} to {end_date}")
    print(f"Indicators: {len(indicators)}")

    # Execute sync
    request = SyncMacroDataRequest(
        start_date=start_date,
        end_date=end_date,
        indicators=indicators,
        force_refresh=True
    )

    response = sync_use_case.execute(request)

    # 4. Show results
    print("\n" + "=" * 60)
    print("Sync complete!")
    print(f"Synced: {response.synced_count} records")
    print(f"Skipped: {response.skipped_count} records")
    if response.errors:
        print(f"Errors: {len(response.errors)}")
        for err in response.errors[:5]:
            print(f"  - {err}")
    print("=" * 60)

    # 5. Count after sync
    total_after = MacroIndicator.objects.count()
    codes_after = MacroIndicator.objects.values('code').distinct().count()
    print(f"\nAfter: {total_after} records, {codes_after} indicators")

if __name__ == '__main__':
    main()
