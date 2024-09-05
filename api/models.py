from django.db import models


class Assembly(models.Model):
    assembly_id = models.CharField(max_length=255,primary_key=True)
    bgcdb_id = models.IntegerField(unique=True)
    true_id = models.BooleanField(blank=True, null=True)
    accession = models.CharField(max_length=255)
    study = models.ForeignKey('Study', models.DO_NOTHING, blank=True, null=True)
    biome = models.ForeignKey('Biome', models.DO_NOTHING, blank=True, null=True)

    class Meta:
        db_table = 'assembly'


class BgcManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().select_related('bgc_detector').select_related('bgc_class')


class BgcWithContigManager(BgcManager):
    def get_queryset(self):
        return super().get_queryset().select_related('mgyc', 'mgyc__assembly')


class Bgc(models.Model):
    objects = BgcManager()
    objects_with_contigs = BgcWithContigManager()

    mgyb = models.IntegerField(primary_key=True)
    mgyc = models.ForeignKey('Contig', models.DO_NOTHING, db_column='mgyc', blank=True, null=True)
    bgc_detector = models.ForeignKey('BgcDetector', models.DO_NOTHING, blank=True, null=True)
    bgc_class = models.ForeignKey('BgcClass', models.DO_NOTHING, blank=True, null=True)
    bgc_identifier = models.CharField(max_length=255)
    start_position = models.IntegerField()
    end_position = models.IntegerField()
    bgc_metadata = models.TextField(blank=True, null=True)  # This field type is a guess.
    partial = models.IntegerField(blank=True, null=True)

    @property
    def accession(self):
        return f"MGYB{self.mgyb:012}"

    class Meta:
        db_table = 'bgc'


class BgcClass(models.Model):
    bgc_class_id = models.IntegerField(primary_key=True)
    bgc_class_name = models.CharField(max_length=255,blank=True, null=True)

    class Meta:
        db_table = 'bgc_class'


class BgcDetector(models.Model):
    bgc_detector_id = models.IntegerField(primary_key=True)
    bgc_detector_name = models.CharField(max_length=255,blank=True, null=True)
    version = models.CharField(max_length=255,blank=True, null=True)

    class Meta:
        db_table = 'bgc_detector'


class Biome(models.Model):
    biome_id = models.IntegerField(primary_key=True)
    lineage = models.CharField(max_length=255,blank=True, null=True)

    class Meta:
        db_table = 'biome'


class Contig(models.Model):
    mgyc = models.CharField(max_length=255,primary_key=True)
    bgcdb_id = models.IntegerField(unique=True)
    assembly = models.ForeignKey(Assembly, models.DO_NOTHING)
    contig_name = models.CharField(max_length=255,blank=True, null=True)
    sequence_hash = models.CharField(max_length=255,blank=True, null=True)
    contig_length = models.IntegerField(blank=True, null=True)
    true_id = models.BooleanField(blank=True, null=True)
    sequence = models.TextField()

    class Meta:
        db_table = 'contig'


class FileMd5(models.Model):
    file_md5_id = models.IntegerField(primary_key=True)
    file_path = models.CharField(max_length=255,blank=True, null=True)
    file_md5 = models.CharField(max_length=255,blank=True, null=True)

    class Meta:
        db_table = 'file_md5'


class GeneCaller(models.Model):
    gene_caller_id = models.IntegerField(primary_key=True)
    gene_caller = models.CharField(max_length=255,blank=True, null=True)
    version = models.CharField(max_length=255,blank=True, null=True)

    class Meta:
        db_table = 'gene_caller'


class Protein(models.Model):
    mgyp = models.CharField(max_length=255, primary_key=True)
    sequence = models.CharField(max_length=255,blank=True, null=True)
    cluster_representative = models.CharField(max_length=255,blank=True, null=True)
    pfam = models.TextField(blank=True, null=True)  # This field type is a guess.

    class Meta:
        db_table = 'protein'


class Metadata(models.Model):
    bgcdb_id = models.IntegerField(unique=True,primary_key=True)
    mgyp = models.ForeignKey(Protein, models.DO_NOTHING, db_column='mgyp')
    mgyc = models.ForeignKey(Contig, models.DO_NOTHING, db_column='mgyc')
    assembly = models.ForeignKey(Assembly, models.DO_NOTHING)
    gene_caller = models.ForeignKey(GeneCaller, models.DO_NOTHING)
    true_id = models.BooleanField(blank=True, null=True)
    start_position = models.IntegerField(blank=True, null=True)
    end_position = models.IntegerField(blank=True, null=True)
    strand = models.IntegerField(blank=True, null=True)
    protein_identifier = models.CharField(max_length=255,blank=True, null=True)
    pipeline_version = models.CharField(max_length=255)

    class Meta:
        db_table = 'metadata'


class Study(models.Model):
    study_id = models.IntegerField(primary_key=True)
    accession = models.CharField(max_length=255)

    class Meta:
        db_table = 'study'


class CurrentStats(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    id = models.IntegerField(primary_key=True)
    stats = models.JSONField(default=dict, blank=True)