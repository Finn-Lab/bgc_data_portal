import { Header } from "./Header";
import { Sidebar } from "./Sidebar";
import { ExploreLayout } from "./panels/ExploreLayout";
import { QueryLayout } from "./panels/QueryLayout";
import { useModeStore } from "@/stores/mode-store";
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { FilterPanel } from "@/components/filters/FilterPanel";
import { SidebarShortlists } from "@/components/trays/SidebarShortlists";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { SlidersHorizontal } from "lucide-react";
import { WelcomeModal } from "@/components/onboarding/WelcomeModal";
import { GuidedTour } from "@/components/onboarding/GuidedTour";

export function DashboardShell() {
  const mode = useModeStore((s) => s.mode);

  return (
    <div className="flex flex-col" style={{ height: "calc(100vh - var(--vf-chrome-height, 90px))" }}>
      <WelcomeModal />
      <GuidedTour />
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
                  <SidebarShortlists />
                </div>
              </ScrollArea>
            </SheetContent>
          </Sheet>
        </div>

        {/* Main content — Evaluate Asset mode retired in v2 (P1.4b);
            legacy `/legacy/*` route now only exposes Explore + Query. */}
        {mode === "query" ? <QueryLayout /> : <ExploreLayout />}
      </div>
    </div>
  );
}
