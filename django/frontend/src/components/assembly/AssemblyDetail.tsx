import { useAssemblyDetail } from "@/hooks/use-assembly-detail";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Separator } from "@/components/ui/separator";
import { useShortlistStore } from "@/stores/shortlist-store";
import { Star, ExternalLink, ListPlus } from "lucide-react";
import { toast } from "sonner";
import { HelpTooltip } from "@/components/ui/help-tooltip";

interface AssemblyDetailProps {
  assemblyId: number;
}

function ScoreBar({ label, value, tooltipKey }: { label: string; value: number; tooltipKey?: string }) {
  return (
    <div className="flex items-center gap-2">
      <span className="w-32 flex items-center gap-1 text-xs text-muted-foreground">
        {label}
        {tooltipKey && <HelpTooltip tooltipKey={tooltipKey} side="right" />}
      </span>
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

export function AssemblyDetail({ assemblyId }: AssemblyDetailProps) {
  const { data: assembly, isLoading } = useAssemblyDetail(assemblyId);
  const addAssembly = useShortlistStore((s) => s.addAssembly);

  if (isLoading) {
    return (
      <div className="grid gap-4 md:grid-cols-2">
        <Skeleton className="h-40" />
        <Skeleton className="h-40" />
      </div>
    );
  }

  if (!assembly) {
    return (
      <p className="py-4 text-center text-sm text-muted-foreground">
        Assembly not found
      </p>
    );
  }

  const label = assembly.organism_name ?? assembly.accession;

  return (
    <div className="vf-stack vf-stack--400">
      {/* Action buttons */}
      <div className="flex justify-end gap-2">
        <Button
          variant="outline"
          size="sm"
          className="gap-1 text-xs"
          onClick={() => {
            const ok = addAssembly({ id: assembly.id, label });
            if (ok) toast.success("Added to assembly shortlist");
            else toast.error("Shortlist full");
          }}
        >
          <ListPlus className="h-3 w-3" />
          Add to Assembly Shortlist
        </Button>
      </div>

    <div className="vf-grid vf-grid__col-2" style={{ gap: "1.5rem" }}>
      {/* Profile */}
      <div className="vf-stack vf-stack--400">
        <div>
          <div className="flex items-center gap-2">
            <h4 className="vf-summary__title">
              {assembly.organism_name ?? assembly.accession}
            </h4>
            {assembly.is_type_strain && (
              <Badge variant="outline" className="gap-1 border-amber-300 text-amber-600">
                <Star className="h-3 w-3 fill-amber-400" />
                Type Strain
                <HelpTooltip tooltipKey="type_strain" side="right" />
              </Badge>
            )}
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            {assembly.url ? (
              <a
                href={assembly.url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-primary hover:underline"
              >
                {assembly.accession}
                <ExternalLink className="h-3 w-3" />
              </a>
            ) : (
              assembly.accession
            )}
          </p>
        </div>

        <div className="space-y-1 text-xs">
          {assembly.biome_path && (
            <div>
              <span className="text-muted-foreground">Biome: </span>
              {assembly.biome_path.replace(/\./g, " > ")}
            </div>
          )}
          {assembly.assembly_size_mb && (
            <div>
              <span className="text-muted-foreground">Assembly size: </span>
              {assembly.assembly_size_mb.toFixed(2)} Mb
            </div>
          )}
          {assembly.type_strain_catalog_url && (
            <div>
              <a
                href={assembly.type_strain_catalog_url}
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
        <ScoreBar label="BGC Novelty" value={assembly.bgc_novelty_score} tooltipKey="novelty_score_assembly" />
        <ScoreBar label="BGC Diversity" value={assembly.bgc_diversity_score} tooltipKey="diversity_score" />
        <ScoreBar label="BGC Density" value={assembly.bgc_density} tooltipKey="density" />
        <ScoreBar label="Taxonomic Novelty" value={assembly.taxonomic_novelty} tooltipKey="taxonomic_novelty" />
        <div className="flex gap-4 pt-2 text-xs">
          <span>
            <strong>{assembly.bgc_count}</strong> BGCs
          </span>
          <span>
            <strong>{assembly.l1_class_count}</strong> classes
          </span>
        </div>
      </div>
    </div>
    </div>
  );
}
