import { ScrollArea } from "@/components/ui/scroll-area";
import { FilterPanel } from "@/components/filters/FilterPanel";
import { WeightTuner } from "@/components/WeightTuner";
import { SidebarShortlists } from "@/components/trays/SidebarShortlists";
import { Separator } from "@/components/ui/separator";
import { useModeStore } from "@/stores/mode-store";
import { useAssessStore } from "@/stores/assess-store";

export function Sidebar() {
  const mode = useModeStore((s) => s.mode);
  const assetType = useAssessStore((s) => s.assetType);
  const showWeights = mode !== "assess" || assetType === "genome";

  return (
    <aside className="hidden w-80 border-r xl:block">
      <ScrollArea className="h-full">
        <div className="space-y-4 p-4">
          {mode !== "assess" && (
            <>
              <FilterPanel />
              <Separator />
            </>
          )}
          {showWeights && (
            <>
              <WeightTuner />
              <Separator />
            </>
          )}
          <SidebarShortlists />
        </div>
      </ScrollArea>
    </aside>
  );
}
