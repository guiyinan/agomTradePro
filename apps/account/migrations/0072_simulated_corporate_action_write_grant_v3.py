"""Extend the fixed grant ledger constraint for explicit V3 capability records."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("account", "0071_simulated_corporate_action_grant_capabilities"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="simulatedcorporateactionwritegrantmodel",
            name="acct_scawg_fixed_ck",
        ),
        migrations.AddConstraint(
            model_name="simulatedcorporateactionwritegrantmodel",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    owner="account",
                    artifact_type="simulated_corporate_action_write_grant",
                    service_actor_id="simulated-trading",
                    status="active",
                    account_namespace="simulated",
                )
                & (
                    models.Q(
                        schema="account.simulated_corporate_action_write_grant.v1",
                        permission="simulated_corporate_action_stage_write",
                        capabilities__isnull=True,
                        terms_version__isnull=True,
                        terms_sha256__isnull=True,
                    )
                    | models.Q(
                        schema="account.simulated_corporate_action_write_grant.v2",
                        permission="simulated_corporate_action_capability_bundle",
                        capabilities__isnull=False,
                        terms_version__isnull=False,
                        terms_version__gt="",
                        terms_sha256__isnull=False,
                        terms_sha256__regex=r"^[0-9a-f]{64}$",
                    )
                    | models.Q(
                        schema="account.simulated_corporate_action_write_grant.v3",
                        permission="simulated_corporate_action_capability_bundle_v3",
                        capabilities__isnull=False,
                        terms_version__isnull=False,
                        terms_version__gt="",
                        terms_sha256__isnull=False,
                        terms_sha256__regex=r"^[0-9a-f]{64}$",
                    )
                ),
                name="acct_scawg_fixed_ck",
            ),
        ),
    ]
