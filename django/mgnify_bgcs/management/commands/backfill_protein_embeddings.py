import os
from typing import List, Tuple, Optional

import numpy as np
import pyarrow.dataset as ds

from django.core.management.base import BaseCommand
from django.db import connection, transaction

try:
    # psycopg v3
    from psycopg import sql
    from psycopg.extras import execute_values
except Exception:
    sql = None
    execute_values = None

DIM = 1152
TABLE_NAME = "mgnify_bgcs_protein"
INDEX_NAME = "protein_embedding_hnsw"
STAGE_TABLE = "protein_embedding_stage"


def pgvector_literal(vec: np.ndarray) -> str:
    v = np.asarray(vec, dtype=np.float32)
    return "[" + ",".join(f"{x:.8g}" for x in v) + "]"


def iter_parquet_files(root_dirs: List[str]) -> List[str]:
    files: List[str] = []
    for root in root_dirs:
        for dirpath, _, filenames in os.walk(root):
            for fn in filenames:
                if fn.endswith(".parquet"):
                    files.append(os.path.join(dirpath, fn))
    if not files:
        raise FileNotFoundError(f"No .parquet files found under: {root_dirs}")
    return files


def decode_vector(blob: bytes, dtype_name: Optional[str]) -> np.ndarray:
    if dtype_name == "float16":
        return np.frombuffer(blob, dtype="<f2").astype(np.float32, copy=False)
    return np.frombuffer(blob, dtype="<f4").astype(np.float32, copy=False)


def ensure_stage_table() -> None:
    with connection.cursor() as cur:
        cur.execute(
            f"""
            CREATE UNLOGGED TABLE IF NOT EXISTS {STAGE_TABLE} (
                sequence_sha256 text PRIMARY KEY,
                embedding vector({DIM}) NOT NULL
            );
        """
        )


def drop_hnsw_index() -> None:
    connection.set_autocommit(True)
    try:
        with connection.cursor() as cur:
            cur.execute(f"DROP INDEX IF EXISTS {INDEX_NAME};")
    finally:
        connection.set_autocommit(False)


def create_hnsw_index() -> None:
    connection.set_autocommit(True)
    try:
        with connection.cursor() as cur:
            cur.execute(
                f"""
                CREATE INDEX CONCURRENTLY {INDEX_NAME}
                ON {TABLE_NAME}
                USING hnsw (embedding vector_cosine_ops)
                WITH (m = 16, ef_construction = 512);
            """
            )
    finally:
        connection.set_autocommit(False)


def load_stage_rows(rows: List[Tuple[str, str]]) -> None:
    """
    Bulk load rows into stage table using psycopg3 COPY.
    rows: [(sha, pgvector_literal), ...]
    """
    raw_conn = connection.connection  # psycopg.Connection (v3)

    with raw_conn.cursor() as cur:
        cur.execute(f"TRUNCATE {STAGE_TABLE};")

        with cur.copy(
            f"COPY {STAGE_TABLE} (sequence_sha256, embedding) FROM STDIN"
        ) as copy:

            for sha, vec_lit in rows:
                # COPY expects tab-separated values in text mode
                line = f"{sha}\t{vec_lit}\n"
                copy.write(line.encode("utf-8"))


def apply_stage_update(only_null: bool) -> None:
    with connection.cursor() as cur:
        if only_null:
            cur.execute(
                f"""
                UPDATE {TABLE_NAME} p
                SET embedding = s.embedding
                FROM {STAGE_TABLE} s
                WHERE p.sequence_sha256 = s.sequence_sha256
                  AND p.embedding IS NULL;
            """
            )
        else:
            cur.execute(
                f"""
                UPDATE {TABLE_NAME} p
                SET embedding = s.embedding
                FROM {STAGE_TABLE} s
                WHERE p.sequence_sha256 = s.sequence_sha256;
            """
            )


class Command(BaseCommand):
    help = "Backfill Protein.embedding from parquet files under one or more directories (psycopg3-compatible)."

    def add_arguments(self, parser):
        parser.add_argument("--parquet-dir", nargs="+", required=True)
        parser.add_argument("--batch-proteins", type=int, default=20_000)
        parser.add_argument("--only-null", action="store_true")
        parser.add_argument("--rebuild-index", action="store_true")
        parser.add_argument(
            "--dtype-column",
            action="store_true",
            help="If set, use parquet column 'dtype' (float16/float32) to decode ith_blob.",
        )

    def handle(self, *args, **opts):
        root_dirs: List[str] = opts["parquet_dir"]
        batch_target: int = opts["batch_proteins"]
        only_null: bool = opts["only_null"]
        rebuild_index: bool = opts["rebuild_index"]
        use_dtype_col: bool = opts["dtype_column"]

        parquet_files = iter_parquet_files(root_dirs)
        dataset = ds.dataset(parquet_files, format="parquet")

        cols = ["protein_sequence_sha256", "ith_blob", "ith_dim"]
        if use_dtype_col:
            cols.append("dtype")

        if rebuild_index:
            self.stdout.write("Dropping HNSW index...")
            drop_hnsw_index()

        ensure_stage_table()

        scanner = dataset.scanner(columns=cols, batch_size=100_000)

        pending: List[Tuple[str, str]] = []
        staged_total = 0
        skipped_bad_dim = 0

        def flush():
            nonlocal pending, staged_total
            if not pending:
                return
            with transaction.atomic():
                load_stage_rows(pending)  # TRUNCATE + INSERT VALUES (...)
                apply_stage_update(only_null)
            staged_total += len(pending)
            pending = []

        for rb in scanner.to_batches():
            d = rb.to_pydict()
            shas = d["protein_sequence_sha256"]
            blobs = d["ith_blob"]
            dims = d["ith_dim"]
            dtypes = d.get("dtype") if use_dtype_col else None

            for i in range(len(shas)):
                sha = shas[i]
                blob = blobs[i]
                ith_dim = int(dims[i] or 0)

                if blob is None:
                    continue
                if ith_dim != DIM:
                    skipped_bad_dim += 1
                    continue

                dtype_name = dtypes[i] if dtypes is not None else None
                vec = decode_vector(blob, dtype_name=dtype_name)

                if vec.shape[0] != DIM:
                    raise ValueError(
                        f"Decoded length mismatch for {sha}: decoded={vec.shape[0]} ith_dim={ith_dim} expected={DIM}"
                    )

                pending.append((sha, pgvector_literal(vec)))

                if len(pending) >= batch_target:
                    flush()

        flush()

        if rebuild_index:
            self.stdout.write("Rebuilding HNSW index (CONCURRENTLY)...")
            create_hnsw_index()

        self.stdout.write(
            self.style.SUCCESS(
                f"Completed embedding backfill from {len(parquet_files)} parquet files. "
                f"staged={staged_total} skipped_bad_dim={skipped_bad_dim}"
            )
        )
