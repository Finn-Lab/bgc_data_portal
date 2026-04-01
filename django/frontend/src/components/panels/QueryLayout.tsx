import { QueryResultsRoster } from "@/components/query/QueryResultsRoster";
import { QueryGenomeRoster } from "@/components/query/QueryGenomeRoster";
import { QueryGenomeScatter } from "@/components/query/QueryGenomeScatter";
import { GenomeDetail } from "@/components/genome/GenomeDetail";
import { BgcScatter } from "@/components/bgc/BgcScatter";
import { BgcDetail } from "@/components/bgc/BgcDetail";
import { BgcStats, BgcStatsActions } from "@/components/bgc/BgcStats";
import { GenomeStats, GenomeStatsActions } from "@/components/genome/GenomeStats";
import { PanelContainer } from "./PanelContainer";
import { Badge } from "@/components/ui/badge";
import { QueryActions } from "@/components/query/QueryActions";
import { useSelectionStore } from "@/stores/selection-store";
import { useShortlistStore } from "@/stores/shortlist-store";
import { useQueryStore } from "@/stores/query-store";
import { useParentAssemblies } from "@/hooks/use-parent-assemblies";

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

function useQueryAssemblyIds(): string | undefined {
  const bgcShortlist = useShortlistStore((s) => s.bgcs);
  const activeBgcId = useSelectionStore((s) => s.activeBgcId);
  const bgcIds =
    bgcShortlist.length > 0
      ? bgcShortlist.map((b) => b.id)
      : activeBgcId
        ? [activeBgcId]
        : [];
  const { data: assemblyIds } = useParentAssemblies(bgcIds);
  return assemblyIds && assemblyIds.length > 0
    ? assemblyIds.join(",")
    : undefined;
}

export function QueryLayout() {
  const activeBgcId = useSelectionStore((s) => s.activeBgcId);
  const activeGenomeId = useSelectionStore((s) => s.activeGenomeId);
  const queryAssemblyIds = useQueryAssemblyIds();
  const resultBgcIds = useQueryStore((s) => s.resultBgcIds);

  return (
    <div className="flex flex-1 flex-col gap-4 overflow-auto p-4">
      {/* Query controls */}
      <QueryActions />

      {/* BGC results — Roster full height left, Scatter + Stats stacked right */}
      <div className="grid gap-4 xl:grid-cols-2">
        <PanelContainer title="BGC Roster" className="min-h-[600px] xl:row-span-2">
          <QueryResultsRoster />
        </PanelContainer>
        <div className="flex flex-col gap-4">
          <PanelContainer title="BGC Chemical Space (UMAP)" className="min-h-[300px]">
            <BgcScatter />
          </PanelContainer>
          <PanelContainer title="BGC Stats" className="min-h-[280px]" actions={<BgcStatsActions bgcIds={resultBgcIds} />}>
            <BgcStats bgcIds={resultBgcIds} />
          </PanelContainer>
        </div>
      </div>

      {/* BGC detail */}
      {activeBgcId && (
        <PanelContainer title="BGC Detail" collapsible>
          <BgcDetail bgcId={activeBgcId} />
        </PanelContainer>
      )}

      {/* Genome panels — Roster full height left, Scatter + Stats stacked right */}
      <div className="grid gap-4 xl:grid-cols-2">
        <PanelContainer title="Genome Roster" className="min-h-[600px] xl:row-span-2" actions={<GenomeSourceBadge />}>
          <QueryGenomeRoster />
        </PanelContainer>
        <div className="flex flex-col gap-4">
          <PanelContainer title="Genome Space Map" className="min-h-[300px]" actions={<GenomeSourceBadge />}>
            <QueryGenomeScatter />
          </PanelContainer>
          <PanelContainer
            title="Genome Stats"
            className="min-h-[280px]"
            actions={<GenomeStatsActions assemblyIds={queryAssemblyIds} />}
          >
            <GenomeStats assemblyIds={queryAssemblyIds} />
          </PanelContainer>
        </div>
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
