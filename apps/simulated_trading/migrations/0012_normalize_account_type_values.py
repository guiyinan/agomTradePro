from django.db import migrations


def normalize_account_type_values(apps, schema_editor):
    SimulatedAccountModel = apps.get_model("simulated_trading", "SimulatedAccountModel")
    SimulatedAccountModel.objects.filter(account_type="SIMULATED").update(account_type="simulated")
    SimulatedAccountModel.objects.filter(account_type="REAL").update(account_type="real")


def noop_reverse(apps, schema_editor):
    # Keep normalized values on rollback.
    return


class Migration(migrations.Migration):

    dependencies = [
        ("simulated_trading", "0011_alter_positionmodel_unrealized_pnl_and_more"),
    ]

    operations = [
        migrations.RunPython(normalize_account_type_values, noop_reverse),
    ]
