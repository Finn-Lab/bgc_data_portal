from django.core.management.base import BaseCommand
from django.db import transaction
from mgnify_bgcs.models import CurrentStats
from mgnify_bgcs.utils.helpers import generate_current_stats


class Command(BaseCommand):
    help = "Recompute BGC/project statistics and append a new CurrentStats entry."

    def handle(self, *args, **options):
        self.stdout.write("Generating new stats…", ending="\n")
        stats = generate_current_stats()

        # wrap creation in a transaction
        with transaction.atomic():
            cs = CurrentStats.objects.create(stats=stats)

        self.stdout.write(
            self.style.SUCCESS(
                f"✔ Created CurrentStats id={cs.pk} at {cs.created_at.isoformat()}"
            )
        )
