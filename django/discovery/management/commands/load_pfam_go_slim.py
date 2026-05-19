"""Deprecated. Renamed to ``backfill_go_slim``.

The Pfam-keyed slim mapping was retired when ETL began emitting per-signature
``go_terms`` from InterProScan. This shim forwards to the new command so any
cron / runbook keeps working for one release. Remove after the next minor.
"""

import warnings

from .backfill_go_slim import Command as BackfillCommand


class Command(BackfillCommand):
    help = (
        "DEPRECATED: use `manage.py backfill_go_slim` instead. "
        + BackfillCommand.help
    )

    def handle(self, *args, **options):
        warnings.warn(
            "`load_pfam_go_slim` is deprecated; use `backfill_go_slim`.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.stdout.write(
            self.style.WARNING(
                "DEPRECATED: `load_pfam_go_slim` is renamed to `backfill_go_slim`. "
                "Update your callers."
            )
        )
        return super().handle(*args, **options)
