import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("decision_rhythm", "0014_execution_link_transaction_source"),
        ("portfolio", "0002_transition_plan_evidence"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.AlterField(
                    model_name="executionapprovalrequestmodel",
                    name="transition_plan",
                    field=models.ForeignKey(
                        blank=True,
                        help_text="关联的账户级调仓计划",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="approval_requests",
                        to="portfolio.portfoliotransitionplanmodel",
                    ),
                ),
                migrations.DeleteModel(name="PortfolioTransitionPlanModel"),
            ],
        )
    ]

