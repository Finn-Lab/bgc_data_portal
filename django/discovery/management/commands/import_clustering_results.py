"""Apply an HPC clustering output tarball to the discovery database.

Reads ``clustering_run.json`` + hierarchy/coords/scores/partial parquet files
and writes:

  * a new (or updated-by-sha256) ``ClusteringRun`` row
  * ``DashboardGCF`` nodes for the tree
  * ``NonRedundantBGC`` per-row classification (primaries + partial projections)
  * ``DashboardBgc`` back-prop on source BGCs of primary NRBs
  * ``NonRedundantBGCClusteringSnapshot`` per-NRB pre-import values for rollback

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

NRB_BULK_UPDATE_FIELDS = (
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
        "DashboardGCF, NonRedundantBGC, DashboardBgc back-prop, partials, "
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
        n_primary = len(payload["hierarchy"]["nrb_id"])
        n_partials = len(payload["partial_assignments"]["nrb_id"])

        self.stdout.write(
            f"Tarball: {tarball.name}\n"
            f"  sha256:       {sha}\n"
            f"  device:       {run_meta.get('device')}\n"
            f"  primary NRBs: {n_primary}\n"
            f"  partial NRBs: {n_partials}\n"
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
            "n_nrbs": int(run_meta.get("n_nrbs", 0)),
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

        # Snapshot the *current* per-NRB columns of every NRB we'll touch,
        # so set_active_clustering_run can roll back.
        primary_ids = [int(x) for x in payload["hierarchy"]["nrb_id"]]
        partial_ids = [int(x) for x in payload["partial_assignments"]["nrb_id"]]
        touched_ids = primary_ids + partial_ids
        if touched_ids:
            self._snapshot_existing(run, touched_ids)

        # Apply primary NRB classification.
        now = timezone.now()
        self._update_primary_nrbs(run, payload, now)

        # Back-propagate to source DashboardBgcs.
        self._backprop_dashboard_bgcs(run, payload, now)

        # Apply partial projections.
        self._update_partial_nrbs(run, payload, now)

        return run

    # ── GCF tree ────────────────────────────────────────────────────────────

    def _import_gcfs(self, run, gcf_table: dict):
        from discovery.models import DashboardBgc, DashboardGCF

        rep_nrb_ids = [int(x) for x in gcf_table.get("representative_nrb_id", [])]
        # Resolve representative_nrb_id -> a source DashboardBgc.id once per NRB.
        rep_bgc_map: dict[int, int | None] = {}
        if rep_nrb_ids:
            unique_ids = list({i for i in rep_nrb_ids if i})
            qs = (
                DashboardBgc.objects.filter(
                    non_redundant_bgc_id__in=_bigint_array_in(unique_ids),
                )
                .order_by("non_redundant_bgc_id", "id")
                .values_list("non_redundant_bgc_id", "id")
            )
            for nrb_id, bgc_id in qs:
                rep_bgc_map.setdefault(int(nrb_id), int(bgc_id))

        rows: list[DashboardGCF] = []
        n = len(gcf_table.get("family_path", []))
        for i in range(n):
            rep_nrb = rep_nrb_ids[i] if i < len(rep_nrb_ids) else None
            rep_bgc_id = rep_bgc_map.get(int(rep_nrb)) if rep_nrb else None
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

    def _snapshot_existing(self, run, nrb_ids: list[int]):
        from discovery.models import (
            NonRedundantBGC,
            NonRedundantBGCClusteringSnapshot,
        )

        existing = list(
            NonRedundantBGC.objects.filter(id__in=_bigint_array_in(nrb_ids))
            .only(
                "id", "umap_x", "umap_y", "umap_projected",
                "gene_cluster_family", "novelty_score", "domain_novelty",
            )
        )
        snaps = [
            NonRedundantBGCClusteringSnapshot(
                clustering_run=run,
                nrb_id=nrb.id,
                umap_x=nrb.umap_x,
                umap_y=nrb.umap_y,
                umap_projected=nrb.umap_projected,
                gene_cluster_family=nrb.gene_cluster_family or "",
                novelty_score=nrb.novelty_score,
                domain_novelty=nrb.domain_novelty,
            )
            for nrb in existing
        ]
        # Wipe any existing snapshot rows for this run (idempotent re-import).
        NonRedundantBGCClusteringSnapshot.objects.filter(clustering_run=run).delete()
        NonRedundantBGCClusteringSnapshot.objects.bulk_create(
            snaps, batch_size=5_000, ignore_conflicts=False,
        )
        log.info("Snapshot wrote %d rows for run pk=%s", len(snaps), run.pk)

    # ── Primary NRBs ────────────────────────────────────────────────────────

    def _update_primary_nrbs(self, run, payload: dict, now):
        from discovery.models import NonRedundantBGC

        h = payload["hierarchy"]
        coords = payload["coords"]
        scores = payload["scores"]
        n = len(h["nrb_id"])
        if n == 0:
            return

        coords_by_id = {
            int(coords["nrb_id"][i]): (
                float(coords["umap_x"][i]),
                float(coords["umap_y"][i]),
            )
            for i in range(len(coords["nrb_id"]))
        }
        scores_by_id = {
            int(scores["nrb_id"][i]): (
                scores["novelty_score"][i],
                scores["domain_novelty"][i],
            )
            for i in range(len(scores["nrb_id"]))
        }

        nrb_ids = [int(x) for x in h["nrb_id"]]
        leaf_paths = list(h["leaf_path"])
        rows = list(NonRedundantBGC.objects.filter(id__in=_bigint_array_in(nrb_ids)))
        leaf_by_id = dict(zip(nrb_ids, leaf_paths))
        for nrb in rows:
            x, y = coords_by_id.get(nrb.id, (None, None))
            nv, dn = scores_by_id.get(nrb.id, (None, None))
            nrb.umap_x = x
            nrb.umap_y = y
            nrb.umap_projected = False
            nrb.gene_cluster_family = leaf_by_id[nrb.id]
            nrb.novelty_score = nv
            nrb.domain_novelty = dn
            nrb.classification_run = run
            nrb.classified_at = now
        NonRedundantBGC.objects.bulk_update(
            rows, list(NRB_BULK_UPDATE_FIELDS), batch_size=5_000,
        )
        log.info("Updated %d primary NonRedundantBGC rows", len(rows))

    # ── DashboardBgc back-prop ─────────────────────────────────────────────

    def _backprop_dashboard_bgcs(self, run, payload: dict, now):
        from discovery.models import DashboardBgc

        h = payload["hierarchy"]
        coords = payload["coords"]
        nrb_ids = [int(x) for x in h["nrb_id"]]
        if not nrb_ids:
            return
        leaf_by_id = dict(zip(nrb_ids, h["leaf_path"]))
        coords_by_id = {
            int(coords["nrb_id"][i]): (
                float(coords["umap_x"][i]),
                float(coords["umap_y"][i]),
            )
            for i in range(len(coords["nrb_id"]))
        }

        source_bgcs = list(
            DashboardBgc.objects.filter(
                non_redundant_bgc_id__in=_bigint_array_in(nrb_ids),
            ).only(
                "id", "non_redundant_bgc_id", "umap_x", "umap_y",
                "gene_cluster_family", "classification_source",
                "classification_run_id", "classified_at",
            )
        )
        for bgc in source_bgcs:
            x, y = coords_by_id.get(bgc.non_redundant_bgc_id, (None, None))
            bgc.umap_x = x
            bgc.umap_y = y
            bgc.gene_cluster_family = leaf_by_id.get(bgc.non_redundant_bgc_id, "")
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

    def _update_partial_nrbs(self, run, payload: dict, now):
        from discovery.models import NonRedundantBGC

        p = payload["partial_assignments"]
        n = len(p["nrb_id"])
        if n == 0:
            return
        ids = [int(x) for x in p["nrb_id"]]
        leaf = list(p["leaf_path"])
        ux = [_maybe_float(x) for x in p["umap_x"]]
        uy = [_maybe_float(x) for x in p["umap_y"]]
        nv = [_maybe_float(x) for x in p["novelty_score"]]
        dn = [_maybe_float(x) for x in p["domain_novelty"]]
        by_id = {ids[i]: (leaf[i], ux[i], uy[i], nv[i], dn[i]) for i in range(n)}

        rows = list(NonRedundantBGC.objects.filter(id__in=_bigint_array_in(ids)))
        for nrb in rows:
            leaf_p, x, y, novelty, dom = by_id[nrb.id]
            nrb.umap_x = x
            nrb.umap_y = y
            nrb.umap_projected = True
            nrb.gene_cluster_family = leaf_p or ""
            nrb.novelty_score = novelty
            nrb.domain_novelty = dom
            nrb.classification_run = run
            nrb.classified_at = now
        NonRedundantBGC.objects.bulk_update(
            rows, list(NRB_BULK_UPDATE_FIELDS), batch_size=5_000,
        )
        log.info("Updated %d partial-projection NonRedundantBGC rows", len(rows))


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
