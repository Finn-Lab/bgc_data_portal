__all__ = ["device", "ESMEmbedder", "parse_arguments", "main"]

import torch
from typing import List, Optional, Union
from Bio import SeqIO
from tqdm import tqdm
import torch.nn.functional as F
from esm.models.esmc import ESMC
from esm.sdk.api import ESMProtein, LogitsConfig

device = "cuda" if torch.cuda.is_available() else "cpu"
if device == "cuda":
    print("Using GPU")
else:
    print("Using CPU")


class ESMEmbedder:
    """Class to embed protein sequences using ESMC model."""

    def __init__(self, model_name="esmc_300m", device=device, logits_config_dct=None):
        self.device = device
        self.client = ESMC.from_pretrained(model_name).to(device)
        self.logits_config_dct = logits_config_dct or {
            "sequence": True,
            "return_embeddings": True,
            "return_hidden_states": True,
            # "ith_hidden_layer": 29,
        }

    def _get_embeddings(self, protein_sequence):
        protein = ESMProtein(sequence=protein_sequence)
        protein_tensor = self.client.encode(protein)
        logits_output = self.client.logits(
            protein_tensor, LogitsConfig(**self.logits_config_dct)
        )
        return logits_output

    def embed(
        self, protein_sequences: Union[str, list[str]]  # Protein sequences to embed
    ) -> torch.stack:
        if isinstance(protein_sequences, str):
            protein_sequences = [protein_sequences]
        embeddings = []
        for sequence in tqdm(protein_sequences, desc="Embedding protein sequences"):
            embedding = self._get_embeddings(sequence).embeddings
            embeddings.append(torch.mean(embedding, dim=-2).squeeze())
        return embeddings

    @staticmethod
    def mean_embeddings(
        normalized_protein_embeddings: torch.Tensor,
        weights: Optional[List[float]] = None,  # This works with fuzzy BGCs
        device: str = "cpu",
    ):  # returns a tensor with mean embedding
        if weights is not None:
            weights_tensor = torch.tensor(weights, dtype=torch.float32, device=device)
            weights_tensor = weights_tensor / weights_tensor.sum()
            mean_embedding = torch.sum(
                normalized_protein_embeddings * weights_tensor[:, None], dim=0
            )
        else:
            mean_embedding = normalized_protein_embeddings.mean(dim=0)
        return mean_embedding

    def embed_gene_cluster(
        self,
        protein_sequences: list[str],
        ith_hidden_layer: int = 26,  # 26th is based on our benchmarks for esmc_300m. See bgc_vectors repo for details
        weights: list[float] = None,  # This works with fuzzy BGCs
    ):  # returns a tuple of embeddings and mean embedding
        """
        Compute a mean embedding for a gene cluster based on a specific hidden layer.

        Args:
            protein_sequences (list[str]): List of protein sequences.
            ith_hidden_layer (int): Index of the hidden layer to use. If None, uses final embeddings.
            weights (list[float], optional): Weights for each sequence. Must match the length of protein_sequences.

        Returns:
            tuple of vectors: protein embeddings and Mean embedding vector for the gene cluster.
        """
        if weights is not None and len(weights) != len(protein_sequences):
            raise ValueError(
                "Length of weights must match the number of protein sequences"
            )

        embeddings = []
        for sequence in protein_sequences:
            logits_output = self._get_embeddings(sequence)
            if ith_hidden_layer is not None:
                embedding = logits_output.hidden_states.squeeze(1).mean(dim=1)[
                    ith_hidden_layer
                ]
            else:
                embedding = torch.mean(logits_output.embeddings, dim=-2).squeeze()
            embeddings.append(embedding)

        embeddings_tensor = torch.stack(embeddings)

        normalized = F.normalize(embeddings_tensor, p=2, dim=1)

        mean_embedding = self.mean_embeddings(
            normalized_protein_embeddings=normalized,
            weights=weights,
            device=self.device,
        )
        normalized_mean_embedding = F.normalize(mean_embedding, p=2, dim=0)
        return embeddings_tensor.tolist(), normalized_mean_embedding.tolist()

    def embed_from_file(
        self,
        protein_sequences_file: str,  # Path to file, aa fasta or genebank containing protein sequences
        format: str = "fasta",  # Format of the file, fasta or genbank
        output_file: str = None,  # Path to save the embeddings
    ):
        """
        Embed proteins from a file. It uses SeqIO to parse the file and extract protein sequences.
        and get output as a dictionary of numpy tensors where the key is the protein accesion from the record.name.
        """

        protein_sequences = {}
        # get protein sequences from file
        if format == "fasta":
            protein_sequences = {
                record.id: record.seq
                for record in SeqIO.parse(protein_sequences_file, "fasta")
            }
        elif format == "genbank":
            nuc_records = SeqIO.parse(protein_sequences_file, "genbank")
            for record in nuc_records:
                for feature in record.features:
                    if feature.type == "CDS":
                        protein_sequences[
                            feature.qualifiers.get("protein_id", [None])[0]
                            or feature.qualifiers.get("locus_tag", [None])[0]
                        ] = str(feature.qualifiers["translation"][0])
        else:
            raise ValueError("Format must be either fasta or genbank")

        # generate dictionary with protein embeddings

        embeddings_dictionary = {}
        for prot_id, protein_sequence in protein_sequences.items():
            logits_output = self._get_embeddings(protein_sequence)
            embedding = torch.mean(logits_output.embeddings, dim=-2).squeeze()
            hidden = logits_output.hidden_states.squeeze(1).mean(dim=1)
            embeddings_dictionary[protein_sequence] = (embedding, hidden)

        # save to file if output_file:
        if output_file:
            torch.save(embeddings_dictionary, output_file)

        return embeddings_dictionary


def parse_arguments():
    import argparse

    parser = argparse.ArgumentParser(
        description="Embed protein sequences using ESMC model"
    )
    parser.add_argument(
        "--input_file",
        type=str,
        required=True,
        help="Path to the input file containing protein sequences in fasta or genbank format",
    )
    parser.add_argument(
        "--output_file",
        type=str,
        required=True,
        help="Path to the output file to save the embeddings",
    )
    parser.add_argument(
        "--format",
        type=str,
        default="fasta",
        help="Format of the input file, either fasta or genbank",
    )
    return parser.parse_args()


def main():
    args = parse_arguments()
    embedder = ESMEmbedder()
    embeddings = embedder.embed_from_file(
        args.input_file, format=args.format, output_file=args.output_file
    )

    print(f"Embeddings saved to {args.output_file}")


if __name__ == "__main__":
    main()
