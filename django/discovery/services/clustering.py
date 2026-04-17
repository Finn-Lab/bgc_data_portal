"""Pure pipeline functions for BGC clustering.

All heavy imports (numpy, sklearn, umap, hdbscan) are deferred inside each
function body so this module can be imported on the web container without
those packages installed.

Pipeline:
  BgcEmbedding (960-dim)
    → PCA(50, whiten=True)
    → UMAP-20d  (clustering space)
    → HDBSCAN   (cluster labels)
    → KNN       (classify remaining BGCs)
    → UMAP-2d   (visualization coordinates, replaces DashboardBgc.umap_x/y)
"""

from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import numpy as np

log = logging.getLogger(__name__)

BATCH = 10_000


def build_training_sample(
    n_samples: int = 100_000,
) -> tuple[list[int], "np.ndarray"]:
    """Return (bgc_ids, float32 N×960 embedding matrix) for the training sample.

    Guarantees all is_validated BGCs are included. The remainder is filled with
    random non-partial, non-validated BGCs up to n_samples total.
    """
    import numpy as np

    from discovery.models import BgcEmbedding

    validated_ids = list(
        BgcEmbedding.objects.filter(bgc__is_validated=True).values_list(
            "bgc_id", flat=True
        )
    )
    log.info("Found %d validated BGCs", len(validated_ids))

    remaining = max(0, n_samples - len(validated_ids))
    pool_ids = list(
        BgcEmbedding.objects.filter(
            bgc__is_validated=False,
            bgc__is_partial=False,
        )
        .exclude(bgc_id__in=validated_ids)
        .order_by("?")
        .values_list("bgc_id", flat=True)[:remaining]
    )

    final_ids = validated_ids + pool_ids
    log.info("Training sample: %d BGCs total (%d validated + %d random)",
             len(final_ids), len(validated_ids), len(pool_ids))

    vectors = list(
        BgcEmbedding.objects.filter(bgc_id__in=final_ids).values_list(
            "vector", flat=True
        )
    )
    embeddings = np.array(vectors, dtype=np.float32)
    return final_ids, embeddings


def run_pca(
    embeddings: "np.ndarray",
    n_components: int = 50,
) -> tuple["np.ndarray", Any]:
    """Fit PCA(n_components, whiten=True). Return (reduced, pca_obj)."""
    from sklearn.decomposition import PCA

    log.info("Running PCA to %d components (whiten=True)", n_components)
    pca = PCA(n_components=n_components, whiten=True)
    reduced = pca.fit_transform(embeddings)
    log.info("PCA complete: %s → %s", embeddings.shape, reduced.shape)
    return reduced, pca


def run_umap(
    reduced: "np.ndarray",
    n_neighbors: int = 30,
    min_dist: float = 0.0,
    n_components: int = 20,
    metric: str = "euclidean",
    random_state: int = 42,
) -> tuple["np.ndarray", Any]:
    """Fit UMAP for clustering space. Return (coords N×n_components, umap_obj)."""
    import umap as umap_lib

    log.info(
        "Training UMAP-20d (n_neighbors=%d, min_dist=%.3f, metric=%s, n_components=%d)",
        n_neighbors, min_dist, metric, n_components,
    )
    reducer = umap_lib.UMAP(
        n_neighbors=n_neighbors,
        min_dist=min_dist,
        n_components=n_components,
        metric=metric,
        random_state=random_state,
    )
    coords = reducer.fit_transform(reduced)
    log.info("UMAP-20d complete: %s", coords.shape)
    return coords, reducer


def run_hdbscan(
    umap_coords: "np.ndarray",
    min_cluster_size: int = 20,
    min_samples: int = 5,
    metric: str = "euclidean",
) -> tuple["np.ndarray", Any]:
    """Fit HDBSCAN on umap_coords. Return (labels N, hdbscan_obj). labels==-1 for noise."""
    import hdbscan

    log.info(
        "Running HDBSCAN (min_cluster_size=%d, min_samples=%d, metric=%s)",
        min_cluster_size, min_samples, metric,
    )
    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=min_cluster_size,
        min_samples=min_samples,
        metric=metric,
    )
    labels = clusterer.fit_predict(umap_coords)
    n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
    n_noise = int((labels == -1).sum())
    log.info("HDBSCAN complete: %d clusters, %d noise points", n_clusters, n_noise)
    return labels, clusterer


def train_knn(
    umap_coords: "np.ndarray",
    labels: "np.ndarray",
    k: int = 5,
) -> Any:
    """Fit KNeighborsClassifier on non-noise points. Return fitted knn_obj."""
    from sklearn.neighbors import KNeighborsClassifier

    mask = labels != -1
    X_train = umap_coords[mask]
    y_train = labels[mask]
    log.info("Training KNN (k=%d) on %d non-noise points", k, len(X_train))
    knn = KNeighborsClassifier(n_neighbors=k, metric="euclidean", n_jobs=-1)
    knn.fit(X_train, y_train)
    return knn


def run_umap_2d(
    umap_20d_coords: "np.ndarray",
    random_state: int = 42,
) -> tuple["np.ndarray", Any]:
    """Fit UMAP(n_components=2) on 20-dim coords for visualization.

    These coordinates replace DashboardBgc.umap_x/y.
    """
    import umap as umap_lib

    log.info("Training UMAP-2d for visualization on %s input", umap_20d_coords.shape)
    reducer = umap_lib.UMAP(n_components=2, random_state=random_state)
    coords = reducer.fit_transform(umap_20d_coords)
    log.info("UMAP-2d complete: %s", coords.shape)
    return coords, reducer


def classify_remaining(
    knn: Any,
    pca: Any,
    umap_reducer: Any,
    umap2d_reducer: Any,
    excluded_bgc_ids: set[int],
) -> dict[int, tuple[int, float, float]]:
    """Transform all BGCs not in excluded_bgc_ids through PCA→UMAP-20d→KNN+UMAP-2d.

    Returns {bgc_id: (cluster_label_int, umap_x, umap_y)} in batches of BATCH rows.
    """
    import numpy as np

    from discovery.models import BgcEmbedding

    qs = BgcEmbedding.objects.exclude(bgc_id__in=excluded_bgc_ids).values_list(
        "bgc_id", "vector"
    )
    total = qs.count()
    log.info("Classifying %d remaining BGCs via KNN", total)

    results: dict[int, tuple[int, float, float]] = {}
    batch_ids: list[int] = []
    batch_vecs: list = []

    def _flush():
        if not batch_ids:
            return
        arr = np.array(batch_vecs, dtype=np.float32)
        arr = pca.transform(arr)
        arr20 = umap_reducer.transform(arr)
        arr2 = umap2d_reducer.transform(arr20)
        preds = knn.predict(arr20)
        for bid, label, xy in zip(batch_ids, preds, arr2):
            results[bid] = (int(label), float(xy[0]), float(xy[1]))
        batch_ids.clear()
        batch_vecs.clear()

    for bgc_id, vector in qs.iterator(chunk_size=BATCH):
        batch_ids.append(bgc_id)
        batch_vecs.append(vector)
        if len(batch_ids) >= BATCH:
            _flush()

    _flush()
    log.info("KNN classification complete: %d BGCs assigned", len(results))
    return results


def pick_representative(
    bgc_ids: list[int],
    umap_coords: "np.ndarray",
) -> int:
    """Return bgc_id closest to the centroid of the cluster (medoid selection)."""
    import numpy as np

    centroid = umap_coords.mean(axis=0)
    dists = np.linalg.norm(umap_coords - centroid, axis=1)
    return bgc_ids[int(dists.argmin())]


def compute_bundle_sha256(
    pca_blob: bytes,
    umap_blob: bytes,
    hdbscan_blob: bytes,
    knn_blob: bytes,
    umap2d_blob: bytes,
) -> str:
    """Return sha256 hex digest of the five blobs concatenated."""
    h = hashlib.sha256()
    for blob in (pca_blob, umap_blob, hdbscan_blob, knn_blob, umap2d_blob):
        h.update(blob)
    return h.hexdigest()
