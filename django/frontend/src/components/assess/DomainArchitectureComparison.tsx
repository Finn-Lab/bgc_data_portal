import { useState } from "react";
import { RegionPlot } from "@/components/bgc/RegionPlot";
import { useBgcRegion } from "@/hooks/use-bgc-region";
import { Loader2 } from "lucide-react";
import type { RegionCds } from "@/api/types";

interface DomainArchitectureComparisonProps {
  bgcId: number;
  nearestValidatedBgcId: number | null;
  nearestValidatedAccession: string | null;
}

export function DomainArchitectureComparison({
  bgcId,
  nearestValidatedBgcId,
  nearestValidatedAccession,
}: DomainArchitectureComparisonProps) {
  const submittedRegion = useBgcRegion(bgcId);
  const validatedRegion = useBgcRegion(nearestValidatedBgcId);

  const [selectedCds, setSelectedCds] = useState<string | null>(null);

  const handleCdsClick = (_cds: RegionCds) => {
    setSelectedCds((prev) => (prev === _cds.protein_id ? null : _cds.protein_id));
  };

  if (submittedRegion.isLoading) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (!submittedRegion.data) {
    return (
      <p className="py-4 text-sm text-muted-foreground">
        Region data not available for this BGC.
      </p>
    );
  }

  return (
    <div className="space-y-4">
      {/* Submitted BGC region */}
      <div>
        <p className="mb-1 text-xs font-medium">Submitted BGC</p>
        <RegionPlot
          data={submittedRegion.data}
          onCdsClick={handleCdsClick}
          selectedCdsId={selectedCds}
        />
      </div>

      {/* Nearest Validated region */}
      {nearestValidatedBgcId && (
        <div>
          <p className="mb-1 text-xs font-medium">
            Nearest Validated: {nearestValidatedAccession || "Unknown"}
          </p>
          {validatedRegion.isLoading ? (
            <div className="flex items-center justify-center py-4">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : validatedRegion.data ? (
            <RegionPlot
              data={validatedRegion.data}
              onCdsClick={handleCdsClick}
              selectedCdsId={selectedCds}
            />
          ) : (
            <p className="py-2 text-xs text-muted-foreground">
              Region data not available for validated reference.
            </p>
          )}
        </div>
      )}

      {!nearestValidatedBgcId && nearestValidatedAccession && (
        <p className="text-xs text-muted-foreground">
          Nearest Validated: {nearestValidatedAccession} (region data not available)
        </p>
      )}
    </div>
  );
}
