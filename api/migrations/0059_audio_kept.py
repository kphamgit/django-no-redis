# Audio.in_library is now Audio.kept: an audio chosen to keep (listed in searches, never deleted
# automatically), as opposed to a take nobody kept.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0058_delete_shadowingsentence"),
    ]

    operations = [
        migrations.RemoveIndex(model_name="audio", name="api_audio_in_libr_4d0c35_idx"),
        migrations.RenameField(model_name="audio", old_name="in_library", new_name="kept"),
        migrations.AddIndex(
            model_name="audio",
            index=models.Index(fields=["kept", "created_at"], name="api_audio_kept_created_idx"),
        ),
    ]
