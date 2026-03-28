import { ScrollArea } from "@/components/ui/scroll-area";
import { FilterPanel } from "@/components/filters/FilterPanel";
import { WeightTuner } from "@/components/WeightTuner";
import { SidebarShortlists } from "@/components/trays/SidebarShortlists";
import { Separator } from "@/components/ui/separator";

export function Sidebar() {
  return (
    <aside className="hidden w-80 border-r xl:block">
      <ScrollArea className="h-full">
        <div className="space-y-4 p-4">
          <FilterPanel />
          <Separator />
          <WeightTuner />
          <Separator />
          <SidebarShortlists />
        </div>
      </ScrollArea>
    </aside>
  );
}
