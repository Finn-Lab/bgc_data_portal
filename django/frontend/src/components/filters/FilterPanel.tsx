import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Search, RotateCcw } from "lucide-react";
import { SourceFilter } from "./SourceFilter";
import { DetectorFilter } from "./DetectorFilter";
import { AssemblyTypeFilter } from "./AssemblyTypeFilter";
import { TaxonomyFilter } from "./TaxonomyFilter";
import { BiomeLineageFilter } from "./BiomeLineageFilter";
import { BgcClassFilter } from "./BgcClassFilter";
import { ChemOntClassFilter } from "./ChemOntClassFilter";
import { AccessionsFilter } from "./AccessionsFilter";
import { AdvancedQuerySheet } from "./AdvancedQuerySheet";
import { useFilterStore } from "@/stores/filter-store";
import { useModeStore } from "@/stores/mode-store";

export function FilterPanel() {
  const mode = useModeStore((s) => s.mode);
  const search = useFilterStore((s) => s.search);
  const setSearch = useFilterStore((s) => s.setSearch);
  const clearFilters = useFilterStore((s) => s.clearFilters);

  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="relative">
        <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
        <Input
          placeholder="Search organisms…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="vf-form__input h-8 w-56 pl-7 text-xs"
        />
      </div>

      <SourceFilter />
      <DetectorFilter />
      <AssemblyTypeFilter />
      <TaxonomyFilter />
      <BiomeLineageFilter />
      <BgcClassFilter />
      <ChemOntClassFilter />

      {mode === "query" && (
        <>
          <AccessionsFilter />
          <AdvancedQuerySheet />
        </>
      )}

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
