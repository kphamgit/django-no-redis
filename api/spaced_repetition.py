"""SM-2 spaced-repetition scheduling.

Originally ported from the reviewFlashcard() implementation in the spaced-rep app
(flashcard.ts), with these differences from it:
  - quality is graded 0..5
  - the lapse threshold is `quality < 4` (NOT the textbook `< 3`): any grade below
    4 resets interval to 1 day and repetitions to 1.
  - easiness is adjusted on EVERY grade, lapses included (as in textbook SM-2), so
    hard cards get a lower easiness and grow their intervals more slowly. (flashcard.ts
    only adjusted it when `quality >= 4`, which meant easiness could never decrease.)
  - cards come due at the START of the day in REVIEW_TZ, not at the exact time of
    day they were last reviewed, so a card due "tomorrow" shows up all of tomorrow.
"""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
from django.utils import timezone

# Timezone whose midnight starts a new review day (the students' local time).
REVIEW_TZ = ZoneInfo("Asia/Ho_Chi_Minh")


def apply_sm2(review, quality, review_date=None):
    """Mutate a CardReview instance in place according to SM-2 and the given grade.

    Args:
        review: a CardReview instance (has easiness, interval, repetitions, next_review_at).
        quality: integer 0..5, how well the user recalled the card.
        review_date: optional aware datetime to schedule from; defaults to now.

    Returns:
        bool: True if the card lapsed (quality < 4) and needs more practice.
    """
    base_date = review_date or timezone.now()

    review.repetitions = (review.repetitions or 0) + 1

    if review.repetitions == 1:
        interval = 1
    elif review.repetitions == 2:
        interval = 6
    else:
        interval = round(review.interval * review.easiness)

    easiness = review.easiness + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    if easiness < 1.3:
        easiness = 1.3
    review.easiness = easiness

    if quality < 4:
        # Having difficulty recalling: restart the schedule.
        interval = 1
        review.repetitions = 1

    review.interval = interval
    review.next_review_at = start_of_review_day(base_date, interval)

    return quality < 4


def start_of_review_day(base_date, days_ahead):
    """Midnight (REVIEW_TZ) of the day `days_ahead` days after base_date's local day."""
    due_day = base_date.astimezone(REVIEW_TZ).date() + timedelta(days=days_ahead)
    return datetime.combine(due_day, time.min, tzinfo=REVIEW_TZ)


# --- Grading a multiple-choice answer -----------------------------------------------
#
# The student sees the word (after its audio plays) plus 4 definitions, and the clock
# starts when the options appear. The SM-2 grade comes from correctness + response time:
#
#   ANSWER_TIME_LIMIT_MS (12 s) -- the hard limit. If no option is picked within 12 s the
#       card counts as not known (grade 1, a lapse): the answer is shown and the card comes
#       back tomorrow. 12 s is meant to be enough to read 4 short definitions and pick the
#       one you recognize, but not enough to work it out slowly by elimination.
#       The frontend counts down and auto-submits at 12 s; the backend also treats any
#       reported time over 12 s as a timeout.
#
#   FAST_ANSWER_MS (5 s) -- splits correct answers into "knew it instantly" vs "had to
#       think". Correct within 5 s = grade 5 (easiness +0.1: the word's intervals grow
#       faster). Correct in 5-12 s = grade 4 (easiness unchanged: intervals still grow,
#       at the normal rate).
#
#   Both are starting guesses, not measured values: tune them once real response
#   times are available. Long definitions take longer to read, so a slow-but-correct
#   answer on a long card may be reading time, not weak recall.
#
# Grades (apply_sm2 treats < 4 as a lapse):
#   5  correct, under FAST_ANSWER_MS
#   4  correct, FAST_ANSWER_MS .. ANSWER_TIME_LIMIT_MS
#   2  "I don't know"   -- a lapse, but a smaller easiness drop (-0.32) than a wrong
#                          answer, so being honest is never worse than guessing
#   1  wrong, or timed out (-0.54)
ANSWER_TIME_LIMIT_MS = 12_000
FAST_ANSWER_MS = 5_000

DONT_KNOW = "dont_know"
TIMEOUT = "timeout"


def grade_answer(correct, choice, latency_ms):
    """Return (result, quality, reason) for one multiple-choice answer.

    Args:
        correct: whether the chosen option is the card's definition.
        choice: the option key, or DONT_KNOW / TIMEOUT.
        latency_ms: time from options shown to answer, as measured by the client.

    result is one of "correct" / "wrong" / DONT_KNOW / TIMEOUT (ReviewLog.result).
    reason is a human-readable explanation of the grade, shown after answering.
    """
    seconds = latency_ms / 1000
    if choice == DONT_KNOW:
        return DONT_KNOW, 2, "You chose \"I don't know\" → grade 2."
    if choice == TIMEOUT or latency_ms > ANSWER_TIME_LIMIT_MS:
        return TIMEOUT, 1, f"No answer within the {ANSWER_TIME_LIMIT_MS // 1000} s limit → grade 1."
    if not correct:
        return "wrong", 1, f"Wrong answer after {seconds:.1f} s → grade 1."
    if latency_ms < FAST_ANSWER_MS:
        return "correct", 5, f"Correct in {seconds:.1f} s, under the {FAST_ANSWER_MS // 1000} s \"fast\" mark → grade 5."
    return "correct", 4, (f"Correct in {seconds:.1f} s, slower than the {FAST_ANSWER_MS // 1000} s \"fast\" mark "
                          f"but within the {ANSWER_TIME_LIMIT_MS // 1000} s limit → grade 4.")
