"""Dispatch a BGC clustering run to the Celery worker.

Supersedes ``train_umap_model``. This pipeline produces cluster assignments,
GCF annotations, and DashboardBgc.umap_x/y visualization coordinates in one pass.
"""

from django.core.management.base import BaseCommand

from discovery.tasks import run_bgc_clustering_task


class Command(BaseCommand):
    help = "Dispatch a BGC clustering job (PCA→UMAP-20d→HDBSCAN→KNN→UMAP-2d) to Celery"

    def add_arguments(self, parser):
        parser.add_argument("--n-samples", type=int, default=100_000)
        parser.add_argument("--pca-components", type=int, default=50)
        parser.add_argument("--umap-n-neighbors", type=int, default=30)
        parser.add_argument("--umap-min-dist", type=float, default=0.0)
        parser.add_argument("--umap-n-components", type=int, default=20)
        parser.add_argument("--umap-metric", type=str, default="euclidean")
        parser.add_argument("--hdbscan-min-cluster-size", type=int, default=20)
        parser.add_argument("--hdbscan-min-samples", type=int, default=5)
        parser.add_argument("--knn-k", type=int, default=5)
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Update DashboardBgc.gene_cluster_family and DashboardGCF records after clustering",
        )
        parser.add_argument(
            "--sync",
            action="store_true",
            help="Run synchronously in the current process instead of dispatching to Celery",
        )

    def handle(self, *args, **options):
        kwargs = {
            "n_samples": options["n_samples"],
            "pca_components": options["pca_components"],
            "umap_n_neighbors": options["umap_n_neighbors"],
            "umap_min_dist": options["umap_min_dist"],
            "umap_n_components": options["umap_n_components"],
            "umap_metric": options["umap_metric"],
            "hdbscan_min_cluster_size": options["hdbscan_min_cluster_size"],
            "hdbscan_min_samples": options["hdbscan_min_samples"],
            "knn_k": options["knn_k"],
            "apply": options["apply"],
        }
        if options["sync"]:
            self.stdout.write("Running BGC clustering synchronously ...")
            run_bgc_clustering_task.apply(kwargs=kwargs)
            self.stdout.write(self.style.SUCCESS("Done."))
        else:
            result = run_bgc_clustering_task.apply_async(kwargs=kwargs, queue="scores")
            self.stdout.write(
                self.style.SUCCESS(f"Dispatched run_bgc_clustering_task: {result.id}")
            )
