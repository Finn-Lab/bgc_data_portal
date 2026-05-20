"""Export per-iBGC signature matrices for an HPC clustering run.

Builds the small inputs the HPC ``bgc-cluster`` CLI needs (M_domains,
M_pairs, vocabs, ibgc_ids for primaries and partials, validated subset) and
writes them as a single ``.tgz`` under ``CLUSTERING_ARTIFACTS_DIR/exports/``.
No N×N matrix is produced — that's the whole point of the HPC handoff.
"""

from __future__ import annotations

import datetime as _dt
import logging
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

log = logging.getLogger(__name__)


DEFAULT_DOMAIN_SOURCES = ("PFAM", "NCBIFAM","TIGRFAM")


class Command(BaseCommand):
    help = (
        "Export per-iBGC signature matrices as a tarball for the HPC "
        "bgc-cluster job. Writes to CLUSTERING_ARTIFACTS_DIR/exports/<tag>.tgz."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--run-tag",
            type=str,
            default=None,
            help="Tag for the export filename (default: UTC timestamp).",
        )
        parser.add_argument(
            "--domain-sources",
            type=str,
            nargs="+",
            default=list(DEFAULT_DOMAIN_SOURCES),
            help="ref_db sources for domain selection (default PFAM NCBIFAM).",
        )
        parser.add_argument(
            "--score-weights",
            type=float,
            nargs=2,
            default=[0.5, 0.5],
            metavar=("W_DOMAIN", "W_ADJACENCY"),
        )
        parser.add_argument(
            "--leiden-resolutions",
            type=float,
            nargs="+",
            default=[0.03, 0.08, 0.15, 0.25],
        )
        parser.add_argument("--knn-k", type=int, default=None)
        parser.add_argument("--seed", type=int, default=42)

    def handle(self, *args, **options):
        run_tag = options["run_tag"] or _dt.datetime.utcnow().strftime("%Y%m%dT%H%M%S")
        out_dir = Path(settings.CLUSTERING_ARTIFACTS_DIR) / "exports"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{run_tag}.tgz"

        sources = tuple(s.upper() for s in options["domain_sources"])

        inputs = self._build_inputs(
            sources=sources,
            weights=tuple(options["score_weights"]),
            resolutions=tuple(options["leiden_resolutions"]),
            knn_k=options["knn_k"],
            seed=options["seed"],
            run_tag=run_tag,
        )

        from common_core.clustering.io import write_inputs_tarball

        write_inputs_tarball(out_path, inputs)
        self.stdout.write(self.style.SUCCESS(f"Wrote {out_path}"))

    def _build_inputs(
        self,
        *,
        sources: tuple[str, ...],
        weights: tuple[float, float],
        resolutions: tuple[float, ...],
        knn_k: int | None,
        seed: int,
        run_tag: str,
    ):
        """Construct ``ClusteringInputs`` from the live database."""
        import numpy as np
        import scipy.sparse as sp
        from common_core.clustering.schema import ClusteringInputs, RunParams

        from discovery.models import DashboardBgc, IntegratedBGC
        from discovery.services.clustering.adjacency import (
            build_ibgc_adjacency_pair_matrix,
        )
        from discovery.services.clustering.membership import (
            build_ibgc_domain_matrix,
        )
        from discovery.services.clustering.pipeline import _align_rows

        if not IntegratedBGC.objects.exists():
            raise CommandError(
                "IntegratedBGC table is empty — run build_integrated_bgcs first."
            )

        # Primary set: iBGCs with at least one non-partial-or-validated source BGC.
        clusterable_ibgc_ids = list(
            DashboardBgc.objects.filter(integrated_bgc__isnull=False)
            .filter(Q(is_partial=False) | Q(is_validated=True))
            .values_list("integrated_bgc_id", flat=True)
            .distinct()
        )
        if not clusterable_ibgc_ids:
            raise CommandError(
                "No clusterable iBGCs (all iBGCs are partial+unvalidated)."
            )

        M_domains, ibgc_ids, domain_accs = build_ibgc_domain_matrix(
            sources=sources, ibgc_ids_subset=clusterable_ibgc_ids,
        )
        if M_domains.shape[0] == 0:
            raise CommandError("No iBGCs with selected-source domains found.")

        M_pairs, ibgc_ids_adj, pair_vocab = build_ibgc_adjacency_pair_matrix(
            sources=sources, ibgc_ids_subset=ibgc_ids.tolist(),
        )
        M_pairs = _align_rows(M_pairs, ibgc_ids_adj, ibgc_ids)

        # Partials: iBGCs not in the primary set.
        partial_ibgc_ids = list(
            IntegratedBGC.objects.exclude(id__in=list(ibgc_ids.tolist()))
            .order_by("id")
            .values_list("id", flat=True)
        )
        if partial_ibgc_ids:
            partials_M_domains, partials_row_ids, _ = build_ibgc_domain_matrix(
                sources=sources,
                domain_accs_subset=domain_accs.tolist(),
                ibgc_ids_subset=partial_ibgc_ids,
            )
            (
                partials_M_pairs,
                partials_pair_row_ids,
                _,
            ) = build_ibgc_adjacency_pair_matrix(
                sources=sources,
                pair_vocab_subset=pair_vocab.tolist(),
                ibgc_ids_subset=partial_ibgc_ids,
            )
            partials_M_pairs = _align_rows(
                partials_M_pairs, partials_pair_row_ids, partials_row_ids,
            )
            partials_ibgc_ids = partials_row_ids
        else:
            partials_M_domains = sp.csr_matrix(
                (0, M_domains.shape[1]), dtype=M_domains.dtype,
            )
            partials_M_pairs = sp.csr_matrix(
                (0, M_pairs.shape[1]), dtype=M_pairs.dtype,
            )
            partials_ibgc_ids = np.empty(0, dtype=np.int64)

        validated_ibgc_ids = np.asarray(
            sorted(
                DashboardBgc.objects.filter(
                    is_validated=True, integrated_bgc__isnull=False,
                ).values_list("integrated_bgc_id", flat=True).distinct()
            ),
            dtype=np.int64,
        )

        params = RunParams(
            domain_sources=list(sources),
            score_weights=weights,
            leiden_resolutions=resolutions,
            knn_k=knn_k,
            seed=seed,
            run_tag=run_tag,
            exporter_versions={
                "django-portal": _safe_version("bgc-data-portal"),
                "common-core": _safe_version("mgnify-bgcs-common-core"),
                "scipy": _safe_version("scipy"),
                "numpy": _safe_version("numpy"),
            },
        )

        log.info(
            "export_clustering_inputs: primaries=%d partials=%d "
            "domains=%d pairs=%d validated=%d",
            M_domains.shape[0],
            partials_M_domains.shape[0],
            M_domains.shape[1],
            M_pairs.shape[1],
            len(validated_ibgc_ids),
        )
        return ClusteringInputs(
            M_domains=M_domains,
            M_pairs=M_pairs,
            domain_accs=domain_accs,
            pair_vocab=pair_vocab,
            ibgc_ids=ibgc_ids,
            partials_M_domains=partials_M_domains,
            partials_M_pairs=partials_M_pairs,
            partials_ibgc_ids=partials_ibgc_ids,
            validated_ibgc_ids=validated_ibgc_ids,
            params=params,
        )


def _safe_version(pkg: str) -> str:
    try:
        return _pkg_version(pkg)
    except PackageNotFoundError:
        return ""
