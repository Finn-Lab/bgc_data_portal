from django.contrib import admin

from .models import (
    ClusteringRun,
    ConsensusBgc,
    DashboardAssembly,
    DashboardBgcClass,
    DashboardDomain,
    DashboardGCF,
    IbgcNaturalProduct,
    IntegratedBgc,
    PrecomputedStats,
    SourceBgcPrediction,
)


@admin.register(DashboardAssembly)
class DashboardAssemblyAdmin(admin.ModelAdmin):
    list_display = (
        "assembly_accession", "organism_name",
        "bgc_count", "bgc_novelty_score", "is_type_strain",
    )
    search_fields = ("assembly_accession", "organism_name")
    list_filter = ("is_type_strain",)


@admin.register(ConsensusBgc)
class ConsensusBgcAdmin(admin.ModelAdmin):
    list_display = ("accession", "contig_id", "bgc_range")
    search_fields = ("accession",)


@admin.register(IntegratedBgc)
class IntegratedBgcAdmin(admin.ModelAdmin):
    list_display = (
        "accession", "cbgc_id", "contig_id", "bgc_range",
        "source_tools", "gene_cluster_family",
    )
    search_fields = ("accession", "gene_cluster_family")


@admin.register(SourceBgcPrediction)
class SourceBgcPredictionAdmin(admin.ModelAdmin):
    list_display = (
        "prediction_accession", "detector", "bgc_range",
        "is_partial", "is_validated", "integrated_bgc_id",
    )
    search_fields = ("prediction_accession",)
    list_filter = ("is_partial", "is_validated", "detector")


@admin.register(DashboardGCF)
class DashboardGCFAdmin(admin.ModelAdmin):
    list_display = (
        "family_path", "level", "member_count",
        "validated_count", "descendant_count", "clustering_run_id",
    )
    list_filter = ("level", "clustering_run")
    search_fields = ("family_path", "parent_path")


@admin.register(ClusteringRun)
class ClusteringRunAdmin(admin.ModelAdmin):
    list_display = (
        "id", "created_at", "knn_k", "n_levels",
        "n_ibgcs", "n_leaf_communities",
    )
    readonly_fields = (
        "created_at", "sha256", "n_proteins", "n_ibgcs",
        "n_levels", "n_root_communities", "n_leaf_communities",
        "igraph_version", "leidenalg_version", "umap_version", "scipy_version",
    )


@admin.register(IbgcNaturalProduct)
class IbgcNaturalProductAdmin(admin.ModelAdmin):
    list_display = ("name", "ibgc_id", "np_class_path")
    search_fields = ("name", "smiles")


@admin.register(DashboardBgcClass)
class DashboardBgcClassAdmin(admin.ModelAdmin):
    list_display = ("name", "bgc_count")


@admin.register(DashboardDomain)
class DashboardDomainAdmin(admin.ModelAdmin):
    list_display = ("acc", "name", "bgc_count")
    search_fields = ("acc", "name")


@admin.register(PrecomputedStats)
class PrecomputedStatsAdmin(admin.ModelAdmin):
    list_display = ("key", "updated_at")
