import json
import os

from django.core.management.base import BaseCommand

from discovery.models import BgcDomain

DATA_FILE = os.path.join(os.path.dirname(__file__), "data", "pfam2goSlim.json")
BATCH_SIZE = 5000


def build_pfam_to_go_slim(pfam2go_dict: dict) -> dict[str, str]:
    """Return {pfam_acc: first molecular_function GO slim term (capitalized)}."""
    result = {}
    for pfam_acc, go_slims in pfam2go_dict.items():
        mol_func_terms = [
            desc.capitalize()
            for desc, go_type in go_slims
            if go_type == "molecular_function"
        ]
        seen = []
        for t in mol_func_terms:
            if t not in seen:
                seen.append(t)
        if seen:
            result[pfam_acc] = seen[0]
    return result


class Command(BaseCommand):
    help = (
        "Populate BgcDomain.go_slim from the bundled pfam2goSlim.json mapping "
        "(derived from v2 portal; maps Pfam accessions to molecular-function GO slim terms)."
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

        self.stdout.write(f"Loading pfam2goSlim from {DATA_FILE}")
        with open(DATA_FILE) as f:
            pfam2go_dict = json.load(f)

        pfam_to_slim = build_pfam_to_go_slim(pfam2go_dict)
        self.stdout.write(
            f"Loaded {len(pfam_to_slim):,} Pfam → GO slim mappings "
            f"(from {len(pfam2go_dict):,} total entries)"
        )

        total = BgcDomain.objects.count()
        self.stdout.write(f"Total BgcDomain records: {total:,}")

        if dry_run:
            mapped = BgcDomain.objects.filter(
                domain_acc__in=pfam_to_slim.keys()
            ).count()
            self.stdout.write(
                self.style.WARNING(
                    f"[dry-run] Would update go_slim for {mapped:,} / {total:,} domains"
                )
            )
            return

        updated = 0
        batch: list[BgcDomain] = []

        for domain in BgcDomain.objects.only("id", "domain_acc", "go_slim").iterator(
            chunk_size=batch_size
        ):
            slim = pfam_to_slim.get(domain.domain_acc, "")
            if domain.go_slim != slim:
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
