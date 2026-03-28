import { QueryResultsRoster } from "@/components/query/QueryResultsRoster";
import { GenomeAggregationRoster } from "@/components/query/GenomeAggregationRoster";
import { BgcScatter } from "@/components/bgc/BgcScatter";
import { BgcDetail } from "@/components/bgc/BgcDetail";
import { PanelContainer } from "./PanelContainer";
import { QueryActions } from "@/components/query/QueryActions";
import { useSelectionStore } from "@/stores/selection-store";

export function QueryLayout() {
  const activeBgcId = useSelectionStore((s) => s.activeBgcId);

  return (
    <div className="flex flex-1 flex-col gap-4 overflow-auto p-4">
      {/* Query controls */}
      <QueryActions />

      {/* BGC results + scatter */}
      <div className="grid gap-4 xl:grid-cols-2">
        <PanelContainer title="BGC Query Results" className="min-h-[300px]">
          <QueryResultsRoster />
        </PanelContainer>
        <PanelContainer title="BGC Chemical Space (UMAP)" className="min-h-[300px]">
          <BgcScatter />
        </PanelContainer>
      </div>

      {/* BGC detail */}
      {activeBgcId && (
        <PanelContainer title="BGC Detail" collapsible>
          <BgcDetail bgcId={activeBgcId} />
        </PanelContainer>
      )}

      {/* Genome aggregation */}
      <PanelContainer title="Genome Aggregation" className="min-h-[250px]">
        <GenomeAggregationRoster />
      </PanelContainer>

    </div>
  );
}
