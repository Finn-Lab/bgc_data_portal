#!/usr/bin/env python
"""
Run inside the cluster.  Arguments:
Calculate UMAP coordinates for a set of embeddings, using PCA for initial dimensionality reduction.
Usage:
    python train_umap.py --input_parquet <embeddings.parquet> --output_prefix <output_prefix>
Where:
"""
import argparse
import json
import os
import hashlib
import tempfile
import tarfile
import joblib
import umap
import numpy as np
import pandas as pd
import sklearn
from pathlib import Path
from shutil import copy2

spec = {
    "n_neighbors": 15,  # number of neighbors for UMAP
    "min_dist": 0.1,  # minimum distance between points in UMAP space
    "metric": "euclidean",  # distance metric for UMAP
    "pca_components": 50,  # number of PCA components to reduce to before UMAP
}


def sha256sum(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def copy(src: str, dst: str) -> None:
    """Copy a file from src to dst, creating directories as needed."""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(src, "rb") as fsrc:
        with open(dst, "wb") as fdst:
            fdst.write(fsrc.read())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--input_parquet", required=True)
    ap.add_argument(
        "--output_dir",
        default=".",
        help="Output directory for the UMAP model and coordinates.",
    )
    args = ap.parse_args()

    df = pd.read_parquet(args.input_parquet)
    ids = df["id"].to_numpy()
    X = np.vstack(df["embedding"].to_numpy())  # each row = np.array

    pca = sklearn.decomposition.PCA(
        n_components=min(spec["pca_components"], X.shape[0] - 1)
    )
    X_reduced = pca.fit_transform(X)

    model = umap.UMAP(
        n_neighbors=min(spec["n_neighbors"], X_reduced.shape[0] - 1),
        min_dist=spec["min_dist"],
        metric=spec["metric"],
    ).fit(X_reduced)

    coords = model.transform(X)  # (n, 2)

    temp_outdir = Path(tempfile.mkdtemp())
    model_file = temp_outdir / "model.joblib"
    coords_file = temp_outdir / "projection.parquet"

    joblib.dump(model, model_file)

    pd.DataFrame(
        {
            "id": ids,
            "x": coords[:, 0].astype("float32"),
            "y": coords[:, 1].astype("float32"),
        }
    ).to_parquet(coords_file, index=False)

    sha = sha256sum(model_file)

    manifest = {
        **{k: spec[k] for k in ("n_neighbors", "min_dist", "metric", "pca_components")},
        "n_samples_fit": len(ids),
        "sha256": sha,
        "model_file": f"model_{sha}.joblib",
        "coords_file": f"projection_{sha}.parquet",
        "sklearn_version": sklearn.__version__,
        "umap_version": umap.__version__,
    }

    manifest_path = temp_outdir / "manifest.json"
    Path(manifest_path).write_text(json.dumps(manifest, indent=2))

    prefix = Path(args.output_dir)
    prefix.mkdir(parents=True, exist_ok=True)

    output_filename = prefix / f"umap_train_{sha}.tgz"
    # make a <prefix>/umap_train_<sha>.tgz with the model, coordinates and manifest
    with tarfile.open(output_filename, "w:gz") as tar:
        tar.add(temp_outdir, arcname=os.path.basename(temp_outdir))

    # success flag
    copy2(Path("/dev/null"), f"{prefix}/_SUCCESS")
    print("Finished UMAP job")
    print(f"OUTPUT_FILE={output_filename}")
