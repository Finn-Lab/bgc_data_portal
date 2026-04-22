import { useState } from "react";
import { Command, CommandInput, CommandItem, CommandList, CommandEmpty } from "@/components/ui/command";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useBgcClasses } from "@/hooks/use-filter-data";
import { useFilterStore } from "@/stores/filter-store";
import { HelpTooltip } from "@/components/ui/help-tooltip";
import { X } from "lucide-react";

export function BgcClassFilter() {
  const [search, setSearch] = useState("");
  const { data: classes, isLoading } = useBgcClasses();
  const bgcClass = useFilterStore((s) => s.bgcClass);
  const setBgcClass = useFilterStore((s) => s.setBgcClass);

  const filtered = (classes ?? []).filter((cls) =>
    cls.name.toLowerCase().includes(search.toLowerCase())
  );

  if (isLoading) {
    return (
      <div className="space-y-2">
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-8 w-full" />
      </div>
    );
  }

  return (
    <div className="space-y-2" data-tour="bgc-class-filter">
      <span className="flex items-center gap-1 text-sm font-medium">
        BGC Class <HelpTooltip tooltipKey="bgc_class_toggle" side="right" />
      </span>
      {bgcClass && (
        <Badge variant="secondary" className="gap-1 text-xs">
          {bgcClass}
          <button
            className="ml-1 hover:opacity-70"
            onClick={() => setBgcClass("")}
          >
            <X className="h-3 w-3" />
          </button>
        </Badge>
      )}
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
    </div>
  );
}
