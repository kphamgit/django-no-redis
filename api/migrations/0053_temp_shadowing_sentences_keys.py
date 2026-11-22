# The S3 folder audios/shadowing/ (dev/audios/shadowing/ locally) was renamed to
# audios/temp_shadowing_sentences/: point the takes' stored reference keys at the new folder.
from django.db import migrations
from django.db.models import F, Func, Value

OLD = "audios/shadowing/"
NEW = "audios/temp_shadowing_sentences/"


def _rename(apps, old, new):
    StudentShadowing = apps.get_model("api", "StudentShadowing")
    for root in ("", "dev/"):
        StudentShadowing.objects.filter(reference_s3_key__startswith=root + old).update(
            reference_s3_key=Func(F("reference_s3_key"), Value(root + old), Value(root + new), function="replace")
        )


def forwards(apps, schema_editor):
    _rename(apps, OLD, NEW)


def backwards(apps, schema_editor):
    _rename(apps, NEW, OLD)


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0052_question_audio"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
