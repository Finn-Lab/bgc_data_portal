import { useQueryStore } from "@/stores/query-store";
import { Label } from "@/components/ui/label";
import { Slider } from "@/components/ui/slider";

export function ChemicalStructureSearch() {
  const smilesQuery = useQueryStore((s) => s.smilesQuery);
  const setSmilesQuery = useQueryStore((s) => s.setSmilesQuery);
  const similarityThreshold = useQueryStore((s) => s.similarityThreshold);
  const setSimilarityThreshold = useQueryStore(
    (s) => s.setSimilarityThreshold
  );

  return (
    <div className="space-y-4 pt-2">
      <div className="space-y-1.5">
        <Label className="text-xs">SMILES Query</Label>
        <textarea
          placeholder="Paste a SMILES string, e.g. CC(=O)OC1=CC=CC=C1C(=O)O"
          value={smilesQuery}
          onChange={(e) => setSmilesQuery(e.target.value)}
          className="vf-form__input w-full rounded-md border bg-background px-3 py-2 text-xs font-mono min-h-[60px] resize-y focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          rows={3}
        />
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center justify-between">
          <Label className="text-xs">Similarity Threshold</Label>
          <span className="font-mono text-xs text-muted-foreground">
            {similarityThreshold.toFixed(2)}
          </span>
        </div>
        <Slider
          value={[similarityThreshold]}
          onValueChange={([v]) => {
            if (v !== undefined) setSimilarityThreshold(v);
          }}
          min={0.1}
          max={1}
          step={0.05}
          className="w-full"
        />
      </div>

      <p className="text-[10px] text-muted-foreground">
        Press "Run Query" above to search. Results are combined with any active filters and domain conditions.
      </p>
    </div>
  );
}
