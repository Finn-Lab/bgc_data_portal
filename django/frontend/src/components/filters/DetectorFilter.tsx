import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Command, CommandInput, CommandItem, CommandList, CommandEmpty } from "@/components/ui/command";
import { Badge } from "@/components/ui/badge";
import { Label } from "@/components/ui/label";
import { X } from "lucide-react";
import { fetchDetectors } from "@/api/filters";
import { useFilterStore } from "@/stores/filter-store";

export function DetectorFilter() {
  const [search, setSearch] = useState("");
  const detectorTools = useFilterStore((s) => s.detectorTools);
  const setDetectorTools = useFilterStore((s) => s.setDetectorTools);

  const { data } = useQuery({
    queryKey: ["filters", "detectors", search],
    queryFn: () => fetchDetectors({ search, page: 1, page_size: 20 }),
    staleTime: 60_000,
  });

  function addDetector(tool: string) {
    if (!detectorTools.includes(tool)) {
      setDetectorTools([...detectorTools, tool]);
    }
    setSearch("");
  }

  function removeDetector(tool: string) {
    setDetectorTools(detectorTools.filter((t) => t !== tool));
  }

  return (
    <div className="space-y-2">
      <Label className="text-xs">BGC Detector</Label>

      {detectorTools.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {detectorTools.map((tool) => (
            <Badge key={tool} variant="default" className="gap-1 text-xs">
              {tool}
              <button className="hover:opacity-70" onClick={() => removeDetector(tool)}>
                <X className="h-3 w-3" />
              </button>
            </Badge>
          ))}
        </div>
      )}

      <Command className="rounded-md border" shouldFilter={false}>
        <CommandInput
          placeholder="Search detectors..."
          value={search}
          onValueChange={setSearch}
        />
        <CommandList>
          <CommandEmpty>No detectors found</CommandEmpty>
          {(data?.items ?? [])
            .filter((d) => !detectorTools.includes(d.tool))
            .map((detector) => (
              <CommandItem
                key={detector.tool}
                value={detector.tool}
                onSelect={() => addDetector(detector.tool)}
              >
                <div className="flex flex-1 items-center justify-between">
                  <span className="text-xs">{detector.tool}</span>
                  <Badge variant="secondary" className="text-[10px]">
                    {detector.count}
                  </Badge>
                </div>
              </CommandItem>
            ))}
        </CommandList>
      </Command>
    </div>
  );
}
