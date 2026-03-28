import { Header } from "./Header";
import { Sidebar } from "./Sidebar";
import { ExploreLayout } from "./panels/ExploreLayout";
import { QueryLayout } from "./panels/QueryLayout";
import { useModeStore } from "@/stores/mode-store";
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { FilterPanel } from "@/components/filters/FilterPanel";
import { WeightTuner } from "@/components/WeightTuner";
import { SidebarShortlists } from "@/components/trays/SidebarShortlists";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { SlidersHorizontal } from "lucide-react";

export function DashboardShell() {
  const mode = useModeStore((s) => s.mode);

  return (
    <div className="flex flex-col" style={{ height: "calc(100vh - var(--vf-chrome-height, 90px))" }}>
      <Header />
      <div className="flex flex-1 overflow-hidden">
        {/* Desktop sidebar */}
        <Sidebar />

        {/* Mobile sidebar trigger */}
        <div className="fixed bottom-4 left-4 z-50 xl:hidden">
          <Sheet>
            <SheetTrigger asChild>
              <Button size="icon" variant="outline" className="rounded-full shadow-lg">
                <SlidersHorizontal className="h-4 w-4" />
              </Button>
            </SheetTrigger>
            <SheetContent side="left" className="w-80 p-0">
              <ScrollArea className="h-full">
                <div className="space-y-4 p-4">
                  <FilterPanel />
                  <Separator />
                  <WeightTuner />
                  <Separator />
                  <SidebarShortlists />
                </div>
              </ScrollArea>
            </SheetContent>
          </Sheet>
        </div>

        {/* Main content */}
        {mode === "explore" ? <ExploreLayout /> : <QueryLayout />}
      </div>
    </div>
  );
}
