from django.core.management.base import BaseCommand

from english.audio import delete_unused_audios


class Command(BaseCommand):
    help = ("Delete the question audios (rows and S3 files) that no question uses, aren't in the "
            "library, and are more than a day old. Safe to run any time, e.g. from Heroku Scheduler.")

    def handle(self, *args, **options):
        self.stdout.write(f"Deleted {delete_unused_audios()} unused audio(s).")
