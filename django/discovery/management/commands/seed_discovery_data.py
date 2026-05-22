"""Deprecated synthetic-seed command (v1 schema).

The v2 iBGC-first schema mints accessions via ``AccessionRegistry`` and
ties CDS / domains to the contig with range-overlap joins. Synthetic
seeding would need to recreate all of those invariants by hand and was
not worth the maintenance cost — for dev work, load real NDJSON dumps
with ``manage.py load_discovery_data`` (see the runbook).

This command stub is preserved so existing scripts / CI references don't
break with an ``Unknown command`` error.
"""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Deprecated. The v2 schema is incompatible with the old synthetic "
        "seed payloads. Use `manage.py load_discovery_data <ndjson_tarball>` "
        "with a real fixture instead."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--num-assemblies", type=int, default=0,
            help="Ignored — kept for backwards compatibility.",
        )
        parser.add_argument(
            "--num-bgcs", type=int, default=0,
            help="Ignored — kept for backwards compatibility.",
        )
        parser.add_argument(
            "--clear", action="store_true",
            help="Ignored — use `--truncate` on `load_discovery_data` instead.",
        )
        parser.add_argument(
            "--small", action="store_true",
            help="Ignored — kept for backwards compatibility.",
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING(
            "seed_discovery_data is deprecated under the v2 iBGC-first schema."
        ))
        self.stdout.write(
            "Load real NDJSON dumps with:\n"
            "    manage.py load_discovery_data <path/to/dump.tgz> [--truncate]\n"
            "or follow docs/runbooks/discovery_seed.md for the staging flow."
        )
