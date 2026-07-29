"""List the voices available in the configured ElevenLabs account.

Usage:
    python manage.py list_voices              # table view
    python manage.py list_voices --ids        # just "Name -> voice_id" lines
    python manage.py list_voices --category premade   # filter by category
"""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from elevenlabs.client import ElevenLabs


class Command(BaseCommand):
    help = "Print all voices available in the ElevenLabs account (queried live)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--ids",
            action="store_true",
            help="Print only 'Name -> voice_id' lines (easy to copy).",
        )
        parser.add_argument(
            "--category",
            default=None,
            help="Only show voices in this category (e.g. premade, professional, cloned).",
        )

    def handle(self, *args, **options):
        api_key = settings.ELEVENLABS_API_KEY
        if not api_key:
            raise CommandError("ELEVENLABS_API_KEY is not set.")

        client = ElevenLabs(api_key=api_key)
        try:
            resp = client.voices.get_all()
        except AttributeError:
            # Newer SDKs replace get_all() with search().
            resp = client.voices.search()
        voices = list(resp.voices)

        category = options["category"]
        if category:
            voices = [v for v in voices if (getattr(v, "category", "") or "") == category]

        voices.sort(key=lambda v: ((getattr(v, "category", "") or ""), v.name or ""))

        if not voices:
            self.stdout.write(self.style.WARNING("No voices found."))
            return

        if options["ids"]:
            for v in voices:
                self.stdout.write(f"{v.name} -> {v.voice_id}")
            self.stdout.write(self.style.SUCCESS(f"\n{len(voices)} voices."))
            return

        self.stdout.write(f"\n{len(voices)} voices in your ElevenLabs account:\n")
        self.stdout.write(f"{'NAME':<40} {'VOICE_ID':<24} {'CATEGORY':<12} LABELS")
        self.stdout.write("-" * 100)
        for v in voices:
            labels = getattr(v, "labels", None) or {}
            label_str = ", ".join(f"{k}={val}" for k, val in labels.items())
            name = (v.name or "")[:39]
            category = getattr(v, "category", "") or ""
            self.stdout.write(f"{name:<40} {v.voice_id:<24} {category:<12} {label_str}")
