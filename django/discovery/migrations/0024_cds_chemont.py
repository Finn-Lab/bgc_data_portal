"""Replace BGC-level CHAMOIS ChemOnt classification with per-CDS classification.

Drops:
  - ``NaturalProductChemOntClass`` model + ``discovery_np_chemont_class`` table.

Adds:
  - ``DashboardCdsChemOnt`` model + ``discovery_cds_chemont`` table — one row
    per CDS holding the deepest ChemOnt class predicted by CHAMOIS
    (argmax-class with BGC-level probability > 0.5, iteratively descended to
    children with gene weight > 1.0).

``DashboardNaturalProduct`` is preserved as the per-BGC curated-compound table
(SMILES, np_class_path, structure SVG, Morgan fingerprint); it is no longer
populated by CHAMOIS.

Irreversible without re-running CHAMOIS.
"""

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("discovery", "0023_nrb_clustering_snapshot"),
    ]

    operations = [
        migrations.DeleteModel(name="NaturalProductChemOntClass"),
        migrations.CreateModel(
            name="DashboardCdsChemOnt",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "chemont_id",
                    models.CharField(
                        help_text="ChemOnt ontology term ID, e.g. CHEMONTID:0000147",
                        max_length=30,
                    ),
                ),
                ("chemont_name", models.CharField(max_length=255)),
                (
                    "probability",
                    models.FloatField(
                        default=0.0,
                        help_text=(
                            "BGC-level probability of the argmax class for this CDS."
                        ),
                    ),
                ),
                (
                    "weight",
                    models.FloatField(
                        default=0.0,
                        help_text="Gene-specific weight of the deepest selected class.",
                    ),
                ),
                (
                    "cds",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="chemont",
                        to="discovery.dashboardcds",
                    ),
                ),
            ],
            options={
                "db_table": "discovery_cds_chemont",
                "indexes": [
                    models.Index(
                        fields=["chemont_id"], name="idx_cdschemont_cid"
                    ),
                    models.Index(fields=["cds"], name="idx_cdschemont_cds"),
                ],
                "unique_together": {("cds", "chemont_id")},
            },
        ),
    ]
