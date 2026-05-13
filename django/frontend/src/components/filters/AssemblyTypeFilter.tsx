import { useFilterStore } from "@/stores/filter-store";
import { FilterChip } from "./FilterChip";
import { cn } from "@/lib/utils";

const TYPES = ["", "metagenome", "genome", "region"] as const;
const LABELS: Record<string, string> = {
  "": "All",
  metagenome: "Metagenome",
  genome: "Genome",
  region: "Region",
};

export function AssemblyTypeFilter() {
  const assemblyType = useFilterStore((s) => s.assemblyType);
  const setAssemblyType = useFilterStore((s) => s.setAssemblyType);
  const isActive = !!assemblyType;

  return (
    <FilterChip
      label={isActive ? `Type: ${LABELS[assemblyType]}` : "Assembly Type"}
      active={isActive}
      onClear={() => setAssemblyType("")}
      dataTour="assembly-type-filter"
      width="sm"
    >
      <div className="flex flex-col gap-1">
        {TYPES.map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setAssemblyType(t)}
            className={cn(
              "rounded-md px-2 py-1.5 text-left text-sm hover:bg-accent",
              assemblyType === t && "bg-primary/10 font-medium",
            )}
          >
            {LABELS[t]}
          </button>
        ))}
      </div>
    </FilterChip>
  );
}
