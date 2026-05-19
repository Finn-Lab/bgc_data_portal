// Stable colour assignment for GO-slim term names.
//
// Previously seeded from a hardcoded vocabulary mirrored from pfam2goSlim.json
// (single MF term per Pfam accession). The ingestion path now derives slim
// names from per-signature GO terms via goatools.mapslim against
// goslim_metagenomics (see `discovery/services/go_slim.py`), so the vocabulary
// is open-ended. Colours are therefore derived deterministically from the
// term string itself — same term ⇒ same colour, no regeneration needed.

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

// FNV-1a 32-bit hash, lifted into [0, 1).
function hashTo01(s: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  // Normalise — strip sign and divide by 2^32.
  return ((h >>> 0) % 1_000_000) / 1_000_000;
}

const colorCache = new Map<string, string>();

export function getGoSlimColor(term: string | null | undefined): string {
  if (!term) return UNANNOTATED_COLOR;
  const cached = colorCache.get(term);
  if (cached) return cached;

  // Hue from a hash of the term; lightness/saturation alternate by hue band so
  // adjacent terms in alphabetical view stay visually distinct.
  const h = hashTo01(term);
  const band = Math.floor(h * 16);
  const l = band % 2 === 0 ? 0.6 : 0.66;
  const s = Math.floor(band / 2) % 2 === 0 ? 0.78 : 0.86;
  const [r, g, b] = hlsToRgb(h, l, s);
  const color = `rgb(${Math.round(r * 255)}, ${Math.round(g * 255)}, ${Math.round(b * 255)})`;
  colorCache.set(term, color);
  return color;
}

// Back-compat: existing call sites destructure GO_SLIM_COLOR_MAP[term] with a
// `?? UNANNOTATED_COLOR` fallback. Expose a Proxy-shaped object that resolves
// lazily so they keep working without refactor.
export const GO_SLIM_COLOR_MAP: Record<string, string> = new Proxy(
  {} as Record<string, string>,
  {
    get(_target, prop: string) {
      if (typeof prop !== "string") return undefined;
      return getGoSlimColor(prop);
    },
  },
);
