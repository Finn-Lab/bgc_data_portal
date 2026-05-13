from django.contrib import admin

from .models import (
    DashboardAssembly,
    DashboardBgc,
    BgcDomain,
    ClusteringRun,
    DashboardGCF,
    DashboardNaturalProduct,
    DashboardBgcClass,
    DashboardDomain,
    NonRedundantBGC,
    PrecomputedStats,
)


@admin.register(DashboardAssembly)
class DashboardAssemblyAdmin(admin.ModelAdmin):
    list_display = (
        "assembly_accession", "organism_name",
        "bgc_count", "bgc_novelty_score", "is_type_strain",
    )
    search_fields = ("assembly_accession", "organism_name")
    list_filter = ("is_type_strain",)


@admin.register(DashboardBgc)
class DashboardBgcAdmin(admin.ModelAdmin):
    list_display = (
        "bgc_accession", "classification_path", "novelty_score",
        "domain_novelty", "size_kb", "is_partial",
    )
    search_fields = ("bgc_accession",)
    list_filter = ("is_partial",)


@admin.register(DashboardGCF)
class DashboardGCFAdmin(admin.ModelAdmin):
    list_display = (
        "family_path",
        "level",
        "member_count",
        "validated_count",
        "descendant_count",
        "clustering_run_id",
    )
    list_filter = ("level", "clustering_run")
    search_fields = ("family_path", "parent_path")


@admin.register(ClusteringRun)
class ClusteringRunAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "created_at",
        "knn_k",
        "n_levels",
        "n_nrbs",
        "n_leaf_communities",
    )
    readonly_fields = (
        "created_at", "sha256", "n_proteins", "n_nrbs",
        "n_levels", "n_root_communities", "n_leaf_communities",
        "igraph_version", "leidenalg_version", "umap_version", "scipy_version",
    )


@admin.register(NonRedundantBGC)
class NonRedundantBGCAdmin(admin.ModelAdmin):
    list_display = (
        "id", "contig_id", "start_position", "end_position",
        "source_tools", "gene_cluster_family",
    )
    search_fields = ("gene_cluster_family",)


@admin.register(DashboardNaturalProduct)
class DashboardNaturalProductAdmin(admin.ModelAdmin):
    list_display = ("name", "np_class_path")
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
