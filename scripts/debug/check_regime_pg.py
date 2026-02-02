"""Check current Regime data in PostgreSQL database"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings.development')
django.setup()

from apps.regime.infrastructure.models import RegimeLog
from django.db import connection

print("=" * 60)
print("数据库连接信息:")
print("-" * 60)
print(f"Engine: {connection.settings_dict['ENGINE']}")
print(f"Name: {connection.settings_dict['NAME']}")
print(f"Host: {connection.settings_dict['HOST']}")
print(f"Port: {connection.settings_dict['PORT']}")
print(f"User: {connection.settings_dict['USER']}")

print("\n" + "=" * 60)
print("Regime 数据库中的记录:")
print("-" * 60)
count = RegimeLog.objects.count()
print(f"总记录数: {count}")

if count > 0:
    print("\n最新 15 条记录:")
    for r in RegimeLog.objects.all().order_by("-observed_at")[:15]:
        print(
            f"{r.observed_at}: {r.dominant_regime} ({r.confidence:.1%}) | "
            f"Z=[{r.growth_momentum_z:+.2f}, {r.inflation_momentum_z:+.2f}]"
        )
else:
    print("数据库中没有 Regime 记录！")
