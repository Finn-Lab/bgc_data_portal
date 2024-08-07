from django.db import models


class Assembly(models.Model):
    assembly_id = models.CharField(max_length=255,primary_key=True)
    accession = models.CharField(max_length=255)
    bgcdb_accession = models.CharField(max_length=255)
    study = models.ForeignKey('Study', models.DO_NOTHING, blank=True, null=True)
    biome = models.ForeignKey('Biome', models.DO_NOTHING, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'assembly'


class Bgc(models.Model):
    bgc_id = models.IntegerField(primary_key=True)
    mgyc = models.ForeignKey('Contig', models.DO_NOTHING, db_column='mgyc', blank=True, null=True)
    bgc_detector = models.ForeignKey('BgcDetector', models.DO_NOTHING, blank=True, null=True)
    bgc_class = models.ForeignKey('BgcClass', models.DO_NOTHING, blank=True, null=True)
    bgc_accession = models.CharField(max_length=255)
    start_position = models.IntegerField()
    end_position = models.IntegerField()
    bgc_metadata = models.TextField(blank=True, null=True)  # This field type is a guess.

    class Meta:
        managed = False
        db_table = 'bgc'


class BgcClass(models.Model):
    bgc_class_id = models.IntegerField(primary_key=True)
    bgc_class_name = models.CharField(max_length=255,blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'bgc_class'


class BgcDetector(models.Model):
    
    ANTISMASH = "antiSMASH"
    GECCO = "GECCO"
    SANNTIS = "SanntiS"
    
    bgc_detector_id = models.IntegerField(primary_key=True)
    bgc_detector_name = models.CharField(max_length=255,blank=True, null=True)
    version = models.CharField(max_length=255,blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'bgc_detector'


class Biome(models.Model):
    biome_id = models.IntegerField(primary_key=True)
    lineage = models.CharField(max_length=255,blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'biome'


class Contig(models.Model):
    mgyc = models.CharField(max_length=255,primary_key=True)
    assembly = models.ForeignKey(Assembly, models.DO_NOTHING)
    contig_name = models.CharField(max_length=255,blank=True, null=True)
    sequence_hash = models.CharField(max_length=255,blank=True, null=True)
    contig_length = models.IntegerField(blank=True, null=True)
    true_mgyc = models.BooleanField(blank=True, null=True)
    sequence = models.TextField()

    class Meta:
        managed = False
        db_table = 'contig'


class FileMd5(models.Model):
    file_md5_id = models.IntegerField(primary_key=True)
    file_path = models.CharField(max_length=255,blank=True, null=True)
    file_md5 = models.CharField(max_length=255,blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'file_md5'


class Metadata(models.Model):
    mgyp = models.OneToOneField('Protein', models.DO_NOTHING, db_column='mgyp',primary_key=True)
    mgyc = models.ForeignKey(Contig, models.DO_NOTHING, db_column='mgyc', blank=True, null=True)
    assembly = models.ForeignKey(Assembly, models.DO_NOTHING, blank=True, null=True)
    start_position = models.IntegerField(blank=True, null=True)
    end_position = models.IntegerField(blank=True, null=True)
    strand = models.IntegerField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'metadata'


class Protein(models.Model):
    mgyp = models.CharField(max_length=255,primary_key=True)
    sequence = models.TextField()
    cluster_representative = models.CharField(max_length=255,blank=True, null=True)
    pfam = models.TextField(blank=True, null=True)  # This field type is a guess.

    class Meta:
        managed = False
        db_table = 'protein'


class Study(models.Model):
    study_id = models.IntegerField(primary_key=True)
    accession = models.CharField(max_length=255)

    class Meta:
        managed = False
        db_table = 'study'
