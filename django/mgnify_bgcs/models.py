from django.db import models
from pgvector.django import VectorField, HnswIndex
from django.contrib.postgres.indexes import GinIndex


class Study(models.Model):
    id = models.AutoField(primary_key=True)
    accession = models.CharField(max_length=255, unique=True)


class Biome(models.Model):
    id = models.AutoField(primary_key=True)
    lineage = models.CharField(max_length=255, default="root", unique=True)


class Assembly(models.Model):
    id = models.AutoField(primary_key=True)
    accession = models.CharField(max_length=255, unique=True)
    collection = models.CharField(max_length=255, blank=True, null=True)
    study = models.ForeignKey(
        Study,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assemblies",
    )
    biome = models.ForeignKey(
        Biome,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assemblies",
    )
    # 7-rank taxonomy
    taxonomy_kingdom = models.CharField(max_length=100, blank=True, null=True)
    taxonomy_phylum = models.CharField(max_length=100, blank=True, null=True)
    taxonomy_class = models.CharField(max_length=100, blank=True, null=True)
    taxonomy_order = models.CharField(max_length=100, blank=True, null=True)
    taxonomy_family = models.CharField(max_length=100, blank=True, null=True)
    taxonomy_genus = models.CharField(max_length=100, blank=True, null=True)
    taxonomy_species = models.CharField(max_length=100, blank=True, null=True)
    # Genome metadata
    organism_name = models.CharField(max_length=255, blank=True, null=True)
    is_type_strain = models.BooleanField(default=False)
    type_strain_catalog_url = models.URLField(blank=True, null=True)
    genome_size_mb = models.FloatField(blank=True, null=True)
    genome_quality = models.FloatField(blank=True, null=True)
    isolation_source = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        indexes = [
            models.Index(fields=["taxonomy_family"], name="idx_assembly_tax_family"),
            models.Index(fields=["taxonomy_genus"], name="idx_assembly_tax_genus"),
            models.Index(fields=["is_type_strain"], name="idx_assembly_type_strain"),
        ]


class Contig(models.Model):
    id = models.AutoField(primary_key=True)
    sequence_sha256 = models.CharField(max_length=64, unique=True, db_index=True)
    mgyc = models.CharField(max_length=255, blank=True, null=True)
    accession = models.CharField(max_length=255, blank=True, null=True)
    assembly = models.ForeignKey(
        Assembly,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contigs",
    )
    name = models.CharField(max_length=255, blank=True, null=True)
    source_organism = models.JSONField(default=dict, blank=True)
    length = models.IntegerField(blank=True, null=True)
    sequence = models.TextField()


class BgcClass(models.Model):
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=255, unique=True, db_index=True)

    def __str__(self):
        return self.name


class BgcDetector(models.Model):
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=255, unique=True, db_index=True)
    tool = models.CharField(max_length=255, blank=True, null=True)
    version = models.CharField(max_length=50, blank=True, null=True)


class Bgc(models.Model):
    id = models.BigAutoField(primary_key=True)
    contig = models.ForeignKey(
        Contig, on_delete=models.SET_NULL, null=True, blank=True, related_name="bgcs"
    )
    detector = models.ForeignKey(
        BgcDetector,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bgcs",
    )
    identifier = models.CharField(max_length=255, unique=False, blank=True, null=True)
    start_position = models.IntegerField()
    end_position = models.IntegerField()
    metadata = models.JSONField(blank=True, null=True)
    is_partial = models.BooleanField(default=False)
    classes = models.ManyToManyField(
        BgcClass,
        through="BgcBgcClass",
        related_name="bgcs",
    )
    embedding = VectorField(dimensions=1152, null=True, blank=True)
    is_aggregated_region = models.BooleanField(default=False)
    is_mibig = models.BooleanField(default=False)
    compounds = models.JSONField(
        default=list,
        blank=True,
        null=True,
        help_text="contains dictionaries with compound representations. SMILEs are used as keys, and values are dictionaries with 'name' and 'type' keys.",
    )
    smiles_svg = models.CharField(unique=False, blank=True, null=True)

    @property
    def accession(self):
        return f"MGYB{self.id:012}"

    class Meta:
        indexes = [
            models.Index(fields=["identifier"], name="idx_bgc_identifier"),
            GinIndex(fields=["metadata"], name="idx_bgc_metadata_gin"),
            HnswIndex(
                fields=["embedding"],
                name="bgc_embedding_hnsw",
                opclasses=["vector_cosine_ops"],
                m=16,
                ef_construction=512,
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["contig", "start_position", "end_position", "detector"],
                name="unique_bgc_region_per_contig_detector",
            ),
        ]


class BgcBgcClass(models.Model):
    id = models.AutoField(primary_key=True)
    bgc = models.ForeignKey(Bgc, on_delete=models.CASCADE, db_index=True)
    bgc_class = models.ForeignKey(BgcClass, on_delete=models.CASCADE, db_index=True)

    class Meta:
        db_table = "app_bgcbgcclass"
        unique_together = ("bgc", "bgc_class")
        indexes = [
            models.Index(fields=["bgc_class", "bgc"], name="idx_bgcbgc_class_bgc"),
        ]


class Domain(models.Model):
    id = models.AutoField(primary_key=True)
    acc = models.CharField(max_length=50, unique=True, db_index=True)
    name = models.CharField(max_length=255, db_index=True)
    ref_db = models.CharField(max_length=50, db_index=True)
    description = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.name


class Protein(models.Model):
    id = models.AutoField(primary_key=True)
    sequence = models.TextField()
    sequence_sha256 = models.CharField(max_length=64, unique=True, db_index=True)
    mgyp = models.CharField(max_length=64, null=True, blank=True)
    cluster_representative = models.CharField(max_length=64, null=True, blank=True)
    domains = models.ManyToManyField(
        Domain,
        through="ProteinDomain",
        related_name="proteins",
    )
    embedding = VectorField(dimensions=1152, null=True, blank=True)

    class Meta:
        indexes = [
            HnswIndex(
                fields=["embedding"],
                name="protein_embedding_hnsw",
                opclasses=["vector_cosine_ops"],
                m=16,
                ef_construction=512,
            ),
        ]


class ProteinDomain(models.Model):
    id = models.AutoField(primary_key=True)
    protein = models.ForeignKey(Protein, on_delete=models.CASCADE, db_index=True)
    domain = models.ForeignKey(Domain, on_delete=models.CASCADE, db_index=True)
    start_position = models.IntegerField()
    end_position = models.IntegerField()
    score = models.FloatField(blank=True, null=True)

    class Meta:
        db_table = "app_proteindomain"
        unique_together = ("protein", "domain", "start_position", "end_position")
        indexes = [
            models.Index(
                fields=["domain", "protein"], name="idx_protdomain_domain_prot"
            ),
            models.Index(
                fields=["protein", "domain"], name="idx_protdomain_prot_domain"
            ),
            models.Index(
                fields=["domain", "start_position", "end_position"],
                name="idx_protdomain_domain_position",
            ),
        ]


class GeneCaller(models.Model):
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=255, unique=True, db_index=True)
    tool = models.CharField(max_length=255, blank=True, null=True)
    version = models.CharField(max_length=50, blank=True, null=True)


class Cds(models.Model):
    id = models.AutoField(primary_key=True)
    protein = models.ForeignKey(
        Protein, on_delete=models.CASCADE, related_name="cds", db_index=True
    )
    contig = models.ForeignKey(
        Contig, on_delete=models.CASCADE, related_name="cds", db_index=True
    )

    gene_caller = models.ForeignKey(
        GeneCaller,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cds",
        db_index=True,
    )
    start_position = models.IntegerField()
    end_position = models.IntegerField()
    strand = models.SmallIntegerField()
    protein_identifier = models.CharField(max_length=255, blank=True, null=True)
    pipeline_version = models.CharField(max_length=50, blank=True, null=True)

    class Meta:
        indexes = [
            models.Index(fields=["protein"], name="idx_cds_protein"),
            models.Index(fields=["contig"], name="idx_cds_contig"),
            models.Index(
                fields=["start_position", "end_position"], name="idx_cds_positions"
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "contig",
                    "start_position",
                    "end_position",
                    "strand",
                    "protein",
                    "gene_caller",
                ],
                name="uniq_cds_location_protein_caller",
            )
        ]


class CurrentStats(models.Model):
    id = models.AutoField(primary_key=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    stats = models.JSONField(default=dict, blank=True)


class UMAPTransform(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    n_samples_fit = models.PositiveIntegerField()
    pca_components = models.PositiveIntegerField()
    n_neighbors = models.PositiveSmallIntegerField()
    min_dist = models.FloatField()
    metric = models.CharField(max_length=50)
    sklearn_version = models.CharField(max_length=50)
    umap_version = models.CharField(max_length=50)
    model_blob = models.BinaryField()

    sha256 = models.CharField(max_length=64, unique=True)

    class Meta:
        ordering = ["-created_at"]
