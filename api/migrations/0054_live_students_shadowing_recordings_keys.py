# The S3 folder audios/students_shadowing_recordings/ (dev/... locally) was renamed to
# audios/live_students_shadowing_recordings/: point the takes' stored recording keys at the new folder.
from django.db import migrations
from django.db.models import F, Func, Value

OLD = "audios/students_shadowing_recordings/"
NEW = "audios/live_students_shadowing_recordings/"


def _rename(apps, old, new):
    StudentShadowing = apps.get_model("api", "StudentShadowing")
    for root in ("", "dev/"):
        StudentShadowing.objects.filter(recording_s3_key__startswith=root + old).update(
            recording_s3_key=Func(F("recording_s3_key"), Value(root + old), Value(root + new), function="replace")
        )


def forwards(apps, schema_editor):
    _rename(apps, OLD, NEW)


def backwards(apps, schema_editor):
    _rename(apps, NEW, OLD)


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0053_temp_shadowing_sentences_keys"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
