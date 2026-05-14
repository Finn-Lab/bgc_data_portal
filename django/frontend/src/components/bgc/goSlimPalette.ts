// Global GO slim term → color map. Computed once over the full sorted
// molecular-function vocabulary so the same term gets the same color in
// every RegionPlot instance.
//
// Vocabulary source: django/discovery/management/commands/data/pfam2goSlim.json.
// Capitalization matches discovery/management/commands/load_pfam_go_slim.py
// (`desc.capitalize()`), which is what ends up in BgcDomain.go_slim. Regenerate
// this list if the JSON gains new molecular_function entries.

export const GO_SLIM_VOCABULARY: readonly string[] = Object.freeze([
  "Amino acid binding",
  "Antioxidant activity",
  "Carbohydrate binding",
  "Catalytic activity",
  "Coenzyme binding",
  "Drug transporter activity",
  "Electron carrier activity",
  "Hydrolase activity",
  "Ion binding",
  "Iron-sulfur cluster binding",
  "Isomerase activity",
  "Kinase activity",
  "Ligase activity",
  "Lyase activity",
  "Metal ion binding",
  "Molecular function",
  "Nucleic acid binding",
  "Nucleoside-triphosphatase activity",
  "Nucleotide binding",
  "Nucleotidyltransferase activity",
  "Oxidoreductase activity",
  "Penicillin binding",
  "Peptidase activity",
  "Peroxidase activity",
  "Phosphatase activity",
  "Protein binding",
  "Pyridoxal phosphate binding",
  "Receptor activity",
  "Recombinase activity",
  "Signal transducer activity",
  "Structural constituent of ribosome",
  "Tetrapyrrole binding",
  "Transcription factor activity, sequence-specific dna binding",
  "Transcription factor binding",
  "Transferase activity",
  "Transporter activity",
  // Note: "activiy" typo is propagated from the source JSON. Do not "fix" it
  // here — BgcDomain.go_slim rows already contain this exact string.
  "Transposase activiy",
  "Vitamin binding",
]);

export const UNANNOTATED_COLOR = "#e8e8e8";
export const UNANNOTATED_LABEL = "Unannotated";

function hlsToRgb(h: number, l: number, s: number): [number, number, number] {
  if (s === 0) return [l, l, l];
  const hue2rgb = (p: number, q: number, t: number) => {
    if (t < 0) t += 1;
    if (t > 1) t -= 1;
    if (t < 1 / 6) return p + (q - p) * 6 * t;
    if (t < 1 / 2) return q;
    if (t < 2 / 3) return p + (q - p) * (2 / 3 - t) * 6;
    return p;
  };
  const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
  const p = 2 * l - q;
  return [hue2rgb(p, q, h + 1 / 3), hue2rgb(p, q, h), hue2rgb(p, q, h - 1 / 3)];
}

function makeDistinctColorMap(keys: readonly string[]): Record<string, string> {
  const PHI = 0.618033988749895;
  const SEED = 0.12;
  const L0 = 0.6, L1 = 0.66;
  const S0 = 0.78, S1 = 0.86;
  const unique = [...new Set(keys)].sort();
  const out: Record<string, string> = {};
  for (let i = 0; i < unique.length; i++) {
    const h = (SEED + i * PHI) % 1.0;
    const l = i % 2 === 0 ? L0 : L1;
    const s = Math.floor(i / 2) % 2 === 0 ? S0 : S1;
    const [r, g, b] = hlsToRgb(h, l, s);
    out[unique[i]!] = `rgb(${Math.round(r * 255)}, ${Math.round(g * 255)}, ${Math.round(b * 255)})`;
  }
  return out;
}

export const GO_SLIM_COLOR_MAP: Readonly<Record<string, string>> = Object.freeze(
  makeDistinctColorMap(GO_SLIM_VOCABULARY),
);

const warnedUnknown = new Set<string>();

export function getGoSlimColor(term: string | null | undefined): string {
  if (!term) return UNANNOTATED_COLOR;
  const c = GO_SLIM_COLOR_MAP[term];
  if (c) return c;
  if (!warnedUnknown.has(term)) {
    warnedUnknown.add(term);
    // Surfaces vocabulary drift (e.g. pfam2goSlim.json gained new entries
    // but goSlimPalette.ts wasn't regenerated).
    console.warn(`[goSlimPalette] Unknown GO slim term: "${term}"`);
  }
  return UNANNOTATED_COLOR;
}
