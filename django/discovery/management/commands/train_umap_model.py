"""Management command to train a UMAP model from BGC embeddings.

Trains a UMAP model on a sample of BgcEmbedding vectors, saves it to the
UMAPTransform table, and optionally transforms all embeddings to update
umap_x/umap_y on DashboardBgc.
"""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Train a UMAP model from BGC embeddings and optionally apply it"

    def add_arguments(self, parser):
        parser.add_argument(
            "--n-samples",
            type=int,
            default=50_000,
            help="Number of BGC embeddings to sample for training (default: 50000)",
        )
        parser.add_argument(
            "--stratify-by-gcf",
            action="store_true",
            help="Stratified sampling across gene_cluster_family groups",
        )
        parser.add_argument(
            "--n-neighbors",
            type=int,
            default=15,
            help="UMAP n_neighbors parameter (default: 15)",
        )
        parser.add_argument(
            "--min-dist",
            type=float,
            default=0.1,
            help="UMAP min_dist parameter (default: 0.1)",
        )
        parser.add_argument(
            "--metric",
            type=str,
            default="cosine",
            help="UMAP metric (default: cosine)",
        )
        parser.add_argument(
            "--pca-components",
            type=int,
            default=50,
            help="PCA components for dimensionality reduction before UMAP (default: 50)",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="After training, transform all embeddings and update UMAP coordinates",
        )

    def handle(self, *args, **options):
        import hashlib
        import pickle

        import numpy as np
        import sklearn
        import umap

        from discovery.models import BgcEmbedding, DashboardBgc

        n_samples = options["n_samples"]
        stratify = options["stratify_by_gcf"]

        self.stdout.write(f"Collecting embeddings (target: {n_samples} samples) ...")

        if stratify:
            sample_ids = self._stratified_sample(n_samples)
        else:
            total = BgcEmbedding.objects.count()
            if total <= n_samples:
                sample_ids = list(BgcEmbedding.objects.values_list("bgc_id", flat=True))
            else:
                sample_ids = list(
                    BgcEmbedding.objects.order_by("?").values_list("bgc_id", flat=True)[:n_samples]
                )

        vectors = []
        for _, vector in BgcEmbedding.objects.filter(bgc_id__in=sample_ids).values_list("bgc_id", "vector"):
            vectors.append(vector)

        if not vectors:
            self.stderr.write(self.style.ERROR("No embeddings found."))
            return

        embeddings = np.array(vectors, dtype=np.float32)
        self.stdout.write(f"Collected {embeddings.shape[0]} embeddings, shape {embeddings.shape}")

        # PCA reduction
        pca_components = min(options["pca_components"], embeddings.shape[1], embeddings.shape[0])
        if pca_components < embeddings.shape[1]:
            from sklearn.decomposition import PCA

            self.stdout.write(f"Running PCA to {pca_components} components ...")
            pca = PCA(n_components=pca_components)
            reduced = pca.fit_transform(embeddings)
        else:
            reduced = embeddings
            pca = None

        # UMAP training
        self.stdout.write(
            f"Training UMAP (n_neighbors={options['n_neighbors']}, "
            f"min_dist={options['min_dist']}, metric={options['metric']}) ..."
        )
        reducer = umap.UMAP(
            n_neighbors=options["n_neighbors"],
            min_dist=options["min_dist"],
            metric=options["metric"],
            n_components=2,
            random_state=42,
        )
        coords = reducer.fit_transform(reduced)
        self.stdout.write(f"UMAP training complete, output shape: {coords.shape}")

        # Bundle PCA + UMAP into a single transform pipeline
        model_bundle = {"pca": pca, "umap": reducer}
        model_blob = pickle.dumps(model_bundle)
        model_hash = hashlib.sha256(model_blob).hexdigest()

        # Save to UMAPTransform
        try:
            from mgnify_bgcs.models import UMAPTransform

            obj, created = UMAPTransform.objects.update_or_create(
                sha256=model_hash,
                defaults={
                    "n_samples_fit": len(vectors),
                    "pca_components": pca_components,
                    "n_neighbors": options["n_neighbors"],
                    "min_dist": options["min_dist"],
                    "metric": options["metric"],
                    "sklearn_version": sklearn.__version__,
                    "umap_version": umap.__version__,
                    "model_blob": model_blob,
                },
            )
            action = "Created" if created else "Updated"
            self.stdout.write(self.style.SUCCESS(f"{action} UMAPTransform (pk={obj.pk}, sha256={model_hash[:12]}...)"))
        except ImportError:
            self.stderr.write(self.style.WARNING(
                "mgnify_bgcs app not available — model not saved to DB"
            ))

        if options["apply"]:
            self.stdout.write("Applying UMAP transform to all embeddings ...")
            self._apply_transform(model_bundle)
            self.stdout.write(self.style.SUCCESS("UMAP coordinates updated."))

    def _stratified_sample(self, n_samples: int) -> list[int]:
        """Sample BGC embeddings stratified by gene_cluster_family."""
        from django.db.models import Count

        from discovery.models import BgcEmbedding, DashboardBgc

        # Get families with embedding counts
        families = (
            DashboardBgc.objects.exclude(gene_cluster_family="")
            .filter(embedding__isnull=False)
            .values("gene_cluster_family")
            .annotate(cnt=Count("id"))
            .order_by("-cnt")
        )

        family_list = list(families)
        total_with_family = sum(f["cnt"] for f in family_list)

        # Also count BGCs without family
        no_family_count = BgcEmbedding.objects.filter(
            bgc__gene_cluster_family=""
        ).count()
        total = total_with_family + no_family_count

        if total <= n_samples:
            return list(BgcEmbedding.objects.values_list("bgc_id", flat=True))

        sample_ids = []

        # Proportional sampling per family
        for fam in family_list:
            proportion = fam["cnt"] / total
            n_from_family = max(1, int(proportion * n_samples))
            ids = list(
                DashboardBgc.objects.filter(
                    gene_cluster_family=fam["gene_cluster_family"],
                    embedding__isnull=False,
                )
                .order_by("?")
                .values_list("id", flat=True)[:n_from_family]
            )
            sample_ids.extend(ids)

        # Fill remainder from no-family BGCs
        remaining = n_samples - len(sample_ids)
        if remaining > 0 and no_family_count > 0:
            ids = list(
                BgcEmbedding.objects.filter(bgc__gene_cluster_family="")
                .order_by("?")
                .values_list("bgc_id", flat=True)[:remaining]
            )
            sample_ids.extend(ids)

        return sample_ids[:n_samples]

    def _apply_transform(self, model_bundle: dict) -> None:
        """Transform all embeddings and update UMAP coordinates."""
        import numpy as np

        from discovery.models import BgcEmbedding, DashboardBgc

        BATCH = 10_000

        bgc_ids = []
        vectors = []
        for bgc_id, vector in BgcEmbedding.objects.values_list("bgc_id", "vector"):
            bgc_ids.append(bgc_id)
            vectors.append(vector)

        if not vectors:
            return

        embeddings = np.array(vectors, dtype=np.float32)

        # Apply PCA if present
        pca = model_bundle.get("pca")
        if pca is not None:
            embeddings = pca.transform(embeddings)

        # Apply UMAP transform
        reducer = model_bundle["umap"]
        coords = reducer.transform(embeddings)

        # Batch-update DashboardBgc
        objs = DashboardBgc.objects.in_bulk(bgc_ids)
        batch = []
        for i, bgc_id in enumerate(bgc_ids):
            bgc = objs.get(bgc_id)
            if bgc is None:
                continue
            bgc.umap_x = float(coords[i, 0])
            bgc.umap_y = float(coords[i, 1])
            batch.append(bgc)

            if len(batch) >= BATCH:
                DashboardBgc.objects.bulk_update(batch, ["umap_x", "umap_y"], batch_size=BATCH)
                batch.clear()

        if batch:
            DashboardBgc.objects.bulk_update(batch, ["umap_x", "umap_y"], batch_size=BATCH)
