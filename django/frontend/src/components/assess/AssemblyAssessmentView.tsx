import { useAssessStore } from "@/stores/assess-store";
import { useShortlistStore } from "@/stores/shortlist-store";
import { useAssemblyAssessment } from "@/hooks/use-assembly-assessment";
import { PanelContainer } from "@/components/panels/PanelContainer";
import { AssessmentLoading } from "./AssessmentLoading";
import { AssemblyRankCard } from "./AssemblyRankCard";
import { PriorityRadar } from "./PriorityRadar";
import { PercentileCharts } from "./PercentileCharts";
import { RedundancyMatrix } from "./RedundancyMatrix";
import { AssessmentBgcStats } from "./AssessmentBgcStats";
import { ChemicalSpaceMap } from "./ChemicalSpaceMap";
import { BgcRoster } from "@/components/bgc/BgcRoster";
import { BgcScatter } from "@/components/bgc/BgcScatter";
import { CrossModeActions } from "./CrossModeActions";
import { AssessmentExportButton } from "./AssessmentExportButton";
import { Button } from "@/components/ui/button";
import { AlertCircle, ListPlus } from "lucide-react";
import { toast } from "sonner";

export function AssemblyAssessmentView() {
  const assetLabel = useAssessStore((s) => s.assetLabel);
  const isUploaded = useAssessStore((s) => s.isUploaded);
  const { isLoading, isError, result, retry } = useAssemblyAssessment();

  if (isLoading) {
    return <AssessmentLoading label={assetLabel} />;
  }

  if (isError || !result) {
    return (
      <div className="flex flex-col items-center justify-center gap-4 py-24 text-muted-foreground">
        <AlertCircle className="h-10 w-10" />
        <p className="text-sm">Assessment failed.</p>
        <button
          onClick={retry}
          className="text-xs underline hover:text-foreground"
        >
          Retry
        </button>
      </div>
    );
  }

  return (
    <>
      {/* Header bar with name and actions */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">
            Assembly Assessment: {result.organism_name || result.accession}
          </h2>
          <p className="text-xs text-muted-foreground">
            {result.accession}
            {result.is_type_strain && (
              <span className="ml-2 rounded bg-orange-100 px-1.5 py-0.5 text-[10px] font-medium text-orange-700">
                Type Strain
              </span>
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {!isUploaded && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                const ok = useShortlistStore.getState().addAssembly({
                  id: result.assembly_id,
                  label: result.organism_name || result.accession,
                });
                if (ok) toast.success("Added to assembly shortlist");
                else toast.error("Shortlist full (max 20)");
              }}
            >
              <ListPlus className="mr-1 h-3 w-3" />
              Add to Shortlist
            </Button>
          )}
          <AssessmentExportButton />
          {!isUploaded && (
            <CrossModeActions assetType="assembly" assetId={result.assembly_id} />
          )}
        </div>
      </div>

      {/* Top row: Rank Card + Radar */}
      <div className="grid gap-4 xl:grid-cols-2">
        <PanelContainer title="Priority Ranking">
          <AssemblyRankCard
            dbRank={result.db_rank}
            dbTotal={result.db_total}
            percentileRanks={result.percentile_ranks}
          />
        </PanelContainer>
        <PanelContainer title="Priority Score Radar" className="min-h-[350px]">
          <PriorityRadar
            percentileRanks={result.percentile_ranks}
            radarReferences={result.radar_references}
          />
        </PanelContainer>
      </div>

      {/* Percentile distribution charts */}
      <PanelContainer title="Score Percentile Distributions">
        <PercentileCharts
          percentileRanks={result.percentile_ranks}
          radarReferences={result.radar_references}
        />
      </PanelContainer>

      {/* BGC Triad — same layout as ExploreLayout */}
      <div className="grid gap-4 xl:grid-cols-2 xl:grid-rows-[450px_420px]">
        <PanelContainer title="BGC Roster" className="xl:row-span-2" constrained>
          <BgcRoster assemblyIdOverride={result.assembly_id} />
        </PanelContainer>
        <PanelContainer title="BGC Space Map" className="h-full" constrained>
          <BgcScatter
            assemblyIdsOverride={[result.assembly_id]}
            markerSymbol="star"
          />
        </PanelContainer>
        <PanelContainer title="BGC Stats" className="h-full" constrained>
          <AssessmentBgcStats bgcNovelty={result.bgc_novelty_breakdown} />
        </PanelContainer>
      </div>

      {/* Redundancy Matrix */}
      <PanelContainer title="Redundancy Matrix" className="min-h-[300px]">
        <RedundancyMatrix matrix={result.redundancy_matrix} />
      </PanelContainer>

      {/* BGC Embeddings Map — real UMAP */}
      {result.chemical_space_points.length > 0 && (
        <PanelContainer title="BGC Embeddings Map" className="min-h-[400px]">
          <ChemicalSpaceMap
            points={result.chemical_space_points}
            validatedPoints={result.validated_reference_points}
            meanValidatedDistance={result.mean_nearest_validated_distance}
            sparseFraction={result.sparse_fraction}
          />
        </PanelContainer>
      )}
    </>
  );
}
