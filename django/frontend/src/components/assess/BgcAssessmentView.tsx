import { useAssessStore } from "@/stores/assess-store";
import { useShortlistStore } from "@/stores/shortlist-store";
import { useBgcAssessment } from "@/hooks/use-bgc-assessment";
import { PanelContainer } from "@/components/panels/PanelContainer";
import { AssessmentLoading } from "./AssessmentLoading";
import { GcfContextPanel } from "./GcfContextPanel";
import { NoveltyGauges } from "./NoveltyGauges";
import { DomainDifferentialChart } from "./DomainDifferentialChart";
import { DomainArchitectureComparison } from "./DomainArchitectureComparison";
import { GcfMemberMap } from "./GcfMemberMap";
import { BgcChemicalSpaceMap } from "./BgcChemicalSpaceMap";
import { CrossModeActions } from "./CrossModeActions";
import { AssessmentExportButton } from "./AssessmentExportButton";
import { Button } from "@/components/ui/button";
import { AlertCircle, ListPlus } from "lucide-react";
import { toast } from "sonner";

export function BgcAssessmentView() {
  const assetLabel = useAssessStore((s) => s.assetLabel);
  const assetId = useAssessStore((s) => s.assetId);
  const { isLoading, isError, result, retry } = useBgcAssessment();

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
      {/* Header bar */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">
            BGC Assessment: {result.accession}
          </h2>
          <p className="text-xs text-muted-foreground">
            {result.classification_l1}
            {result.classification_l2 && ` / ${result.classification_l2}`}
            {result.is_novel_singleton && (
              <span className="ml-2 rounded bg-purple-100 px-1.5 py-0.5 text-[10px] font-medium text-purple-700">
                Novel Singleton
              </span>
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              const ok = useShortlistStore.getState().addBgc({
                id: result.bgc_id,
                label: result.accession,
              });
              if (ok) toast.success("Added to BGC shortlist");
              else toast.error("Shortlist full (max 20)");
            }}
          >
            <ListPlus className="mr-1 h-3 w-3" />
            Add to Shortlist
          </Button>
          <AssessmentExportButton />
          <CrossModeActions assetType="bgc" assetId={assetId!} />
        </div>
      </div>

      {/* Top row: GCF Context + Novelty Gauges */}
      <div className="grid gap-4 xl:grid-cols-2">
        <PanelContainer title="GCF Placement">
          <GcfContextPanel
            gcfContext={result.gcf_context}
            distance={result.distance_to_gcf_representative}
            isNovelSingleton={result.is_novel_singleton}
          />
        </PanelContainer>
        <PanelContainer title="Novelty Decomposition" className="min-h-[250px]">
          <NoveltyGauges novelty={result.novelty} />
        </PanelContainer>
      </div>

      {/* Domain differential */}
      {result.domain_differential.length > 0 && (
        <PanelContainer title="Domain Architecture Differential" className="min-h-[250px]">
          <DomainDifferentialChart domains={result.domain_differential} />
        </PanelContainer>
      )}

      {/* Domain architecture comparison */}
      {result.bgc_id && (
        <PanelContainer title="Domain Architecture Comparison">
          <DomainArchitectureComparison
            bgcId={result.bgc_id}
            nearestMibigBgcId={result.nearest_mibig_bgc_id}
            nearestMibigAccession={result.nearest_mibig_accession}
          />
        </PanelContainer>
      )}

      {/* GCF Member Map */}
      {result.gcf_context && (
        <PanelContainer title="GCF Member Map" className="min-h-[350px]">
          <GcfMemberMap
            members={result.gcf_context.member_points}
            submittedPoint={result.submitted_point}
          />
        </PanelContainer>
      )}

      {/* Chemical Space */}
      <PanelContainer title="Chemical Space" className="min-h-[400px]">
        <BgcChemicalSpaceMap
          submittedPoint={result.submitted_point}
          neighbors={result.nearest_neighbors}
          mibigPoints={result.mibig_reference_points}
        />
      </PanelContainer>
    </>
  );
}
