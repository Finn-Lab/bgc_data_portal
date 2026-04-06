# Discovery Data Specification

Reference for producing the TSV files consumed by the `load_discovery_data` management command.  
All specs are derived from the loader at `django/discovery/services/ingestion/loader.py`.

```bash
python manage.py load_discovery_data --data-dir /path/to/tsvs/
python manage.py load_discovery_data --data-dir /path/to/tsvs/ --truncate      # wipe first
python manage.py load_discovery_data --data-dir /path/to/tsvs/ --skip-stats    # skip post-load aggregations
```

---

## Directory Layout

```
data_dir/
  detectors.tsv            # required
  assemblies.tsv           # required
  contigs.tsv              # required
  contig_sequences.tsv     # optional
  bgcs.tsv                 # required
  cds.tsv                  # optional
  cds_sequences.tsv        # optional
  domains.tsv              # optional
  embeddings_bgc.tsv       # optional
  natural_products.tsv     # optional
  mibig_references.tsv     # optional
  gcf.tsv                  # optional
```

All files are **tab-separated** with a header row. Encoding: UTF-8.  
Batch size: 10,000 rows per database write.

---

## Loading Order and Dependencies

Files are loaded in strict dependency order. Each step resolves foreign keys using in-memory lookup maps built from previously loaded data.

```
1.   detectors.tsv          →  DashboardDetector
2.   assemblies.tsv         →  DashboardAssembly  (+AssemblySource auto-created)
3.   contigs.tsv            →  DashboardContig       (needs assembly_accession from step 2)
3.5  contig_sequences.tsv   →  ContigSequence         (needs contig_accession from step 3)
4.   bgcs.tsv               →  DashboardBgc          (needs contig_accession from step 3,
                                DashboardRegion          detector_name from step 1)
5.   cds.tsv                →  DashboardCds           (needs source_bgc_id from step 4)
5.5  cds_sequences.tsv      →  CdsSequence            (needs source_bgc_id + protein_id_str from step 5)
6.   domains.tsv            →  BgcDomain              (needs source_bgc_id + protein_id_str from step 5)
7.   embeddings_bgc.tsv     →  BgcEmbedding           (needs source_bgc_id from step 4)
8.   natural_products.tsv   →  DashboardNaturalProduct (needs source_bgc_id from step 4)
9.   mibig_references.tsv   →  DashboardMibigReference (needs source_bgc_id from step 4, optional)
10.  gcf.tsv                →  DashboardGCF            (needs representative_source_bgc_id from step 4)
```

After loading, two post-load computations run (unless `--skip-stats`):

- **Assembly scores** — `bgc_count`, `l1_class_count`, `bgc_novelty_score` aggregated from loaded BGCs.
- **Catalog counts** — `DashboardBgcClass` and `DashboardDomain` tables rebuilt from BGC/domain data.

---

## Encoding Conventions

### Booleans

Parsed as truthy when the **lowercased** value is `"true"` or `"1"`. Everything else (including empty) is `False`.

### ltree Dot-Paths

Hierarchical fields use **dot-delimited** paths. Dots separate hierarchy levels. Values must be valid PostgreSQL `ltree` labels (alphanumeric + underscore; no spaces or special characters).

| Field | Example |
|-------|---------|
| `dominant_taxonomy_path` | `Bacteria.Actinomycetota.Actinomycetia.Streptomycetales.Streptomycetaceae.Streptomyces` |
| `biome_path` | `root.Environmental.Terrestrial.Soil` |
| `taxonomy_path` | `Bacteria.Actinomycetota.Actinomycetia` |
| `classification_path` | `Polyketide.Macrolide.14_membered` |
| `np_class_path` | `Polyketide.Macrolide.Erythromycin` |

Replace spaces with underscores. Empty string means "unknown" or "not applicable".

### Base64-Encoded Vectors

Embedding vectors and Morgan fingerprints are transmitted as **base64-encoded little-endian binary**.

**Encoding (Python):**

```python
import base64, struct, numpy as np

# For float32 vectors (embeddings)
vector = np.array([0.1, 0.2, ...], dtype=np.float32)  # 1152 dimensions
encoded = base64.b64encode(vector.tobytes()).decode("ascii")

# For Morgan fingerprints (raw binary)
encoded = base64.b64encode(fingerprint_bytes).decode("ascii")
```

**Decoding (what the loader does):**

```python
raw = base64.b64decode(encoded_string)
vector = list(struct.unpack(f"<{len(raw)//4}f", raw))  # little-endian float32
```

### Nullable Numeric Fields

Empty string or missing column → `None` / `NULL` in the database.

---

## File Specifications

### 1. `detectors.tsv`

Detection tool + version lookup. The loader auto-generates `tool_name_code` (3-letter uppercase, e.g. `"ANT"` for antiSMASH) and `version_sort_key` (integer for semver ordering).

| Column | Type | Required | Description | Example |
|--------|------|----------|-------------|---------|
| `name` | string | **yes** | Human-readable label (unique key) | `antiSMASH v7.1` |
| `tool` | string | **yes** | Tool name | `antiSMASH` |
| `version` | string | **yes** | Semver string | `7.1.0` |

**Uniqueness:** `name` must be unique across all rows.  
**FK resolution key:** `name` is used in `bgcs.tsv` as `detector_name`.

**Auto-computed by loader:**
- `tool_name_code` — first 3 uppercase letters of `tool` (collision-safe)
- `version_sort_key` — `major * 1_000_000 + minor * 1_000 + patch`

---

### 2. `assemblies.tsv`

One row per assembly (genome, metagenome, or region).

| Column | Type | Required | Description | Example |
|--------|------|----------|-------------|---------|
| `assembly_accession` | string | **yes** | Unique accession | `GCA_000009065.1` |
| `source_assembly_id` | integer | **yes** | Cross-reference ID from source DB (unique) | `42` |
| `organism_name` | string | no | Species/strain name | `Streptomyces coelicolor A3(2)` |
| `source` | string | no | Data source name (auto-creates `AssemblySource`) | `GTDB` | <<This should be specified as parameter of workflow>>
| `assembly_type` | integer | no | `1`=metagenome, `2`=genome (default), `3`=region | `2` | <<This should be specified as parameter of workflow>>
| `dominant_taxonomy_path` | string | no | ltree dot-path of most common taxonomy | `Bacteria.Actinomycetota.Actinomycetia` |
| `dominant_taxonomy_label` | string | no | Human label or `"Mixed (N taxa)"` | `Streptomyces coelicolor` |
| `biome_path` | string | no | ltree dot-path for biome | `root.Environmental.Terrestrial.Soil` |
| `is_type_strain` | boolean | no | `true`/`1` if type strain | `true` |
| `type_strain_catalog_url` | URL | no | Link to strain catalog | `https://dsmz.de/...` |
| `assembly_size_mb` | float | no | Assembly size in megabases | `8.67` |
| `assembly_quality` | float | no | Quality score (0.0–1.0) | `0.95` |
| `isolation_source` | string | no | Where isolated from | `soil` |
| `url` | URL | no | Link to source record | `https://www.ncbi.nlm.nih.gov/...` |

**Uniqueness:** `assembly_accession` (unique), `source_assembly_id` (unique).  
**FK resolution key:** `assembly_accession` is used in `contigs.tsv`.

**Auto-computed by loader (post-load):**
- `bgc_count` — count of BGCs in this assembly
- `l1_class_count` — count of distinct `classification_l1` values
- `bgc_novelty_score` — average `novelty_score` of BGCs
- `bgc_diversity_score`, `bgc_density`, `taxonomic_novelty` — not set by loader (default 0.0)
- `pctl_diversity`, `pctl_novelty`, `pctl_density` — not set by loader (default 0.0)

---

### 3. `contigs.tsv`

One row per contig. Each contig belongs to exactly one assembly.

| Column | Type | Required | Description | Example |
|--------|------|----------|-------------|---------|
| `assembly_accession` | string | **yes** | Parent assembly (must exist in `assemblies.tsv`) | `GCA_000009065.1` |
| `accession` | string | **yes** | Contig accession | `MGYC000000001` |
| `source_contig_id` | integer | **yes** | Cross-reference ID from source DB (unique) | `100` |
| `length` | integer | no | Contig length in bp (default 0) | `154000` |
| `taxonomy_path` | string | no | ltree dot-path for this contig's taxonomy | `Bacteria.Actinomycetota.Actinomycetia` |

**Uniqueness:** `accession` (indexed), `source_contig_id` (unique).  
**FK resolution key:** `accession` is used in `bgcs.tsv` as `contig_accession`.

---

### 3.5. `contig_sequences.tsv` (optional)

Compressed nucleotide sequences for contigs. Sequences are zlib-compressed then base64-encoded to keep TSV rows compact.

| Column | Type | Required | Description | Example |
|--------|------|----------|-------------|---------|
| `contig_accession` | string | **yes** | Parent contig (must exist in `contigs.tsv`) | `MGYC000000001` |
| `sequence_base64` | string | **yes** | Base64-encoded zlib-compressed nucleotide sequence | `eJxLSS0u...` |

**Uniqueness:** One sequence per contig (primary key = contig FK).  
**Conflict handling:** Duplicates silently ignored (`ignore_conflicts=True`).

**Encoding (Python):**

```python
import base64, zlib

seq = "ACGTACGT..."  # raw nucleotide string
compressed = zlib.compress(seq.encode("utf-8"))
encoded = base64.b64encode(compressed).decode("ascii")
# Write `encoded` to the sequence_base64 column
```

**What the loader does:** `base64.b64decode(encoded)` → stores the raw zlib bytes directly in `ContigSequence.data`. No double-compression.

**Decoding (to get original sequence):**

```python
import zlib
original = zlib.decompress(stored_bytes).decode("utf-8")
# Or use: ContigSequence.get_sequence()
```

---

### 4. `bgcs.tsv`

One row per BGC prediction. Each BGC belongs to a contig and was detected by a specific detector. The loader automatically assigns BGCs to aggregated regions and generates structured accessions.

| Column | Type | Required | Description | Example |
|--------|------|----------|-------------|---------|
| `contig_accession` | string | **yes** | Parent contig (must exist in `contigs.tsv`) | `MGYC000000001` |
| `detector_name` | string | **yes** | Detector label (must exist in `detectors.tsv`) | `antiSMASH v7.1` |
| `source_bgc_id` | integer | **yes** | Cross-reference ID from source DB (unique) | `5001` |
| `start_position` | integer | **yes** | Start coordinate on contig (bp) | `10000` |
| `end_position` | integer | **yes** | End coordinate on contig (bp) | `45000` |
| `classification_path` | string | no | ltree dot-path for BGC class hierarchy | `Polyketide.Macrolide.14_membered` |
| `classification_l1` | string | no | Top-level class | `Polyketide` |
| `classification_l2` | string | no | Second-level class | `Macrolide` |
| `classification_l3` | string | no | Third-level class | `14_membered` |
| `novelty_score` | float | no | Novelty score (default 0.0) | `0.85` |
| `domain_novelty` | float | no | Domain-level novelty (default 0.0) | `0.72` |
| `size_kb` | float | no | BGC size in kilobases (default 0.0) | `35.0` |
| `nearest_mibig_accession` | string | no | Closest MIBiG cluster | `BGC0000001` |
| `nearest_mibig_distance` | float | no | Distance to nearest MIBiG (nullable) | `0.15` |
| `is_partial` | boolean | no | `true`/`1` if on contig edge | `false` |
| `is_validated` | boolean | no | `true`/`1` if experimentally validated | `false` |
| `is_mibig` | boolean | no | `true`/`1` if this IS a MIBiG entry | `false` |
| `umap_x` | float | no | UMAP x coordinate (default 0.0) | `-3.45` |
| `umap_y` | float | no | UMAP y coordinate (default 0.0) | `7.82` |

**Uniqueness:** `source_bgc_id` (unique). Conflicts are silently ignored (`ignore_conflicts=True`).  
**FK resolution key:** `source_bgc_id` is used in all downstream files.

**Auto-computed by loader:**
- `bgc_accession` — structured accession: `MGYB{region_id:08}.{tool_code}.{detector_id}.{bgc_number:02}`  
  Example: `MGYB00000123.ANT.1.01`
- `region_id` — assigned via overlapping-interval logic (see Region Assignment below)
- `bgc_number` — 2-digit sequential within region + detector
- `assembly_id` — resolved from contig's parent assembly

---

### 5. `cds.tsv` (optional)

Coding sequences within BGC regions.

| Column | Type | Required | Description | Example |
|--------|------|----------|-------------|---------|
| `source_bgc_id` | integer | **yes** | Parent BGC (must exist in `bgcs.tsv`) | `5001` |
| `protein_id_str` | string | **yes** | Display identifier (MGYP or protein_identifier) | `MGYP000000001` |
| `start_position` | integer | **yes** | Start on contig (bp) | `10500` |
| `end_position` | integer | **yes** | End on contig (bp) | `11200` |
| `strand` | integer | **yes** | `1` (forward) or `-1` (reverse) | `1` |
| `protein_length` | integer | no | Amino acid length (default 0) | `233` |
| `gene_caller` | string | no | Tool that called this CDS | `Prodigal` |
| `cluster_representative` | string | no | Protein cluster representative ID | `MGYP000000042` |

**FK resolution key:** The tuple `(source_bgc_id, protein_id_str)` is used in `domains.tsv` to resolve the CDS.

---

### 5.5. `cds_sequences.tsv` (optional)

Compressed amino acid sequences for CDS entries. Same encoding as contig sequences: zlib-compressed then base64-encoded.

| Column | Type | Required | Description | Example |
|--------|------|----------|-------------|---------|
| `source_bgc_id` | integer | **yes** | Parent BGC (must exist in `bgcs.tsv`) | `5001` |
| `protein_id_str` | string | **yes** | Protein identifier (must match a CDS in `cds.tsv`) | `MGYP000000001` |
| `sequence_base64` | string | **yes** | Base64-encoded zlib-compressed amino acid sequence | `eJxLSS0u...` |

**FK resolution:** The tuple `(source_bgc_id, protein_id_str)` resolves to a `DashboardCds` via the CDS lookup built in step 5.  
**Uniqueness:** One sequence per CDS (primary key = CDS FK).  
**Conflict handling:** Duplicates silently ignored (`ignore_conflicts=True`).

**Encoding (Python):**

```python
import base64, zlib

aa_seq = "MKTLSLL..."  # raw amino acid string
compressed = zlib.compress(aa_seq.encode("utf-8"))
encoded = base64.b64encode(compressed).decode("ascii")
# Write `encoded` to the sequence_base64 column
```

**What the loader does:** `base64.b64decode(encoded)` → stores the raw zlib bytes directly in `CdsSequence.data`.

**Decoding:**

```python
# Use: CdsSequence.get_sequence()
```

---

### 6. `domains.tsv` (optional)

Protein domain annotations on CDS entries within BGCs.

| Column | Type | Required | Description | Example |
|--------|------|----------|-------------|---------|
| `source_bgc_id` | integer | **yes** | Parent BGC (must exist in `bgcs.tsv`) | `5001` |
| `protein_id_str` | string | no | Protein identifier (links to CDS if match found) | `MGYP000000001` |
| `domain_acc` | string | **yes** | Domain accession | `PF00109` |
| `domain_name` | string | no | Domain name | `Beta-ketoacyl synthase` |
| `domain_description` | string | no | Longer description | `Beta-ketoacyl synthase, N-terminal` |
| `ref_db` | string | no | Reference database | `Pfam` |
| `start_position` | integer | no | Start on protein (aa, default 0) | `15` |
| `end_position` | integer | no | End on protein (aa, default 0) | `260` |
| `score` | float | no | Hit score (nullable) | `125.3` |

**Uniqueness constraint:** `(bgc, domain_acc, cds, start_position, end_position)` must be unique. Conflicts are silently ignored.

> **Note:** The `url` field on the `BgcDomain` model is NOT populated from TSV — it defaults to empty.

---

### 7. `embeddings_bgc.tsv` (optional)

BGC embedding vectors (1152-dimensional, half-precision storage).

| Column | Type | Required | Description | Example |
|--------|------|----------|-------------|---------|
| `source_bgc_id` | integer | **yes** | Parent BGC (must exist in `bgcs.tsv`) | `5001` |
| `vector_base64` | string | **yes** | Base64-encoded float32 vector (little-endian) | `AAAAAAAAAIA/...` |

**Vector format:** 1152 x float32 = 4608 bytes raw → ~6144 characters base64.

```python
# Producing a conformant vector
import numpy as np, base64
vec = model.encode(bgc)  # shape (1152,), dtype float32
encoded = base64.b64encode(vec.astype(np.float32).tobytes()).decode("ascii")
```

---

### 8. `natural_products.tsv` (optional)

Characterized natural products linked to BGCs.

| Column | Type | Required | Description | Example |
|--------|------|----------|-------------|---------|
| `source_bgc_id` | integer | **yes** | Parent BGC (must exist in `bgcs.tsv`) | `5001` |
| `name` | string | **yes** | Compound name | `erythromycin` |
| `smiles` | string | no | SMILES string | `CC(O)C1CC(=O)...` |
| `np_class_path` | string | no | ltree dot-path for NP class hierarchy | `Polyketide.Macrolide.Erythromycin` |
| `chemical_class_l1` | string | no | Top-level chemical class | `Polyketide` |
| `chemical_class_l2` | string | no | Second-level class | `Macrolide` |
| `chemical_class_l3` | string | no | Third-level class | `Erythromycin` |
| `structure_svg_base64` | string | no | Base64-encoded SVG of structure | `PHN2Zy...` |
| `producing_organism` | string | no | Producing organism name | `Saccharopolyspora erythraea` |
| `morgan_fp_base64` | string | no | Base64-encoded Morgan fingerprint (2048-bit) | `AAAB...` |

**Morgan fingerprint encoding:**

```python
from rdkit.Chem import AllChem, MolFromSmiles
import base64

mol = MolFromSmiles(smiles)
fp = AllChem.GetMorganFingerprintAsBitVect(mol, radius=2, nBits=2048)
raw = fp.ToBitString()  # or use DataStructs.BitVectToBinaryText
encoded = base64.b64encode(raw_bytes).decode("ascii")
```

---

### 9. `mibig_references.tsv` (optional)

Known chemistry landmarks for UMAP visualization (~200 rows typically).

| Column | Type | Required | Description | Example |
|--------|------|----------|-------------|---------|
| `accession` | string | **yes** | MIBiG accession (unique) | `BGC0000001` |
| `compound_name` | string | no | Compound name | `erythromycin` |
| `bgc_class` | string | no | BGC class label | `Polyketide` |
| `umap_x` | float | no | UMAP x coordinate (default 0.0) | `-2.5` |
| `umap_y` | float | no | UMAP y coordinate (default 0.0) | `4.1` |
| `embedding_base64` | string | no | Base64-encoded float32 vector (1152-dim) | `AAAA...` |
| `source_bgc_id` | integer | no | Link to a discovered BGC (nullable) | `5001` |

**Uniqueness:** `accession` must be unique.

> **Note:** MIBiG embeddings use **full-precision** VectorField (not half), since there are few rows and precision matters for reference lookups.

---

### 10. `gcf.tsv` (optional)

Gene Cluster Families.

| Column | Type | Required | Description | Example |
|--------|------|----------|-------------|---------|
| `family_id` | string | **yes** | Family identifier (unique) | `GCF_000001` |
| `representative_source_bgc_id` | integer | no | Source BGC ID of representative member | `5001` |
| `member_count` | integer | no | Number of BGCs in family (default 0) | `15` |
| `known_chemistry_annotation` | string | no | Known chemistry label | `erythromycin-like` |
| `mibig_accession` | string | no | Associated MIBiG accession | `BGC0000001` |
| `mean_novelty` | float | no | Average novelty score of members (default 0.0) | `0.65` |
| `mibig_count` | integer | no | Count of MIBiG members (default 0) | `2` |

**Uniqueness:** `family_id` must be unique.

---

## Region Assignment (Auto-Computed)

The loader does NOT expect region data in the TSV. Regions are computed on-the-fly during BGC loading using interval-tree overlap detection.

### Algorithm

For each BGC `(contig_id, start, end)`:

1. **No overlap** with existing regions on that contig → create a new `DashboardRegion`
2. **One overlap** → extend the existing region's boundaries to encompass the new BGC
3. **Multiple overlaps** → merge all overlapping regions into the survivor (lowest PK), redirect all BGCs, create `RegionAccessionAlias` entries for absorbed regions

### Accession Format

```
MGYB{region_id:08}.{tool_name_code}.{detector_id}.{bgc_number:02}
```

| Part | Source | Example |
|------|--------|---------|
| `MGYB{region_id:08}` | Auto-assigned region primary key | `MGYB00000123` |
| `{tool_name_code}` | 3-letter code from detector's tool name | `ANT` |
| `{detector_id}` | Primary key of DashboardDetector | `1` |
| `{bgc_number:02}` | Sequential counter within region+detector | `01` |

Full example: `MGYB00000123.ANT.1.01`

### Region Aliases

When regions merge, the absorbed region's accession becomes an alias:

```
RegionAccessionAlias:
  alias_accession = "MGYB00000124"  (the absorbed region)
  region_id = 123                    (the surviving region)
```

---

## Post-Load Computed Fields

These fields are populated automatically after all TSV files are loaded. Your pipeline does **not** need to produce them.

### Assembly Scores (on `DashboardAssembly`)

| Field | Computation |
|-------|-------------|
| `bgc_count` | `COUNT(bgcs)` for this assembly |
| `l1_class_count` | `COUNT(DISTINCT bgcs.classification_l1)` |
| `bgc_novelty_score` | `AVG(bgcs.novelty_score)` |

### Catalog Tables (rebuilt from scratch)

| Table | Source |
|-------|--------|
| `DashboardBgcClass` | Distinct `classification_l1` values + count of BGCs per class |
| `DashboardDomain` | Distinct `(domain_acc, domain_name, ref_db)` from `BgcDomain` + count of distinct BGCs per domain |

---

## Validation Summary

### Uniqueness Constraints

| File | Unique Column(s) |
|------|-------------------|
| `detectors.tsv` | `name`; also `(tool, version)` |
| `assemblies.tsv` | `assembly_accession`; `source_assembly_id` |
| `contigs.tsv` | `source_contig_id` |
| `contig_sequences.tsv` | `contig_accession` (PK = contig FK) |
| `bgcs.tsv` | `source_bgc_id` |
| `cds_sequences.tsv` | `(source_bgc_id, protein_id_str)` (PK = CDS FK) |
| `domains.tsv` | `(bgc, domain_acc, cds, start_position, end_position)` |
| `mibig_references.tsv` | `accession` |
| `gcf.tsv` | `family_id` |

### Foreign Key Resolution

| File | Column | Resolves Via | Target |
|------|--------|--------------|--------|
| `contigs.tsv` | `assembly_accession` | in-memory lookup | `DashboardAssembly` |
| `contig_sequences.tsv` | `contig_accession` | in-memory lookup | `DashboardContig` |
| `bgcs.tsv` | `contig_accession` | in-memory lookup | `DashboardContig` |
| `bgcs.tsv` | `detector_name` | in-memory lookup | `DashboardDetector` |
| `cds.tsv` | `source_bgc_id` | in-memory lookup | `DashboardBgc` |
| `cds_sequences.tsv` | `(source_bgc_id, protein_id_str)` | in-memory lookup | `DashboardCds` |
| `domains.tsv` | `source_bgc_id` | in-memory lookup | `DashboardBgc` |
| `domains.tsv` | `(source_bgc_id, protein_id_str)` | in-memory lookup | `DashboardCds` (nullable) |
| `embeddings_bgc.tsv` | `source_bgc_id` | in-memory lookup | `DashboardBgc` |
| `natural_products.tsv` | `source_bgc_id` | in-memory lookup | `DashboardBgc` |
| `mibig_references.tsv` | `source_bgc_id` | in-memory lookup | `DashboardBgc` (nullable) |
| `gcf.tsv` | `representative_source_bgc_id` | in-memory lookup | `DashboardBgc` (nullable) |

### Conflict Handling

All `bulk_create` calls for BGCs, CDS, domains, embeddings, natural products, MIBiG refs, and GCFs use `ignore_conflicts=True`. Duplicate rows (by unique constraint) are silently skipped, making the pipeline **idempotent** for re-runs.

---

## Not Loaded from TSV

The following model data is **not** part of the TSV pipeline and requires separate handling:

| Data | Model | Notes |
|------|-------|-------|
| Protein embeddings | `ProteinEmbedding` | Separate from BGC embeddings |
| Precomputed stats | `PrecomputedStats` | Populated by query-time aggregation service |
| Assembly percentile ranks | `DashboardAssembly.pctl_*` | Not set by loader |
| Assembly diversity/density scores | `DashboardAssembly.bgc_diversity_score`, etc. | Not set by loader |
| Domain URLs | `BgcDomain.url` | Not set by loader |
