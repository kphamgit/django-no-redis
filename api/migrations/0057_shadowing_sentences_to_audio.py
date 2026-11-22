# Each saved shadowing sentence (ShadowingSentence) becomes a library audio (Audio, made_for
# "shadowing"): its MP3 is copied inside the bucket to audios/library/<uuid>.mp3 (dev/... locally),
# where all audios live, and the row keeps the sentence's text, SSML, voice, speed, keywords,
# scoring options, author and date. A sentence whose file is missing from S3 is skipped (an audio
# must have its file). The old files stay where they are, to delete by hand.
import uuid

from django.conf import settings
from django.db import migrations

# The Shadowing panel saved its provider's full name; Audio keeps the provider's code.
PROVIDERS = {
    "elevenlabs": "elevenlabs",
    "google chirp 3 hd": "google",
    "google neural2": "google",
    "amazon polly": "polly",
}


def forwards(apps, schema_editor):
    import boto3
    from botocore.exceptions import ClientError

    ShadowingSentence = apps.get_model("api", "ShadowingSentence")
    Audio = apps.get_model("api", "Audio")
    rows = list(ShadowingSentence.objects.all())
    if not rows:
        return
    s3 = boto3.client(
        "s3",
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_S3_REGION_NAME,
    )
    bucket = settings.AWS_STORAGE_BUCKET_NAME
    prefix = f"{settings.SHADOWING_S3_ROOT}audios/library/"
    copied, skipped = 0, []
    for row in rows:
        new_key = f"{prefix}{uuid.uuid4()}.mp3"
        try:
            s3.copy_object(Bucket=bucket, Key=new_key, CopySource={"Bucket": bucket, "Key": row.s3_key},
                           ContentType="audio/mpeg", MetadataDirective="REPLACE")
        except ClientError as e:
            skipped.append(f"{row.id} ({e.response.get('Error', {}).get('Code')}: {row.s3_key})")
            continue
        tts = row.tts or {}
        provider = PROVIDERS.get(str(tts.get("provider") or "").strip().lower(), str(tts.get("provider") or "").lower())
        audio = Audio.objects.create(
            s3_key=new_key,
            text=row.sentence,
            tts_text=row.tts_text or "",
            provider=provider,
            voice=tts.get("voice") or "",
            speed=tts.get("speed"),
            in_library=True,
            keywords=row.keywords or [],
            made_for="shadowing",
            shadowing_options=row.options or {},
            created_by_id=row.created_by_id,
        )
        Audio.objects.filter(id=audio.id).update(created_at=row.created_at)  # auto_now_add on create
        copied += 1
    print(f"\n  Shadowing sentences -> library audios: {copied} copied, {len(skipped)} skipped"
          + (f" (file missing: {', '.join(skipped)})" if skipped else ""))


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0056_audio_made_for_shadowing_options"),
    ]

    # Not reversible: going back would need the old table, which the next migration drops.
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
