import { useGenomeDetail } from "@/hooks/use-genome-detail";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Separator } from "@/components/ui/separator";
import { Star, ExternalLink } from "lucide-react";

interface GenomeDetailProps {
  genomeId: number;
}

function ScoreBar({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex items-center gap-2">
      <span className="w-32 text-xs text-muted-foreground">{label}</span>
      <div className="h-2 flex-1 overflow-hidden rounded-full bg-muted">
        <div
          className="h-full rounded-full bg-primary"
          style={{ width: `${Math.round(value * 100)}%` }}
        />
      </div>
      <span className="w-10 text-right font-mono text-xs">{value.toFixed(2)}</span>
    </div>
  );
}

export function GenomeDetail({ genomeId }: GenomeDetailProps) {
  const { data: genome, isLoading } = useGenomeDetail(genomeId);

  if (isLoading) {
    return (
      <div className="grid gap-4 md:grid-cols-2">
        <Skeleton className="h-40" />
        <Skeleton className="h-40" />
      </div>
    );
  }

  if (!genome) {
    return (
      <p className="py-4 text-center text-sm text-muted-foreground">
        Genome not found
      </p>
    );
  }

  const taxonomy = [
    genome.taxonomy_kingdom,
    genome.taxonomy_phylum,
    genome.taxonomy_class,
    genome.taxonomy_order,
    genome.taxonomy_family,
    genome.taxonomy_genus,
    genome.taxonomy_species,
  ]
    .filter(Boolean)
    .join(" > ");

  return (
    <div className="vf-grid vf-grid__col-2" style={{ gap: "1.5rem" }}>
      {/* Profile */}
      <div className="vf-stack vf-stack--400">
        <div>
          <div className="flex items-center gap-2">
            <h4 className="vf-summary__title">
              {genome.organism_name ?? genome.accession}
            </h4>
            {genome.is_type_strain && (
              <Badge variant="outline" className="gap-1 border-amber-300 text-amber-600">
                <Star className="h-3 w-3 fill-amber-400" />
                Type Strain
              </Badge>
            )}
          </div>
          <p className="mt-1 text-xs text-muted-foreground">{genome.accession}</p>
        </div>

        <div className="space-y-1 text-xs">
          <div>
            <span className="text-muted-foreground">Taxonomy: </span>
            {taxonomy || "-"}
          </div>
          {genome.genome_size_mb && (
            <div>
              <span className="text-muted-foreground">Genome size: </span>
              {genome.genome_size_mb.toFixed(2)} Mb
            </div>
          )}
          {genome.isolation_source && (
            <div>
              <span className="text-muted-foreground">Isolation source: </span>
              {genome.isolation_source}
            </div>
          )}
          {genome.type_strain_catalog_url && (
            <div>
              <a
                href={genome.type_strain_catalog_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-primary hover:underline"
              >
                <ExternalLink className="h-3 w-3" />
                Purchase strain
              </a>
            </div>
          )}
        </div>
      </div>

      {/* Scores */}
      <div className="vf-stack vf-stack--200">
        <h4 className="vf-section-header__heading" style={{ fontSize: "0.875rem" }}>Scores</h4>
        <Separator />
        <ScoreBar label="Composite" value={genome.composite_score} />
        <ScoreBar label="BGC Novelty" value={genome.bgc_novelty_score} />
        <ScoreBar label="BGC Diversity" value={genome.bgc_diversity_score} />
        <ScoreBar label="BGC Density" value={genome.bgc_density} />
        <ScoreBar label="Taxonomic Novelty" value={genome.taxonomic_novelty} />
        {genome.genome_quality !== null && (
          <ScoreBar label="Genome Quality" value={genome.genome_quality} />
        )}
        <div className="flex gap-4 pt-2 text-xs">
          <span>
            <strong>{genome.bgc_count}</strong> BGCs
          </span>
          <span>
            <strong>{genome.l1_class_count}</strong> classes
          </span>
        </div>
      </div>
    </div>
  );
}
