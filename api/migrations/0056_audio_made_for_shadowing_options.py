from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0054_live_students_shadowing_recordings_keys"),
    ]

    operations = [
        migrations.AddField(
            model_name="audio",
            name="made_for",
            field=models.CharField(choices=[("question", "Question"), ("shadowing", "Shadowing")],
                                   default="question", max_length=20),
        ),
        migrations.AddField(
            model_name="audio",
            name="shadowing_options",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
