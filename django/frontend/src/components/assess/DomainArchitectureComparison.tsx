import { useState } from "react";
import { RegionPlot } from "@/components/bgc/RegionPlot";
import { CdsProteinInfo } from "@/components/bgc/CdsProteinInfo";
import { useBgcRegion } from "@/hooks/use-bgc-region";
import { useSelectionStore } from "@/stores/selection-store";
import { Loader2 } from "lucide-react";
import type { RegionCds } from "@/api/types";

interface DomainArchitectureComparisonProps {
  bgcId: number;
}

export function DomainArchitectureComparison({
  bgcId,
}: DomainArchitectureComparisonProps) {
  const isUploaded = bgcId < 0;
  // Uploaded BGCs aren't in the DB, so skip the region fetch that would 404.
  const submittedRegion = useBgcRegion(isUploaded ? null : bgcId);

  // The comparison slot is driven by whichever BGC row the user clicks
  // in the BGC Roster panel above — same global activeBgcId that the
  // rest of the app uses for selection.
  const activeBgcId = useSelectionStore((s) => s.activeBgcId);
  const comparisonId =
    activeBgcId !== null && activeBgcId !== bgcId ? activeBgcId : null;
  const comparisonRegion = useBgcRegion(comparisonId);

  const [selectedCds, setSelectedCds] = useState<RegionCds | null>(null);

  const handleCdsClick = (cds: RegionCds) => {
    setSelectedCds((prev) =>
      prev?.protein_id === cds.protein_id ? null : cds,
    );
  };

  if (!isUploaded && submittedRegion.isLoading) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const hasSubmittedRegion = !isUploaded && !!submittedRegion.data;

  if (isUploaded && !comparisonId) {
    return (
      <p className="py-4 text-sm text-muted-foreground">
        Region-level architecture is unavailable for uploaded BGCs — the
        upload bundle doesn't include CDS coordinates. Click a BGC in the
        roster above to show its architecture here.
      </p>
    );
  }

  if (!hasSubmittedRegion && !comparisonId) {
    return (
      <p className="py-4 text-sm text-muted-foreground">
        Region data not available for this BGC.
      </p>
    );
  }

  return (
    <div className="space-y-4">
      {/* Submitted BGC region */}
      {hasSubmittedRegion && (
        <div>
          <p className="mb-1 text-xs font-medium">Submitted BGC</p>
          <RegionPlot
            data={submittedRegion.data!}
            onCdsClick={handleCdsClick}
            selectedCdsId={selectedCds?.protein_id ?? null}
          />
        </div>
      )}

      {/* Comparison BGC — the row clicked in the BGC Roster. */}
      {comparisonId ? (
        <div>
          <p className="mb-1 text-xs font-medium">
            Compared against BGC #{comparisonId}
          </p>
          {comparisonRegion.isLoading ? (
            <div className="flex items-center justify-center py-4">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : comparisonRegion.data ? (
            <RegionPlot
              data={comparisonRegion.data}
              onCdsClick={handleCdsClick}
              selectedCdsId={selectedCds?.protein_id ?? null}
            />
          ) : (
            <p className="py-2 text-xs text-muted-foreground">
              Region data not available for the selected BGC.
            </p>
          )}
        </div>
      ) : (
        <p className="py-2 text-xs text-muted-foreground">
          Click a BGC in the roster above to compare its domain architecture
          against the submitted BGC.
        </p>
      )}

      {/* Protein details for the CDS clicked in either plot — mirrors the
          Search BGCs → BGC Detail behavior. */}
      {selectedCds && (
        <CdsProteinInfo
          cds={selectedCds}
          onClose={() => setSelectedCds(null)}
        />
      )}
    </div>
  );
}
