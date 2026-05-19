
# MGnify Biosynthetic Gene Clusters site

MGnify Biosynthetic Gene Clusters is a platform developed by EMBL-EBI to support the exploration, analysis, and retrieval of biosynthetic gene cluster (BGC) predictions from metagenomic assemblies. The platform integrates results of multiple detection tools, such as antiSMASH, GECCO, and SanntiS.

## Features

- Access to standardised BGC predictions from metagenomic assemblies.
- Multi-tool analysis for consensus predictions.
- API.

## Dataset

The dataset contains BGC predictions organised in an SQLite database, including details on associated contigs, assemblies, proteins, and metadata.

## Funding

This portal is part of the EUREMAP project, funded by the European Union under HORIZON-INFRA-2023-DEV-01-04 (Grant No. 101131663).


## Docs
The documentation for this project is created using Quarto and is located in the docs directory. To update the documentation, make any necessary changes and then run quarto render to regenerate the files. Please ensure that the content from the about.html page in the docs directory is copied to bgc_data_portal/templates/about.html to maintain consistency across the site.

## GO-slim map

The Discovery domain panel and Protein Information card colour CDS by GO-slim
term. The mapping `GO id → slim term names` lives at
`django/discovery/services/data/go_slim_map.json` and is regenerated locally
with a standalone script (no Django needed):

```bash
pip install goatools
python scripts/refresh_go_slim_map.py --download
```

`--download` fetches `go-basic.obo` + `goslim_metagenomics.obo` into
`/tmp/go_obo`. Run `--help` for the other knobs (`--slim`, `--aspect`,
`--obo-dir`, `--output`). After regenerating, commit the JSON and run
`python manage.py backfill_go_slim` to refresh existing `BgcDomain.go_slim`
rows.

## DB stats
A set of summary statistics can be computed, for the data in the database, which are then persisted back to the
database as a cache.

These are computed by a management command, which should be run after any data changes to the DB:

`python manage.py gather_latest_stats`
