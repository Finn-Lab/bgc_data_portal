"""Management command to recompute all discovery scores.

By default dispatches to Celery on the ``scores`` queue.
Use ``--sync`` for synchronous execution.
"""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Recompute all discovery scores (novelty, assembly aggregates, GCF, catalogs, UMAP)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--sync",
            action="store_true",
            help="Run synchronously instead of dispatching to Celery",
        )

    def handle(self, *args, **options):
        if options["sync"]:
            from discovery.services.scores import recompute_all_scores

            self.stdout.write("Running score recomputation synchronously ...")
            recompute_all_scores()
            self.stdout.write(self.style.SUCCESS("Done."))
        else:
            from discovery.tasks import recompute_scores_task

            result = recompute_scores_task.apply_async(queue="scores")
            self.stdout.write(
                self.style.SUCCESS(f"Dispatched recompute_scores_task: {result.id}")
            )
