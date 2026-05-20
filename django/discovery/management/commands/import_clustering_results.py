"""Apply an HPC clustering output tarball to the discovery database.

Reads ``clustering_run.json`` + hierarchy/coords/scores/partial parquet files
and writes:

  * a new (or updated-by-sha256) ``ClusteringRun`` row
  * ``DashboardGCF`` nodes for the tree
  * ``IntegratedBGC`` per-row classification (primaries + partial projections)
  * ``DashboardBgc`` back-prop on source BGCs of primary iBGCs
  * ``IntegratedBGCClusteringSnapshot`` per-iBGC pre-import values for rollback

The whole operation is wrapped in ``@transaction.atomic`` so a failure leaves
the live state untouched. ``--dry-run`` validates the tarball and prints a
diff summary without writing anything. ``--force`` allows overwriting an
existing ClusteringRun with the same sha256.
"""

from __future__ import annotations

import logging
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models.expressions import RawSQL
from django.utils import timezone

log = logging.getLogger(__name__)

IBGC_BULK_UPDATE_FIELDS = (
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
        "Import an HPC bgc-cluster output tarball: upsert ClusteringRun, "
        "DashboardGCF, IntegratedBGC, DashboardBgc back-prop, partials, "
        "and rollback snapshot."
    )

    def add_arguments(self, parser):
        parser.add_argument("tarball", type=str)
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Validate the tarball and print a summary; no DB writes.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Overwrite an existing ClusteringRun with the same sha256.",
        )

    def handle(self, *args, **options):
        from common_core.clustering.io import read_outputs_tarball

        tarball = Path(options["tarball"])
        if not tarball.exists():
            raise CommandError(f"Tarball not found: {tarball}")

        payload = read_outputs_tarball(tarball)
        run_meta = payload["run"]
        sha = run_meta["sha256"]
        n_primary = len(payload["hierarchy"]["ibgc_id"])
        n_partials = len(payload["partial_assignments"]["ibgc_id"])

        self.stdout.write(
            f"Tarball: {tarball.name}\n"
            f"  sha256:       {sha}\n"
            f"  device:       {run_meta.get('device')}\n"
            f"  primary iBGCs: {n_primary}\n"
            f"  partial iBGCs: {n_partials}\n"
            f"  GCF nodes:    {len(payload['gcf_nodes']['family_path'])}\n"
            f"  levels:       {run_meta.get('n_levels')}\n"
        )

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("--dry-run: no DB writes performed."))
            return

        run = self._apply(payload, force=options["force"])
        self.stdout.write(
            self.style.SUCCESS(f"Imported ClusteringRun pk={run.pk} sha256={sha[:12]}…")
        )

    @transaction.atomic
    def _apply(self, payload: dict, *, force: bool):
        from discovery.models import (
            ClusteringRun,
            DashboardGCF,
        )

        run_meta = payload["run"]
        sha = run_meta["sha256"]
        params = run_meta.get("params") or {}

        existing = ClusteringRun.objects.filter(sha256=sha).first()
        if existing is not None and not force:
            raise CommandError(
                f"ClusteringRun with sha256={sha[:12]} already exists "
                f"(pk={existing.pk}). Re-run with --force to overwrite.",
            )

        libs = run_meta.get("library_versions", {}) or {}
        defaults = {
            "domain_sources": params.get("domain_sources", []),
            "score_weights": params.get("score_weights", []),
            "knn_k": int(params.get("knn_k") or 0),
            "leiden_resolutions": params.get("leiden_resolutions", []),
            "seed": int(params.get("seed") or 42),
            "n_proteins": 0,
            "n_ibgcs": int(run_meta.get("n_ibgcs", 0)),
            "n_levels": int(run_meta.get("n_levels", 0)),
            "n_root_communities": int(run_meta.get("n_root_communities", 0)),
            "n_leaf_communities": int(run_meta.get("n_leaf_communities", 0)),
            "igraph_version": libs.get("igraph", ""),
            "leidenalg_version": libs.get("leidenalg", ""),
            "umap_version": libs.get("umap-learn", "") or libs.get("cuml", ""),
            "scipy_version": libs.get("scipy", ""),
        }
        run, created = ClusteringRun.objects.update_or_create(
            sha256=sha, defaults=defaults,
        )
        log.info(
            "%s ClusteringRun pk=%s sha=%s",
            "Created" if created else "Updated", run.pk, sha[:12],
        )

        # GCF tree — wipe and replace this run's nodes.
        DashboardGCF.objects.filter(clustering_run=run).delete()
        self._import_gcfs(run, payload["gcf_nodes"])

        # Snapshot the *current* per-iBGC columns of every iBGC we'll touch,
        # so set_active_clustering_run can roll back.
        primary_ids = [int(x) for x in payload["hierarchy"]["ibgc_id"]]
        partial_ids = [int(x) for x in payload["partial_assignments"]["ibgc_id"]]
        touched_ids = primary_ids + partial_ids
        if touched_ids:
            self._snapshot_existing(run, touched_ids)

        # Apply primary iBGC classification.
        now = timezone.now()
        self._update_primary_ibgcs(run, payload, now)

        # Back-propagate to source DashboardBgcs.
        self._backprop_dashboard_bgcs(run, payload, now)

        # Apply partial projections.
        self._update_partial_ibgcs(run, payload, now)

        return run

    # ── GCF tree ────────────────────────────────────────────────────────────

    def _import_gcfs(self, run, gcf_table: dict):
        from discovery.models import DashboardBgc, DashboardGCF

        rep_ibgc_ids = [int(x) for x in gcf_table.get("representative_ibgc_id", [])]
        # Resolve representative_ibgc_id -> a source DashboardBgc.id once per iBGC.
        rep_bgc_map: dict[int, int | None] = {}
        if rep_ibgc_ids:
            unique_ids = list({i for i in rep_ibgc_ids if i})
            qs = (
                DashboardBgc.objects.filter(
                    integrated_bgc_id__in=_bigint_array_in(unique_ids),
                )
                .order_by("integrated_bgc_id", "id")
                .values_list("integrated_bgc_id", "id")
            )
            for ibgc_id, bgc_id in qs:
                rep_bgc_map.setdefault(int(ibgc_id), int(bgc_id))

        rows: list[DashboardGCF] = []
        n = len(gcf_table.get("family_path", []))
        for i in range(n):
            rep_ibgc = rep_ibgc_ids[i] if i < len(rep_ibgc_ids) else None
            rep_bgc_id = rep_bgc_map.get(int(rep_ibgc)) if rep_ibgc else None
            rows.append(
                DashboardGCF(
                    clustering_run=run,
                    family_path=gcf_table["family_path"][i],
                    parent_path=gcf_table["parent_path"][i] or "",
                    level=int(gcf_table["level"][i]),
                    representative_bgc_id=rep_bgc_id,
                    member_count=int(gcf_table["member_count"][i]),
                    descendant_count=int(gcf_table["descendant_count"][i]),
                )
            )
        DashboardGCF.objects.bulk_create(rows, batch_size=5_000)
        log.info("Imported %d DashboardGCF rows", len(rows))

    # ── Snapshot ────────────────────────────────────────────────────────────

    def _snapshot_existing(self, run, ibgc_ids: list[int]):
        from discovery.models import (
            IntegratedBGC,
            IntegratedBGCClusteringSnapshot,
        )

        existing = list(
            IntegratedBGC.objects.filter(id__in=_bigint_array_in(ibgc_ids))
            .only(
                "id", "umap_x", "umap_y", "umap_projected",
                "gene_cluster_family", "novelty_score", "domain_novelty",
            )
        )
        snaps = [
            IntegratedBGCClusteringSnapshot(
                clustering_run=run,
                ibgc_id=ibgc.id,
                umap_x=ibgc.umap_x,
                umap_y=ibgc.umap_y,
                umap_projected=ibgc.umap_projected,
                gene_cluster_family=ibgc.gene_cluster_family or "",
                novelty_score=ibgc.novelty_score,
                domain_novelty=ibgc.domain_novelty,
            )
            for ibgc in existing
        ]
        # Wipe any existing snapshot rows for this run (idempotent re-import).
        IntegratedBGCClusteringSnapshot.objects.filter(clustering_run=run).delete()
        IntegratedBGCClusteringSnapshot.objects.bulk_create(
            snaps, batch_size=5_000, ignore_conflicts=False,
        )
        log.info("Snapshot wrote %d rows for run pk=%s", len(snaps), run.pk)

    # ── Primary iBGCs ────────────────────────────────────────────────────────

    def _update_primary_ibgcs(self, run, payload: dict, now):
        from discovery.models import IntegratedBGC

        h = payload["hierarchy"]
        coords = payload["coords"]
        scores = payload["scores"]
        n = len(h["ibgc_id"])
        if n == 0:
            return

        coords_by_id = {
            int(coords["ibgc_id"][i]): (
                float(coords["umap_x"][i]),
                float(coords["umap_y"][i]),
            )
            for i in range(len(coords["ibgc_id"]))
        }
        scores_by_id = {
            int(scores["ibgc_id"][i]): (
                scores["novelty_score"][i],
                scores["domain_novelty"][i],
            )
            for i in range(len(scores["ibgc_id"]))
        }

        ibgc_ids = [int(x) for x in h["ibgc_id"]]
        leaf_paths = list(h["leaf_path"])
        rows = list(IntegratedBGC.objects.filter(id__in=_bigint_array_in(ibgc_ids)))
        leaf_by_id = dict(zip(ibgc_ids, leaf_paths))
        for ibgc in rows:
            x, y = coords_by_id.get(ibgc.id, (None, None))
            nv, dn = scores_by_id.get(ibgc.id, (None, None))
            ibgc.umap_x = x
            ibgc.umap_y = y
            ibgc.umap_projected = False
            ibgc.gene_cluster_family = leaf_by_id[ibgc.id]
            ibgc.novelty_score = nv
            ibgc.domain_novelty = dn
            ibgc.classification_run = run
            ibgc.classified_at = now
        IntegratedBGC.objects.bulk_update(
            rows, list(IBGC_BULK_UPDATE_FIELDS), batch_size=5_000,
        )
        log.info("Updated %d primary IntegratedBGC rows", len(rows))

    # ── DashboardBgc back-prop ─────────────────────────────────────────────

    def _backprop_dashboard_bgcs(self, run, payload: dict, now):
        from discovery.models import DashboardBgc

        h = payload["hierarchy"]
        coords = payload["coords"]
        ibgc_ids = [int(x) for x in h["ibgc_id"]]
        if not ibgc_ids:
            return
        leaf_by_id = dict(zip(ibgc_ids, h["leaf_path"]))
        coords_by_id = {
            int(coords["ibgc_id"][i]): (
                float(coords["umap_x"][i]),
                float(coords["umap_y"][i]),
            )
            for i in range(len(coords["ibgc_id"]))
        }

        source_bgcs = list(
            DashboardBgc.objects.filter(
                integrated_bgc_id__in=_bigint_array_in(ibgc_ids),
            ).only(
                "id", "integrated_bgc_id", "umap_x", "umap_y",
                "gene_cluster_family", "classification_source",
                "classification_run_id", "classified_at",
            )
        )
        for bgc in source_bgcs:
            x, y = coords_by_id.get(bgc.integrated_bgc_id, (None, None))
            bgc.umap_x = x
            bgc.umap_y = y
            bgc.gene_cluster_family = leaf_by_id.get(bgc.integrated_bgc_id, "")
            bgc.classification_source = "primary"
            bgc.classification_run = run
            bgc.classified_at = now
        DashboardBgc.objects.bulk_update(
            source_bgcs,
            [
                "umap_x", "umap_y", "gene_cluster_family",
                "classification_source", "classification_run", "classified_at",
            ],
            batch_size=10_000,
        )
        log.info("Back-propagated to %d source DashboardBgc rows", len(source_bgcs))

    # ── Partial projections ────────────────────────────────────────────────

    def _update_partial_ibgcs(self, run, payload: dict, now):
        from discovery.models import IntegratedBGC

        p = payload["partial_assignments"]
        n = len(p["ibgc_id"])
        if n == 0:
            return
        ids = [int(x) for x in p["ibgc_id"]]
        leaf = list(p["leaf_path"])
        ux = [_maybe_float(x) for x in p["umap_x"]]
        uy = [_maybe_float(x) for x in p["umap_y"]]
        nv = [_maybe_float(x) for x in p["novelty_score"]]
        dn = [_maybe_float(x) for x in p["domain_novelty"]]
        by_id = {ids[i]: (leaf[i], ux[i], uy[i], nv[i], dn[i]) for i in range(n)}

        rows = list(IntegratedBGC.objects.filter(id__in=_bigint_array_in(ids)))
        for ibgc in rows:
            leaf_p, x, y, novelty, dom = by_id[ibgc.id]
            ibgc.umap_x = x
            ibgc.umap_y = y
            ibgc.umap_projected = True
            ibgc.gene_cluster_family = leaf_p or ""
            ibgc.novelty_score = novelty
            ibgc.domain_novelty = dom
            ibgc.classification_run = run
            ibgc.classified_at = now
        IntegratedBGC.objects.bulk_update(
            rows, list(IBGC_BULK_UPDATE_FIELDS), batch_size=5_000,
        )
        log.info("Updated %d partial-projection IntegratedBGC rows", len(rows))


# ── Helpers ─────────────────────────────────────────────────────────────────


def _bigint_array_in(ids):
    """Send an id list as one bigint[] parameter to dodge Postgres' 65535-param cap."""
    return RawSQL("SELECT unnest(%s::bigint[])", [list(ids)])


def _maybe_float(x) -> float | None:
    if x is None:
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None
