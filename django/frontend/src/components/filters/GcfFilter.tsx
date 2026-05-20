import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Command,
  CommandInput,
  CommandItem,
  CommandList,
  CommandEmpty,
} from "@/components/ui/command";
import { Badge } from "@/components/ui/badge";
import { fetchGcfs } from "@/api/filters";
import { useFilterStore } from "@/stores/filter-store";
import { FilterChip } from "./FilterChip";

// Subtree-match GCF filter. The selected ``family_path`` is forwarded to the
// backend as ``leaf_path_prefix`` so the iBGC query matches the picked node
// AND all its descendants in the cluster ltree.
export function GcfFilter() {
  const [search, setSearch] = useState("");
  const gcfPath = useFilterStore((s) => s.gcfPath);
  const setGcfPath = useFilterStore((s) => s.setGcfPath);

  const { data, isLoading } = useQuery({
    queryKey: ["filters", "gcfs", search],
    queryFn: () =>
      fetchGcfs({
        search: search.length >= 2 ? search : undefined,
        page: 1,
        page_size: 20,
      }),
    staleTime: 30_000,
  });

  const label = gcfPath ? `GCF: ${gcfPath}` : "GCF";

  return (
    <FilterChip
      label={label}
      active={!!gcfPath}
      onClear={() => setGcfPath("")}
      dataTour="gcf-filter"
    >
      <Command className="rounded-md border" shouldFilter={false}>
        <CommandInput
          placeholder="Search GCFs (path, e.g. cluster.0042)..."
          value={search}
          onValueChange={setSearch}
        />
        <CommandList>
          {isLoading ? (
            <div className="p-2 text-xs text-muted-foreground">Loading…</div>
          ) : (
            <>
              <CommandEmpty>No GCFs found</CommandEmpty>
              {(data?.items ?? []).map((gcf) => {
                const selected = gcfPath === gcf.family_path;
                return (
                  <CommandItem
                    key={gcf.family_path}
                    value={gcf.family_path}
                    onSelect={() => {
                      setGcfPath(selected ? "" : gcf.family_path);
                      setSearch("");
                    }}
                    className={selected ? "bg-accent" : ""}
                  >
                    <div className="flex flex-1 items-center justify-between gap-2">
                      <div className="flex min-w-0 items-center gap-2">
                        <Badge variant="outline" className="text-[10px]">
                          L{gcf.level}
                        </Badge>
                        <span className="truncate font-mono text-xs">
                          {gcf.family_path}
                        </span>
                      </div>
                      <Badge variant="secondary" className="text-[10px] px-1">
                        {gcf.member_count.toLocaleString()}
                      </Badge>
                    </div>
                  </CommandItem>
                );
              })}
            </>
          )}
        </CommandList>
      </Command>
    </FilterChip>
  );
}
