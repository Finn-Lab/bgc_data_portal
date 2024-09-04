from django.core.management.base import BaseCommand

from api.models import CurrentStats
from api.utils import generate_bgc_statistics

class Command(BaseCommand):
    help = "Computes latest headline statistics for the DB and writes them back into DB"

    def handle(self, *args, **options):
        stats = generate_bgc_statistics()

        CurrentStats.objects.create(
            stats=stats,
        )
        self.stdout.write(self.style.SUCCESS('Successfully computed latest statistics'))
        self.stdout.write(self.style.SUCCESS(stats))
