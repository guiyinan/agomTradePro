"""Check current Regime data in database"""
import os

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings.development')
django.setup()

from apps.regime.infrastructure.models import RegimeLog

print("Current Regime data in database:")
print("-" * 60)
for r in RegimeLog.objects.all().order_by("-observed_at")[:15]:
    print(
        f"{r.observed_at}: {r.dominant_regime} ({r.confidence:.1%}) | "
        f"Z=[{r.growth_momentum_z:+.2f}, {r.inflation_momentum_z:+.2f}]"
    )
