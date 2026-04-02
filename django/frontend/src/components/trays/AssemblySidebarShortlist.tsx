import { useState } from "react";
import { useShortlistStore } from "@/stores/shortlist-store";
import { useModeStore } from "@/stores/mode-store";
import { exportGenomeShortlist } from "@/api/exports";
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

export function GenomeSidebarShortlist() {
  const [open, setOpen] = useState(true);
  const genomes = useShortlistStore((s) => s.genomes);
  const removeGenome = useShortlistStore((s) => s.removeGenome);
  const clearGenomes = useShortlistStore((s) => s.clearGenomes);
  const mode = useModeStore((s) => s.mode);
  const isActive = mode === "explore";

  const handleExport = async () => {
    if (genomes.length === 0) {
      toast.error("No genomes in shortlist");
      return;
    }
    try {
      await exportGenomeShortlist(genomes.map((g) => g.id));
      toast.success("CSV downloaded");
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
            Genome Shortlist
            <Badge variant="secondary" className="ml-0.5 text-[10px]">
              {genomes.length}/20
            </Badge>
          </CollapsibleTrigger>
          <div className="flex gap-0.5">
            <Button
              variant="ghost"
              size="sm"
              className="h-6 gap-1 px-1.5 text-[10px]"
              onClick={handleExport}
              disabled={genomes.length === 0}
            >
              <Download className="h-3 w-3" />
              CSV
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="h-6 px-1.5 text-[10px]"
              onClick={clearGenomes}
              disabled={genomes.length === 0}
            >
              <Trash2 className="h-3 w-3" />
            </Button>
          </div>
        </div>
        <CollapsibleContent>
          {genomes.length > 0 ? (
            <div className="mt-1.5 flex flex-wrap gap-1">
              {genomes.map((g) => (
                <Badge key={g.id} variant="secondary" className="gap-0.5 text-[10px]">
                  {g.label}
                  <button onClick={() => removeGenome(g.id)}>
                    <X className="h-2.5 w-2.5" />
                  </button>
                </Badge>
              ))}
            </div>
          ) : (
            <p className="mt-1.5 text-[10px] text-muted-foreground">
              Right-click a genome to add it
            </p>
          )}
        </CollapsibleContent>
      </div>
    </Collapsible>
  );
}
