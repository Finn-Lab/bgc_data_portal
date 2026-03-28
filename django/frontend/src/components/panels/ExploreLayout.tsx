import { GenomeRoster } from "@/components/genome/GenomeRoster";
import { GenomeScatter } from "@/components/genome/GenomeScatter";
import { GenomeDetail } from "@/components/genome/GenomeDetail";
import { BgcRoster } from "@/components/bgc/BgcRoster";
import { BgcScatter } from "@/components/bgc/BgcScatter";
import { BgcDetail } from "@/components/bgc/BgcDetail";
import { PanelContainer } from "./PanelContainer";
import { useSelectionStore } from "@/stores/selection-store";

export function ExploreLayout() {
  const activeGenomeId = useSelectionStore((s) => s.activeGenomeId);
  const activeBgcId = useSelectionStore((s) => s.activeBgcId);

  return (
    <div className="flex flex-1 flex-col gap-4 overflow-auto p-4">
      {/* Top section: Genome panels */}
      <div className="grid gap-4 xl:grid-cols-2">
        <PanelContainer title="Genome Roster" className="min-h-[300px]">
          <GenomeRoster />
        </PanelContainer>
        <PanelContainer title="Genome Space Map" className="min-h-[300px]">
          <GenomeScatter />
        </PanelContainer>
      </div>

      {/* Genome detail */}
      {activeGenomeId && (
        <PanelContainer title="Genome Detail" collapsible>
          <GenomeDetail genomeId={activeGenomeId} />
        </PanelContainer>
      )}

      {/* Bottom section: BGC panels */}
      <div className="grid gap-4 xl:grid-cols-2">
        <PanelContainer title="BGC Roster" className="min-h-[300px]">
          <BgcRoster />
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

    </div>
  );
}
