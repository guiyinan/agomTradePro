from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("filter", "0002_filterparameterconfigmodel"),
    ]

    operations = [
        migrations.AlterField(
            model_name="filterconfig",
            name="hp_lambda",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("129600"),
                help_text="HP 滤波 lambda 参数",
                max_digits=20,
            ),
        ),
        migrations.AlterField(
            model_name="filterconfig",
            name="kalman_level_variance",
            field=models.DecimalField(
                decimal_places=6,
                default=Decimal("0.05"),
                help_text="Kalman 水平方差",
                max_digits=20,
            ),
        ),
        migrations.AlterField(
            model_name="filterconfig",
            name="kalman_observation_variance",
            field=models.DecimalField(
                decimal_places=6,
                default=Decimal("0.5"),
                help_text="Kalman 观测方差",
                max_digits=20,
            ),
        ),
        migrations.AlterField(
            model_name="filterconfig",
            name="kalman_slope_variance",
            field=models.DecimalField(
                decimal_places=6,
                default=Decimal("0.005"),
                help_text="Kalman 斜率方差",
                max_digits=20,
            ),
        ),
        migrations.AddConstraint(
            model_name="filterconfig",
            constraint=models.CheckConstraint(
                condition=models.Q(("hp_lambda__gte", 0)),
                name="filter_config_hp_lambda_nonnegative",
            ),
        ),
        migrations.AddConstraint(
            model_name="filterconfig",
            constraint=models.CheckConstraint(
                condition=models.Q(("kalman_level_variance__gte", 0)),
                name="filter_config_level_variance_nonnegative",
            ),
        ),
        migrations.AddConstraint(
            model_name="filterconfig",
            constraint=models.CheckConstraint(
                condition=models.Q(("kalman_slope_variance__gte", 0)),
                name="filter_config_slope_variance_nonnegative",
            ),
        ),
        migrations.AddConstraint(
            model_name="filterconfig",
            constraint=models.CheckConstraint(
                condition=models.Q(("kalman_observation_variance__gt", 0)),
                name="filter_config_observation_variance_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="kalmanstatemodel",
            constraint=models.CheckConstraint(
                condition=models.Q(("level_variance__gte", 0)),
                name="kalman_state_level_variance_nonnegative",
            ),
        ),
        migrations.AddConstraint(
            model_name="kalmanstatemodel",
            constraint=models.CheckConstraint(
                condition=models.Q(("slope_variance__gte", 0)),
                name="kalman_state_slope_variance_nonnegative",
            ),
        ),
    ]
