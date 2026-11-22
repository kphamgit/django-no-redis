"""The audio library: the Audio table (api.models.Audio) and its MP3s in S3, which questions and the
live Shadowing exercise draw audio from. Same design as the p2p-voice-chat server's src/audio.ts.

An audio comes into existence through store_audio: a voice generated in a question form
(create_audio) or a sentence saved in the Shadowing panel. Questions point to audios by id and may
share one. An audio is kept for good once `kept` is set; one that isn't kept and that no question
uses (a discarded take, a form closed without saving) is deleted a day later.

The MP3s are public (the bucket policy grants s3:GetObject on audios/library/* and
dev/audios/library/*), at audios/library/<uuid>.mp3 (dev/audios/library/<uuid>.mp3 from a local
server, see SHADOWING_S3_ROOT), and never overwritten.

The rows are the source of truth: questions point to rows, and every write goes through them (file
then row to create, row then file to delete). check_library compares the folder with the rows, for
the rare drift: a file no row points to (a failed save or delete, a reset database) or a row whose
file is gone (deleted directly in S3). The cleanup deletes such stray files once they're a day old.
"""
import re
import time
import uuid
from datetime import timedelta

import boto3
from django.conf import settings
from django.db.models import Case, Count, IntegerField, Q, Value, When
from django.utils import timezone

from api.models import Audio

AUDIO_PREFIX = f"{settings.SHADOWING_S3_ROOT}audios/library/"  # dev/audios/library/ locally

# An audio unused for this long (no question, not kept) is deleted.
UNUSED_MAX_AGE = timedelta(days=1)

PROVIDERS = ("google", "elevenlabs", "polly")
MADE_FOR = ("question", "shadowing")


class TtsInputError(ValueError):
    """Bad input for text-to-speech (unknown provider or voice, no text): a 400, not a 502."""


def _s3():
    return boto3.client(
        "s3",
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_S3_REGION_NAME,
    )


def plain_text(text):
    """What an audio says, as students see it: any <tag> (SSML, ElevenLabs breaks) removed and
    spaces collapsed."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]*>", " ", str(text or ""))).strip()


def keywords_from(value):
    """"apology, average; question intonation" (or a list) -> lower-case, trimmed, no duplicates,
    at most 50 characters each."""
    items = value if isinstance(value, (list, tuple)) else re.split(r"[,;\n]", str(value or ""))
    keywords = []
    for item in items:
        k = re.sub(r"\s+", " ", str(item)).strip().lower()[:50]
        if k and k not in keywords:
            keywords.append(k)
    return keywords


def _speed(value, low, high):
    try:
        speed = float(value)
    except (TypeError, ValueError):
        return None
    return max(low, min(high, speed))


def synthesize(text, provider, voice, speed=None):
    """The MP3 bytes of `text` (plain, or SSML starting with <speak>) spoken by `voice`, and the
    speed actually used (clamped to the provider's range; None for normal). Uses the same clients
    as the google_tts, eleven_lab_tts and polly_tts endpoints. Raises TtsInputError for bad input."""
    text = (text or "").strip()
    if not text:
        raise TtsInputError("No text to speak.")
    if not voice:
        raise TtsInputError("Pick a voice.")

    if provider == "google":
        from google.cloud import texttospeech
        from english.views import _google_tts_client
        speed = _speed(speed, 0.25, 4.0)
        is_ssml = text.lower().startswith("<speak")
        resp = _google_tts_client().synthesize_speech(
            input=texttospeech.SynthesisInput(ssml=text) if is_ssml else texttospeech.SynthesisInput(text=text),
            voice=texttospeech.VoiceSelectionParams(language_code="en-US", name=voice),
            audio_config=texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.MP3, speaking_rate=speed or 1.0
            ),
        )
        return resp.audio_content, speed

    if provider == "elevenlabs":
        from elevenlabs import VoiceSettings
        from api.views import VOICES, eleven_client
        if voice not in VOICES:
            raise TtsInputError(f"Unknown ElevenLabs voice '{voice}'.")
        speed = _speed(speed, 0.7, 1.2)
        chunks = eleven_client.text_to_speech.convert(
            text=text,
            voice_id=VOICES[voice]["voice_id"],
            model_id="eleven_multilingual_v2",
            output_format="mp3_44100_128",
            voice_settings=VoiceSettings(speed=speed or 1.0),
        )
        return b"".join(chunk for chunk in chunks if chunk), speed

    if provider == "polly":
        from api.views import POLLY_REGION, POLLY_VOICES, _polly_ssml
        if voice not in POLLY_VOICES:
            raise TtsInputError(f"Unknown Polly voice '{voice}'.")
        speed = _speed(speed, 0.5, 1.0)
        polly = boto3.client(
            "polly",
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=POLLY_REGION,
        )
        resp = polly.synthesize_speech(
            Text=_polly_ssml(text, speed or 1.0), TextType="ssml", VoiceId=voice, Engine="neural", OutputFormat="mp3"
        )
        return resp["AudioStream"].read(), speed

    raise TtsInputError(f"Unknown provider '{provider}' (use one of: {', '.join(PROVIDERS)}).")


def store_audio(mp3, text, provider, voice, speed=None, created_by=None, *, made_for="question",
                kept=False, keywords=None, shadowing_options=None, shown_text=None):
    """Store an MP3 as a new audio: the file in S3 at audios/library/<uuid>.mp3, then its Audio row.
    `text` is what was spoken (plain, or the SSML / tagged text it was made from); shown_text, if
    given, is what students see (otherwise `text` without its markup)."""
    s3_key = f"{AUDIO_PREFIX}{uuid.uuid4()}.mp3"
    s3 = _s3()
    s3.put_object(Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=s3_key, Body=mp3, ContentType="audio/mpeg")
    text = (text or "").strip()
    plain = plain_text(text)
    try:
        return Audio.objects.create(
            s3_key=s3_key,
            text=plain_text(shown_text) if shown_text else plain,
            tts_text="" if text == plain else text,
            provider=provider,
            voice=voice,
            speed=None if speed in (None, 1.0) else speed,
            created_by=created_by if created_by and created_by.is_authenticated else None,
            made_for=made_for if made_for in MADE_FOR else "question",
            kept=kept,
            keywords=keywords_from(keywords),
            shadowing_options=shadowing_options or {},
        )
    except Exception:
        # Keep S3 and the table in step: no row, no file.
        try:
            s3.delete_object(Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=s3_key)
        except Exception:
            pass
        raise


def create_audio(text, provider, voice, speed=None, created_by=None, made_for="question"):
    """Speak `text` and keep it (store_audio). Raises TtsInputError for bad input; any other
    exception means the TTS provider, S3 or the database failed."""
    mp3, speed = synthesize(text, provider, voice, speed)
    return store_audio(mp3, text, provider, voice, speed, created_by, made_for=made_for)


def search_kept(query="", made_for=None, prefer=None, limit=200):
    """The kept audios (see search_audios): what the question forms and the Shadowing panel offer."""
    return search_audios(query, made_for, prefer, kept=True, limit=limit)


def search_audios(query="", made_for=None, prefer=None, kept=None, limit=200):
    """The audios whose text or keywords contain every word of `query`, newest first, each with
    question_count (how many questions use it). kept: True / False for only the kept / not kept
    ones, None for both; made_for: only that kind; prefer: that kind first (e.g. the Shadowing
    panel lists the shadowing sentences before the question audios)."""
    rows = Audio.objects.select_related("created_by").annotate(question_count=Count("questions"))
    if kept is not None:
        rows = rows.filter(kept=kept)
    for term in str(query or "").split():
        rows = rows.filter(Q(text__icontains=term) | Q(keywords__icontains=term))
    if made_for in MADE_FOR:
        rows = rows.filter(made_for=made_for)
    order = ["-created_at"]
    if prefer in MADE_FOR:
        rows = rows.annotate(preferred=Case(When(made_for=prefer, then=Value(0)), default=Value(1),
                                            output_field=IntegerField()))
        order.insert(0, "preferred")
    return rows.order_by(*order)[:limit]


def _library_objects():
    """Every file in the library folder (AUDIO_PREFIX): S3's dicts, with Key, Size, LastModified."""
    pages = _s3().get_paginator("list_objects_v2").paginate(
        Bucket=settings.AWS_STORAGE_BUCKET_NAME, Prefix=AUDIO_PREFIX)
    return [o for page in pages for o in page.get("Contents", [])]


def existing_keys():
    """The keys of the audio files in S3 (under AUDIO_PREFIX), to tell which rows lost their file."""
    return {o["Key"] for o in _library_objects()}


def check_library():
    """The library folder compared with the Audio rows: (stray_files, missing_files). stray_files:
    the files no row points to, oldest first, as {key, size, last_modified}; missing_files: the rows
    (with question_count) whose file isn't in the folder, newest first."""
    objects = _library_objects()
    file_keys = {o["Key"] for o in objects}
    row_keys = set(Audio.objects.filter(s3_key__startswith=AUDIO_PREFIX).values_list("s3_key", flat=True))
    stray = sorted(
        ({"key": o["Key"], "size": o["Size"], "last_modified": o["LastModified"]}
         for o in objects if o["Key"] not in row_keys),
        key=lambda f: f["last_modified"],
    )
    missing = (Audio.objects.filter(s3_key__startswith=AUDIO_PREFIX).exclude(s3_key__in=file_keys)
               .select_related("created_by").annotate(question_count=Count("questions"))
               .order_by("-created_at"))
    return stray, list(missing)


def delete_stray_file(key):
    """Delete a library file no row points to. Returns False (and deletes nothing) if a row points
    to it. Raises ValueError for a key outside the library folder."""
    name = key[len(AUDIO_PREFIX):] if key.startswith(AUDIO_PREFIX) else ""
    if not name or "/" in name:
        raise ValueError(f"key must be a file in {AUDIO_PREFIX}.")
    if Audio.objects.filter(s3_key=key).exists():
        return False
    _s3().delete_object(Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=key)
    return True


def read_audio(audio):
    """The MP3 bytes of an audio, from S3."""
    return _s3().get_object(Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=audio.s3_key)["Body"].read()


def delete_audio(audio):
    """Delete an audio no question uses: the row, then its file. Raises ProtectedError if a question
    uses it."""
    s3_key = audio.s3_key
    audio.delete()
    _s3().delete_object(Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=s3_key)


def _unused():
    return Audio.objects.filter(
        kept=False, created_at__lt=timezone.now() - UNUSED_MAX_AGE, questions__isnull=True
    )


def delete_unused_audios():
    """Delete the audios (rows and MP3s) that no question uses, aren't kept, and are more
    than a day old: voices generated in a form that was never saved, voices a regeneration replaced,
    and those of deleted questions. Returns how many were deleted."""
    rows = list(_unused().values_list("id", "s3_key"))
    if not rows:
        return 0
    ids = [r[0] for r in rows]
    # Rows first (only those still unused, in case one was just picked), then their files: a
    # leftover file is harmless, a row without its file isn't.
    _unused().filter(id__in=ids).delete()
    still_there = set(Audio.objects.filter(id__in=ids).values_list("id", flat=True))
    keys = [{"Key": key} for (i, key) in rows if i not in still_there]
    s3 = _s3()
    for start in range(0, len(keys), 1000):  # delete_objects takes at most 1000 keys
        s3.delete_objects(Bucket=settings.AWS_STORAGE_BUCKET_NAME,
                          Delete={"Objects": keys[start:start + 1000], "Quiet": True})
    print(f"🧹 Deleted {len(keys)} unused audio(s)")
    return len(keys)


# The stray-file cleanup deletes at most this many per run, so a wrong database (e.g. an empty one
# by mistake) can't wipe the folder in one go.
MAX_STRAY_DELETES = 200


def delete_stray_files():
    """Delete the library files no row points to that are more than a day old (younger ones may
    belong to a save still in progress). Does nothing while the Audio table is empty, which looks
    more like a wrong database than a folder of strays. Returns how many were deleted."""
    if not Audio.objects.exists():
        return 0
    stray, _missing = check_library()
    cutoff = timezone.now() - UNUSED_MAX_AGE
    old = [f["key"] for f in stray if f["last_modified"] < cutoff]
    keys = old[:MAX_STRAY_DELETES]
    # Check again right before deleting: a row may have just been made.
    taken = set(Audio.objects.filter(s3_key__in=keys).values_list("s3_key", flat=True))
    doomed = [{"Key": k} for k in keys if k not in taken]
    if doomed:
        _s3().delete_objects(Bucket=settings.AWS_STORAGE_BUCKET_NAME,
                             Delete={"Objects": doomed, "Quiet": True})
        left = len(old) - len(keys)
        print(f"🧹 Deleted {len(doomed)} stray library file(s)" + (f" ({left} left for the next run)" if left else ""))
    return len(doomed)


# The cleanup runs every so often while the server is used (each Generate voice checks), since
# there's no scheduler here; `python manage.py delete_unused_audios` runs it by hand or from
# Heroku Scheduler.
CLEANUP_EVERY_SECONDS = 6 * 60 * 60
_last_cleanup = 0.0


def maybe_delete_unused_audios():
    global _last_cleanup
    if time.monotonic() - _last_cleanup < CLEANUP_EVERY_SECONDS and _last_cleanup:
        return
    _last_cleanup = time.monotonic()
    try:
        delete_unused_audios()
        delete_stray_files()
    except Exception as e:  # never fail the request for this
        print("delete_unused_audios failed:", e)
