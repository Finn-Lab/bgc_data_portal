"""Management command to bulk-load discovery data from TSV files.

Usage::

    python manage.py load_discovery_data --data-dir /path/to/tsvs/
    python manage.py load_discovery_data --data-dir /path/to/tsvs/ --truncate
    python manage.py load_discovery_data --data-dir /path/to/tsvs/ --truncate --skip-stats
"""

import logging
import time

from django.core.management.base import BaseCommand

from discovery.services.ingestion.loader import run_pipeline

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Bulk-load discovery platform data from a directory of TSV files."

    def add_arguments(self, parser):
        parser.add_argument(
            "--data-dir",
            required=True,
            help="Directory containing TSV files (detectors.tsv, assemblies.tsv, etc.)",
        )
        parser.add_argument(
            "--truncate",
            action="store_true",
            default=False,
            help="TRUNCATE all discovery tables before loading (full reload).",
        )
        parser.add_argument(
            "--skip-stats",
            action="store_true",
            default=False,
            help="Skip post-load assembly score and catalog count computation.",
        )

    def handle(self, *args, **options):
        data_dir = options["data_dir"]
        truncate = options["truncate"]
        skip_stats = options["skip_stats"]

        self.stdout.write(f"Loading discovery data from: {data_dir}")
        if truncate:
            self.stdout.write(self.style.WARNING("TRUNCATE mode: all discovery tables will be cleared first."))

        t0 = time.perf_counter()
        run_pipeline(data_dir, truncate=truncate, skip_stats=skip_stats)
        elapsed = time.perf_counter() - t0

        self.stdout.write(self.style.SUCCESS(f"Done in {elapsed:.1f}s"))
