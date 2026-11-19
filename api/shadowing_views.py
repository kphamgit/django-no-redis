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
import re
import uuid
from concurrent.futures import ThreadPoolExecutor

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

def _clean_sentence(text):
    """The sentence without TTS markup such as ElevenLabs' <break time="0.4s" /> (any <...>
    tag): students see, and are scored on, only the words."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]*>", " ", text or "")).strip()


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


def _tolerance(value, default):
    """The linking tolerance (a multiplier, 1 = the analyzer's original limits), clamped to 0.5-3."""
    try:
        return max(0.5, min(3.0, float(value)))
    except (TypeError, ValueError):
        return default


def _load_exercise(shadowing_id):
    raw = settings.R_CONN.get(_exercise_key(shadowing_id)) if shadowing_id else None
    return json.loads(raw) if raw else None


def _tts_from(data):
    """How the reference was made, from the form fields tts_provider, tts_voice, tts_speed (the
    speed sent to the TTS engine; blank when SSML set it) and tts_ssml_rate (the SSML's
    <prosody rate>, if any)."""
    try:
        speed = float(data.get("tts_speed")) if data.get("tts_speed") not in (None, "") else None
    except (TypeError, ValueError):
        speed = None
    return {
        "provider": data.get("tts_provider") or None,  # e.g. "ElevenLabs"
        "voice": data.get("tts_voice") or None,        # e.g. "Matilda"
        "speed": speed,                                # e.g. 0.7
        "ssml_rate": data.get("tts_ssml_rate") or None,  # e.g. "slow"
    }


def _options_from(data):
    """The teacher's scoring options from a request's form fields."""
    return {
        "targeted_words": (data.get("targeted_words") or "").strip(),
        "strict_connected_speech": str(data.get("strict_connected_speech", "true")).lower() == "true",
        "fall_match_ratio": _ratio(data.get("fall_match_ratio"), 0.75),
        "rise_match_ratio": _ratio(data.get("rise_match_ratio"), 0.5),
        "link_tolerance": _tolerance(data.get("link_tolerance"), 1.0),
        # Word Syllables Stress Check: the multi-syllable words to check (required by send and test)
        # and how much of the reference's stressed/unstressed contrast the student must reach.
        "stress_words": (data.get("stress_words") or "").strip(),
        "stress_contrast_ratio": _ratio(data.get("stress_contrast_ratio"), 0.6),
        # Melody of each stress word: the shape similarity needed for "Same melody" (0.1-0.9).
        "melody_min_similarity": max(0.1, min(0.9, _ratio(data.get("melody_min_similarity"), 0.35))),
        # Which syllable should be stressed: "dictionary" (CMU, the reference audio as fallback,
        # e.g. at the end of a Yes/No question) or "reference" (the reference audio).
        "stress_source": "reference" if data.get("stress_source") == "reference" else "dictionary",
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
                # Exercises sent before this option existed don't have it.
                "link_tolerance": str(options.get("link_tolerance", 1.0)),
                "stress_words": options.get("stress_words", ""),
                "stress_contrast_ratio": str(options.get("stress_contrast_ratio", 0.6)),
                "melody_min_similarity": str(options.get("melody_min_similarity", 0.35)),
                "stress_source": options.get("stress_source", "dictionary"),
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
    _add_hyphenation(evaluation)
    _add_cmu_arpabet(evaluation)
    return evaluation, None


def _add_cmu_arpabet(evaluation):
    """Adds "cmu_arpabet": each word of the sentence with its CMU dictionary ARPAbet and the
    dictionary's own stress digits (1 = primary, 2 = secondary, 0 = unstressed), e.g.
    {"word": "basketball", "arpabet": "B AE1 S K AH0 T B AO2 L"} (arpabet None if not in the
    dictionary). The analyzer renumbers the digits (3/1/0) and unstresses function words, so the
    teacher's Sounds row shows these instead. Same cmudict package and first pronunciation as
    the analyzer."""
    from english.utils import syllabify

    words = ((evaluation or {}).get("stage1_cmu") or {}).get("words") or []
    out = []
    for w in words:
        word = str(w.get("word", ""))
        try:
            found = syllabify(word)
            out.append({"word": word, "arpabet": " ".join(found["phonemes"]) if found["found"] else None})
        except Exception as e:  # never let the dictionary break a result
            print("shadowing: CMU lookup failed for", word, e)
            out.append({"word": word, "arpabet": None})
    if evaluation is not None:
        evaluation["cmu_arpabet"] = out


def _hyphenated_syllables(word, syllable_count, stressed):
    """The dictionary's syllable split of WORD (english.utils corrected_hyphenation: the Moby
    list, else pyphen corrected to cmudict's syllable count) as a list, e.g. ["dad", "dy"], or
    None when it doesn't have as many parts as the analyzer found syllables. Of two variants
    (noun/verb, e.g. "pres-ent / pre-sent"), a 1st-syllable stress picks the closed one."""
    from english.utils import corrected_hyphenation

    variants = [v.strip() for v in corrected_hyphenation(word).split(" / ")]
    fitting = [v.lower().split("-") for v in variants if v and len(v.split("-")) == syllable_count]
    if not fitting:
        return None
    if len(fitting) > 1 and stressed is not None:
        closed = [p for p in fitting if p[0] and p[0][-1].lower() not in "aeiouy"]
        opened = [p for p in fitting if p not in closed]
        fitting = (closed if stressed == 1 else opened) or fitting
    return fitting[0]


def _add_hyphenation(evaluation):
    """Adds "hyphenated" (the syllables as spelled, e.g. ["bas", "ket", "ball"], or None) to
    each stress word of the Word Syllables Stress Check, for the result tables."""
    for w in ((evaluation or {}).get("word_stress_check") or {}).get("words") or []:
        pattern = (w.get("expected_pattern") or w.get("reference_pattern") or w.get("recorded_pattern") or "").split()
        count = w.get("syllable_count") or len(pattern)
        try:
            w["hyphenated"] = (
                _hyphenated_syllables(
                    str(w.get("word", "")).lower(), count,
                    w.get("expected_stressed_syllable") or w.get("reference_stressed_syllable"),
                )
                if count and count > 1 else None
            )
        except Exception as e:  # never let the dictionary break a result
            print("shadowing: hyphenation failed for", w.get("word"), e)
            w["hyphenated"] = None


@api_view(["POST"])
def shadowing_send(request):
    """Teacher only. Multipart: reference_file (the TTS MP3), sentence, voice (label, for display),
    tts_provider / tts_voice / tts_speed / tts_ssml_rate (kept as "tts"),
    targeted_words, strict_connected_speech ("true"/"false"), fall_match_ratio, rise_match_ratio,
    link_tolerance, stress_words, stress_contrast_ratio, melody_min_similarity, stress_source.
    Saves the reference to S3 and the exercise to Redis, then announces it to the students.
    Returns {shadowing_id, audio_url}."""
    if not request.user.is_staff:
        return JsonResponse({"error": "Teachers only."}, status=403)
    reference = request.FILES.get("reference_file")
    sentence = _clean_sentence(request.data.get("sentence"))
    if not reference or not sentence:
        return JsonResponse({"error": "A reference recording and its sentence are required."}, status=400)
    if not (request.data.get("stress_words") or "").strip():
        return JsonResponse({"error": "Type at least one stress word."}, status=400)

    shadowing_id = uuid.uuid4().hex[:12]
    s3_key = f"{settings.SHADOWING_S3_ROOT}audios/shadowing/{shadowing_id}.mp3"
    reference.seek(0)
    _s3().put_object(
        Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=s3_key, Body=reference, ContentType="audio/mpeg"
    )

    exercise = {
        "shadowing_id": shadowing_id,
        "sentence": sentence,
        "voice": request.data.get("voice", ""),
        "tts": _tts_from(request.data),
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
    sentence = _clean_sentence(request.data.get("sentence"))
    if not reference or not recorded or not sentence:
        return JsonResponse({"error": "A reference, a recording and the sentence are required."}, status=400)
    if not (request.data.get("stress_words") or "").strip():
        return JsonResponse({"error": "Type at least one stress word."}, status=400)
    evaluation, error = _evaluate(
        sentence, _options_from(request.data), reference.read(), reference.name or "reference.mp3", recorded.read()
    )
    return error or JsonResponse(evaluation)


SAVED_TESTS_PREFIX = f"{settings.SHADOWING_S3_ROOT}audios/shadowing_tests/"  # dev/audios/... locally
SAVED_TEST_FOLDER_RE = re.compile(r"[A-Za-z0-9_-]+")  # e.g. 2026-11-18_160222_991267


@api_view(["POST"])
def shadowing_save_test(request):
    """Teacher only: keep a "Test it yourself" run in S3 so it can be re-run later exactly.
    Multipart: reference_file (the TTS MP3), recorded_file (the scored WAV), sentence, voice,
    tts_provider / tts_voice / tts_speed / tts_ssml_rate (saved as "tts"),
    the scoring options as in shadowing_send, and evaluation (the result, as JSON text).
    Each save gets its own new folder (date, time, random code; the sentence is in test.json),
    so nothing is ever overwritten:
        audios/shadowing_tests/<YYYY-MM-DD_HHMMSS>_<code>/
            reference.mp3, recording.wav, test.json (sentence, voice, options, result)
    Returns {folder}."""
    if not request.user.is_staff:
        return JsonResponse({"error": "Teachers only."}, status=403)
    reference = request.FILES.get("reference_file")
    recorded = request.FILES.get("recorded_file")
    sentence = _clean_sentence(request.data.get("sentence"))
    if not reference or not recorded or not sentence:
        return JsonResponse({"error": "A reference, a recording and the sentence are required."}, status=400)
    try:
        evaluation = json.loads(request.data.get("evaluation") or "null")
    except ValueError:
        evaluation = None

    now = timezone.localtime()
    folder = f"{now:%Y-%m-%d_%H%M%S}_{uuid.uuid4().hex[:6]}"
    prefix = f"{SAVED_TESTS_PREFIX}{folder}/"
    test = {
        "folder": folder,
        "saved_at": now.isoformat(),
        "saved_by": request.user.username,
        "sentence": sentence,
        "voice": request.data.get("voice", ""),  # display label, e.g. "11L Matilda · 0.7×"
        "tts": _tts_from(request.data),           # {provider, voice, speed, ssml_rate}
        "options": _options_from(request.data),
        "files": {"reference": "reference.mp3", "recording": "recording.wav"},
        "evaluation": evaluation,  # the result when it was saved, to compare re-runs with
    }
    s3 = _s3()
    bucket = settings.AWS_STORAGE_BUCKET_NAME
    reference.seek(0)
    recorded.seek(0)
    s3.put_object(Bucket=bucket, Key=f"{prefix}reference.mp3", Body=reference.read(), ContentType="audio/mpeg")
    s3.put_object(Bucket=bucket, Key=f"{prefix}recording.wav", Body=recorded.read(), ContentType="audio/wav")
    s3.put_object(
        Bucket=bucket, Key=f"{prefix}test.json",
        Body=json.dumps(test, indent=2, ensure_ascii=False).encode(), ContentType="application/json",
    )
    return JsonResponse({"folder": folder})


def _saved_test_summary(s3, bucket, folder):
    """One saved test for the teacher app's list: test.json's details (without the full result)
    and links to its two recordings (valid for an hour)."""
    prefix = f"{SAVED_TESTS_PREFIX}{folder}/"
    try:
        test = json.loads(s3.get_object(Bucket=bucket, Key=f"{prefix}test.json")["Body"].read())
    except Exception as e:  # a folder without (readable) test.json is still listed
        print("shadowing_saved_tests: can't read test.json of", folder, e)
        test = {}
    summary = (test.get("evaluation") or {}).get("summary") or {}
    return {
        "folder": folder,
        "saved_at": test.get("saved_at"),
        "saved_by": test.get("saved_by"),
        "sentence": test.get("sentence", ""),
        "voice": test.get("voice", ""),
        "tts": test.get("tts"),
        "options": test.get("options", {}),
        "scores": {
            "overall": summary.get("overall_score_pct"),
            "pronunciation": summary.get("pronunciation_score_pct"),
            "stress": summary.get("stress_match_pct"),
            "intonation": summary.get("intonation_score_pct"),
            "linking": summary.get("connected_speech_summary"),
            "heard": summary.get("heard_transcript"),
        },
        "reference_url": get_s3_audio_url(f"{prefix}reference.mp3"),
        "recording_url": get_s3_audio_url(f"{prefix}recording.wav"),
    }


@api_view(["GET"])
def shadowing_saved_tests(request):
    """Teacher only: every test saved with shadowing_save_test, newest first.
    Returns {tests: [{folder, saved_at, saved_by, sentence, voice, options, scores,
    reference_url, recording_url}]}."""
    if not request.user.is_staff:
        return JsonResponse({"error": "Teachers only."}, status=403)
    s3 = _s3()
    bucket = settings.AWS_STORAGE_BUCKET_NAME
    folders = []
    for page in s3.get_paginator("list_objects_v2").paginate(
        Bucket=bucket, Prefix=SAVED_TESTS_PREFIX, Delimiter="/"
    ):
        for p in page.get("CommonPrefixes", []):
            folders.append(p["Prefix"][len(SAVED_TESTS_PREFIX):].rstrip("/"))
    folders.sort(reverse=True)  # names start with the date and time
    with ThreadPoolExecutor(max_workers=8) as pool:
        tests = list(pool.map(lambda f: _saved_test_summary(s3, bucket, f), folders))
    return JsonResponse({"tests": tests})


@api_view(["POST"])
def shadowing_delete_saved_tests(request):
    """Teacher only. JSON {folders: [...]}: deletes those saved tests (every file in each folder).
    Returns {deleted: [...]}."""
    if not request.user.is_staff:
        return JsonResponse({"error": "Teachers only."}, status=403)
    folders = request.data.get("folders") or []
    if not isinstance(folders, list) or not folders:
        return JsonResponse({"error": "No saved tests were given."}, status=400)
    # Only plain folder names (no "/" or ".."), so nothing outside the saved tests can be deleted.
    if not all(isinstance(f, str) and SAVED_TEST_FOLDER_RE.fullmatch(f) for f in folders):
        return JsonResponse({"error": "Invalid saved test name."}, status=400)
    s3 = _s3()
    bucket = settings.AWS_STORAGE_BUCKET_NAME
    for folder in folders:
        keys = [
            {"Key": o["Key"]}
            for page in s3.get_paginator("list_objects_v2").paginate(
                Bucket=bucket, Prefix=f"{SAVED_TESTS_PREFIX}{folder}/"
            )
            for o in page.get("Contents", [])
        ]
        if keys:
            s3.delete_objects(Bucket=bucket, Delete={"Objects": keys, "Quiet": True})
    return JsonResponse({"deleted": folders})


# ---- Saved reference sentences (Postgres row + S3 audio) --------------------------------------

SENTENCES_PREFIX = f"{settings.SHADOWING_S3_ROOT}audios/shadowing_sentences/"  # dev/audios/... locally


def _keywords_from(value):
    """Keywords from "apology, average; question intonation" (or a JSON list): lower-case,
    trimmed, no duplicates, at most 50 characters each."""
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            items = parsed if isinstance(parsed, list) else [value]
        except ValueError:
            items = re.split(r"[,;\n]", value)
    else:
        items = value or []
    keywords = []
    for k in items:
        k = re.sub(r"\s+", " ", str(k)).strip().lower()[:50]
        if k and k not in keywords:
            keywords.append(k)
    return keywords


def _sentence_json(row):
    return {
        "id": row.id,
        "sentence": row.sentence,
        "tts_text": row.tts_text,
        "keywords": row.keywords,
        "voice": row.voice,
        "tts": row.tts,
        "options": row.options,
        "created_by": row.created_by.username if row.created_by else None,
        "created_at": row.created_at.isoformat(),
        "audio_url": get_s3_audio_url(row.s3_key),  # valid for an hour
    }


@api_view(["POST"])
def shadowing_save_sentence(request):
    """Teacher only: keep a reference sentence and its audio, to find and reuse later.
    Multipart: reference_file (the TTS MP3), sentence, keywords ("apology, average"), voice,
    tts_text (the SSML, if any), tts_provider / tts_voice / tts_speed / tts_ssml_rate, and the
    scoring options as in shadowing_send. The audio goes to a new S3 folder (never overwritten):
        audios/shadowing_sentences/<YYYY-MM-DD_HHMMSS>_<code>/reference.mp3
    Returns the saved sentence (as in shadowing_sentences)."""
    from .models import ShadowingSentence

    if not request.user.is_staff:
        return JsonResponse({"error": "Teachers only."}, status=403)
    reference = request.FILES.get("reference_file")
    sentence = _clean_sentence(request.data.get("sentence"))
    if not reference or not sentence:
        return JsonResponse({"error": "A reference and the sentence are required."}, status=400)

    now = timezone.localtime()
    s3_key = f"{SENTENCES_PREFIX}{now:%Y-%m-%d_%H%M%S}_{uuid.uuid4().hex[:6]}/reference.mp3"
    reference.seek(0)
    _s3().put_object(
        Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=s3_key, Body=reference.read(), ContentType="audio/mpeg"
    )
    row = ShadowingSentence.objects.create(
        sentence=sentence,
        tts_text=(request.data.get("tts_text") or "").strip(),
        keywords=_keywords_from(request.data.get("keywords")),
        s3_key=s3_key,
        voice=(request.data.get("voice") or "")[:120],
        tts=_tts_from(request.data),
        options=_options_from(request.data),
        created_by=request.user,
    )
    return JsonResponse(_sentence_json(row))


@api_view(["GET"])
def shadowing_sentences(request):
    """Teacher only: saved sentences, newest first. ?q=apology average finds the sentences where
    every word of q appears in the sentence or in a keyword (case-insensitive, partial words
    count: "apolog" finds "apology"). No q = all of them. At most 200.
    Returns {sentences: [{id, sentence, tts_text, keywords, voice, tts, options, created_by,
    created_at, audio_url}]}."""
    from django.db.models import Func, Q, TextField, Value

    from .models import ShadowingSentence

    if not request.user.is_staff:
        return JsonResponse({"error": "Teachers only."}, status=403)
    rows = ShadowingSentence.objects.select_related("created_by").annotate(
        keywords_text=Func("keywords", Value(" "), function="array_to_string", output_field=TextField())
    )
    for term in (request.query_params.get("q") or "").split():
        rows = rows.filter(Q(sentence__icontains=term) | Q(keywords_text__icontains=term))
    return JsonResponse({"sentences": [_sentence_json(r) for r in rows[:200]]})


@api_view(["POST"])
def shadowing_delete_sentences(request):
    """Teacher only. JSON {ids: [...]}: deletes those saved sentences and their audio in S3.
    Returns {deleted: [...ids]}."""
    from .models import ShadowingSentence

    if not request.user.is_staff:
        return JsonResponse({"error": "Teachers only."}, status=403)
    ids = request.data.get("ids") or []
    if not isinstance(ids, list) or not ids or not all(isinstance(i, int) for i in ids):
        return JsonResponse({"error": "No saved sentences were given."}, status=400)
    rows = list(ShadowingSentence.objects.filter(id__in=ids))
    keys = [{"Key": r.s3_key} for r in rows if r.s3_key.startswith(SENTENCES_PREFIX)]
    if keys:
        _s3().delete_objects(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME, Delete={"Objects": keys, "Quiet": True}
        )
    deleted = [r.id for r in rows]
    ShadowingSentence.objects.filter(id__in=deleted).delete()
    return JsonResponse({"deleted": deleted})


def _is_sentence_key(key):
    """A key inside the sentences folder (and nothing else in the bucket)."""
    return isinstance(key, str) and key.startswith(SENTENCES_PREFIX) and len(key) > len(SENTENCES_PREFIX) and ".." not in key


def _sentence_storage_json(row, obj):
    """A saved sentence as the Manage Shadowing Sentences tab shows it: the row's metadata and the
    S3 object its s3_key points to (obj: from list_objects_v2 / head_object, None if missing)."""
    return {
        "id": row.id,
        "sentence": row.sentence,
        "keywords": row.keywords,
        "voice": row.voice,
        "created_by": row.created_by.username if row.created_by else None,
        "created_at": row.created_at.isoformat(),
        "s3_key": row.s3_key,
        "file": {"size": obj["Size"], "last_modified": obj["LastModified"].isoformat()} if obj else None,
        "audio_url": get_s3_audio_url(row.s3_key) if obj else None,  # valid for an hour
    }


@api_view(["GET"])
def shadowing_sentence_files(request):
    """Teacher only: how the saved sentences are stored, for the teacher app's Manage Shadowing
    Sentences tab. Each ShadowingSentence row (the metadata, newest first) with the S3 file its
    s3_key points to (file is null if that file is missing from S3), and the files in S3 under
    audios/shadowing_sentences/ that no row points to.
    Returns {prefix (the folder, e.g. "audios/shadowing_sentences/"),
    sentences: [{id, sentence, keywords, voice, created_by, created_at, s3_key,
    file: {size, last_modified} | null, audio_url | null}],
    orphan_files: [{key, size, last_modified, url}]}."""
    from .models import ShadowingSentence

    if not request.user.is_staff:
        return JsonResponse({"error": "Teachers only."}, status=403)
    objects = {
        o["Key"]: o
        for page in _s3().get_paginator("list_objects_v2").paginate(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME, Prefix=SENTENCES_PREFIX
        )
        for o in page.get("Contents", [])
    }
    sentences = [
        _sentence_storage_json(row, objects.pop(row.s3_key, None))
        for row in ShadowingSentence.objects.select_related("created_by")  # newest first (Meta.ordering)
    ]
    orphan_files = [
        {
            "key": o["Key"],
            "size": o["Size"],
            "last_modified": o["LastModified"].isoformat(),
            "url": get_s3_audio_url(o["Key"]),
        }
        for o in sorted(objects.values(), key=lambda o: o["LastModified"], reverse=True)
    ]
    return JsonResponse({"prefix": SENTENCES_PREFIX, "sentences": sentences, "orphan_files": orphan_files})


@api_view(["POST"])
def shadowing_recognize_file(request):
    """Teacher only. JSON {s3_key}: transcribes a file under audios/shadowing_sentences/ that no
    saved sentence points to yet (OpenAI Whisper, English) and saves the transcript as a new saved
    sentence (ShadowingSentence row) for it, with no keywords. The row is dated when the file was
    uploaded, so it sorts with the others by save time.
    Returns the new saved sentence (as in shadowing_sentence_files)."""
    from openai import OpenAI

    from .models import ShadowingSentence

    if not request.user.is_staff:
        return JsonResponse({"error": "Teachers only."}, status=403)
    s3_key = request.data.get("s3_key")
    if not _is_sentence_key(s3_key):
        return JsonResponse({"error": "Invalid file name."}, status=400)
    if ShadowingSentence.objects.filter(s3_key=s3_key).exists():
        return JsonResponse({"error": "That file already has a saved sentence. Click Refresh."}, status=409)
    try:
        obj = _s3().get_object(Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=s3_key)
        audio = obj["Body"].read()
    except Exception as e:
        print("shadowing_recognize_file: can't read", s3_key, e)
        return JsonResponse({"error": "That file is no longer in S3. Click Refresh."}, status=404)
    try:
        transcription = OpenAI(api_key=os.getenv("OPENAI_API_KEY")).audio.transcriptions.create(
            model="whisper-1",
            file=(s3_key.rsplit("/", 1)[-1], audio, obj.get("ContentType") or "audio/mpeg"),
            language="en",  # force English, so short audio isn't taken for another language
        )
    except Exception as e:
        print("shadowing_recognize_file: transcription failed for", s3_key, e)
        return JsonResponse({"error": "The transcription service failed. Try again."}, status=502)
    sentence = _clean_sentence(transcription.text)
    if not sentence:
        return JsonResponse({"error": "No speech was recognized in that file."}, status=422)
    row = ShadowingSentence.objects.create(sentence=sentence, s3_key=s3_key, created_by=request.user)
    # created_at is auto_now_add, so it can only be changed after the row is created.
    ShadowingSentence.objects.filter(id=row.id).update(created_at=obj["LastModified"])
    row.refresh_from_db()
    return JsonResponse(_sentence_storage_json(row, {"Size": obj["ContentLength"], "LastModified": obj["LastModified"]}))


@api_view(["POST"])
def shadowing_set_sentence_keywords(request):
    """Teacher only. JSON {id, keywords}: replaces a saved sentence's keywords ("apology, average"
    or a list; cleaned as when saving). Returns {id, keywords}."""
    from .models import ShadowingSentence

    if not request.user.is_staff:
        return JsonResponse({"error": "Teachers only."}, status=403)
    row = ShadowingSentence.objects.filter(id=request.data.get("id")).first() if isinstance(request.data.get("id"), int) else None
    if row is None:
        return JsonResponse({"error": "That saved sentence no longer exists. Click Refresh."}, status=404)
    row.keywords = _keywords_from(request.data.get("keywords"))
    row.save(update_fields=["keywords"])
    return JsonResponse({"id": row.id, "keywords": row.keywords})


@api_view(["POST"])
def shadowing_delete_sentence_files(request):
    """Teacher only. JSON {keys: [...]}: deletes those files from S3 (keys as listed by
    shadowing_sentence_files) and the saved sentences whose s3_key they are.
    Returns {deleted: [...keys], sentences_deleted: n}."""
    from .models import ShadowingSentence

    if not request.user.is_staff:
        return JsonResponse({"error": "Teachers only."}, status=403)
    keys = request.data.get("keys") or []
    if not isinstance(keys, list) or not keys:
        return JsonResponse({"error": "No files were given."}, status=400)
    # Only keys inside the sentences folder, so nothing else in the bucket can be deleted.
    if not all(_is_sentence_key(k) for k in keys):
        return JsonResponse({"error": "Invalid file name."}, status=400)
    keys = list(dict.fromkeys(keys))
    s3 = _s3()
    for i in range(0, len(keys), 1000):  # delete_objects takes at most 1000 keys
        s3.delete_objects(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME,
            Delete={"Objects": [{"Key": k} for k in keys[i:i + 1000]], "Quiet": True},
        )
    _, deleted_per_model = ShadowingSentence.objects.filter(s3_key__in=keys).delete()
    sentences_deleted = deleted_per_model.get(ShadowingSentence._meta.label, 0)
    return JsonResponse({"deleted": keys, "sentences_deleted": sentences_deleted})


@api_view(["GET"])
def shadowing_sentence_audio(request, sentence_id):
    """Teacher only: a saved sentence's reference MP3, through Django (the browser can't fetch
    the S3 link itself because of CORS), so the Shadowing panel can use it as the reference."""
    from django.http import HttpResponse

    from .models import ShadowingSentence

    if not request.user.is_staff:
        return JsonResponse({"error": "Teachers only."}, status=403)
    row = ShadowingSentence.objects.filter(id=sentence_id).first()
    if row is None:
        return JsonResponse({"error": "That saved sentence no longer exists."}, status=404)
    try:
        body = _s3().get_object(Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=row.s3_key)["Body"].read()
    except Exception as e:
        print("shadowing_sentence_audio: can't read", row.s3_key, e)
        return JsonResponse({"error": "The audio couldn't be read from S3."}, status=502)
    return HttpResponse(body, content_type="audio/mpeg")
