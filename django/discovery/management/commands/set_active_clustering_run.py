"""Roll back to a prior ClusteringRun by replaying its snapshot.

Each ``import_clustering_results`` call snapshots the per-NRB classification
columns *before* it overwrites them. This command undoes that overwrite by
restoring the columns from a chosen run's snapshot.
"""

from __future__ import annotations

import logging

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

log = logging.getLogger(__name__)

NRB_RESTORE_FIELDS = (
    "umap_x",
    "umap_y",
    "umap_projected",
    "gene_cluster_family",
    "novelty_score",
    "domain_novelty",
    "classification_run",
    "classified_at",
)


class Command(BaseCommand):
    help = (
        "Restore NonRedundantBGC per-row columns from a ClusteringRun's "
        "import-time snapshot and re-point classification_run."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--sha", required=True,
            help="ClusteringRun.sha256 (full or prefix matching exactly one run).",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Print what would change; no DB writes.",
        )

    def handle(self, *args, **options):
        from discovery.models import ClusteringRun, NonRedundantBGCClusteringSnapshot

        sha_arg = options["sha"]
        match = ClusteringRun.objects.filter(sha256__startswith=sha_arg)
        n_match = match.count()
        if n_match == 0:
            raise CommandError(f"No ClusteringRun matches sha={sha_arg!r}.")
        if n_match > 1:
            raise CommandError(
                f"sha prefix {sha_arg!r} matches {n_match} runs — provide more digits."
            )
        target = match.first()

        n_snaps = NonRedundantBGCClusteringSnapshot.objects.filter(
            clustering_run=target,
        ).count()
        if n_snaps == 0:
            raise CommandError(
                f"ClusteringRun pk={target.pk} has no snapshot rows — cannot roll back."
            )

        self.stdout.write(
            f"Target run: pk={target.pk} sha={target.sha256[:12]}…\n"
            f"  Snapshot rows: {n_snaps}\n"
        )
        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("--dry-run: no DB writes performed."))
            return

        restored = self._apply(target)
        self.stdout.write(
            self.style.SUCCESS(
                f"Restored {restored} NRBs to ClusteringRun pk={target.pk}.",
            ),
        )

    @transaction.atomic
    def _apply(self, target) -> int:
        from discovery.models import (
            NonRedundantBGC,
            NonRedundantBGCClusteringSnapshot,
        )

        snaps = list(
            NonRedundantBGCClusteringSnapshot.objects.filter(clustering_run=target)
        )
        snap_by_id = {s.nrb_id: s for s in snaps}
        now = timezone.now()

        nrbs = list(NonRedundantBGC.objects.filter(id__in=list(snap_by_id.keys())))
        for nrb in nrbs:
            s = snap_by_id[nrb.id]
            nrb.umap_x = s.umap_x
            nrb.umap_y = s.umap_y
            nrb.umap_projected = s.umap_projected
            nrb.gene_cluster_family = s.gene_cluster_family or ""
            nrb.novelty_score = s.novelty_score
            nrb.domain_novelty = s.domain_novelty
            nrb.classification_run = target
            nrb.classified_at = now
        NonRedundantBGC.objects.bulk_update(
            nrbs, list(NRB_RESTORE_FIELDS), batch_size=5_000,
        )
        log.info(
            "set_active_clustering_run: restored %d NRBs to run pk=%s",
            len(nrbs), target.pk,
        )
        return len(nrbs)
