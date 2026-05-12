"""
Ledger Migration Verification Script

Usage:
    python scripts/verify_ledger_migration.py

Checks:
  1. Count parity  — mapping table counts vs source/target table counts
  2. Field accuracy — spot-check 100 random migrated positions for field accuracy
  3. Total value    — aggregate market_value matches between source and target
  4. Orphaned maps  — mapping entries whose target_id no longer exists
  5. Unmapped       — active source records with no mapping entry

Run after `manage.py migrate_account_ledger` to confirm the migration is complete.
"""

import os
import random
import sys

import django

# Bootstrap Django
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.development")
django.setup()

from decimal import Decimal

from apps.account.infrastructure.models import PortfolioModel, TransactionModel
from apps.account.infrastructure.models import PositionModel as AccountPositionModel
from apps.simulated_trading.infrastructure.models import (
    LedgerMigrationMapModel,
    SimulatedAccountModel,
    SimulatedTradeModel,
)
from apps.simulated_trading.infrastructure.models import (
    PositionModel as SimPositionModel,
)

PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
WARN = "\033[93m⚠\033[0m"

issues = []

def check(label, ok, detail=""):
    if ok:
        print(f"  {PASS}  {label}")
    else:
        print(f"  {FAIL}  {label}" + (f": {detail}" if detail else ""))
        issues.append(label)


def warn(label, detail=""):
    print(f"  {WARN}  {label}" + (f": {detail}" if detail else ""))


# ── 1. Count parity ───────────────────────────────────────────────────────

print("\n[1] Count parity")

portfolio_count = PortfolioModel.objects.count()
portfolio_maps = LedgerMigrationMapModel.objects.filter(source_table="portfolio").count()
check(
    f"Portfolio maps ({portfolio_maps}/{portfolio_count})",
    portfolio_maps == portfolio_count,
    f"{portfolio_count - portfolio_maps} portfolios unmapped" if portfolio_maps < portfolio_count else "",
)

active_positions = AccountPositionModel.objects.filter(is_closed=False).count()
position_maps = LedgerMigrationMapModel.objects.filter(source_table="position").count()
check(
    f"Active position maps ({position_maps}/{active_positions})",
    position_maps >= active_positions,
    f"{active_positions - position_maps} positions unmapped" if position_maps < active_positions else "",
)

txn_count = TransactionModel.objects.count()
txn_maps = LedgerMigrationMapModel.objects.filter(source_table="transaction").count()
check(
    f"Transaction maps ({txn_maps}/{txn_count})",
    txn_maps >= txn_count,
    f"{txn_count - txn_maps} transactions unmapped" if txn_maps < txn_count else "",
)


# ── 2. Field accuracy spot-check ─────────────────────────────────────────

print("\n[2] Field accuracy (random sample of migrated positions)")

all_pos_maps = list(
    LedgerMigrationMapModel.objects.filter(source_table="position").values("source_id", "target_id")
)
sample = random.sample(all_pos_maps, min(100, len(all_pos_maps)))

field_ok = 0
field_fail = 0

for row in sample:
    try:
        src = AccountPositionModel.objects.get(pk=row["source_id"])
        tgt = SimPositionModel.objects.get(pk=row["target_id"])
    except Exception:
        field_fail += 1
        continue

    # Compare shares vs quantity (allow integer rounding)
    qty_ok = abs(tgt.quantity - int(round(src.shares))) <= 1
    # Compare avg_cost (allow 1% tolerance for blended merges)
    cost_ok = abs(float(tgt.avg_cost) - float(src.avg_cost)) / max(float(src.avg_cost), 0.0001) < 0.01
    # Compare asset_code
    code_ok = tgt.asset_code == src.asset_code

    if qty_ok and cost_ok and code_ok:
        field_ok += 1
    else:
        field_fail += 1
        issues.append(
            f"Position mismatch src={row['source_id']} tgt={row['target_id']}: "
            f"qty={'ok' if qty_ok else 'FAIL'} cost={'ok' if cost_ok else 'FAIL'} code={'ok' if code_ok else 'FAIL'}"
        )

check(
    f"Field accuracy ({field_ok}/{len(sample)} samples correct)",
    field_fail == 0,
    f"{field_fail} mismatches" if field_fail else "",
)


# ── 3. Total market value ─────────────────────────────────────────────────

print("\n[3] Aggregate market value comparison")

# Sum of active account positions
src_mv = AccountPositionModel.objects.filter(is_closed=False).aggregate(
    total=__import__("django.db.models", fromlist=["Sum"]).Sum("market_value")
)["total"] or Decimal("0")

# Sum of corresponding sim positions (via mapping)
target_ids = list(
    LedgerMigrationMapModel.objects.filter(source_table="position").values_list("target_id", flat=True)
)
tgt_mv = SimPositionModel.objects.filter(pk__in=target_ids).aggregate(
    total=__import__("django.db.models", fromlist=["Sum"]).Sum("market_value")
)["total"] or Decimal("0")

mv_diff = abs(src_mv - tgt_mv)
mv_pct = float(mv_diff / max(src_mv, Decimal("0.01"))) * 100

check(
    f"Market value delta < 1% (src={src_mv:.0f}, tgt={tgt_mv:.0f}, diff={mv_diff:.0f})",
    mv_pct < 1.0,
    f"{mv_pct:.2f}% deviation",
)


# ── 4. Orphaned mapping entries ────────────────────────────────────────────

print("\n[4] Orphaned mapping entries")

orphaned = 0
for row in LedgerMigrationMapModel.objects.filter(target_table="simulated_position").values("target_id"):
    if not SimPositionModel.objects.filter(pk=row["target_id"]).exists():
        orphaned += 1

check(f"No orphaned position maps ({orphaned} found)", orphaned == 0, f"{orphaned} orphans")

for row in LedgerMigrationMapModel.objects.filter(target_table="simulated_account").values("target_id"):
    if not SimulatedAccountModel.objects.filter(pk=row["target_id"]).exists():
        orphaned += 1

check(f"No orphaned account maps ({orphaned} total)", orphaned == 0)


# ── 5. Unmapped active records ─────────────────────────────────────────────

print("\n[5] Unmapped active source records")

mapped_portfolio_ids = set(
    LedgerMigrationMapModel.objects.filter(source_table="portfolio").values_list("source_id", flat=True)
)
unmapped_portfolios = PortfolioModel.objects.exclude(pk__in=mapped_portfolio_ids).count()
check(f"All portfolios mapped ({unmapped_portfolios} unmapped)", unmapped_portfolios == 0)

mapped_pos_ids = set(
    LedgerMigrationMapModel.objects.filter(source_table="position").values_list("source_id", flat=True)
)
unmapped_pos = AccountPositionModel.objects.filter(is_closed=False).exclude(pk__in=mapped_pos_ids).count()
check(f"All active positions mapped ({unmapped_pos} unmapped)", unmapped_pos == 0)


# ── Summary ────────────────────────────────────────────────────────────────

print("\n" + "=" * 60)
if not issues:
    print(f"{PASS} All checks passed — migration is consistent.")
else:
    print(f"{FAIL} {len(issues)} check(s) failed:")
    for i, issue in enumerate(issues, 1):
        print(f"  {i}. {issue}")
print("=" * 60)
sys.exit(0 if not issues else 1)
