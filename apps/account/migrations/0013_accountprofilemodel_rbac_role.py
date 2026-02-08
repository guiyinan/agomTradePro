from django.db import migrations, models


def seed_rbac_roles(apps, schema_editor):
    AccountProfileModel = apps.get_model("account", "AccountProfileModel")
    User = apps.get_model("auth", "User")

    superuser_ids = set(
        User.objects.filter(is_superuser=True).values_list("id", flat=True)
    )

    for profile in AccountProfileModel.objects.all().only("id", "user_id", "rbac_role"):
        profile.rbac_role = "admin" if profile.user_id in superuser_ids else "owner"
        profile.save(update_fields=["rbac_role"])


class Migration(migrations.Migration):
    dependencies = [
        ("account", "0012_alter_investmentrulemodel_rule_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="accountprofilemodel",
            name="rbac_role",
            field=models.CharField(
                choices=[
                    ("admin", "管理员"),
                    ("owner", "所有者"),
                    ("analyst", "分析师"),
                    ("investment_manager", "投资经理"),
                    ("trader", "交易员"),
                    ("risk", "风控"),
                    ("read_only", "只读用户"),
                ],
                default="owner",
                help_text="系统统一角色（与 MCP 对齐）",
                max_length=32,
                verbose_name="RBAC角色",
            ),
        ),
        migrations.RunPython(seed_rbac_roles, migrations.RunPython.noop),
    ]
