"""Ephemeral asset-upload pipeline for the Discovery dashboard.

A user uploads a ``tar.gz`` containing the same TSV layout that the
persistent ingestion loader accepts (``assemblies.tsv``, ``bgcs.tsv``, …),
the platform builds virtual iBGCs from it, projects them onto the latest
``ClusteringRun``'s composite-Dice space (KNN inheritance for
``gene_cluster_family``, weighted-avg UMAP coords, novelty + domain
novelty), and caches the result in Redis under an ``asset:{token}:*`` key
namespace for 6 hours. Nothing is persisted to the database.

Public surface:

* ``validate.validate_tarball(file_obj) -> ValidatedTarball``
* ``parse.parse_asset_tar(tar_bytes) -> AssetData``
* ``project.project_asset(token, asset_data) -> AssetProjectionSummary``
* ``cache.read_asset_*``/``cache.write_asset_*`` helpers
"""
