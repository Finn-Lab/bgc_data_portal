from django.contrib import admin

from .models import (
    DashboardAssembly,
    DashboardBgc,
    BgcEmbedding,
    BgcDomain,
    DashboardGCF,
    DashboardNaturalProduct,
    DashboardBgcClass,
    DashboardDomain,
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
    list_display = ("family_id", "member_count", "known_chemistry_annotation", "validated_accession")
    search_fields = ("family_id", "known_chemistry_annotation")


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
