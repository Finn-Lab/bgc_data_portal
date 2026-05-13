import { useQueryStore } from "@/stores/query-store";
import { Label } from "@/components/ui/label";
import { Slider } from "@/components/ui/slider";
import { HelpTooltip } from "@/components/ui/help-tooltip";

const MAX_AA_LENGTH = 5000;

// Bitscore slider: 0..500 in steps of 5. Bitscores can exceed 500 in
// practice, but anything above that easily passes the filter — values are
// clamped on the way in so manual entry of higher numbers still works.
const BITSCORE_MIN = 0;
const BITSCORE_MAX = 500;
const BITSCORE_STEP = 5;

// Percent sliders share the same 0..100 / 1-step range.
const PCT_MIN = 0;
const PCT_MAX = 100;
const PCT_STEP = 1;

function parseSequenceLength(raw: string): number {
  const lines = raw.trim().split("\n");
  const seqLines = lines.filter((l) => !l.startsWith(">"));
  return seqLines.join("").replace(/\s/g, "").length;
}

export function SequenceSearch() {
  const sequenceQuery = useQueryStore((s) => s.sequenceQuery);
  const setSequenceQuery = useQueryStore((s) => s.setSequenceQuery);
  const minBitscore = useQueryStore((s) => s.sequenceMinBitscore);
  const setMinBitscore = useQueryStore((s) => s.setSequenceMinBitscore);
  const minPident = useQueryStore((s) => s.sequenceMinPident);
  const setMinPident = useQueryStore((s) => s.setSequenceMinPident);
  const minQcov = useQueryStore((s) => s.sequenceMinQcov);
  const setMinQcov = useQueryStore((s) => s.setSequenceMinQcov);

  const aaLength = parseSequenceLength(sequenceQuery);
  const isOverLimit = aaLength > MAX_AA_LENGTH;

  // Clamp slider display values into their visual ranges so saved/restored
  // values outside the slider still render somewhere sensible.
  const bitscoreSlider = Math.min(BITSCORE_MAX, Math.max(BITSCORE_MIN, minBitscore));
  const pidentSlider = Math.min(PCT_MAX, Math.max(PCT_MIN, minPident));
  const qcovSlider = Math.min(PCT_MAX, Math.max(PCT_MIN, minQcov));

  return (
    <div className="space-y-4 pt-2">
      <div className="space-y-1.5">
        <Label className="text-xs">Protein Sequence</Label>
        <textarea
          placeholder="Paste a protein sequence (FASTA or raw AA)..."
          value={sequenceQuery}
          onChange={(e) => setSequenceQuery(e.target.value)}
          className="vf-form__input w-full rounded-md border bg-background px-3 py-2 text-xs font-mono min-h-[80px] resize-y focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          rows={4}
        />
        <div className="flex items-center justify-between">
          <span
            className={`text-[10px] ${isOverLimit ? "text-destructive font-medium" : "text-muted-foreground"}`}
          >
            {aaLength > 0
              ? `${aaLength.toLocaleString()} / ${MAX_AA_LENGTH.toLocaleString()} AA`
              : ""}
          </span>
          {isOverLimit && (
            <span className="text-[10px] text-destructive">
              Exceeds maximum length
            </span>
          )}
        </div>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center justify-between">
          <Label className="flex items-center gap-1 text-xs">
            Min bitscore
            <HelpTooltip tooltipKey="phmmer_bitscore" side="right" />
          </Label>
          <span className="font-mono text-xs text-muted-foreground">
            ≥ {minBitscore}
          </span>
        </div>
        <Slider
          value={[bitscoreSlider]}
          onValueChange={([v]) => {
            if (v !== undefined) setMinBitscore(v);
          }}
          min={BITSCORE_MIN}
          max={BITSCORE_MAX}
          step={BITSCORE_STEP}
          className="w-full"
        />
        <div className="flex justify-between text-[10px] text-muted-foreground">
          <span>permissive (0)</span>
          <span>strict (500)</span>
        </div>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center justify-between">
          <Label className="flex items-center gap-1 text-xs">
            Min % identity
            <HelpTooltip tooltipKey="phmmer_pident" side="right" />
          </Label>
          <span className="font-mono text-xs text-muted-foreground">
            ≥ {minPident}%
          </span>
        </div>
        <Slider
          value={[pidentSlider]}
          onValueChange={([v]) => {
            if (v !== undefined) setMinPident(v);
          }}
          min={PCT_MIN}
          max={PCT_MAX}
          step={PCT_STEP}
          className="w-full"
        />
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center justify-between">
          <Label className="flex items-center gap-1 text-xs">
            Min query coverage
            <HelpTooltip tooltipKey="phmmer_qcoverage" side="right" />
          </Label>
          <span className="font-mono text-xs text-muted-foreground">
            ≥ {minQcov}%
          </span>
        </div>
        <Slider
          value={[qcovSlider]}
          onValueChange={([v]) => {
            if (v !== undefined) setMinQcov(v);
          }}
          min={PCT_MIN}
          max={PCT_MAX}
          step={PCT_STEP}
          className="w-full"
        />
      </div>

      <p className="text-[10px] text-muted-foreground">
        Press "Run Query" above to search by protein similarity (phmmer). A
        hit must satisfy all three cut-offs. Results are combined with any
        active filters and domain conditions.
      </p>
    </div>
  );
}
