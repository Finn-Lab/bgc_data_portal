import { ScrollArea } from "@/components/ui/scroll-area";
import { FilterPanel } from "@/components/filters/FilterPanel";
import { SidebarShortlists } from "@/components/trays/SidebarShortlists";
import { UploadForEvaluation } from "@/components/assess/UploadForEvaluation";
import { Separator } from "@/components/ui/separator";
import { useModeStore } from "@/stores/mode-store";

export function Sidebar() {
  const mode = useModeStore((s) => s.mode);

  return (
    <aside className="hidden w-80 border-r xl:block">
      <ScrollArea className="h-full">
        <div className="space-y-4 p-4">
          {mode === "assess" && (
            <>
              <UploadForEvaluation />
              <Separator />
            </>
          )}
          {mode !== "assess" && (
            <>
              <FilterPanel />
              <Separator />
            </>
          )}
          <SidebarShortlists />
        </div>
      </ScrollArea>
    </aside>
  );
}
