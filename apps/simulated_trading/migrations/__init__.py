"""
Data migration: assign a default system user to SimulatedAccountModel records
that have user=NULL.

Note: The field is kept nullable until use cases and domain mappers
consistently pass user. This migration handles existing legacy data.
"""

from django.conf import settings
from django.db import migrations


def assign_default_user(apps, schema_editor):
    """Assign existing null-user accounts to the first superuser or first user."""
    User = apps.get_model(
        settings.AUTH_USER_MODEL.split(".")[0],
        settings.AUTH_USER_MODEL.split(".")[1],
    )
    SimulatedAccountModel = apps.get_model(
        "simulated_trading", "SimulatedAccountModel"
    )

    null_accounts = SimulatedAccountModel.objects.filter(user__isnull=True)
    if not null_accounts.exists():
        return

    # Find or create a system user
    default_user = User.objects.filter(is_superuser=True).order_by("id").first()
    if not default_user:
        default_user = User.objects.order_by("id").first()
    if not default_user:
        # Create a system user if none exists
        default_user = User.objects.create(
            username="system",
            is_active=True,
            is_staff=True,
        )

    null_accounts.update(user=default_user)


def reverse_assign(apps, schema_editor):
    """Reverse: no-op, keep assigned users."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("simulated_trading", "0012_normalize_account_type_values"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(assign_default_user, reverse_assign),
    ]
