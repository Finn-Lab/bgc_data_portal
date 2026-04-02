import { QueryResultsRoster } from "@/components/query/QueryResultsRoster";
import { QueryAssemblyRoster } from "@/components/query/QueryAssemblyRoster";
import { QueryAssemblyScatter } from "@/components/query/QueryAssemblyScatter";
import { AssemblyDetail } from "@/components/assembly/AssemblyDetail";
import { BgcScatter } from "@/components/bgc/BgcScatter";
import { BgcDetail } from "@/components/bgc/BgcDetail";
import { BgcStats, BgcStatsActions } from "@/components/bgc/BgcStats";
import { AssemblyStats, AssemblyStatsActions } from "@/components/assembly/AssemblyStats";
import { PanelContainer } from "./PanelContainer";
import { Badge } from "@/components/ui/badge";
import { QueryActions } from "@/components/query/QueryActions";
import { useSelectionStore } from "@/stores/selection-store";
import { useShortlistStore } from "@/stores/shortlist-store";
import { useQueryStore } from "@/stores/query-store";
import { useParentAssemblies } from "@/hooks/use-parent-assemblies";

function AssemblySourceBadge() {
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
  const activeAssemblyId = useSelectionStore((s) => s.activeAssemblyId);
  const queryAssemblyIds = useQueryAssemblyIds();
  const resultBgcIds = useQueryStore((s) => s.resultBgcIds);

  return (
    <div className="flex flex-1 flex-col gap-4 overflow-auto p-4">
      {/* Query controls */}
      <QueryActions />

      {/* BGC results — Roster full height left, Scatter + Stats stacked right */}
      <div className="grid gap-4 xl:grid-cols-2 xl:grid-rows-[450px_420px]">
        <PanelContainer title="BGC Roster" className="xl:row-span-2">
          <QueryResultsRoster />
        </PanelContainer>
        <PanelContainer title="BGC Space Map" className="h-full">
          <BgcScatter />
        </PanelContainer>
        <PanelContainer title="BGC Stats" className="h-full" actions={<BgcStatsActions bgcIds={resultBgcIds} />}>
          <BgcStats bgcIds={resultBgcIds} />
        </PanelContainer>
      </div>

      {/* BGC detail */}
      {activeBgcId && (
        <PanelContainer title="BGC Detail" collapsible>
          <BgcDetail bgcId={activeBgcId} />
        </PanelContainer>
      )}

      {/* Assembly panels — Roster full height left, Scatter + Stats stacked right */}
      <div className="grid gap-4 xl:grid-cols-2 xl:grid-rows-[450px_420px]">
        <PanelContainer title="Assembly Roster" className="xl:row-span-2" actions={<AssemblySourceBadge />}>
          <QueryAssemblyRoster />
        </PanelContainer>
        <PanelContainer title="Assembly Space Map" className="h-full" actions={<AssemblySourceBadge />}>
          <QueryAssemblyScatter />
        </PanelContainer>
        <PanelContainer
          title="Assembly Stats"
          className="h-full"
          actions={<AssemblyStatsActions assemblyIds={queryAssemblyIds} />}
        >
          <AssemblyStats assemblyIds={queryAssemblyIds} enabled={!!queryAssemblyIds} />
        </PanelContainer>
      </div>

      {/* Assembly detail */}
      {activeAssemblyId && (
        <PanelContainer title="Assembly Detail" collapsible>
          <AssemblyDetail assemblyId={activeAssemblyId} />
        </PanelContainer>
      )}

    </div>
  );
}
