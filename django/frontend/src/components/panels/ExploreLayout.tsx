import { AssemblyRoster } from "@/components/assembly/AssemblyRoster";
import { AssemblyScatter } from "@/components/assembly/AssemblyScatter";
import { AssemblyDetail } from "@/components/assembly/AssemblyDetail";
import { AssemblyStats, AssemblyStatsActions } from "@/components/assembly/AssemblyStats";
import { BgcRoster } from "@/components/bgc/BgcRoster";
import { BgcScatter } from "@/components/bgc/BgcScatter";
import { BgcDetail } from "@/components/bgc/BgcDetail";
import { BgcStats, BgcStatsActions } from "@/components/bgc/BgcStats";
import { PanelContainer } from "./PanelContainer";
import { ExploreActions } from "./ExploreActions";
import { Badge } from "@/components/ui/badge";
import { useSelectionStore } from "@/stores/selection-store";
import { useShortlistStore } from "@/stores/shortlist-store";
import { useFilterStore } from "@/stores/filter-store";

function BgcSourceBadge() {
  const assemblyShortlist = useShortlistStore((s) => s.assemblies);
  const activeAssemblyId = useSelectionStore((s) => s.activeAssemblyId);

  if (assemblyShortlist.length > 0) {
    return (
      <Badge variant="outline" className="text-[10px]">
        From {assemblyShortlist.length} shortlisted assembl{assemblyShortlist.length > 1 ? "ies" : "y"}
      </Badge>
    );
  }
  if (activeAssemblyId) {
    return (
      <Badge variant="outline" className="text-[10px]">
        From selected assembly
      </Badge>
    );
  }
  return null;
}

export function ExploreLayout() {
  const activeAssemblyId = useSelectionStore((s) => s.activeAssemblyId);
  const activeBgcId = useSelectionStore((s) => s.activeBgcId);
  const exploreQueryTriggered = useFilterStore((s) => s.exploreQueryTriggered);

  return (
    <div className="flex flex-1 flex-col gap-4 overflow-auto p-4">
      {/* Query controls */}
      <ExploreActions />

      {/* Top section: Assembly panels — Roster full height left, Map + Stats stacked right */}
      <div className="grid gap-4 xl:grid-cols-2 xl:grid-rows-[450px_420px]" data-tour="assembly-triad">
        <PanelContainer title="Assembly Roster" className="xl:row-span-2" constrained dataTour="assembly-roster">
          <AssemblyRoster />
        </PanelContainer>
        <PanelContainer title="Assembly Space Map" className="h-full" constrained dataTour="assembly-space-map">
          <AssemblyScatter />
        </PanelContainer>
        <PanelContainer title="Assembly Stats" className="h-full" constrained actions={<AssemblyStatsActions />}>
          <AssemblyStats enabled={exploreQueryTriggered} />
        </PanelContainer>
      </div>

      {/* Assembly detail */}
      {activeAssemblyId && (
        <PanelContainer title="Assembly Detail" collapsible>
          <AssemblyDetail assemblyId={activeAssemblyId} />
        </PanelContainer>
      )}

      {/* Bottom section: BGC panels — Roster full height left, Scatter + Stats stacked right */}
      <div className="grid gap-4 xl:grid-cols-2 xl:grid-rows-[450px_420px]" data-tour="bgc-triad">
        <PanelContainer title="BGC Roster" className="xl:row-span-2" constrained actions={<BgcSourceBadge />} dataTour="bgc-roster">
          <BgcRoster />
        </PanelContainer>
        <PanelContainer title="BGC Space Map" className="h-full" constrained actions={<BgcSourceBadge />}>
          <BgcScatter />
        </PanelContainer>
        <PanelContainer title="BGC Stats" className="h-full" constrained actions={<BgcStatsActions />}>
          <BgcStats />
        </PanelContainer>
      </div>

      {/* BGC detail */}
      {activeBgcId && (
        <PanelContainer title="BGC Detail" collapsible>
          <BgcDetail bgcId={activeBgcId} />
        </PanelContainer>
      )}

    </div>
  );
}
