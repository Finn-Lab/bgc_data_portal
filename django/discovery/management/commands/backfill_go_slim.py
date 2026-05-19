"""Recompute ``BgcDomain.go_slim`` from ``go_terms`` using the bundled slim map.

Ingestion and asset projection now populate ``go_slim`` inline at write
time using :func:`discovery.services.go_slim.go_slim_for_terms`. Run this
command after refreshing ``services/data/go_slim_map.json`` (via
``scripts/refresh_go_slim_map.py``) or to repair rows ingested before the
wiring was in place.
"""

from django.core.management.base import BaseCommand

from discovery.models import BgcDomain
from discovery.services.go_slim import go_slim_for_terms

BATCH_SIZE = 5000


class Command(BaseCommand):
    help = (
        "Backfill BgcDomain.go_slim from go_terms using the bundled "
        "go_slim_map.json. Ingestion and asset projection populate go_slim "
        "inline at write time; this command is for refreshes after the slim "
        "map changes."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report counts without writing to the database.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=BATCH_SIZE,
            help=f"Number of domains to update per batch (default: {BATCH_SIZE}).",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        batch_size = options["batch_size"]

        total = BgcDomain.objects.count()
        self.stdout.write(f"Total BgcDomain records: {total:,}")

        if dry_run:
            mismatched = 0
            for domain in BgcDomain.objects.only("go_terms", "go_slim").iterator(
                chunk_size=batch_size
            ):
                if list(domain.go_slim or []) != go_slim_for_terms(domain.go_terms):
                    mismatched += 1
            self.stdout.write(
                self.style.WARNING(
                    f"[dry-run] Would update go_slim for {mismatched:,} / {total:,} domains"
                )
            )
            return

        updated = 0
        batch: list[BgcDomain] = []

        for domain in BgcDomain.objects.only("id", "go_terms", "go_slim").iterator(
            chunk_size=batch_size
        ):
            slim = go_slim_for_terms(domain.go_terms)
            if list(domain.go_slim or []) != slim:
                domain.go_slim = slim
                batch.append(domain)

            if len(batch) >= batch_size:
                BgcDomain.objects.bulk_update(batch, ["go_slim"])
                updated += len(batch)
                batch = []
                self.stdout.write(f"  … {updated:,} updated", ending="\r")

        if batch:
            BgcDomain.objects.bulk_update(batch, ["go_slim"])
            updated += len(batch)

        self.stdout.write(
            self.style.SUCCESS(f"\n✔ Updated go_slim on {updated:,} BgcDomain records")
        )
