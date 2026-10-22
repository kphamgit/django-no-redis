"""Backfill PartOfSpeech.viet_pron_code for dictionary entries created before the
value was auto-generated on creation.

Uses the SAME helper the serializer uses -- respell_in_vietnamese(head_word,
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
from english.utils import respell_in_vietnamese

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
            # A row needs filling if EITHER form is missing (e.g. old rows have the
            # flapped viet_pron_code but not the new standard one).
            qs = qs.filter(
                Q(viet_pron_code__isnull=True) | Q(viet_pron_code="")
                | Q(viet_pron_code_standard__isnull=True) | Q(viet_pron_code_standard="")
            )

        total = qs.count()
        scope = "(overwrite: all rows)" if overwrite else "missing a viet_pron_code form"
        self.stdout.write(f"Scanning {total} part-of-speech row(s) for source {source!r} {scope}...")

        updated = skipped = 0
        for pos in qs:
            head_word = pos.dict_entry.head_word
            # American/flapped (T -> đ) and STANDARD/non-flapped (keeps t).
            flapped = respell_in_vietnamese(head_word, part_of_speech=pos.name, flap_t=True)
            standard = respell_in_vietnamese(head_word, part_of_speech=pos.name, flap_t=False)
            if not flapped and not standard:
                skipped += 1
                self.stdout.write(f"  skip (not in cmudict): {head_word!r} [{pos.name}]")
                continue
            flapped_json = json.dumps(flapped, ensure_ascii=False)
            standard_json = json.dumps(standard, ensure_ascii=False)
            self.stdout.write(f"  {head_word!r} [{pos.name}] -> standard={standard_json} american={flapped_json}")
            if not dry_run:
                pos.viet_pron_code = flapped_json
                pos.viet_pron_code_standard = standard_json
                pos.save(update_fields=["viet_pron_code", "viet_pron_code_standard"])
            updated += 1

        verb = "would update" if dry_run else "updated"
        self.stdout.write(self.style.SUCCESS(
            f"Done. {verb} {updated}, skipped {skipped} (no cmudict pronunciation), of {total} scanned."
        ))
