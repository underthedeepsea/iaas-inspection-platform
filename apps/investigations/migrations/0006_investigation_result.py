from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("investigations", "0005_alter_conversation_context_type")]

    operations = [
        migrations.AddField(
            model_name="investigation",
            name="result",
            field=models.JSONField(default=dict),
        ),
    ]
