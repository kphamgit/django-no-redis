# The audio folder is now audios/library/ (dev/audios/library/ locally), the library that questions
# and the live Shadowing exercise draw audio from; it was question-audios/. Each audio still there
# is moved: its MP3 copied to the new folder, the row pointed at the copy, then the old file deleted.
# An audio whose file can't be copied (missing) is left as it is.
import re

from django.conf import settings
from django.db import migrations

OLD = re.compile(r"^((?:dev/)?)question-audios/([^/]+\.mp3)$")


def forwards(apps, schema_editor):
    import boto3
    from botocore.exceptions import ClientError

    Audio = apps.get_model("api", "Audio")
    rows = [(a, OLD.match(a.s3_key)) for a in Audio.objects.filter(s3_key__contains="question-audios/")]
    rows = [(a, m) for a, m in rows if m]
    if not rows:
        return
    s3 = boto3.client(
        "s3",
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_S3_REGION_NAME,
    )
    bucket = settings.AWS_STORAGE_BUCKET_NAME
    moved, failed = 0, []
    for audio, m in rows:
        old_key, new_key = audio.s3_key, f"{m.group(1)}audios/library/{m.group(2)}"
        try:
            s3.copy_object(Bucket=bucket, Key=new_key, CopySource={"Bucket": bucket, "Key": old_key},
                           ContentType="audio/mpeg", MetadataDirective="REPLACE")
        except ClientError as e:
            failed.append(f"{audio.id} ({e.response.get('Error', {}).get('Code')})")
            continue
        Audio.objects.filter(id=audio.id).update(s3_key=new_key)
        try:
            s3.delete_object(Bucket=bucket, Key=old_key)
        except ClientError:
            pass  # a leftover copy is harmless
        moved += 1
    print(f"\n  Audio files -> audios/library/: {moved} moved, {len(failed)} not moved"
          + (f" ({', '.join(failed)})" if failed else ""))


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0059_audio_kept"),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
