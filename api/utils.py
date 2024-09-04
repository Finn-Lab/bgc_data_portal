import logging
from functools import reduce
import json
import operator
from collections import Counter
from django.http import Http404
import pandas as pd
from .models import Bgc, Contig, Protein, Metadata, CurrentStats
from .pfam_annots import pfamToGoSlim,pfam_desc
from typing import Optional
from django.db.models import Q,F

class RegionFeatureError(Exception):
    """Custom exception for errors related to region features."""
    pass

def generate_bgc_statistics():
    """Generate dictionary with summary statistics of db"""
    # Start with an empty QuerySet
    results = Bgc.objects.select_related('bgc_detector', 'bgc_class', 'mgyc__assembly__biome').all()

    # Generate the required statistics
    result_stats = dict(
        # Regions is the length of the QuerySet
        total_regions=len(results),

        # Distribution of BGC classes
        bgc_class_dist=dict(Counter(
            # Access bgc_class_names, split on ',', and take the first element for each result
            [bgc.bgc_class.bgc_class_name.split(',')[0] for bgc in results if bgc.bgc_class]
        )),

        # Count of distinct assemblies by their accession
        n_assemblies=results.values('mgyc__assembly__accession').distinct().count(),

        # Count of distinct studies
        n_studies=results.values('mgyc__assembly__study').distinct().count(),
    )

    
    return result_stats

def get_latest_stats():
    latest_stats = CurrentStats.objects.order_by("-created_at").first()
    if latest_stats:
        return latest_stats.stats
    return {}


def mgyb_converter(mgyb,text_to_int=True):
    """Function to convert mgyb text to int and viceversa. Match format with Bgc.mgyb model """
    mgyb_template = "MGYB{:012}"
    return int(mgyb[4:]) if text_to_int else mgyb_template.format(mgyb)




def find_region_features( 
              mgyc: str = None, 
              start_position: int = None, 
              end_position: int = None,
    ):

    try:
        # Query the database to get the contig and associated assembly
        contig = Contig.objects.get(pk=mgyc)
    except Contig.DoesNotExist:
        raise RegionFeatureError(f"No Contig matches the given query for MGYC: {mgyc}")

    assembly_accession = contig.assembly.accession

    # Retrieve BGCs that are within or partially overlap with the specified region
    bgcs = Bgc.objects.filter(
        mgyc=mgyc,
        start_position__lte=end_position,
        end_position__gte=start_position
    )

    # Retrieve proteins within or partially overlapping the specified region
    protein_metadata = Metadata.objects.filter(
        mgyc=mgyc,
        start_position__lte=end_position,
        end_position__gte=start_position
    ).select_related('mgyp')

    # modified_bgcs, modified_protein_metadata = get_modified_positions(bgcs, protein_metadata, start_position, end_position)

    return contig,assembly_accession,bgcs,protein_metadata
    # return contig,assembly_accession,modified_bgcs,modified_protein_metadata
def get_region_features(               
        mgyc: str = None, 
        start_position: int = None, 
        end_position: int = None,
        extended_window=0
):
        """
        Retrieves and formats data into a df with gff3 style for a contig region.

        Args:
            contig_name (str): The name of the contig.
            start_position (int): The start position of the region.
            end_position (int): The end position of the region.
            extended_window (int): define if want to extend the retrived features, but not modifying the aggregated region
        Returns:
            pd.DataFrame: DataFrame containing the formatted feature data.
        """

        # Delimit features window with extention
        window_start = start_position - extended_window
        window_end = end_position + extended_window

        try:
            contig, assembly_accession, bgcs, protein_metadata = find_region_features(
                mgyc=mgyc,
                start_position=window_start,
                end_position=window_end,
            )
        except RegionFeatureError as e:
            raise Http404(str(e))

        features = []

        mgyb_template = "MGYB{:012}"

        # BGC features
        for bgc in bgcs:
            features.append({
                'seqid':mgyc,
                'source': bgc.bgc_detector.bgc_detector_name,
                'type': 'CLUSTER',
                'start': bgc.start_position,
                'end': bgc.end_position,
                'score':None,
                'strand': 0,
                'attrib':{
                    'ID': mgyb_template.format(bgc.mgyb),
                    'BGC_CLASS':bgc.bgc_class.bgc_class_name if bgc.bgc_class else 'Unknown',
                    'detector_version': bgc.bgc_detector.version
                },
            })
        # Add aggregated region
        features.append({
            'seqid':mgyc,
            'source': "Aggregated region",
            'type': 'CLUSTER',
            'start': start_position,
            'end': end_position,
            'score': None,
            'strand': 0,
            'attrib':{
                'ID': f"{mgyc}-{start_position}-{end_position}",
                'BGC_CLASS':"Aggregated region"},
        })

        # Protein features
        for meta in protein_metadata:

            protein = meta.mgyp
            pfam_json = json.loads(protein.pfam) if protein.pfam !='NaN' else []

            features.append({
                'seqid':mgyc,
                'source': 'Prodigal', # TODO change for gene_caller.gene_calle
                'type': 'CDS',
                'start': meta.start_position,
                'end': meta.end_position,
                'score':None,
                'strand': meta.strand,
                'attrib':{
                    'cluster_representative':protein.cluster_representative,
                    'ID': meta.mgyp.mgyp,
                    'assembly_accession':assembly_accession,
                    'biome_lineage':meta.assembly.biome.lineage,
                    'mgyp':meta.mgyp.mgyp,
                    'sequence':protein.sequence,
                    'cluster_representative':protein.cluster_representative or meta.mgyp.mgyp,
                    'pfam':pfam_json,
                    'gene_caller':'Prodigal',# meta.gene_caller.gene_caller TODO
                    'start':meta.start_position,
                    'end':meta.end_position,
                    'strand':meta.strand,
                },
            })
            for pfam in pfam_json:
                pfam_start = meta.start_position + (pfam.get('envelope_start') * 3)
                pfam_end = meta.start_position + (pfam.get('envelope_end') * 3)
                pfam_id = pfam.get('PFAM')

                go_slim = pfamToGoSlim.get(pfam_id, [None])
                features.append({
                    'seqid':mgyc,
                    'source': 'PFAM',
                    'type': 'ANNOT',
                    'start': pfam_start,
                    'end': pfam_end,
                    'score':None,
                    'strand': meta.strand,
                    'attrib':{
                        'ID': pfam_id,
                        'GOslim':go_slim,
                        'mgyp':meta.mgyp.mgyp,
                        'description':pfam_desc.get(pfam_id, 'Domain of Unknown Function'),
                        # 'PFAM':pfam_id,
                        },
                })

        # Add limits to avoid features going neyon de defined limits
        features_df = pd.DataFrame(features)
        features_df = features_df[(features_df.start<=window_end)&(features_df.end>=window_start)]
        features_df['start'] = features_df['start'].apply(lambda x: max(x, window_start))
        features_df['end'] = features_df['end'].apply(lambda x: min(x, window_end))

        return contig, assembly_accession,features_df

