"""Shadowing: the teacher sends a reference recording of a sentence (made with TTS in the
teacher's Shadowing section) to the students; each student records themselves repeating it,
and VoiceAnalyzer_Claude (~/Desktop/VoiceAnalyzer_Claude, FastAPI, POST /api/evaluate) scores the recording against
the reference: pronunciation, word stress, intonation and linking.

The exercise (sentence, reference S3 key, the teacher's scoring options) lives in Redis for a
day, so students can't change the options and the teacher can reload the results. Both the
prompt and each student's result go out on the Redis 'notifications' channel, which the
ws-server relays: the prompt to everyone, a result to the teacher only.
"""
import json
import os
import uuid

import boto3
import requests
from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone
from rest_framework.decorators import api_view

from english.utils import get_s3_audio_url

# VoiceAnalyzer_Claude's evaluate endpoint. Local testing: port 8001 (Django has 8000).
# Production: https://voice.tienganhtuyhoa.com/api/evaluate (Cloudflare Tunnel to the Mac),
# which requires VOICE_ANALYZER_API_KEY (the same key as VoiceAnalyzer_Claude's api_key.txt).
EVALUATE_URL = os.environ.get("VOICE_ANALYZER_EVALUATE_URL", "http://127.0.0.1:8001/api/evaluate")
EVALUATE_API_KEY = os.environ.get("VOICE_ANALYZER_API_KEY", "")

EXERCISE_TTL_SECONDS = 24 * 60 * 60
LATEST_KEY = "shadowing:latest"  # id of the most recently sent exercise


def _exercise_key(shadowing_id):
    return f"shadowing:{shadowing_id}"


def _results_key(shadowing_id):
    return f"shadowing:{shadowing_id}:results"  # hash: user_name -> latest result (JSON)


def _s3():
    return boto3.client(
        "s3",
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_S3_REGION_NAME,
    )


def _ratio(value, default):
    """A pitch threshold (share of the reference's movement), clamped to 0.1-1."""
    try:
        return max(0.1, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def _load_exercise(shadowing_id):
    raw = settings.R_CONN.get(_exercise_key(shadowing_id)) if shadowing_id else None
    return json.loads(raw) if raw else None


def _options_from(data):
    """The teacher's scoring options from a request's form fields."""
    return {
        "targeted_words": (data.get("targeted_words") or "").strip(),
        "strict_connected_speech": str(data.get("strict_connected_speech", "true")).lower() == "true",
        "fall_match_ratio": _ratio(data.get("fall_match_ratio"), 0.75),
        "rise_match_ratio": _ratio(data.get("rise_match_ratio"), 0.5),
    }


def _evaluate(sentence, options, reference_bytes, reference_name, recorded_bytes):
    """Scores a recording against the reference with VoiceAnalyzer_Claude.
    Returns (evaluation, None), or (None, a JsonResponse with the error)."""
    content_type = "audio/wav" if reference_name.endswith(".wav") else "audio/mpeg"
    try:
        res = requests.post(
            EVALUATE_URL,
            data={
                "spoken_text": sentence,
                "targeted_words": options["targeted_words"],
                "strict_connected_speech": "true" if options["strict_connected_speech"] else "false",
                "fall_match_ratio": str(options["fall_match_ratio"]),
                "rise_match_ratio": str(options["rise_match_ratio"]),
            },
            files={
                "reference_file": (reference_name, reference_bytes, content_type),
                "recorded_file": ("recording.wav", recorded_bytes, "audio/wav"),
            },
            headers={"X-API-Key": EVALUATE_API_KEY} if EVALUATE_API_KEY else {},
            timeout=120,
        )
    except requests.RequestException as e:
        print("shadowing: can't reach VoiceAnalyzer_Claude:", e)
        return None, JsonResponse({"error": "Can't reach the voice assessment server."}, status=502)

    try:
        evaluation = res.json()
    except ValueError:
        evaluation = None
    if not res.ok or evaluation is None:
        # FastAPI: {detail: "..."}, or a list of problems for a rejected request.
        detail = (evaluation or {}).get("detail") if isinstance(evaluation, dict) else None
        if isinstance(detail, list):
            detail = "; ".join(str(d.get("msg", d)) for d in detail)
        return None, JsonResponse(
            {"error": detail or f"The voice assessment failed ({res.status_code})."}, status=502
        )
    return evaluation, None


@api_view(["POST"])
def shadowing_send(request):
    """Teacher only. Multipart: reference_file (the TTS MP3), sentence, voice (label, for display),
    targeted_words, strict_connected_speech ("true"/"false"), fall_match_ratio, rise_match_ratio.
    Saves the reference to S3 and the exercise to Redis, then announces it to the students.
    Returns {shadowing_id, audio_url}."""
    if not request.user.is_staff:
        return JsonResponse({"error": "Teachers only."}, status=403)
    reference = request.FILES.get("reference_file")
    sentence = (request.data.get("sentence") or "").strip()
    if not reference or not sentence:
        return JsonResponse({"error": "A reference recording and its sentence are required."}, status=400)

    shadowing_id = uuid.uuid4().hex[:12]
    s3_key = f"audios/shadowing/{shadowing_id}.mp3"
    reference.seek(0)
    _s3().put_object(
        Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=s3_key, Body=reference, ContentType="audio/mpeg"
    )

    exercise = {
        "shadowing_id": shadowing_id,
        "sentence": sentence,
        "voice": request.data.get("voice", ""),
        "s3_key": s3_key,
        "sent_at": timezone.now().isoformat(),
        "options": _options_from(request.data),
    }
    settings.R_CONN.set(_exercise_key(shadowing_id), json.dumps(exercise), ex=EXERCISE_TTL_SECONDS)
    settings.R_CONN.set(LATEST_KEY, shadowing_id, ex=EXERCISE_TTL_SECONDS)

    audio_url = get_s3_audio_url(s3_key)
    settings.R_CONN.publish("notifications", json.dumps({
        "message_type": "shadowing_prompt",
        "user_name": request.user.username,
        "content": {"shadowing_id": shadowing_id, "sentence": sentence, "audio_url": audio_url},
    }))
    return JsonResponse({"shadowing_id": shadowing_id, "audio_url": audio_url})


@api_view(["POST"])
def shadowing_assess(request):
    """A student's attempt. Multipart: shadowing_id, recorded_file (16 kHz mono WAV).
    Sends the exercise's reference and this recording to VoiceAnalyzer_Claude with the teacher's
    options, keeps the result for the teacher and relays it to them, and returns
    VoiceAnalyzer_Claude's full reply to the student."""
    exercise = _load_exercise(request.data.get("shadowing_id"))
    if exercise is None:
        return JsonResponse({"error": "This shadowing exercise has expired."}, status=404)
    recorded = request.FILES.get("recorded_file")
    if not recorded:
        return JsonResponse({"error": "No recording was sent."}, status=400)

    reference_bytes = _s3().get_object(
        Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=exercise["s3_key"]
    )["Body"].read()
    evaluation, error = _evaluate(
        exercise["sentence"], exercise["options"], reference_bytes, "reference.mp3", recorded.read()
    )
    if error:
        return error

    user_name = request.user.username
    results_key = _results_key(exercise["shadowing_id"])
    previous = settings.R_CONN.hget(results_key, user_name)
    result = {
        "user_name": user_name,
        "shadowing_id": exercise["shadowing_id"],
        "attempt": (json.loads(previous)["attempt"] + 1) if previous else 1,
        "at": timezone.now().isoformat(),
        "evaluation": evaluation,
    }
    settings.R_CONN.hset(results_key, user_name, json.dumps(result))
    settings.R_CONN.expire(results_key, EXERCISE_TTL_SECONDS)
    settings.R_CONN.publish("notifications", json.dumps({
        "message_type": "shadowing_result",  # ws-server sends this to the teacher only
        "user_name": user_name,
        "content": result,
    }))
    return JsonResponse(evaluation)


@api_view(["GET"])
def shadowing_results(request):
    """Teacher only. The latest exercise (or ?shadowing_id=...) and each student's latest result:
    {exercise: {...} | null, results: [...]}. Lets the teacher's panel reload after a refresh."""
    if not request.user.is_staff:
        return JsonResponse({"error": "Teachers only."}, status=403)
    exercise = _load_exercise(request.GET.get("shadowing_id") or settings.R_CONN.get(LATEST_KEY))
    if exercise is None:
        return JsonResponse({"exercise": None, "results": []})
    raw = settings.R_CONN.hgetall(_results_key(exercise["shadowing_id"]))
    results = sorted((json.loads(v) for v in raw.values()), key=lambda r: r["user_name"])
    exercise["audio_url"] = get_s3_audio_url(exercise["s3_key"])
    return JsonResponse({"exercise": exercise, "results": results})


@api_view(["POST"])
def shadowing_test(request):
    """Teacher only: try the scoring yourself before (or without) sending to the students.
    Multipart: reference_file (the TTS MP3), recorded_file (16 kHz mono WAV), sentence, and the
    scoring options as in shadowing_send. Nothing is saved or relayed; returns the evaluation."""
    if not request.user.is_staff:
        return JsonResponse({"error": "Teachers only."}, status=403)
    reference = request.FILES.get("reference_file")
    recorded = request.FILES.get("recorded_file")
    sentence = (request.data.get("sentence") or "").strip()
    if not reference or not recorded or not sentence:
        return JsonResponse({"error": "A reference, a recording and the sentence are required."}, status=400)
    evaluation, error = _evaluate(
        sentence, _options_from(request.data), reference.read(), reference.name or "reference.mp3", recorded.read()
    )
    return error or JsonResponse(evaluation)
