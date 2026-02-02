"""
Fix RSSHub routes for government sources
"""
import os
import sys
import django

# Fix encoding for Windows
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings.development')
django.setup()

from apps.policy.infrastructure.models import RSSSourceConfigModel

# Research findings for correct RSSHub routes:
# Based on research on GitHub RSSHub repository:
# - PBC: /pbc/fx (外汇公告)
# - CSRC: /csrc/zfxxgk_zdgk (政府信息公开)
# - MOF: /gov/mof/gss (关税文件)

# The correct routes are:
ROUTES_TO_FIX = {
    2: ('/pbc/fx', 'central_bank'),
    3: ('/csrc/zfxxgk_zdgk', 'csrc'),
    4: ('/gov/mof/gss', 'mof'),
}

print("=" * 100)
print("Current RSS Sources Configuration:")
print("=" * 100)
print("ID | Name | Category | Current Route | Status")
print("-" * 100)

for source in RSSSourceConfigModel.objects.all():
    print(f"{source.id} | {source.name} | {source.category} | {source.rsshub_route_path} | {source.last_fetch_status}")

print("\n" + "=" * 100)
print("Updating RSSHub routes:")
print("=" * 100)

for source_id, (new_route, category) in ROUTES_TO_FIX.items():
    try:
        source = RSSSourceConfigModel.objects.get(id=source_id)
        old_route = source.rsshub_route_path
        source.rsshub_route_path = new_route
        source.save()
        print(f"[OK] Updated ID {source_id} ({source.category}): {old_route} -> {new_route}")
    except RSSSourceConfigModel.DoesNotExist:
        print(f"[FAIL] Source ID {source_id} not found")

print("\n" + "=" * 100)
print("Verification - Updated Configuration:")
print("=" * 100)
print("ID | Name | Category | Updated Route | Status")
print("-" * 100)

for source_id in ROUTES_TO_FIX.keys():
    source = RSSSourceConfigModel.objects.get(id=source_id)
    print(f"{source.id} | {source.name} | {source.category} | {source.rsshub_route_path} | {source.last_fetch_status}")

print("\n" + "=" * 100)
print("Done! Please test RSS fetching at http://127.0.0.1:8000/policy/rss/manage/")
print("=" * 100)
