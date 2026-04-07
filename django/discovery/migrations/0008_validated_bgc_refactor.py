"""Validated BGC refactor: unify MIBiG into validated concept, add gene_cluster_family.

- DashboardBgc: remove is_mibig; rename nearest_mibig_* → nearest_validated_*;
  remove gcf_id, distance_to_gcf_representative; add gene_cluster_family
- DashboardGCF: rename mibig_accession → validated_accession, mibig_count → validated_count
- Delete DashboardMibigReference model
- Sync state for url fields already present in DB (assembly, bgc_domain)
"""

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("discovery", "0007_schema_simplification"),
    ]

    operations = [
        # ── DashboardBgc: rename fields (preserves data) ────────────────
        migrations.RenameField(
            model_name="dashboardbgc",
            old_name="nearest_mibig_accession",
            new_name="nearest_validated_accession",
        ),
        migrations.RenameField(
            model_name="dashboardbgc",
            old_name="nearest_mibig_distance",
            new_name="nearest_validated_distance",
        ),

        # ── DashboardBgc: remove fields ─────────────────────────────────
        migrations.RemoveField(
            model_name="dashboardbgc",
            name="is_mibig",
        ),
        migrations.RemoveField(
            model_name="dashboardbgc",
            name="gcf_id",
        ),
        migrations.RemoveField(
            model_name="dashboardbgc",
            name="distance_to_gcf_representative",
        ),

        # ── DashboardBgc: add gene_cluster_family ───────────────────────
        migrations.AddField(
            model_name="dashboardbgc",
            name="gene_cluster_family",
            field=models.CharField(
                blank=True,
                default="",
                help_text="ltree dot-path, e.g. GCF_001.SubFamily_A",
                max_length=512,
            ),
        ),
        migrations.AddIndex(
            model_name="dashboardbgc",
            index=models.Index(
                fields=["gene_cluster_family"],
                name="idx_db_gcf_path",
            ),
        ),

        # ── DashboardGCF: rename fields (preserves data) ────────────────
        migrations.RenameField(
            model_name="dashboardgcf",
            old_name="mibig_accession",
            new_name="validated_accession",
        ),
        migrations.RenameField(
            model_name="dashboardgcf",
            old_name="mibig_count",
            new_name="validated_count",
        ),

        # ── Delete DashboardMibigReference ──────────────────────────────
        migrations.DeleteModel(
            name="DashboardMibigReference",
        ),

        # ── Sync state: fields already in DB but not in migration state ─
        # url was added to assembly and bgc_domain directly in DB
        # (via seed_discovery_data or raw SQL) but never through a migration.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="dashboardassembly",
                    name="url",
                    field=models.URLField(blank=True, default="", max_length=512),
                ),
                migrations.AddField(
                    model_name="bgcdomain",
                    name="url",
                    field=models.URLField(blank=True, default="", max_length=512),
                ),
            ],
            database_operations=[],  # columns already exist in DB
        ),
    ]
