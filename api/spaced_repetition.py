"""SM-2 spaced-repetition scheduling.

Ported 1:1 from the reviewFlashcard() implementation in the spaced-rep app
(flashcard.ts) to keep behavior identical across apps. Notable choices preserved
from that implementation:
  - quality is graded 0..5
  - the lapse threshold is `quality < 4` (NOT the textbook `< 3`): any grade below
    4 resets interval to 1 day and repetitions to 1, and does NOT update easiness.
  - easiness is only adjusted when `quality >= 4`.
"""

from datetime import timedelta
from django.utils import timezone


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

    if quality < 4:
        # Having difficulty recalling: restart the schedule, keep easiness unchanged.
        interval = 1
        review.repetitions = 1
    else:
        review.easiness = easiness

    review.interval = interval
    review.next_review_at = base_date + timedelta(days=interval)

    return quality < 4
