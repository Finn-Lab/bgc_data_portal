"""
Celery tasks that ingest metagenomic packages and populate the new
biosynthetic-gene-cluster schema.

A “package” is a gzipped, newline-delimited-JSON (NDJSON) file that contains
records in the following **order**:

    study, biome, assembly, contig, bgc, protein, domain, cds

Down-stream components can stream-produce it; we stream-consume it so that
100-GB uploads never hit RAM.

The task is fully idempotent: hashes are unique, we upsert on conflicts,
and all inserts are surrounded by `atomic()` transactions.
"""

from __future__ import annotations


from mgnify_bgcs.utils.seqrecord_utils import build_bgc_record
from mgnify_bgcs.utils.helpers import (
    from_queryset_to_website_results,
)

# prefer orjson for speed but fall back to stdlib for environments without it
try:
    import orjson as json  # type: ignore
except Exception:  # pragma: no cover - env-specific
    import json  # type: ignore
import logging
from pathlib import Path
from typing import Any, cast

from celery import shared_task
from django.conf import settings

# from pgvector.django import VectorField
# pgvector is an optional runtime dependency; provide a tiny stub for static checks
try:  # pragma: no cover - env specific
    from pgvector import Vector  # type: ignore
except Exception:  # pragma: no cover - env specific

    class Vector:  # type: ignore[misc]
        def __init__(self, *args, **kwargs):
            self._v = list(args) if args else []

        def __iter__(self):
            return iter(self._v)

        def __len__(self):
            return len(self._v)


from .services.aggregated_bgcs import build_aggregated_for_contigs
from .services.annotate_record import SeqAnnotator
from .services.db_operations import (
    ingest_package as svc_ingest_package,
    export_bgc_embeddings_base64 as svc_export_bgc_embeddings_base64,
    register_umap_transform as svc_register_umap_transform,
)


import json

from mgnify_bgcs.searches import (
    search_bgcs_by_keyword,
    search_bgcs_by_advanced,
    search_bgcs_by_record,
    sequence_bgcs_by_smiles,
)
from .cache_utils import set_job_cache

log = logging.getLogger(__name__)
numeric_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
log.setLevel(numeric_level)


N_EMBEDDING_SAMPLE = 100_000  # max number of embedding to export


# helper functions are provided by mgnify_bgcs.utils.helpers


# ----------------------------------------------------------------------
# API tasks
# ----------------------------------------------------------------------
# DB mantainance specific tasks


@shared_task(name="mgnify_bgcs.tasks.ingest_package", bind=True, acks_late=True)
def ingest_package(self, package_path: str) -> bool:
    """
    Main entry point. `package_path` **must** be on a volume the Django worker can read.
    """
    # Delegate to service which returns counts and touched contigs
    try:
        task_id = getattr(self.request, "id", None)
        set_job_cache(
            search_key=str(task_id), task_id=task_id, timeout=settings.CACHE_TIMEOUT
        )
        package_ingestion_result = svc_ingest_package(package_path)
        touched_contig_ids = package_ingestion_result.get("touched_contig_ids", [])
        # record the celery task id on the result and log it
        log.info("ingest_package running as task id: %s", task_id)

        aggregate_bgcs_result = calculate_aggregated_bgcs(touched_contig_ids)
        log.info(
            "Triggered calculation of aggregated BGCs for %s contigs",
            len(touched_contig_ids),
        )
        package_ingestion_result.update(aggregate_bgcs_result or {})

        set_job_cache(
            search_key=str(task_id),
            results=package_ingestion_result,
            task_id=task_id,
            timeout=settings.CACHE_TIMEOUT,
        )
        return True
    finally:
        package = Path(package_path)
        if package.exists():
            try:
                package.unlink()
                log.info("Deleted package file: %s", package_path)
            except Exception:
                log.exception("Failed to delete package file: %s", package_path)


@shared_task(
    name="mgnify_bgcs.tasks.register_umap_transform", bind=True, acks_late=True
)
def register_umap_transform(
    self,
    model_file: str,
    coords_file: str,
    manifest_file: str,
) -> bool:
    """
    1) Read the coords parquet, update each Bgc.metadata
    2) Record a UMAPTransform row
    Returns the UMAPTransform PK.

    args are {
                "model_file": str(tmpdir / Path(manifest.model_file).name),
                "coords_file": str(tmpdir / Path(manifest.coords_file).name),
                "manifest_file": str(manifest_path),
            }
    """

    # Delegate heavy lifting to service function
    try:
        task_id = getattr(self.request, "id", None)
        set_job_cache(
            search_key=str(task_id), task_id=task_id, timeout=settings.CACHE_TIMEOUT
        )
        pk = svc_register_umap_transform(model_file, coords_file, manifest_file)
        log.info("register_umap_transform running as task id: %s", task_id)
        set_job_cache(
            search_key=str(task_id),
            results={"umap_transform_pk": pk},
            task_id=task_id,
            timeout=settings.CACHE_TIMEOUT,
        )
        return True
    finally:
        # Clean up the files (service doesn't remove artifacts)
        for fp in (Path(model_file), Path(coords_file), Path(manifest_file)):
            try:
                if fp.exists():
                    fp.unlink()
                    log.info("Deleted file: %s", fp)
            except Exception:
                log.exception("Failed to delete file: %s", fp)


@shared_task(
    name="mgnify_bgcs.tasks.calculate_aggregated_bgcs",
    bind=True,
    acks_late=True,
)
def calculate_aggregated_bgcs(self, contig_ids: list[int] | None = None) -> bool:
    """
    Celery entry-point – thin wrapper around the service function so we can
    queue work per-contig if we wish.  Pass `contig_ids=None` to rebuild ALL.
    """
    task_id = getattr(self.request, "id", None)
    set_job_cache(
        search_key=str(task_id), task_id=task_id, timeout=settings.CACHE_TIMEOUT
    )
    created = build_aggregated_for_contigs(contig_ids)
    log.info("calculate_aggregated_bgcs running as task id: %s", task_id)
    log.info("Aggregated-BGC rebuild complete – %s regions created", created)
    set_job_cache(
        search_key=str(task_id),
        results={"created_aggregated_bgcs": created},
        task_id=task_id,
        timeout=settings.CACHE_TIMEOUT,
    )
    return True


@shared_task(
    name="mgnify_bgcs.tasks.export_bgc_embeddings_base64", bind=True, acks_late=True
)
def export_bgc_embeddings_base64() -> Any:
    """
    Return a base64‐encoded Parquet file containing all BGC embeddings
    with detector IS NULL (optionally random‐sampled).
    """
    task_id = getattr(self.request, "id", None)
    log.info("export_bgc_embeddings_base64 running as task id: %s", task_id)
    set_job_cache(
        search_key=str(task_id), task_id=task_id, timeout=settings.CACHE_TIMEOUT
    )
    bgc_embbeddings = svc_export_bgc_embeddings_base64(N_EMBEDDING_SAMPLE)
    set_job_cache(
        search_key=str(task_id),
        results={"embeddings_base64_parquet": bgc_embbeddings},
        task_id=task_id,
        timeout=settings.CACHE_TIMEOUT,
    )
    return True


# ----------------------------------------------------------------------
# SEARCH tasks


@shared_task(name="mgnify_bgcs.tasks.keyword_search", bind=True, akns_late=True)
def keyword_search(self, search_key: str, clean_params: dict) -> Any:
    """
    Search BGCs by keyword and return a DataFrame.
    """
    keyword = clean_params.get("keyword", "")
    log.info("Searching BGCs by keyword: %s", keyword)
    task_id = getattr(self.request, "id", None)
    log.debug("Generated search_key: %s", search_key)
    set_job_cache(
        search_key=str(search_key), task_id=str(task_id), timeout=settings.CACHE_TIMEOUT
    )

    query_rows = search_bgcs_by_keyword(keyword)

    log.info("Found %s BGCs for keyword: %s", len(query_rows), keyword)

    df, result_stats, scatter_data, display_columns = from_queryset_to_website_results(
        query_rows
    )
    # Store primary search payload and task id using helper
    set_job_cache(
        search_key=search_key,
        results={
            "stats": result_stats,
            "df": df,
            "scatter_data": scatter_data,
            "display_columns": display_columns,
        },
        task_id=str(task_id),
        timeout=settings.CACHE_TIMEOUT,
    )

    return True


@shared_task(name="mgnify_bgcs.tasks.advanced_search", bind=True)
def advanced_search(self, search_key: str, clean_params: dict) -> Any:
    """
    Search BGCs by keyword and return a DataFrame.
    """
    log.info("Searching BGCs by criteria: %s", clean_params)
    task_id = getattr(self.request, "id", None)
    log.debug("Generated search_key: %s", search_key)
    set_job_cache(
        search_key=str(search_key), task_id=str(task_id), timeout=settings.CACHE_TIMEOUT
    )

    query_rows = search_bgcs_by_advanced(clean_params)
    log.info("Found %s BGCs for criteria: %s", len(query_rows), clean_params)

    df, result_stats, scatter_data, display_columns = from_queryset_to_website_results(
        query_rows
    )
    # Store primary search payload and task id using helper
    set_job_cache(
        search_key=search_key,
        results={
            "stats": result_stats,
            "df": df,
            "scatter_data": scatter_data,
            "display_columns": display_columns,
        },
        task_id=str(task_id),
        timeout=settings.CACHE_TIMEOUT,
    )

    return True


@shared_task(name="mgnify_bgcs.tasks.sequence_search", bind=True)
def sequence_search(self, search_key: str, clean_params: dict) -> Any:
    """
    Build an SeqIO record with annotated CDS, embeddings, and UMAP projections
    """
    fasta_txt = clean_params.get("sequence")
    if not fasta_txt:
        raise ValueError("No sequence provided for search")

    task_id = getattr(self.request, "id", None)
    log.debug("Generated search_key: %s", search_key)
    set_job_cache(
        search_key=str(search_key), task_id=str(task_id), timeout=settings.CACHE_TIMEOUT
    )

    molecule_type = clean_params.get("sequence_type") or ""
    unit_of_comparison = clean_params.get("unit_of_comparison") or ""
    similarity_measure = clean_params.get("similarity_measure") or ""
    similarity_threshold = float(clean_params.get("similarity_threshold") or 0.0)
    set_similarity_threshold = float(
        clean_params.get("set_similarity_threshold") or 0.0
    )

    sequence_annotator = SeqAnnotator()
    record = sequence_annotator.annotate_sequence_file(
        file_string=fasta_txt,
        molecule_type=cast(Any, molecule_type),
        unit_of_comparison=cast(Any, unit_of_comparison),
        similarity_measure=cast(Any, similarity_measure),
    )

    # ------------------------------------------------------------------
    # 2. Fast similarity search (pgvector + SQL when possible)
    # ------------------------------------------------------------------
    query_rows = search_bgcs_by_record(
        record=record,
        unit_of_comparison=cast(Any, unit_of_comparison),
        similarity_measure=cast(Any, similarity_measure),
        molecule_type=cast(Any, molecule_type),
        similarity_threshold=similarity_threshold,
        set_similarity_threshold=set_similarity_threshold,
    )

    df, result_stats, scatter_data, display_columns = from_queryset_to_website_results(
        query_rows
    )
    display_columns.append({"name": "Similarity", "slug": "similarity"})

    set_job_cache(
        search_key=search_key,
        results={
            "stats": result_stats,
            "df": df,
            "scatter_data": scatter_data,
            "display_columns": display_columns,
        },
        task_id=str(task_id),
        timeout=settings.CACHE_TIMEOUT,
    )

    return True


@shared_task(name="mgnify_bgcs.tasks.compound_search", bind=True)
def compound_search(self, search_key: str, clean_params: dict) -> Any:
    """
    Search BGCs by chemical structure (SMILES) and return a DataFrame.
    """
    log.info(
        "Searching BGCs by chemical structure: %s", clean_params.get("smiles", "")[:20]
    )
    task_id = getattr(self.request, "id", None)
    log.debug("Generated search_key: %s", search_key)
    set_job_cache(
        search_key=str(search_key), task_id=str(task_id), timeout=settings.CACHE_TIMEOUT
    )

    query_smiles = clean_params.get("smiles", "").strip()
    similarity_threshold = float(clean_params.get("similarity_threshold") or 0.0)
    query_rows = sequence_bgcs_by_smiles(
        query_smiles=query_smiles, similarity_threshold=similarity_threshold
    )

    df, result_stats, scatter_data, display_columns = from_queryset_to_website_results(
        query_rows
    )
    # Store primary search payload and task id using helper
    set_job_cache(
        search_key=search_key,
        results={
            "stats": result_stats,
            "df": df,
            "scatter_data": scatter_data,
            "display_columns": display_columns,
        },
        task_id=str(task_id),
        timeout=settings.CACHE_TIMEOUT,
    )

    return True


@shared_task(name="mgnify_bgcs.tasks.collect_bgc_data", bind=True)
def collect_bgc_data(self, search_key: str, clean_params: dict) -> Any:
    log.info("Collecting BGC data for: %s", clean_params.get("bgc_id", ""))
    task_id = getattr(self.request, "id", None)
    log.debug("Generated search_key: %s", search_key)
    set_job_cache(
        search_key=str(search_key), task_id=str(task_id), timeout=settings.CACHE_TIMEOUT
    )

    bgc_id = clean_params.get("bgc_id", None)
    if bgc_id is None:
        raise ValueError("bgc_id must be provided for collect_bgc_data")

    record = build_bgc_record(bgc_id)
    plot_html = record.to_plotly_plot()

    predicted_classes_dict = {
        f.qualifiers["source"][0]: f.qualifiers["BGC_CLASS"]
        for f in record.features
        if f.type == "CLUSTER"
    }
    functional_annotation_dict = {
        "GO Slim": sorted(
            {
                f"- {go}"
                for f in record.features
                if f.type == "ANNOT"
                for go in f.qualifiers.get("GOslim", [])
            }
        )
    }
    # record.annotations can contain non-str values; ensure we pass a string
    record_source = json.loads(str(record.annotations.get("source", "{}")))

    bgc_data_results = {
        "record_genebank_text": record.format("genbank"),
        "plot_html": plot_html,
        "bgc_id": bgc_id,
        "assembly_accession": record_source.get("assembly_accession", ""),
        "assembly_url": (
            f"https://www.ebi.ac.uk/metagenomics/assemblies/{record_source.get('assembly_accession')}"
            if record_source.get("assembly_accession", None)
            else ""
        ),
        "biome_lineage": record_source.get("biome_lineage", ""),
        "predicted_classes_dict": predicted_classes_dict,
        "functional_annotation_dict": functional_annotation_dict,
        "cds_info_dict": record.to_cds_info_dct(),
        "contig_accession": record_source.get("contig_accession", ""),
        "start_position": record_source.get("start_position", 0),
        "end_position": record_source.get("end_position", 0),
    }

    set_job_cache(
        search_key=search_key,
        results=bgc_data_results,
        task_id=str(task_id),
        timeout=settings.CACHE_TIMEOUT,
    )

    return True
