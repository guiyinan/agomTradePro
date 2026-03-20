from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("terminal", "0003_terminal_runtime_settings"),
    ]

    operations = [
        migrations.AddField(
            model_name="terminalruntimesettingsorm",
            name="fallback_chat_system_prompt",
            field=models.TextField(
                blank=True,
                default="",
                help_text="Terminal 与共享网页聊天在 fallback 普通对话时注入的系统提示词。可由管理员控制回答范围，例如系统状态、Regime、持仓、信号、回测、RSS 新闻、政策、热点、配置中心等。留空则使用系统默认提示词。",
            ),
        ),
    ]
