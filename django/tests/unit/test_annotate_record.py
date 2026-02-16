import types
import sys
from pathlib import Path


# Ensure the `django` package directory is on sys.path so tests can import the package
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import types as _types

# Provide a lightweight fake `pyrodigal` module for import-time to avoid heavy deps during collection.
fake_pyrodigal = _types.ModuleType("pyrodigal")
fake_pyrodigal.GeneFinder = lambda meta=True: _types.SimpleNamespace(
    find_genes=lambda seq: iter(())
)
import sys as _sys

_sys.modules.setdefault("pyrodigal", fake_pyrodigal)
# Some project modules import third-party libs at import-time (e.g. pgvector). Provide lightweight fakes.
fake_pgvector = _types.ModuleType("pgvector")
fake_pgvector.django = _types.SimpleNamespace(
    VectorField=lambda *a, **k: object, HnswIndex=lambda *a, **k: object
)
_sys.modules.setdefault("pgvector", fake_pgvector)
_sys.modules.setdefault("pgvector.django", fake_pgvector.django)

# Provide a fake lazy_loaders module so importing `annotate_record` doesn't import project models
fake_lazy = _types.ModuleType("mgnify_bgcs.utils.lazy_loaders")


def _fake_protein_embedder():
    class E:
        def embed_gene_cluster(self, protein_sequences):
            return (["fake_emb" for _ in protein_sequences], "bgc_fake")

    return E


def _fake_umap_model():
    class U:
        def transform(self, arr):
            return [[0.0, 0.0] for _ in arr]

    return U


fake_lazy.protein_embedder = lambda: _fake_protein_embedder()
fake_lazy.umap_model = lambda: _fake_umap_model()
_sys.modules.setdefault("mgnify_bgcs.utils.lazy_loaders", fake_lazy)

from mgnify_bgcs.services.annotate_record import (
    SeqAnnotator,
    detect_format_from_string,
)


def test_detect_format_from_string_fasta():
    data = [">seq1", "ATGC"]
    assert detect_format_from_string(data) == "fasta"


def test_detect_format_from_string_gbk():
    data = ["LOCUS       SCU49845     5028 bp    DNA             PLN       21-JUN-1999"]
    assert detect_format_from_string(data) == "gbk"


def test_detect_format_from_string_unknown():
    data = ["", "   ", "something else"]
    assert detect_format_from_string(data) == "unknown"


def make_fake_pred(begin, end, strand, aa):
    # Minimal object that pyrodigal returns
    class P:
        def __init__(self, begin, end, strand, aa):
            self.begin = begin
            self.end = end
            self.strand = strand

        def translate(self):
            return aa

    return P(begin, end, strand, aa)


def test_load_fasta_nucleotide_predict_genes_and_embed(monkeypatch):
    # Prepare a simple nucleotide FASTA
    fasta = ">contig1\nATGAAATTTGGGCCCTTTAAATAG\n"

    # Mock pyrodigal.GeneFinder and its find_genes
    fake_finder = types.SimpleNamespace()

    # Two fake predictions
    fake_preds = [make_fake_pred(0, 9, 1, "MKF"), make_fake_pred(9, 21, 1, "GL*")]

    def fake_find_genes(seq_bytes):
        # ensure we received bytes
        assert isinstance(seq_bytes, (bytes, bytearray))
        for p in fake_preds:
            yield p

    fake_finder.find_genes = fake_find_genes

    monkeypatch.setattr(
        "mgnify_bgcs.services.annotate_record.pyrodigal.GeneFinder",
        lambda meta=True: fake_finder,
    )

    # Monkeypatch SeqIO.read to return a simple record-like object whose seq is bytes
    class DummyRec:
        def __init__(self, seq_bytes, id):
            self.seq = seq_bytes
            self.id = id
            self.features = []
            self.annotations = {}

    # Provide a sequence-like object that supports str() and bytes()
    class FakeSeq:
        def __init__(self, s: str):
            self._s = s

        def __str__(self):
            return self._s

        def __bytes__(self):
            return self._s.encode("ascii")

    monkeypatch.setattr(
        "mgnify_bgcs.services.annotate_record.SeqIO.read",
        lambda fasta_io, fmt: DummyRec(FakeSeq("ATGAAATTTGGGCCCTTTAAATAG"), "contig1"),
    )

    # Mock embedder to return embeddings
    class FakeEmbedder:
        def embed_gene_cluster(self, protein_sequences):
            # return embeddings for each protein and a bgc_embedding
            return (["emb1", "emb2"], "bgc_emb")

    monkeypatch.setattr(
        "mgnify_bgcs.services.annotate_record.protein_embedder", lambda: FakeEmbedder()
    )

    # Mock umap
    class FakeUMAP:
        def transform(self, arr):
            return [[1.0, 2.0]]

    monkeypatch.setattr(
        "mgnify_bgcs.services.annotate_record.umap_model", lambda: FakeUMAP()
    )

    annotator = SeqAnnotator()
    rec = annotator.annotate_sequence_file(fasta, molecule_type="nucleotide")

    # Should have two CDS features appended
    cds = [f for f in rec.features if f.type == "CDS"]
    assert len(cds) == 2
    # Each CDS should have translation and embedding qualifiers
    for f in cds:
        assert "translation" in f.qualifiers
        assert "embedding" in f.qualifiers

    # bgc_embedding and umap coords should be present in annotations
    assert rec.annotations.get("bgc_embedding") == "bgc_emb"
    assert rec.annotations.get("umap_x_coord") == 1.0
    assert rec.annotations.get("umap_y_coord") == 2.0


def test_load_fasta_protein_backtranslate_and_embed(monkeypatch):
    # Simple protein FASTA (single-letter amino acids)
    fasta = ">prot1\nMKT\n"

    # Ensure GeneFinder is present but harmless (SeqAnnotator constructor always instantiates it)
    monkeypatch.setattr(
        "mgnify_bgcs.services.annotate_record.pyrodigal.GeneFinder",
        lambda meta=True: types.SimpleNamespace(find_genes=lambda seq: iter(())),
    )

    # Mock codon back_table by patching CodonTable used in module if needed is not necessary

    # Mock embedder
    class FakeEmbedder:
        def embed_gene_cluster(self, protein_sequences):
            return (["embA"], "bgcA")

    monkeypatch.setattr(
        "mgnify_bgcs.services.annotate_record.protein_embedder", lambda: FakeEmbedder()
    )

    class FakeUMAP:
        def transform(self, arr):
            return [[3.0, 4.0]]

    monkeypatch.setattr(
        "mgnify_bgcs.services.annotate_record.umap_model", lambda: FakeUMAP()
    )

    # Monkeypatch SeqIO.read to return a simple record-like object with a protein seq string
    class DummyProtRec:
        def __init__(self, seq_str, id):
            self.seq = seq_str
            self.id = id
            self.features = []
            self.annotations = {}

    monkeypatch.setattr(
        "mgnify_bgcs.services.annotate_record.SeqIO.read",
        lambda fasta_io, fmt: DummyProtRec("MKT", "prot1"),
    )

    annotator = SeqAnnotator()
    rec = annotator.annotate_sequence_file(fasta, molecule_type="protein")

    # Should have one CDS feature
    cds = [f for f in rec.features if f.type == "CDS"]
    assert len(cds) == 1
    f = cds[0]
    assert "translation" in f.qualifiers
    assert f.qualifiers["translation"][0] == "MKT"
    assert "embedding" in f.qualifiers
    assert rec.annotations["bgc_embedding"] == "bgcA"


def test_annotate_record_no_proteins(monkeypatch):
    # Create a minimal genbank-like record with no CDS translations
    from Bio.Seq import Seq
    from Bio.SeqRecord import SeqRecord

    rec = SeqRecord(Seq("ATG"), id="empty")
    # ensure features is empty
    rec.features = []

    # instantiate and call _annotate_record directly
    annot = SeqAnnotator()

    # Patch embedder & umap to ensure they are not called
    monkeypatch.setattr(
        "mgnify_bgcs.services.annotate_record.protein_embedder",
        lambda: (_ for _ in ()).throw(RuntimeError("should not be called")),
    )
    monkeypatch.setattr(
        "mgnify_bgcs.services.annotate_record.umap_model",
        lambda: (_ for _ in ()).throw(RuntimeError("should not be called")),
    )

    out = annot._annotate_record(rec)
    # Should be the same record and annotations unchanged
    assert out is rec
    assert "bgc_embedding" not in out.annotations
