from django.db import models

from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, Integer, String, ForeignKey, JSON, Boolean, Float

Base = declarative_base()

""" BGC DATABASE EXTRA TABLES """
class BGC(Base):
    __tablename__ = 'bgc'
    bgc_id = Column(Integer, primary_key=True, autoincrement=True)
    mgyc = Column(Integer, ForeignKey('contig.mgyc'))
    bgc_detector_id = Column(Integer, ForeignKey('bgc_detector.bgc_detector_id'))
    bgc_class_id = Column(Integer, ForeignKey('bgc_class.bgc_class_id'))
    bgc_accession = Column(String, nullable=False)
    start_position = Column(Integer, nullable=False)
    end_position = Column(Integer, nullable=False)
    bgc_metadata = Column(JSON)

class BGCClass(Base):
    __tablename__ = 'bgc_class'
    bgc_class_id = Column(Integer, primary_key=True, autoincrement=True)
    bgc_class_name = Column(String)

class BGCDetector(Base):
    __tablename__ = 'bgc_detector'
    bgc_detector_id = Column(Integer, primary_key=True, autoincrement=True)
    bgc_detector_name = Column(String)
    version = Column(String)

class FilesMD5(Base): # Control of what files have been processed
    __tablename__ = 'file_md5'
    file_md5_id = Column(Integer, primary_key=True, autoincrement=True)
    file_path = Column(String)
    file_md5 = Column(String)

""" BGC DATABASE MODIFIED TABLES """
class Contig(Base):
    __tablename__ = 'contig'
    mgyc = Column(String, primary_key=True, nullable=False)
    assembly_id = Column(String, ForeignKey('assembly.assembly_id'), nullable=False)
    contig_name = Column(String)
    sequence_hash = Column(String)
    contig_length = Column(Integer)
    true_mgyc = Column(Boolean, unique=False, nullable=True) ## ADDED
    sequence = Column(String, nullable=False)  ## ADDED

class Assembly(Base):
    __tablename__ = 'assembly'
    assembly_id = Column(String, primary_key=True)
    accession = Column(String, nullable=False)
    bgcdb_accession = Column(String, nullable=False) ## ADDED
    study_id = Column(Integer, ForeignKey('study.study_id'))
    biome_id = Column(Integer, ForeignKey('biome.biome_id'))
    
""" PROTEIN DATABASE TABLES """
class Protein(Base):
    __tablename__ = 'protein'
    mgyp = Column(String, primary_key=True, nullable=False)
    sequence = Column(String)
    cluster_representative = Column(String)
    pfam = Column(JSON)

class Study(Base):
    __tablename__ = 'study'
    study_id = Column(Integer, primary_key=True, nullable=False)
    accession = Column(String, nullable=False)

class Biome(Base):
    __tablename__ = 'biome'
    biome_id = Column(Integer, primary_key=True, nullable=False)
    lineage = Column(String)

class Metadata(Base):
    __tablename__ = 'metadata'
    mgyp = Column(String,ForeignKey('protein.mgyp'), primary_key=True)
    mgyc = Column(String, ForeignKey('contig.mgyc'))
    assembly_id = Column(String, ForeignKey('assembly.assembly_id'))
    start_position = Column(Integer)
    end_position = Column(Integer)
    strand = Column(Integer)
  
# Create your models here.
