"""The audio endpoints (teachers only), under /english/audios/. See english/audio.py."""
from django.conf import settings
from django.db.models import ProtectedError
from django.http import HttpResponse
from rest_framework.decorators import api_view
from rest_framework.response import Response

from api.models import Audio
from .audio import (AUDIO_PREFIX, TtsInputError, check_library, create_audio, delete_audio,
                    delete_stray_file, existing_keys, keywords_from, maybe_delete_unused_audios,
                    read_audio, search_audios)
from .serializers import AudioSerializer


def _teachers_only(request):
    if not request.user.is_staff:
        return Response({"error": "Teachers only."}, status=403)
    return None


@api_view(["GET", "POST"])
def audios(request):
    """POST {text, provider ("google" | "elevenlabs" | "polly"), voice, speed?, made_for?}: generate
    a voice and keep it as a new audio (a question uses it once saved with its audio_id). 201 + the
    audio.
    GET: the kept audios. ?kept=0: the ones not kept instead; ?kept=all: both. ?q=words: only the
    ones whose text or keywords contain every word; ?made_for=shadowing|question: only that kind;
    ?prefer=shadowing|question: that kind first; ?check_files=1: add file_exists (whether its MP3
    is in S3) to each. At most 200, newest first."""
    denied = _teachers_only(request)
    if denied:
        return denied
    if request.method == "GET":
        params = request.query_params
        kept = {"all": None, "0": False, "false": False}.get(params.get("kept", "1"), True)
        rows = search_audios(params.get("q", ""), made_for=params.get("made_for"),
                             prefer=params.get("prefer"), kept=kept)
        data = AudioSerializer(rows, many=True).data
        if params.get("check_files") in ("1", "true"):
            keys = existing_keys()
            by_id = {row.id: row.s3_key for row in rows}
            for item in data:
                item["file_exists"] = by_id[item["id"]] in keys
        return Response(data)

    data = request.data
    try:
        audio = create_audio(
            data.get("text") or "",
            (data.get("provider") or "").strip().lower(),
            (data.get("voice") or "").strip(),
            data.get("speed"),
            created_by=request.user,
            made_for=data.get("made_for") or "question",
        )
    except TtsInputError as e:
        return Response({"error": str(e)}, status=400)
    except Exception as e:
        print("create_audio failed:", e)
        return Response({"error": f"Generating the voice failed: {e}"}, status=502)
    maybe_delete_unused_audios()
    return Response(AudioSerializer(audio).data, status=201)


@api_view(["GET"])
def audios_check(request):
    """GET /english/audios/check/: the S3 folder compared with the rows: {prefix, stray_files:
    [{key, url, size, last_modified}] (files no row points to, oldest first), missing_files:
    [audio] (rows whose file isn't in S3)}. Lists the whole folder, so pages run it on request."""
    denied = _teachers_only(request)
    if denied:
        return denied
    try:
        stray, missing = check_library()
    except Exception as e:
        print("audios_check failed:", e)
        return Response({"error": f"Checking the library against S3 failed: {e}"}, status=502)
    base = f"https://{settings.AWS_STORAGE_BUCKET_NAME}.s3.{settings.AWS_S3_REGION_NAME}.amazonaws.com/"
    return Response({
        "prefix": AUDIO_PREFIX,
        "stray_files": [{"key": f["key"], "url": base + f["key"], "size": f["size"],
                         "last_modified": f["last_modified"].isoformat()} for f in stray],
        "missing_files": AudioSerializer(missing, many=True).data,
    })


@api_view(["DELETE"])
def audio_stray_file(request):
    """DELETE /english/audios/stray/?key=<s3 key>: delete a library file no row points to (one the
    check listed). 409 if a row points to it (delete that audio instead). 204."""
    denied = _teachers_only(request)
    if denied:
        return denied
    try:
        deleted = delete_stray_file(request.query_params.get("key", ""))
    except ValueError as e:
        return Response({"error": str(e)}, status=400)
    except Exception as e:
        print("audio_stray_file failed:", e)
        return Response({"error": "The file couldn't be deleted from S3."}, status=502)
    if not deleted:
        return Response({"error": "An audio row points to this file: delete that audio instead."}, status=409)
    return Response(status=204)


@api_view(["PATCH", "DELETE"])
def audio_detail(request, pk):
    """PATCH {kept?, keywords?} (keywords: a list, or "a, b; c"): keep an audio for reuse (or stop
    keeping it, so the cleanup deletes it once no question uses it) and set its keywords. Returns the audio.
    DELETE: delete the audio (row and MP3) now. 409 if a question uses it."""
    denied = _teachers_only(request)
    if denied:
        return denied
    audio = Audio.objects.filter(pk=pk).first()
    if audio is None:
        return Response({"error": "No such audio."}, status=404)
    if request.method == "DELETE":
        try:
            delete_audio(audio)
        except ProtectedError:
            n = audio.questions.count()
            return Response({"error": f"{n} question{'s use' if n != 1 else ' uses'} this audio: "
                                      "remove it from them first."}, status=409)
        return Response(status=204)
    if "kept" in request.data:
        audio.kept = request.data["kept"] in (True, "true", "1", 1)
    if "keywords" in request.data:
        audio.keywords = keywords_from(request.data["keywords"])
    audio.save(update_fields=["kept", "keywords"])
    return Response(AudioSerializer(audio).data)


@api_view(["GET"])
def audio_file(request, pk):
    """The audio's MP3 itself, through Django: for pages that need the bytes (the Shadowing panel
    uses a kept audio as its reference and converts it to WAV), which a browser can't read from
    the S3 link because of CORS."""
    denied = _teachers_only(request)
    if denied:
        return denied
    audio = Audio.objects.filter(pk=pk).first()
    if audio is None:
        return Response({"error": "No such audio."}, status=404)
    try:
        body = read_audio(audio)
    except Exception as e:
        print("audio_file: can't read", audio.s3_key, e)
        return Response({"error": "The audio file couldn't be read from S3."}, status=502)
    return HttpResponse(body, content_type="audio/mpeg")
