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

# VoiceAnalyzer_Claude, called the same way as by the p2p-voice-chat-server (its src/voiceAnalyzer.ts):
#   VOICE_ANALYZER_URL      its base URL. Local testing: http://127.0.0.1:8001 (Django has 8000).
#                           Production: https://voice.tienganhtuyhoa.com (Cloudflare Tunnel to the Mac).
#   VOICE_ANALYZER_API_KEY  sent as X-API-Key; needed through the tunnel (the same key as
#                           VoiceAnalyzer_Claude's api_key.txt), not for a local run.
# Two calls:
#   POST /api/evaluate           a student's recording scored against the reference
#   POST /api/analyze-reference  the stress and melody of the stress words measured from the
#                                reference audio alone, for the teacher's "Analyze reference audio"
# The older VOICE_ANALYZER_EVALUATE_URL (the full evaluate URL) is still read when
# VOICE_ANALYZER_URL isn't set, as is VOICE_ANALYZER_ANALYZE_REFERENCE_URL.
_LEGACY_EVALUATE_URL = os.environ.get("VOICE_ANALYZER_EVALUATE_URL", "")
VOICE_ANALYZER_URL = (
    os.environ.get("VOICE_ANALYZER_URL")
    or re.sub(r"/api/evaluate/?$", "", _LEGACY_EVALUATE_URL)
    or "http://127.0.0.1:8001"
).rstrip("/")
EVALUATE_URL = f"{VOICE_ANALYZER_URL}/api/evaluate"
EVALUATE_API_KEY = os.environ.get("VOICE_ANALYZER_API_KEY", "")
ANALYZE_REFERENCE_URL = os.environ.get(
    "VOICE_ANALYZER_ANALYZE_REFERENCE_URL", f"{VOICE_ANALYZER_URL}/api/analyze-reference"
)
VOICE_ANALYZER_TIMEOUT = 120  # seconds


def _stress_words_ipa(value):
    """The stress words' IPA as the analyzer takes it (display only: each stress word's
    "syllabified" in its reply is made from it): text such as "accept: əkˈsept, apology: əˈpɒlədʒi",
    or a JSON object {"accept": "əkˈsept"} (sent as JSON text). Blank when not given. The same
    for stress_words_viet, the Vietnamese pronunciation code with its syllables separated by
    hyphens ({"apology": "ơ-pô-lơ-di"}), which comes back in "syllabified" too."""
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value).strip() if value is not None else ""

def _helper_words(value):
    """The teacher's Helper Words, sent as JSON text {"have": "vờ"} (or a dict): {word in lower
    case: helper word}, without blanks. {} when missing or not valid JSON."""
    if isinstance(value, str):
        try:
            value = json.loads(value) if value.strip() else {}
        except ValueError:
            value = {}
    if not isinstance(value, dict):
        return {}
    return {str(k).strip().lower(): str(v).strip() for k, v in value.items() if str(k).strip() and str(v).strip()}


def _word_list(text):
    """The words of a teacher's word field ("apology, photography" or "is a"), lower case, each
    once, parsed as VoiceAnalyzer_Claude does (letters and apostrophes)."""
    words = []
    for w in re.findall(r"[A-Za-z']+", text or ""):
        if w.lower() not in words:
            words.append(w.lower())
    return words


def _clean_sentence(text):
    """The sentence without TTS markup such as ElevenLabs' <break time="0.4s" /> (any <...>
    tag): students see, and are scored on, only the words."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]*>", " ", text or "")).strip()


EXERCISE_TTL_SECONDS = 24 * 60 * 60
LATEST_KEY = "shadowing:latest"  # id of the most recently sent exercise
# The reference audio of each exercise sent to the students: <prefix><shadowing_id>.mp3. An S3
# lifecycle rule clears this folder after 2 days.
TEMP_SENTENCES_PREFIX = f"{settings.SHADOWING_S3_ROOT}audios/temp_shadowing_sentences/"  # dev/audios/... locally


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
        # Display only: {targeted word: helper word}, shown to the students under that word's link
        # (e.g. {"have": "vờ"}).
        "helper_words": _helper_words(data.get("helper_words")),
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
        # The stress words' IPA and Vietnamese pronunciation code (optional, display only): see
        # _stress_words_ipa.
        "stress_words_ipa": _stress_words_ipa(data.get("stress_words_ipa")),
        "stress_words_viet": _stress_words_ipa(data.get("stress_words_viet")),
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
                "stress_words_ipa": options.get("stress_words_ipa", ""),
                "stress_words_viet": options.get("stress_words_viet", ""),
            },
            files={
                "reference_file": (reference_name, reference_bytes, content_type),
                "recorded_file": ("recording.wav", recorded_bytes, "audio/wav"),
            },
            headers={"X-API-Key": EVALUATE_API_KEY} if EVALUATE_API_KEY else {},
            timeout=VOICE_ANALYZER_TIMEOUT,
        )
    except requests.RequestException as e:
        print(f"shadowing: can't reach VoiceAnalyzer_Claude at {VOICE_ANALYZER_URL}:", e)
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
    return evaluation, None


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


def _hyphenate_words(words):
    """Adds "hyphenated" (the syllables as spelled, e.g. ["bas", "ket", "ball"], or None) to each
    stress word of an analyzer reply, for the result tables. Same rules as the p2p server's
    addHyphenation: the word's letters only, as many parts as the syllables found."""
    for w in words or []:
        pattern = (w.get("expected_pattern") or w.get("reference_pattern") or w.get("recorded_pattern") or "").split()
        count = w.get("syllable_count") or len(pattern)
        word = re.sub(r"[^A-Za-z']", "", str(w.get("word", ""))).lower()
        try:
            w["hyphenated"] = (
                _hyphenated_syllables(
                    word, count, w.get("expected_stressed_syllable") or w.get("reference_stressed_syllable"),
                )
                if word and count and count > 1 else None
            )
        except Exception as e:  # never let the dictionary break a result
            print("shadowing: hyphenation failed for", w.get("word"), e)
            w["hyphenated"] = None


def _add_hyphenation(evaluation):
    """_hyphenate_words for the Word Syllables Stress Check of an evaluation."""
    _hyphenate_words(((evaluation or {}).get("word_stress_check") or {}).get("words"))


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
    s3_key = f"{TEMP_SENTENCES_PREFIX}{shadowing_id}.mp3"
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
        "content": {
            "shadowing_id": shadowing_id,
            "sentence": sentence,
            "audio_url": audio_url,
            # So the students know before recording which words are checked: the stress words
            # (melody) and the targeted words, each of which should link to the next word.
            "stress_words": _word_list(exercise["options"]["stress_words"]),
            "connected_words": _word_list(exercise["options"]["targeted_words"]),
            "helper_words": exercise["options"]["helper_words"],
        },
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
    recorded_bytes = recorded.read()
    evaluation, error = _evaluate(
        exercise["sentence"], exercise["options"], reference_bytes, "reference.mp3", recorded_bytes
    )
    if error:
        return error

    user_name = request.user.username
    results_key = _results_key(exercise["shadowing_id"])
    previous = settings.R_CONN.hget(results_key, user_name)
    redis_attempt = json.loads(previous)["attempt"] if previous else 0
    take = _save_take(request.user, exercise, evaluation, recorded_bytes, redis_attempt)
    result = {
        "user_name": user_name,
        "shadowing_id": exercise["shadowing_id"],
        "attempt": take["attempt"],
        # The students_shadowing row, for the teacher to play the recording
        # (/api/shadowing/take_recording/<take_id>/); None if it couldn't be kept.
        "take_id": take["id"] if take["recording_s3_key"] else None,
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


STUDENT_RECORDINGS_PREFIX = f"{settings.SHADOWING_S3_ROOT}audios/live_students_shadowing_recordings/"  # dev/... locally


def _save_take(user, exercise, evaluation, recorded_bytes, redis_attempt):
    """Keeps a student's take: the recording in S3 under STUDENT_RECORDINGS_PREFIX and a row in
    students_shadowing (StudentShadowing). attempt = 1, 2, 3... per student and exercise, one more
    than the highest kept in the database or in Redis. A failed upload or save is logged and
    doesn't stop the student getting their result. Returns {attempt, recording_s3_key, id}."""
    from django.db import IntegrityError, transaction
    from django.db.models import Max

    from .models import StudentShadowing

    shadowing_id = exercise["shadowing_id"]
    summary = evaluation.get("summary") or {}
    stress_check = evaluation.get("word_stress_check") or {}
    safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", user.username) or "student"
    for _ in range(3):  # two takes sent at once could pick the same number: retry
        last = StudentShadowing.objects.filter(
            user_name=user.username, shadowing_id=shadowing_id
        ).aggregate(m=Max("attempt"))["m"] or 0
        attempt = max(last, redis_attempt) + 1
        s3_key = f"{STUDENT_RECORDINGS_PREFIX}{shadowing_id}/{safe_name}_attempt{attempt}.wav"
        try:
            with transaction.atomic():
                row = StudentShadowing.objects.create(
                    student=user,
                    user_name=user.username,
                    shadowing_id=shadowing_id,
                    sentence=exercise.get("sentence", ""),
                    attempt=attempt,
                    recording_s3_key=s3_key,
                    reference_s3_key=exercise.get("s3_key", ""),
                    overall_score_pct=summary.get("overall_score_pct"),
                    pronunciation_score_pct=summary.get("pronunciation_score_pct"),
                    stress_match_pct=summary.get("stress_match_pct"),
                    # None since VoiceAnalyzer stopped scoring word stress (the patterns are
                    # still in evaluation); filled on takes scored before that.
                    word_stress_score_pct=stress_check.get("score_pct"),
                    melody_score_pct=stress_check.get("pitch_direction_score_pct"),
                    options=exercise.get("options") or {},
                    evaluation=evaluation,
                )
        except IntegrityError:
            continue
        except Exception as e:
            print("shadowing: saving the take failed for", user.username, e)
            return {"attempt": attempt, "recording_s3_key": "", "id": None}
        break
    else:
        print("shadowing: couldn't number the take for", user.username)
        return {"attempt": redis_attempt + 1, "recording_s3_key": "", "id": None}

    try:
        _s3().put_object(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=s3_key, Body=recorded_bytes, ContentType="audio/wav"
        )
    except Exception as e:
        print("shadowing: uploading the recording failed for", user.username, e)
        StudentShadowing.objects.filter(pk=row.pk).update(recording_s3_key="")
        s3_key = ""
    return {"attempt": attempt, "recording_s3_key": s3_key, "id": row.pk}


# A Shadowing question (format 9) in a quiz: the scored take is kept in Redis for this long under
# a one-time token, which the quiz's submit (check_answer, format 9) turns into points.
QUESTION_TAKE_TTL_SECONDS = 60 * 60
# Points by melody %: under 50% = 0, 50% to under 70% = 5, 70% and up = 10 (the most).
# Any points (50% or more) count as a correct answer.
QUESTION_POINT_BANDS = [(70, 10), (50, 5)]  # (lowest %, points), highest first
QUESTION_MAX_POINTS = 10


def _question_points(pct):
    return next((points for lowest, points in QUESTION_POINT_BANDS if pct >= lowest), 0)


def question_take_key(token):
    return f"shadowing_question_take:{token}"


@api_view(["POST"])
def shadowing_assess_question(request):
    """A student's take of a Shadowing question (format 9) in a quiz. Multipart: question_id,
    recorded_file (16 kHz mono WAV). Scores the recording against the question's audio with
    VoiceAnalyzer_Claude and the question's scoring_options, and keeps the points for the quiz's
    submit: points by the melody % (the stress words' melody; the overall % when the melody wasn't
    measured), see QUESTION_POINT_BANDS; correct when it earns any points. The question's own
    score field isn't used (the teacher app doesn't set it), as for the other formats.
    Returns VoiceAnalyzer_Claude's reply plus "question_take": {token (send it as the answer),
    pct, basis ("melody" / "overall"), points, max_points, passed}."""
    from .models import Question

    question = Question.objects.select_related("audio").filter(
        id=request.data.get("question_id"), format=9
    ).first()
    if question is None:
        return JsonResponse({"error": "This Shadowing question no longer exists."}, status=404)
    if question.audio is None:
        return JsonResponse({"error": "This question has no audio to repeat."}, status=400)
    recorded = request.FILES.get("recorded_file")
    if not recorded:
        return JsonResponse({"error": "No recording was sent."}, status=400)
    sentence = _clean_sentence(question.content)
    try:
        reference_bytes = _s3().get_object(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=question.audio.s3_key
        )["Body"].read()
    except Exception as e:
        print("shadowing_assess_question: can't read", question.audio.s3_key, e)
        return JsonResponse({"error": "The question's audio couldn't be read."}, status=502)
    evaluation, error = _evaluate(
        sentence, _options_from(question.scoring_options or {}), reference_bytes, "reference.mp3", recorded.read()
    )
    if error:
        return error

    melody = (evaluation.get("word_stress_check") or {}).get("pitch_direction_score_pct")
    overall = (evaluation.get("summary") or {}).get("overall_score_pct")
    pct, basis = (melody, "melody") if melody is not None else (overall, "overall")
    pct = float(pct or 0)
    take = {
        "token": uuid.uuid4().hex,
        "pct": round(pct, 1),
        "basis": basis,
        "points": _question_points(pct),
        "max_points": QUESTION_MAX_POINTS,
        "passed": _question_points(pct) > 0,
    }
    settings.R_CONN.set(
        question_take_key(take["token"]),
        json.dumps({**take, "question_id": question.id, "user_name": request.user.username}),
        ex=QUESTION_TAKE_TTL_SECONDS,
    )
    return JsonResponse({**evaluation, "question_take": take})


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


@api_view(["POST"])
def shadowing_analyze_reference(request):
    """Teacher only: what VoiceAnalyzer_Claude measures in the reference audio alone (no student
    recording) for the given stress word(s): the stressed syllable, the dictionary's, and the
    melody. Multipart: reference_file, sentence, stress_words, stress_source (default
    "dictionary"), stress_words_ipa and stress_words_viet (optional, display only). Instead of
    reference_file, audio_id names an audio of the library (api.models.Audio, e.g. a Shadowing
    question's audio in the teacher app's question form), read from S3. Nothing is saved; returns VoiceAnalyzer_Claude's
    reply (POST /api/analyze-reference)."""
    if not request.user.is_staff:
        return JsonResponse({"error": "Teachers only."}, status=403)
    sentence = _clean_sentence(request.data.get("sentence"))
    if not sentence:
        return JsonResponse({"error": "A reference and the sentence are required."}, status=400)
    reference = request.FILES.get("reference_file")
    if reference:
        name = reference.name or "reference.mp3"
        reference_bytes = reference.read()
    elif request.data.get("audio_id"):
        from .models import Audio
        try:
            audio = Audio.objects.get(pk=int(request.data.get("audio_id")))
        except (Audio.DoesNotExist, TypeError, ValueError):
            return JsonResponse({"error": "That audio doesn't exist."}, status=404)
        try:
            obj = _s3().get_object(Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=audio.s3_key)
            reference_bytes = obj["Body"].read()
        except Exception as e:
            print(f"shadowing: can't read audio {audio.pk} ({audio.s3_key}) from S3:", e)
            return JsonResponse({"error": "Can't read that audio's file from S3."}, status=502)
        name = audio.s3_key.rsplit("/", 1)[-1] or "reference.mp3"
    else:
        return JsonResponse({"error": "A reference and the sentence are required."}, status=400)
    try:
        res = requests.post(
            ANALYZE_REFERENCE_URL,
            data={
                "spoken_text": sentence,
                "stress_words": (request.data.get("stress_words") or "").strip(),
                "stress_source": "reference" if request.data.get("stress_source") == "reference" else "dictionary",
                "stress_words_ipa": _stress_words_ipa(request.data.get("stress_words_ipa")),
                "stress_words_viet": _stress_words_ipa(request.data.get("stress_words_viet")),
            },
            files={"reference_file": (name, reference_bytes, "audio/wav" if name.endswith(".wav") else "audio/mpeg")},
            headers={"X-API-Key": EVALUATE_API_KEY} if EVALUATE_API_KEY else {},
            timeout=VOICE_ANALYZER_TIMEOUT,
        )
    except requests.RequestException as e:
        print(f"shadowing: can't reach VoiceAnalyzer_Claude at {VOICE_ANALYZER_URL}:", e)
        return JsonResponse({"error": "Can't reach the voice assessment server."}, status=502)
    try:
        analysis = res.json()
    except ValueError:
        analysis = None
    if not res.ok or not isinstance(analysis, dict):
        # FastAPI: {detail: "..."}, or a list of problems for a rejected request.
        detail = analysis.get("detail") if isinstance(analysis, dict) else None
        if isinstance(detail, list):
            detail = "; ".join(str(d.get("msg", d)) for d in detail)
        return JsonResponse(
            {"error": detail or f"Analyzing the reference failed ({res.status_code})."}, status=502
        )
    # The syllables as spelled (["a", "pol", "o", "gy"], or None), as in the assessment results.
    _hyphenate_words(analysis.get("words"))
    return JsonResponse(analysis)


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


# ---- Saved reference sentences: kept audios in the library (english/audio.py) ----------------------------

# The panel saves its provider's full name (PROVIDER_NAME in the teacher app); Audio keeps the code.
_PROVIDER_CODES = {
    "elevenlabs": "elevenlabs",
    "google chirp 3 hd": "google",
    "google neural2": "google",
    "amazon polly": "polly",
}


@api_view(["POST"])
def shadowing_save_sentence(request):
    """Teacher only: keep a reference sentence and its audio in the audio library, to find and
    reuse later (from any screen: GET /english/audios/). Multipart: reference_file (the TTS MP3),
    sentence, keywords ("apology, average"), tts_text (the SSML, if any), tts_provider / tts_voice /
    tts_speed, and the scoring options as in shadowing_send (kept as the audio's
    shadowing_options). The audio is a new Audio (made_for "shadowing", kept), its MP3 at
    audios/library/<uuid>.mp3. Returns the audio (as /english/audios/ does)."""
    from english.audio import store_audio
    from english.serializers import AudioSerializer

    if not request.user.is_staff:
        return JsonResponse({"error": "Teachers only."}, status=403)
    reference = request.FILES.get("reference_file")
    sentence = _clean_sentence(request.data.get("sentence"))
    if not reference or not sentence:
        return JsonResponse({"error": "A reference and the sentence are required."}, status=400)
    tts = _tts_from(request.data)
    provider_name = (tts["provider"] or "").strip()
    reference.seek(0)
    audio = store_audio(
        reference.read(),
        (request.data.get("tts_text") or "").strip() or sentence,
        _PROVIDER_CODES.get(provider_name.lower(), provider_name.lower()),
        tts["voice"] or "",
        tts["speed"],
        request.user,
        made_for="shadowing",
        kept=True,
        keywords=request.data.get("keywords"),
        shadowing_options=_options_from(request.data),
        shown_text=sentence,
    )
    return JsonResponse(AudioSerializer(audio).data)


STUDENT_RECORDINGS_LIST_LIMIT = 500


@api_view(["GET"])
def shadowing_student_recordings(request):
    """Teacher only: the students' shadowing takes for the teacher app's Utils → Students
    Shadowing Audios tab. Each students_shadowing row (newest first, at most
    STUDENT_RECORDINGS_LIST_LIMIT; ?student=<user name> for one student) with the S3 recording its
    recording_s3_key points to (file is null if missing), and the recordings in S3 under
    audios/live_students_shadowing_recordings/ that no row points to. The full analyzer reply isn't
    sent, only the scores and the transcript.
    Returns {prefix, limit, students: [user names], takes: [{id, user_name, shadowing_id, sentence,
    attempt, created_at, stress_words, stress_source, overall_score_pct, pronunciation_score_pct,
    stress_match_pct, word_stress_score_pct, melody_score_pct, heard_transcript, s3_key,
    file: {size, last_modified} | null, audio_url | null, reference_s3_key,
    reference_audio_url | null}], orphan_files: [{key, size,
    last_modified, url}]}."""
    from .models import StudentShadowing

    if not request.user.is_staff:
        return JsonResponse({"error": "Teachers only."}, status=403)
    objects = {
        o["Key"]: o
        for page in _s3().get_paginator("list_objects_v2").paginate(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME, Prefix=STUDENT_RECORDINGS_PREFIX
        )
        for o in page.get("Contents", [])
    }
    # Every row's key, so a file is an orphan only if no row at all (shown or not) points to it.
    row_keys = set(
        StudentShadowing.objects.exclude(recording_s3_key="").values_list("recording_s3_key", flat=True)
    )
    # The exercises' reference audio still in S3 (an S3 rule clears that folder after 2 days).
    references = {
        o["Key"]
        for page in _s3().get_paginator("list_objects_v2").paginate(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME, Prefix=TEMP_SENTENCES_PREFIX
        )
        for o in page.get("Contents", [])
    }
    rows = StudentShadowing.objects.all()  # newest first (Meta.ordering)
    student = (request.GET.get("student") or "").strip()
    if student:
        rows = rows.filter(user_name=student)
    takes = []
    for r in rows.values(
        "id", "user_name", "shadowing_id", "sentence", "attempt", "created_at", "recording_s3_key",
        "reference_s3_key",
        "overall_score_pct", "pronunciation_score_pct", "stress_match_pct", "word_stress_score_pct",
        "melody_score_pct", "options__stress_words", "options__stress_source",
        "evaluation__summary__heard_transcript",
    )[:STUDENT_RECORDINGS_LIST_LIMIT]:
        key = r["recording_s3_key"]
        obj = objects.get(key) if key else None
        takes.append({
            "id": r["id"],
            "user_name": r["user_name"],
            "shadowing_id": r["shadowing_id"],
            "sentence": r["sentence"],
            "attempt": r["attempt"],
            "created_at": r["created_at"].isoformat(),
            "stress_words": r["options__stress_words"] or "",
            "stress_source": r["options__stress_source"] or "",
            "overall_score_pct": r["overall_score_pct"],
            "pronunciation_score_pct": r["pronunciation_score_pct"],
            "stress_match_pct": r["stress_match_pct"],
            "word_stress_score_pct": r["word_stress_score_pct"],
            "melody_score_pct": r["melody_score_pct"],
            "heard_transcript": r["evaluation__summary__heard_transcript"] or "",
            "s3_key": key,
            "file": {"size": obj["Size"], "last_modified": obj["LastModified"].isoformat()} if obj else None,
            "audio_url": get_s3_audio_url(key) if obj else None,  # valid for an hour
            "reference_s3_key": r["reference_s3_key"],
            # null when the take has no reference key (saved before it was kept) or the file is gone
            "reference_audio_url": (
                get_s3_audio_url(r["reference_s3_key"]) if r["reference_s3_key"] in references else None
            ),
        })
    orphan_files = [
        {
            "key": o["Key"],
            "size": o["Size"],
            "last_modified": o["LastModified"].isoformat(),
            "url": get_s3_audio_url(o["Key"]),
        }
        for o in sorted(
            (o for k, o in objects.items() if k not in row_keys),
            key=lambda o: o["LastModified"], reverse=True,
        )
    ]
    students = list(
        StudentShadowing.objects.order_by("user_name").values_list("user_name", flat=True).distinct()
    )
    return JsonResponse({
        "prefix": STUDENT_RECORDINGS_PREFIX,
        "limit": STUDENT_RECORDINGS_LIST_LIMIT,
        "students": students,
        "takes": takes,
        "orphan_files": orphan_files,
    })


@api_view(["GET"])
def shadowing_take_recording(request, take_id):
    """Teacher only: a student's recorded WAV for one take (students_shadowing row take_id),
    through Django so the teacher's panel can fetch it with its login and play it."""
    from django.http import HttpResponse

    from .models import StudentShadowing

    if not request.user.is_staff:
        return JsonResponse({"error": "Teachers only."}, status=403)
    row = StudentShadowing.objects.filter(id=take_id).first()
    if row is None or not row.recording_s3_key:
        return JsonResponse({"error": "That recording isn't available."}, status=404)
    try:
        body = _s3().get_object(Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=row.recording_s3_key)["Body"].read()
    except Exception as e:
        print("shadowing_take_recording: can't read", row.recording_s3_key, e)
        return JsonResponse({"error": "The recording couldn't be read from S3."}, status=502)
    return HttpResponse(body, content_type="audio/wav")


@api_view(["GET"])
def shadowing_word_stress(request):
    """Teacher only. ?word=apology: the word's stress pattern from the CMU dictionary, for the
    "Get stress pattern and Melody" button next to a stress word. No audio is involved.
    Returns {word, found, pronunciations: [{arpabet, stresses, hyphenated}]}: one entry per
    distinct stress pattern among the CMU pronunciations (two for record / present), first =
    the most common. stresses = the CMU digit per syllable (1 primary, 2 secondary, 0 none);
    hyphenated = the spelled syllables (["a", "pol", "o", "gy"]) or None when the hyphenation
    doesn't have one part per syllable."""
    from english.utils import _get_cmudict

    if not request.user.is_staff:
        return JsonResponse({"error": "Teachers only."}, status=403)
    word = (request.GET.get("word") or "").strip()
    key = word.lower().replace("\u2019", "'")
    if not key:
        return JsonResponse({"error": "No word given."}, status=400)
    out = []
    seen = set()
    for phonemes in _get_cmudict().get(key) or []:
        stresses = [int(p[-1]) for p in phonemes if p[-1].isdigit()]
        if not stresses or tuple(stresses) in seen:
            continue
        seen.add(tuple(stresses))
        primary = stresses.index(1) + 1 if 1 in stresses else None
        try:
            parts = _hyphenated_syllables(key, len(stresses), primary) if len(stresses) > 1 else [key]
        except Exception as e:  # never let the hyphenation break the lookup
            print("shadowing_word_stress: hyphenation failed for", key, e)
            parts = None
        out.append({"arpabet": " ".join(phonemes), "stresses": stresses, "hyphenated": parts})
    return JsonResponse({"word": word, "found": bool(out), "pronunciations": out})
