import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Command, CommandInput, CommandItem, CommandList, CommandEmpty } from "@/components/ui/command";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Slider } from "@/components/ui/slider";
import { Plus, Minus, X } from "lucide-react";
import { fetchDomains } from "@/api/filters";
import { useQueryStore } from "@/stores/query-store";
import { HelpTooltip } from "@/components/ui/help-tooltip";

export function DomainQueryBuilder() {
  const [search, setSearch] = useState("");
  const conditions = useQueryStore((s) => s.domainConditions);
  const domainMode = useQueryStore((s) => s.domainMode);
  const setDomainMode = useQueryStore((s) => s.setDomainMode);
  const addCondition = useQueryStore((s) => s.addDomainCondition);
  const removeCondition = useQueryStore((s) => s.removeDomainCondition);
  const toggleRequired = useQueryStore((s) => s.toggleDomainRequired);
  const architectureText = useQueryStore((s) => s.domainArchitectureText);
  const setArchitectureText = useQueryStore((s) => s.setDomainArchitectureText);
  const architectureWeight = useQueryStore((s) => s.architectureWeight);
  const setArchitectureWeight = useQueryStore((s) => s.setArchitectureWeight);

  const { data: domainResults } = useQuery({
    queryKey: ["filters", "domains", search],
    queryFn: () => fetchDomains({ search, page: 1, page_size: 10 }),
    enabled: search.length >= 2 && domainMode !== "architecture",
    staleTime: 30_000,
  });

  const isArchitecture = domainMode === "architecture";
  const tooltipKey = isArchitecture ? "architecture_search" : "sorensen_dice";

  return (
    <div className="space-y-3" data-tour="domain-query">
      <div className="flex items-center justify-between">
        <span className="flex items-center gap-1 text-sm font-medium">
          Domain Query <HelpTooltip tooltipKey={tooltipKey} side="right" />
        </span>
        <ToggleGroup
          type="single"
          value={domainMode}
          onValueChange={(v) => {
            if (v === "and" || v === "or" || v === "architecture") {
              setDomainMode(v);
            }
          }}
          className="h-7"
        >
          <ToggleGroupItem value="and" className="h-6 px-2 text-xs">
            AND
          </ToggleGroupItem>
          <ToggleGroupItem value="or" className="h-6 px-2 text-xs">
            OR
          </ToggleGroupItem>
          <ToggleGroupItem value="architecture" className="h-6 px-2 text-xs">
            ARCH
          </ToggleGroupItem>
        </ToggleGroup>
      </div>

      {isArchitecture ? (
        <ArchitectureControls
          text={architectureText}
          onTextChange={setArchitectureText}
          weight={architectureWeight}
          onWeightChange={setArchitectureWeight}
        />
      ) : (
        <BooleanDomainControls
          search={search}
          onSearchChange={setSearch}
          conditions={conditions}
          addCondition={addCondition}
          removeCondition={removeCondition}
          toggleRequired={toggleRequired}
          domainResults={domainResults?.items ?? []}
        />
      )}
    </div>
  );
}

interface BooleanDomainControlsProps {
  search: string;
  onSearchChange: (v: string) => void;
  conditions: { acc: string; required: boolean }[];
  addCondition: (c: { acc: string; required: boolean }) => void;
  removeCondition: (acc: string) => void;
  toggleRequired: (acc: string) => void;
  domainResults: { acc: string; name: string; count: number }[];
}

function BooleanDomainControls({
  search,
  onSearchChange,
  conditions,
  addCondition,
  removeCondition,
  toggleRequired,
  domainResults,
}: BooleanDomainControlsProps) {
  return (
    <>
      {conditions.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {conditions.map((cond) => (
            <Badge
              key={cond.acc}
              variant={cond.required ? "default" : "destructive"}
              className="gap-1 text-xs"
            >
              {cond.required ? (
                <Plus className="h-3 w-3" />
              ) : (
                <Minus className="h-3 w-3" />
              )}
              {cond.acc}
              <button
                className="ml-1 hover:opacity-70"
                onClick={() => toggleRequired(cond.acc)}
                title="Toggle required/excluded"
              >
                {cond.required ? "req" : "excl"}
              </button>
              <button
                className="hover:opacity-70"
                onClick={() => removeCondition(cond.acc)}
              >
                <X className="h-3 w-3" />
              </button>
            </Badge>
          ))}
        </div>
      )}

      <Command className="rounded-md border" shouldFilter={false}>
        <CommandInput
          placeholder="Search domains (e.g. KS, PF00109)..."
          value={search}
          onValueChange={onSearchChange}
        />
        <CommandList>
          {search.length >= 2 && (
            <>
              <CommandEmpty>No domains found</CommandEmpty>
              {domainResults.map((domain) => (
                <CommandItem
                  key={domain.acc}
                  value={domain.acc}
                  onSelect={() => {
                    addCondition({ acc: domain.acc, required: true });
                    onSearchChange("");
                  }}
                  disabled={conditions.some((c) => c.acc === domain.acc)}
                >
                  <div className="flex flex-1 items-center justify-between">
                    <div>
                      <span className="font-mono text-xs">{domain.acc}</span>
                      <span className="ml-2 text-xs text-muted-foreground">
                        {domain.name}
                      </span>
                    </div>
                    <Badge variant="secondary" className="text-[10px]">
                      {domain.count}
                    </Badge>
                  </div>
                </CommandItem>
              ))}
            </>
          )}
        </CommandList>
      </Command>

      {conditions.length > 0 && (
        <Button
          variant="outline"
          size="sm"
          className="w-full text-xs"
          onClick={() => useQueryStore.getState().clearQuery()}
        >
          Clear all domains
        </Button>
      )}
    </>
  );
}

interface ArchitectureControlsProps {
  text: string;
  onTextChange: (v: string) => void;
  weight: number;
  onWeightChange: (v: number) => void;
}

function ArchitectureControls({
  text,
  onTextChange,
  weight,
  onWeightChange,
}: ArchitectureControlsProps) {
  const tokenCount = text
    .split(/[,\s]+/)
    .filter((t) => t.trim().length > 0).length;
  const adjacency = (1 - weight).toFixed(2);
  const dice = weight.toFixed(2);

  return (
    <div className="space-y-3">
      <div className="space-y-1">
        <label className="text-[11px] uppercase tracking-wide text-muted-foreground">
          Domain accessions, in order (comma-separated)
        </label>
        <textarea
          value={text}
          onChange={(e) => onTextChange(e.target.value)}
          placeholder="PF00109, PF02801, PF00501, PF08659, ..."
          rows={3}
          className="w-full resize-y rounded-md border bg-background px-2 py-1.5 font-mono text-xs leading-snug placeholder:text-muted-foreground/60 focus:outline-none focus:ring-1 focus:ring-ring"
        />
        <div className="text-[10px] text-muted-foreground">
          {tokenCount} token(s) parsed · unknown accessions are silently dropped
        </div>
      </div>

      <div className="space-y-1">
        <div className="flex items-center justify-between text-[11px] uppercase tracking-wide text-muted-foreground">
          <span>Weight</span>
          <span className="font-mono text-foreground">
            Adj {adjacency} · Dice {dice}
          </span>
        </div>
        <Slider
          min={0}
          max={1}
          step={0.01}
          value={[weight]}
          onValueChange={(v) => onWeightChange(v[0] ?? 0.5)}
        />
        <div className="flex justify-between text-[10px] text-muted-foreground">
          <span>← Adjacency Index</span>
          <span>Sørensen-Dice →</span>
        </div>
      </div>

      {text.trim().length > 0 && (
        <Button
          variant="outline"
          size="sm"
          className="w-full text-xs"
          onClick={() => onTextChange("")}
        >
          Clear architecture
        </Button>
      )}
    </div>
  );
}
