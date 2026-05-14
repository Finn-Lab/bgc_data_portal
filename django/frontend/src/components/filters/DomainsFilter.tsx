import { useQueryStore } from "@/stores/query-store";
import { DomainQueryBuilder } from "./DomainQueryBuilder";
import { FilterChip } from "./FilterChip";

export function DomainsFilter() {
  const conditions = useQueryStore((s) => s.domainConditions);
  const removeCondition = useQueryStore((s) => s.removeDomainCondition);

  return (
    <FilterChip
      label="Domains"
      count={conditions.length}
      onClear={() => {
        for (const c of conditions) removeCondition(c.acc);
      }}
      width="lg"
    >
      <DomainQueryBuilder />
    </FilterChip>
  );
}
