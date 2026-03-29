import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Slider } from "@/components/ui/slider";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { ChevronDown, Info, RotateCcw } from "lucide-react";
import { useModeStore } from "@/stores/mode-store";
import { useGenomeWeightStore } from "@/stores/genome-weight-store";
import { useQueryWeightStore } from "@/stores/query-weight-store";
import type { GenomeWeightParams, QueryWeightParams } from "@/api/types";
import { useState } from "react";

interface WeightSliderProps {
  label: string;
  tooltip: string;
  value: number;
  onChange: (v: number) => void;
}

function WeightSlider({ label, tooltip, value, onChange }: WeightSliderProps) {
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1">
          <Label className="text-xs">{label}</Label>
          <TooltipProvider delayDuration={200}>
            <Tooltip>
              <TooltipTrigger asChild>
                <Info className="h-3 w-3 text-muted-foreground" />
              </TooltipTrigger>
              <TooltipContent side="right" className="max-w-48 text-xs">
                {tooltip}
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        </div>
        <span className="font-mono text-xs text-muted-foreground">
          {value.toFixed(2)}
        </span>
      </div>
      <Slider
        value={[value]}
        onValueChange={([v]) => {
          if (v !== undefined) onChange(v);
        }}
        min={0}
        max={1}
        step={0.05}
        className="w-full"
      />
    </div>
  );
}

const GENOME_WEIGHT_CONFIG: {
  key: keyof GenomeWeightParams;
  label: string;
  tooltip: string;
}[] = [
  {
    key: "w_novelty",
    label: "Novelty",
    tooltip: "How novel are the BGCs compared to known chemistry",
  },
  {
    key: "w_diversity",
    label: "Diversity",
    tooltip: "Shannon entropy of BGC class distribution",
  },
  {
    key: "w_density",
    label: "Density",
    tooltip: "BGC count per megabase of genome",
  },
];

const QUERY_WEIGHT_CONFIG: {
  key: keyof QueryWeightParams;
  label: string;
  tooltip: string;
}[] = [
  {
    key: "w_similarity",
    label: "Query Similarity",
    tooltip: "How similar the BGC is to the query",
  },
  {
    key: "w_novelty",
    label: "Novelty",
    tooltip: "Novelty relative to known chemistry",
  },
  {
    key: "w_completeness",
    label: "Completeness",
    tooltip: "Whether the BGC is complete or fragmented",
  },
  {
    key: "w_domain_novelty",
    label: "Domain Novelty",
    tooltip: "Fraction of novel protein domains",
  },
];

export function WeightTuner() {
  const [open, setOpen] = useState(true);
  const mode = useModeStore((s) => s.mode);

  const genomeWeights = useGenomeWeightStore();
  const queryWeights = useQueryWeightStore();

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <div className="flex items-center justify-between">
        <CollapsibleTrigger className="flex items-center gap-1 text-sm font-semibold uppercase tracking-wide text-muted-foreground hover:text-foreground">
          <ChevronDown
            className={`h-4 w-4 transition-transform ${open ? "" : "-rotate-90"}`}
          />
          {mode === "explore" ? "Priority Weights" : "Relevance Weights"}
        </CollapsibleTrigger>
        <Button
          variant="ghost"
          size="sm"
          className="h-7 gap-1 text-xs"
          onClick={() =>
            mode === "explore"
              ? genomeWeights.resetDefaults()
              : queryWeights.resetDefaults()
          }
        >
          <RotateCcw className="h-3 w-3" />
          Reset
        </Button>
      </div>
      <CollapsibleContent className="space-y-3 pt-2">
        {mode === "explore"
          ? GENOME_WEIGHT_CONFIG.map((cfg) => (
              <WeightSlider
                key={cfg.key}
                label={cfg.label}
                tooltip={cfg.tooltip}
                value={genomeWeights[cfg.key]}
                onChange={(v) => genomeWeights.setWeight(cfg.key, v)}
              />
            ))
          : QUERY_WEIGHT_CONFIG.map((cfg) => (
              <WeightSlider
                key={cfg.key}
                label={cfg.label}
                tooltip={cfg.tooltip}
                value={queryWeights[cfg.key]}
                onChange={(v) => queryWeights.setWeight(cfg.key, v)}
              />
            ))}
      </CollapsibleContent>
    </Collapsible>
  );
}
