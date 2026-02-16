
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

## DB stats
A set of summary statistics can be computed, for the data in the database, which are then persisted back to the
database as a cache.

These are computed by a management command, which should be run after any data changes to the DB:

`python manage.py gather_latest_stats`
