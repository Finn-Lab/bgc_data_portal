import { FilterPanel } from "@/components/filters/FilterPanel";
import { SidebarShortlists } from "@/components/trays/SidebarShortlists";
import { Separator } from "@/components/ui/separator";

/**
 * Legacy sidebar used only by ``/legacy/*``. Evaluate Asset mode + the
 * UploadForEvaluation panel were retired in v2 (P1.4b); the new dashboard
 * doesn't render this component at all.
 */
export function Sidebar() {
  return (
    <aside
      className="hidden h-full w-80 shrink-0 overflow-y-auto border-r xl:block"
      data-tour="sidebar"
    >
      <div className="space-y-4 p-4">
        <FilterPanel />
        <Separator />
        <SidebarShortlists />
      </div>
    </aside>
  );
}
