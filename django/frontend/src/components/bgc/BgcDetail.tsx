import { useEffect, useState } from "react";
import { useBgcDetail } from "@/hooks/use-bgc-detail";
import { useBgcRegion } from "@/hooks/use-bgc-region";
import { RegionPlot } from "./RegionPlot";
import { CdsProteinInfo } from "./CdsProteinInfo";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Separator } from "@/components/ui/separator";
import { useModeStore } from "@/stores/mode-store";
import { useSelectionStore } from "@/stores/selection-store";
import { useQueryStore } from "@/stores/query-store";
import { ExternalLink, Microscope, Search, Star } from "lucide-react";
import type { RegionCds } from "@/api/types";

interface BgcDetailProps {
  bgcId: number;
}

export function BgcDetail({ bgcId }: BgcDetailProps) {
  const { data: bgc, isLoading } = useBgcDetail(bgcId);
  const { data: regionData, isLoading: regionLoading } = useBgcRegion(bgcId);
  const setMode = useModeStore((s) => s.setMode);
  const setActiveGenomeId = useSelectionStore((s) => s.setActiveGenomeId);
  const setSimilarBgcSourceId = useQueryStore((s) => s.setSimilarBgcSourceId);
  const [selectedCds, setSelectedCds] = useState<RegionCds | null>(null);

  // Reset selected CDS when bgcId changes
  useEffect(() => {
    setSelectedCds(null);
  }, [bgcId]);

  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-20 w-full" />
        <Skeleton className="h-8 w-full" />
      </div>
    );
  }

  if (!bgc) {
    return (
      <p className="py-4 text-center text-sm text-muted-foreground">
        BGC not found
      </p>
    );
  }

  const classification = [
    bgc.classification_l1,
    bgc.classification_l2,
    bgc.classification_l3,
  ]
    .filter(Boolean)
    .join(" > ");

  return (
    <div className="vf-stack vf-stack--400">
      <div className="flex items-start justify-between">
        <div>
          <h4 className="vf-summary__title" style={{ fontFamily: "monospace" }}>{bgc.accession}</h4>
          <p className="mt-1 text-sm text-muted-foreground">{classification}</p>
          <div className="mt-2 flex flex-wrap gap-2">
            <Badge variant={bgc.is_partial ? "outline" : "secondary"}>
              {bgc.is_partial ? "Partial" : "Complete"}
            </Badge>
            {bgc.is_validated && <Badge variant="default">Validated</Badge>}
            <Badge variant="outline">{bgc.size_kb.toFixed(1)} kb</Badge>
          </div>
        </div>
        <div className="flex gap-2">
          {bgc.parent_genome && (
            <Button
              variant="outline"
              size="sm"
              className="gap-1 text-xs"
              onClick={() => {
                setActiveGenomeId(bgc.parent_genome!.assembly_id);
                setMode("explore");
              }}
            >
              <Microscope className="h-3 w-3" />
              Explore parent genome
            </Button>
          )}
          <Button
            variant="outline"
            size="sm"
            className="gap-1 text-xs"
            onClick={() => {
              setSimilarBgcSourceId(bgc.id);
              setMode("query");
            }}
          >
            <Search className="h-3 w-3" />
            Find similar BGCs
          </Button>
        </div>
      </div>

      <Separator />

      {/* Scores */}
      <div className="vf-grid vf-grid__col-4" style={{ gap: "1rem", fontSize: "0.75rem" }}>
        <article className="vf-summary">
          <h3 className="vf-summary__title" style={{ fontSize: "0.75rem" }}>Novelty</h3>
          <p className="vf-summary__text font-mono font-medium">{bgc.novelty_score.toFixed(3)}</p>
        </article>
        <article className="vf-summary">
          <h3 className="vf-summary__title" style={{ fontSize: "0.75rem" }}>Domain Novelty</h3>
          <p className="vf-summary__text font-mono font-medium">{bgc.domain_novelty.toFixed(3)}</p>
        </article>
        {bgc.nearest_mibig_accession && (
          <article className="vf-summary">
            <h3 className="vf-summary__title" style={{ fontSize: "0.75rem" }}>Nearest MIBiG</h3>
            <p className="vf-summary__text font-mono font-medium">
              {bgc.nearest_mibig_accession}
            </p>
            <p className="vf-summary__text text-muted-foreground">
              dist: {bgc.nearest_mibig_distance?.toFixed(3)}
            </p>
          </article>
        )}
      </div>

      <Separator />

      {/* Parent assembly */}
      {bgc.parent_genome && (
        <>
          <div className="text-xs">
            <h5 className="vf-section-header__heading" style={{ fontSize: "0.875rem", marginBottom: "0.25rem" }}>Parent Assembly</h5>
            <div className="flex items-center gap-2">
              <a
                href={`https://www.ebi.ac.uk/ena/browser/view/${bgc.parent_genome.accession}`}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-blue-600 hover:underline"
              >
                {bgc.parent_genome.organism_name ?? bgc.parent_genome.accession}
                <ExternalLink className="h-3 w-3" />
              </a>
              {bgc.parent_genome.is_type_strain && (
                <Star className="h-3 w-3 fill-amber-400 text-amber-400" />
              )}
              {bgc.parent_genome.taxonomy_family && (
                <Badge variant="outline" className="text-[10px]">
                  {bgc.parent_genome.taxonomy_family}
                </Badge>
              )}
            </div>
            {bgc.parent_genome.isolation_source && (
              <div className="mt-1 text-muted-foreground">
                Isolation source: {bgc.parent_genome.isolation_source}
              </div>
            )}
          </div>
          <Separator />
        </>
      )}

      {/* Chemical compounds */}
      {bgc.natural_products && bgc.natural_products.length > 0 && (
        <>
          <div>
            <h5 className="vf-section-header__heading" style={{ fontSize: "0.875rem", marginBottom: "0.25rem" }}>
              Chemical Compounds
            </h5>
            <div className="space-y-2">
              {bgc.natural_products.map((np) => (
                <div key={np.id} className="flex items-start gap-3 rounded-md border p-2">
                  {np.smiles_svg && (
                    <div
                      className="flex-shrink-0"
                      dangerouslySetInnerHTML={{ __html: np.smiles_svg }}
                    />
                  )}
                  <div className="text-xs">
                    <div className="font-medium">{np.name}</div>
                    <div className="text-muted-foreground">
                      {[np.chemical_class_l1, np.chemical_class_l2, np.chemical_class_l3]
                        .filter(Boolean)
                        .join(" > ")}
                    </div>
                    <div className="mt-1 font-mono text-[10px] text-muted-foreground break-all">
                      {np.smiles}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
          <Separator />
        </>
      )}

      {/* Explore Region */}
      <div>
        <h5 className="vf-section-header__heading" style={{ fontSize: "0.875rem", marginBottom: "0.5rem" }}>Explore Region</h5>
        {regionLoading ? (
          <Skeleton className="h-40 w-full" />
        ) : regionData ? (
          <>
            <RegionPlot
              data={regionData}
              onCdsClick={(cds) =>
                setSelectedCds((prev) =>
                  prev?.protein_id === cds.protein_id ? null : cds,
                )
              }
              selectedCdsId={selectedCds?.protein_id ?? null}
            />
            {selectedCds && (
              <CdsProteinInfo
                cds={selectedCds}
                onClose={() => setSelectedCds(null)}
              />
            )}
          </>
        ) : (
          <p className="text-xs text-muted-foreground">No region data</p>
        )}
      </div>
    </div>
  );
}
