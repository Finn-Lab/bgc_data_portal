"""Dispatch a BGC clustering run (domain+adjacency hierarchical-CPM-Leiden).

Operates on the ``NonRedundantBGC`` table (run ``build_non_redundant_bgcs``
first, or pass ``--rebuild-nrb`` to chain it). Partial / antiSMASH-absorbed
DashboardBgcs are handled by the chained ``reclassify_bgcs`` step.
"""

from django.core.management.base import BaseCommand

from discovery.tasks import (
    build_non_redundant_bgcs_task,
    run_bgc_clustering_task,
)


class Command(BaseCommand):
    help = (
        "Dispatch a domain+adjacency hierarchical-CPM-Leiden BGC clustering job "
        "(reads the NonRedundantBGC table; emits MIBiG validation artifacts when "
        "--apply is set)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--domain-sources",
            type=str,
            nargs="+",
            default=["PFAM", "NCBIFAM"],
            help="ref_db sources for domain selection (case-insensitive; default PFAM NCBIFAM)",
        )
        parser.add_argument(
            "--score-weights",
            type=float,
            nargs=2,
            default=[0.5, 0.5],
            metavar=("W_DOMAIN", "W_ADJACENCY"),
            help="Weights for composite Dice (w_domain w_adjacency; default 0.5 0.5)",
        )
        parser.add_argument(
            "--knn-k",
            type=int,
            default=None,
            help=(
                "Top-K neighbours per NRB in the union kNN graph. "
                "If omitted, auto-picks max(5, ceil(ln(n_nrbs)))."
            ),
        )
        parser.add_argument(
            "--leiden-resolutions",
            type=float,
            nargs="+",
            default=[0.03, 0.08, 0.15, 0.25],
            help="CPM resolution_parameter per nesting level (coarsest first)",
        )
        parser.add_argument("--seed", type=int, default=42)
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Persist results to NonRedundantBGC + DashboardBgc + DashboardGCF and emit MIBiG artifacts",
        )
        parser.add_argument(
            "--auto-reclassify",
            action="store_true",
            default=True,
            help="Chain reclassify_bgcs for non-primary DashboardBgcs after applying (default true)",
        )
        parser.add_argument(
            "--no-auto-reclassify",
            action="store_false",
            dest="auto_reclassify",
            help="Skip the post-clustering reclassification chain",
        )
        parser.add_argument(
            "--reclassify-scope",
            type=str,
            default="all_non_primary",
            choices=("partial", "stale", "all_non_primary"),
            help="Scope passed to reclassify_bgcs when auto-chaining",
        )
        parser.add_argument(
            "--score-nrbs",
            action="store_true",
            default=True,
            help=(
                "Compute NRB novelty_score and domain_novelty inline with the "
                "clustering apply step, and chain a partial-NRB UMAP projection "
                "task after reclassify (default true)."
            ),
        )
        parser.add_argument(
            "--no-score-nrbs",
            action="store_false",
            dest="score_nrbs",
            help="Skip NRB scoring and partial-NRB projection.",
        )
        parser.add_argument(
            "--rebuild-nrb",
            action="store_true",
            help="Rebuild the NonRedundantBGC table before clustering (chains build_non_redundant_bgcs)",
        )
        parser.add_argument(
            "--sync",
            action="store_true",
            help="Run synchronously in the current process instead of dispatching to Celery",
        )
        parser.add_argument(
            "--queue",
            type=str,
            default="scores",
            help="Celery queue name (default scores)",
        )

    def handle(self, *args, **options):
        kwargs = {
            "domain_sources": [s.upper() for s in options["domain_sources"]],
            "score_weights": options["score_weights"],
            "knn_k": options["knn_k"],
            "leiden_resolutions": options["leiden_resolutions"],
            "seed": options["seed"],
            "apply": options["apply"],
            "auto_reclassify": options["auto_reclassify"],
            "reclassify_scope": options["reclassify_scope"],
            "score_nrbs": options["score_nrbs"],
        }
        if options["score_nrbs"] and not options["auto_reclassify"]:
            self.stdout.write(self.style.WARNING(
                "--score-nrbs is enabled but --no-auto-reclassify was passed: "
                "primary NRBs will be scored inline, but partial NRBs won't be "
                "projected (the projection step is chained after reclassify)."
            ))
        queue = options["queue"]

        # --sync runs both tasks in-process and sequentially, so there is no
        # race; just dispatch them one after the other.
        if options["sync"]:
            if options["rebuild_nrb"]:
                self.stdout.write("Rebuilding NonRedundantBGC table first ...")
                nrb_result = build_non_redundant_bgcs_task.apply().result
                self.stdout.write(self.style.SUCCESS(f"NRB rebuild: {nrb_result}"))
            self.stdout.write("Running BGC clustering synchronously ...")
            result = run_bgc_clustering_task.apply(kwargs=kwargs).result
            self.stdout.write(self.style.SUCCESS(f"Done: {result}"))
            if isinstance(result, dict) and (artifacts_dir := result.get("artifacts_dir")):
                self.stdout.write(
                    self.style.SUCCESS(f"MIBiG analysis artifacts: {artifacts_dir}")
                )
            return

        # Async + --rebuild-nrb: chain via Celery so the clustering task only
        # fires once the rebuild has succeeded. Dispatching both independently
        # races on the scores queue — the clustering captures NRB ids at the
        # start of its run, then the rebuild deletes/recreates them, and the
        # apply-step bulk_update silently no-ops against stale ids. Using an
        # immutable signature (.si) keeps the build's return value from being
        # prepended as a positional arg to the kwargs-only clustering task,
        # and .set(queue=...) routes the linked task explicitly (link does not
        # inherit the parent task's queue).
        if options["rebuild_nrb"]:
            cluster_sig = run_bgc_clustering_task.si(**kwargs).set(queue=queue)
            async_result = build_non_redundant_bgcs_task.apply_async(
                queue=queue, link=cluster_sig,
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"Dispatched build_non_redundant_bgcs_task: {async_result.id} "
                    "(run_bgc_clustering_task will run on success)"
                )
            )
            return

        res = run_bgc_clustering_task.apply_async(kwargs=kwargs, queue=queue)
        self.stdout.write(
            self.style.SUCCESS(f"Dispatched run_bgc_clustering_task: {res.id}")
        )
