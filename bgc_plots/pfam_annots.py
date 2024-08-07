import json
import os


pfam2GoSlim_file = os.path.join(os.path.dirname(__file__),'data/pfam2goSlim.json')
with open(pfam2GoSlim_file) as h:
    _pfam2go_dict = json.load(h)
# Create dictionary of GO slim molecular function
_pfamToGoSlim = {pfam:[desc for desc,go_type in go_slims if go_type == 'molecular_function'] for pfam,go_slims in _pfam2go_dict.items() }
pfamToGoSlim = {pfam:go_slims for pfam,go_slims in _pfamToGoSlim.items() if go_slims!=[]}


pfam_desc_file = os.path.join(os.path.dirname(__file__),'data/pfam_desc.json')
with open(pfam_desc_file) as h:
    pfam_desc = {k:v.strip() for k,v in json.load(h).items()}
