import { Button } from "@/components/ui/button";
import { RotateCcw } from "lucide-react";
import { SourceFilter } from "./SourceFilter";
import { DetectorFilter } from "./DetectorFilter";
import { AssemblyTypeFilter } from "./AssemblyTypeFilter";
import { TaxonomyFilter } from "./TaxonomyFilter";
import { BiomeLineageFilter } from "./BiomeLineageFilter";
import { BgcClassFilter } from "./BgcClassFilter";
import { GcfFilter } from "./GcfFilter";
import { ChemOntClassFilter } from "./ChemOntClassFilter";
import { AccessionsFilter } from "./AccessionsFilter";
import { DomainsFilter } from "./DomainsFilter";
import { LengthFilter } from "./LengthFilter";
import { SequenceFilter } from "./SequenceFilter";
import { ChemicalStructureFilter } from "./ChemicalStructureFilter";
import { LoadAssetChip } from "./LoadAssetChip";
import { useFilterStore } from "@/stores/filter-store";

export function FilterPanel() {
  const clearFilters = useFilterStore((s) => s.clearFilters);

  return (
    <div className="flex flex-wrap items-center gap-2">
      <SourceFilter />
      <DetectorFilter />
      <AssemblyTypeFilter />
      <TaxonomyFilter />
      <BiomeLineageFilter />
      <BgcClassFilter />
      <GcfFilter />
      <ChemOntClassFilter />
      <AccessionsFilter />
      <LengthFilter />
      <DomainsFilter />
      <SequenceFilter />
      <ChemicalStructureFilter />

      <LoadAssetChip />

      <Button
        variant="ghost"
        size="sm"
        className="h-8 gap-1 px-2 text-xs text-muted-foreground"
        onClick={clearFilters}
      >
        <RotateCcw className="h-3 w-3" />
        Reset
      </Button>
    </div>
  );
}
