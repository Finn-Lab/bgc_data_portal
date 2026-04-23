import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Command, CommandInput, CommandItem, CommandList, CommandEmpty } from "@/components/ui/command";
import { Badge } from "@/components/ui/badge";
import { Label } from "@/components/ui/label";
import { X } from "lucide-react";
import { fetchSources } from "@/api/filters";
import { useFilterStore } from "@/stores/filter-store";

export function SourceFilter() {
  const [search, setSearch] = useState("");
  const sourceNames = useFilterStore((s) => s.sourceNames);
  const setSourceNames = useFilterStore((s) => s.setSourceNames);

  const { data } = useQuery({
    queryKey: ["filters", "sources", search],
    queryFn: () => fetchSources({ search, page: 1, page_size: 20 }),
    staleTime: 60_000,
  });

  function addSource(name: string) {
    if (!sourceNames.includes(name)) {
      setSourceNames([...sourceNames, name]);
    }
    setSearch("");
  }

  function removeSource(name: string) {
    setSourceNames(sourceNames.filter((n) => n !== name));
  }

  return (
    <div className="space-y-2">
      <Label className="text-xs">Source</Label>

      {sourceNames.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {sourceNames.map((name) => (
            <Badge key={name} variant="default" className="gap-1 text-xs">
              {name}
              <button className="hover:opacity-70" onClick={() => removeSource(name)}>
                <X className="h-3 w-3" />
              </button>
            </Badge>
          ))}
        </div>
      )}

      <Command className="rounded-md border" shouldFilter={false}>
        <CommandInput
          placeholder="Search sources..."
          value={search}
          onValueChange={setSearch}
        />
        <CommandList>
          <CommandEmpty>No sources found</CommandEmpty>
          {(data?.items ?? [])
            .filter((s) => !sourceNames.includes(s.name))
            .map((source) => (
              <CommandItem
                key={source.name}
                value={source.name}
                onSelect={() => addSource(source.name)}
              >
                <div className="flex flex-1 items-center justify-between">
                  <span className="text-xs">{source.name}</span>
                  <Badge variant="secondary" className="text-[10px]">
                    {source.count}
                  </Badge>
                </div>
              </CommandItem>
            ))}
        </CommandList>
      </Command>
    </div>
  );
}
