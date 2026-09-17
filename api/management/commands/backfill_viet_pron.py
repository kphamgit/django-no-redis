"""Backfill PartOfSpeech.viet_pron_code for dictionary entries created before the
value was auto-generated on creation.

Uses the SAME helper the serializer uses -- word_to_vietnamese(head_word,
part_of_speech=pos.name) -- so POS-specific rules apply and the result matches
what a freshly-created entry would get. Only rows with an empty viet_pron_code
are touched (so hand-edited values are never clobbered), unless --overwrite is
given. Words not in cmudict have no pronunciation to generate and are skipped.

Usage:
    python manage.py backfill_viet_pron                 # fill empties (Viet dict)
    python manage.py backfill_viet_pron --dry-run       # preview, write nothing
    python manage.py backfill_viet_pron --source longman
    python manage.py backfill_viet_pron --overwrite     # recompute all rows
"""
import json

from django.core.management.base import BaseCommand
from django.db.models import Q

from api.models import PartOfSpeech
from english.utils import word_to_vietnamese

VIET_DICT_SOURCE = "ho-ngoc-duc-stardict"


class Command(BaseCommand):
    help = "Generate viet_pron_code for existing dictionary entries that lack it."

    def add_arguments(self, parser):
        parser.add_argument(
            "--source", default=VIET_DICT_SOURCE,
            help="Dictionary source to backfill (default: the Ho Ngoc Duc Viet dict).",
        )
        parser.add_argument(
            "--overwrite", action="store_true",
            help="Recompute even rows that already have a viet_pron_code.",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Show what would change without saving anything.",
        )

    def handle(self, *args, **options):
        source = options["source"]
        overwrite = options["overwrite"]
        dry_run = options["dry_run"]

        qs = PartOfSpeech.objects.filter(dict_entry__source=source).select_related("dict_entry")
        if not overwrite:
            qs = qs.filter(Q(viet_pron_code__isnull=True) | Q(viet_pron_code=""))

        total = qs.count()
        scope = "(overwrite: all rows)" if overwrite else "with empty viet_pron_code"
        self.stdout.write(f"Scanning {total} part-of-speech row(s) for source {source!r} {scope}...")

        updated = skipped = 0
        for pos in qs:
            head_word = pos.dict_entry.head_word
            viet = word_to_vietnamese(head_word, part_of_speech=pos.name)
            if not viet:
                skipped += 1
                self.stdout.write(f"  skip (not in cmudict): {head_word!r} [{pos.name}]")
                continue
            value = json.dumps(viet, ensure_ascii=False)
            self.stdout.write(f"  {head_word!r} [{pos.name}] -> {value}")
            if not dry_run:
                pos.viet_pron_code = value
                pos.save(update_fields=["viet_pron_code"])
            updated += 1

        verb = "would update" if dry_run else "updated"
        self.stdout.write(self.style.SUCCESS(
            f"Done. {verb} {updated}, skipped {skipped} (no cmudict pronunciation), of {total} scanned."
        ))
