import { useState } from "react";
import { useShortlistStore } from "@/stores/shortlist-store";
import { useModeStore } from "@/stores/mode-store";
import { exportBgcShortlist } from "@/api/exports";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { ChevronDown, Download, Trash2, X } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

export function BgcSidebarShortlist() {
  const [open, setOpen] = useState(true);
  const bgcs = useShortlistStore((s) => s.bgcs);
  const removeBgc = useShortlistStore((s) => s.removeBgc);
  const clearBgcs = useShortlistStore((s) => s.clearBgcs);
  const mode = useModeStore((s) => s.mode);
  const isActive = mode === "query";

  const handleExport = async () => {
    if (bgcs.length === 0) {
      toast.error("No BGCs in shortlist");
      return;
    }
    try {
      await exportBgcShortlist(bgcs.map((b) => b.id));
      toast.success("GBK downloaded");
    } catch {
      toast.error("Export failed");
    }
  };

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <div
        className={cn(
          "rounded-sm pl-2 transition-colors",
          isActive ? "border-l-2 border-explore" : "border-l-2 border-transparent"
        )}
      >
        <div className="flex items-center justify-between">
          <CollapsibleTrigger className="flex items-center gap-1.5 text-xs font-semibold text-muted-foreground hover:text-foreground">
            <ChevronDown
              className={cn("h-3.5 w-3.5 transition-transform", !open && "-rotate-90")}
            />
            BGC Shortlist
            <Badge variant="secondary" className="ml-0.5 text-[10px]">
              {bgcs.length}/20
            </Badge>
          </CollapsibleTrigger>
          <div className="flex gap-0.5">
            <Button
              variant="ghost"
              size="sm"
              className="h-6 gap-1 px-1.5 text-[10px]"
              onClick={handleExport}
              disabled={bgcs.length === 0}
            >
              <Download className="h-3 w-3" />
              GBK
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="h-6 px-1.5 text-[10px]"
              onClick={clearBgcs}
              disabled={bgcs.length === 0}
            >
              <Trash2 className="h-3 w-3" />
            </Button>
          </div>
        </div>
        <CollapsibleContent>
          {bgcs.length > 0 ? (
            <div className="mt-1.5 flex flex-wrap gap-1">
              {bgcs.map((b) => (
                <Badge
                  key={b.id}
                  variant="secondary"
                  className="gap-0.5 font-mono text-[10px]"
                >
                  {b.label}
                  <button onClick={() => removeBgc(b.id)}>
                    <X className="h-2.5 w-2.5" />
                  </button>
                </Badge>
              ))}
            </div>
          ) : (
            <p className="mt-1.5 text-[10px] text-muted-foreground">
              Right-click a BGC to add it
            </p>
          )}
        </CollapsibleContent>
      </div>
    </Collapsible>
  );
}
