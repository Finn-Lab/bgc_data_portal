import { useState } from "react";
import { Card } from "@/components/ui/card";
import { useDiscoveryStore } from "@/stores/discovery-store";
import { ChevronDown, ChevronUp, Dna } from "lucide-react";
import { cn } from "@/lib/utils";
import { CdsProteinInfo } from "@/components/bgc/CdsProteinInfo";

/**
 * Collapsible bottom panel — mirrors the CDS selected in either detail
 * card. Auto-expands when a CDS is selected for the first time; user can
 * still collapse manually.
 */
export function ProteinInfoPanel() {
  const [manualExpanded, setManualExpanded] = useState<boolean | null>(null);
  const selectedCds = useDiscoveryStore((s) => s.selectedCds);
  const setSelectedCds = useDiscoveryStore((s) => s.setSelectedCds);

  // Auto-expand when a CDS becomes selected unless the user explicitly
  // collapsed it (manualExpanded === false).
  const expanded =
    manualExpanded === null ? selectedCds !== null : manualExpanded;

  return (
    <Card className="flex h-full flex-col overflow-hidden">
      <button
        type="button"
        onClick={() => setManualExpanded(!expanded)}
        className="flex w-full items-center justify-between border-b px-3 py-2 text-sm hover:bg-muted/40"
      >
        <span className="inline-flex items-center gap-2 font-semibold">
          <Dna className="h-4 w-4" />
          Protein Information
          {selectedCds && (
            <span className="font-mono text-xs text-muted-foreground">
              · {selectedCds.protein_id}
            </span>
          )}
        </span>
        {expanded ? (
          <ChevronUp className="h-4 w-4" />
        ) : (
          <ChevronDown className="h-4 w-4" />
        )}
      </button>
      <div
        className={cn(
          "min-h-0 flex-1 overflow-auto p-3 text-sm",
          !expanded && "hidden",
        )}
      >
        {selectedCds === null ? (
          <span className="text-muted-foreground">
            Click a CDS in either detail card to load its Pfam annotations
            here.
          </span>
        ) : (
          <CdsProteinInfo
            cds={selectedCds}
            onClose={() => setSelectedCds(null)}
          />
        )}
      </div>
    </Card>
  );
}
