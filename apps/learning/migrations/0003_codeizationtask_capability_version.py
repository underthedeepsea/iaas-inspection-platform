from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("capabilities", "0002_initial"),
        ("learning", "0002_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="codeizationtask",
            name="capability_version",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="codeization_tasks",
                to="capabilities.capabilityversion",
            ),
        ),
    ]
