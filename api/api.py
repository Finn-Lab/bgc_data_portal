from ninja import NinjaAPI,Schema
from sqlalchemy.orm import Session
from .utils import get_db
from .models import BGC, Contig
from django.shortcuts import render


api = NinjaAPI()

# 'ERZ2944758.3133-NODE-3133-length-7542-cov-6.081052_sanntis_1'
@api.get("/bgc/search/")
def search_bgc(request, bgc_accession: str):
    # Get a session
    db = next(get_db())
    
    # Execute the query
    query = db.query(BGC, Contig).join(Contig, BGC.mgyc == Contig.mgyc).filter(BGC.bgc_accession == bgc_accession).first()

    # query = db.query(BGC).join(Contig).filter(BGC.bgc_accession == bgc_accession).first()
    if not query:
        return {f"error": "BGC accession not found: {bgc_accession}"}
    bgc, contig = query
    result = {
        "bgc_accession": bgc.bgc_accession,
        "sequence": contig.sequence[bgc.start_position:bgc.end_position],
        "metadata": bgc.bgc_metadata,
    }
    return result
