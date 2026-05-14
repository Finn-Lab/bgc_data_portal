import { useQueryStore } from "@/stores/query-store";
import { SequenceSearch } from "./SequenceSearch";
import { FilterChip } from "./FilterChip";

export function SequenceFilter() {
  const sequenceQuery = useQueryStore((s) => s.sequenceQuery);
  const setSequenceQuery = useQueryStore((s) => s.setSequenceQuery);
  const setMinBitscore = useQueryStore((s) => s.setSequenceMinBitscore);
  const setMinPident = useQueryStore((s) => s.setSequenceMinPident);
  const setMinQcov = useQueryStore((s) => s.setSequenceMinQcov);

  const active = sequenceQuery.trim().length > 0;

  return (
    <FilterChip
      label="Sequence search"
      active={active}
      onClear={() => {
        setSequenceQuery("");
        setMinBitscore(30);
        setMinPident(70);
        setMinQcov(70);
      }}
      width="lg"
    >
      <SequenceSearch />
    </FilterChip>
  );
}
