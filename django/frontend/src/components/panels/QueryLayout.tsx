import { QueryResultsRoster } from "@/components/query/QueryResultsRoster";
import { QueryGenomeRoster } from "@/components/query/QueryGenomeRoster";
import { QueryGenomeScatter } from "@/components/query/QueryGenomeScatter";
import { GenomeDetail } from "@/components/genome/GenomeDetail";
import { BgcScatter } from "@/components/bgc/BgcScatter";
import { BgcDetail } from "@/components/bgc/BgcDetail";
import { PanelContainer } from "./PanelContainer";
import { Badge } from "@/components/ui/badge";
import { QueryActions } from "@/components/query/QueryActions";
import { useSelectionStore } from "@/stores/selection-store";
import { useShortlistStore } from "@/stores/shortlist-store";

function GenomeSourceBadge() {
  const bgcShortlist = useShortlistStore((s) => s.bgcs);
  const activeBgcId = useSelectionStore((s) => s.activeBgcId);

  if (bgcShortlist.length > 0) {
    return (
      <Badge variant="outline" className="text-[10px]">
        From {bgcShortlist.length} shortlisted BGC{bgcShortlist.length > 1 ? "s" : ""}
      </Badge>
    );
  }
  if (activeBgcId) {
    return (
      <Badge variant="outline" className="text-[10px]">
        From selected BGC
      </Badge>
    );
  }
  return null;
}

export function QueryLayout() {
  const activeBgcId = useSelectionStore((s) => s.activeBgcId);
  const activeGenomeId = useSelectionStore((s) => s.activeGenomeId);

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

      {/* Genome panels — filtered by BGC shortlist */}
      <div className="grid gap-4 xl:grid-cols-2">
        <PanelContainer title="Genome Roster" className="min-h-[300px]" actions={<GenomeSourceBadge />}>
          <QueryGenomeRoster />
        </PanelContainer>
        <PanelContainer title="Genome Space Map" className="min-h-[300px]" actions={<GenomeSourceBadge />}>
          <QueryGenomeScatter />
        </PanelContainer>
      </div>

      {/* Genome detail */}
      {activeGenomeId && (
        <PanelContainer title="Genome Detail" collapsible>
          <GenomeDetail genomeId={activeGenomeId} />
        </PanelContainer>
      )}

    </div>
  );
}
