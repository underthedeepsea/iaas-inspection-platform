from django.db import migrations, models


DEFAULT_BODY = "用中文150字内给出结论、最多两条带ID的关键证据和一条核查建议。无历史数据不做对比。"


def seed_prompt(apps, schema_editor):
    Prompt = apps.get_model("investigations", "ExplanationPrompt")
    Prompt.objects.get_or_create(
        key="inspection-explanation",
        defaults={"name": "巡检解读", "body": DEFAULT_BODY, "revision": 1},
    )


class Migration(migrations.Migration):
    dependencies = [("investigations", "0006_investigation_result")]

    operations = [
        migrations.CreateModel(
            name="ExplanationPrompt",
            fields=[
                ("key", models.CharField(max_length=64, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=128)),
                ("body", models.TextField()),
                ("revision", models.PositiveIntegerField(default=1)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"db_table": "explanation_prompts"},
        ),
        migrations.RunPython(seed_prompt, migrations.RunPython.noop),
    ]
