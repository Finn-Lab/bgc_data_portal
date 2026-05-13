import { useState } from "react";
import {
  Command,
  CommandInput,
  CommandItem,
  CommandList,
  CommandEmpty,
} from "@/components/ui/command";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useBgcClasses } from "@/hooks/use-filter-data";
import { useFilterStore } from "@/stores/filter-store";
import { FilterChip } from "./FilterChip";

export function BgcClassFilter() {
  const [search, setSearch] = useState("");
  const { data: classes, isLoading } = useBgcClasses();
  const bgcClass = useFilterStore((s) => s.bgcClass);
  const setBgcClass = useFilterStore((s) => s.setBgcClass);

  const filtered = (classes ?? []).filter((cls) =>
    cls.name.toLowerCase().includes(search.toLowerCase()),
  );

  const label = bgcClass ? `BGC Class: ${bgcClass}` : "BGC Class";

  return (
    <FilterChip
      label={label}
      active={!!bgcClass}
      onClear={() => setBgcClass("")}
      dataTour="bgc-class-filter"
    >
      {isLoading ? (
        <div className="space-y-2">
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
      ) : (
        <Command className="rounded-md border" shouldFilter={false}>
          <CommandInput
            placeholder="Search BGC class..."
            value={search}
            onValueChange={setSearch}
          />
          <CommandList>
            <CommandEmpty>No classes found</CommandEmpty>
            {filtered.map((cls) => (
              <CommandItem
                key={cls.name}
                value={cls.name}
                onSelect={() => {
                  setBgcClass(bgcClass === cls.name ? "" : cls.name);
                  setSearch("");
                }}
                className={bgcClass === cls.name ? "bg-accent" : ""}
              >
                <div className="flex flex-1 items-center justify-between">
                  <span className="text-xs">{cls.name}</span>
                  <Badge variant="secondary" className="text-[10px] px-1">
                    {cls.count}
                  </Badge>
                </div>
              </CommandItem>
            ))}
          </CommandList>
        </Command>
      )}
    </FilterChip>
  );
}
