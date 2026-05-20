"""Rebuild the IntegratedBGC table.

This is the pre-clustering step that consolidates latest-version BGC
predictions into a integrated set: GECCO + SanntiS predictions merged on
transitive interval overlap, plus standalone antiSMASH calls.
"""

from django.core.management.base import BaseCommand

from discovery.tasks import build_integrated_bgcs_task


class Command(BaseCommand):
    help = "Rebuild the IntegratedBGC table from latest-version BGC predictions"

    def add_arguments(self, parser):
        parser.add_argument(
            "--sync",
            action="store_true",
            help="Run synchronously in the current process instead of dispatching to Celery",
        )
        parser.add_argument(
            "--queue",
            type=str,
            default="scores",
        )

    def handle(self, *args, **options):
        if options["sync"]:
            self.stdout.write("Building IntegratedBGC table synchronously ...")
            result = build_integrated_bgcs_task.apply().result
            self.stdout.write(self.style.SUCCESS(f"Done: {result}"))
        else:
            res = build_integrated_bgcs_task.apply_async(queue=options["queue"])
            self.stdout.write(
                self.style.SUCCESS(f"Dispatched build_integrated_bgcs_task: {res.id}")
            )
