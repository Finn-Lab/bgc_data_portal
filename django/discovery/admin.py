from django.contrib import admin

from .models import (
    DashboardGenome,
    DashboardBgc,
    BgcEmbedding,
    BgcDomain,
    DashboardGCF,
    DashboardNaturalProduct,
    DashboardMibigReference,
    DashboardBgcClass,
    DashboardDomain,
    PrecomputedStats,
)


@admin.register(DashboardGenome)
class DashboardGenomeAdmin(admin.ModelAdmin):
    list_display = (
        "assembly_accession", "organism_name", "taxonomy_family",
        "bgc_count", "composite_score", "is_type_strain",
    )
    search_fields = ("assembly_accession", "organism_name")
    list_filter = ("is_type_strain", "taxonomy_kingdom")


@admin.register(DashboardBgc)
class DashboardBgcAdmin(admin.ModelAdmin):
    list_display = (
        "bgc_accession", "classification_l1", "novelty_score",
        "domain_novelty", "size_kb", "is_partial",
    )
    search_fields = ("bgc_accession",)
    list_filter = ("classification_l1", "is_partial")


@admin.register(DashboardGCF)
class DashboardGCFAdmin(admin.ModelAdmin):
    list_display = ("family_id", "member_count", "known_chemistry_annotation", "mibig_accession")
    search_fields = ("family_id", "known_chemistry_annotation")


@admin.register(DashboardNaturalProduct)
class DashboardNaturalProductAdmin(admin.ModelAdmin):
    list_display = ("name", "chemical_class_l1", "chemical_class_l2", "producing_organism")
    search_fields = ("name", "smiles")
    list_filter = ("chemical_class_l1",)


@admin.register(DashboardMibigReference)
class DashboardMibigReferenceAdmin(admin.ModelAdmin):
    list_display = ("accession", "compound_name", "bgc_class")
    search_fields = ("accession", "compound_name")


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
