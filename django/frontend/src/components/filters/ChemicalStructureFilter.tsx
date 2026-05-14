import { useQueryStore } from "@/stores/query-store";
import { ChemicalStructureSearch } from "./ChemicalStructureSearch";
import { FilterChip } from "./FilterChip";

export function ChemicalStructureFilter() {
  const smilesQuery = useQueryStore((s) => s.smilesQuery);
  const setSmilesQuery = useQueryStore((s) => s.setSmilesQuery);
  const setSimilarityThreshold = useQueryStore(
    (s) => s.setSimilarityThreshold,
  );

  const active = smilesQuery.trim().length > 0;

  return (
    <FilterChip
      label="Chemical structure"
      active={active}
      onClear={() => {
        setSmilesQuery("");
        setSimilarityThreshold(0.5);
      }}
      width="lg"
    >
      <ChemicalStructureSearch />
    </FilterChip>
  );
}
