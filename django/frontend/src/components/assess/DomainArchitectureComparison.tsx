import { useCallback, useMemo, useState } from "react";
import { RegionPlot } from "@/components/bgc/RegionPlot";
import { CdsProteinInfo } from "@/components/bgc/CdsProteinInfo";
import { useBgcRegion } from "@/hooks/use-bgc-region";
import { useSelectionStore } from "@/stores/selection-store";
import { Loader2 } from "lucide-react";
import type { BgcRegionData, RegionCds } from "@/api/types";

interface DomainArchitectureComparisonProps {
  bgcId: number;
}

/** HLS → RGB (same palette as RegionPlot) */
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

function makeDistinctColorMap(keys: string[]): Record<string, string> {
  const PHI = 0.618033988749895;
  const SEED = 0.12;
  const unique = [...new Set(keys)].sort();
  const out: Record<string, string> = {};
  for (let i = 0; i < unique.length; i++) {
    const h = (SEED + i * PHI) % 1.0;
    const l = i % 2 === 0 ? 0.6 : 0.66;
    const s = Math.floor(i / 2) % 2 === 0 ? 0.78 : 0.86;
    const [r, g, b] = hlsToRgb(h, l, s);
    out[unique[i]!] = `rgb(${Math.round(r * 255)}, ${Math.round(g * 255)}, ${Math.round(b * 255)})`;
  }
  return out;
}

interface CdsLink {
  fromFraction: number;
  toFraction: number;
  color: string;
}

function computeLinks(
  regionA: BgcRegionData,
  regionB: BgcRegionData,
  positionsA: Record<string, number>,
  positionsB: Record<string, number>,
): CdsLink[] {
  // Build CDS → {domain_acc → count} maps
  const cdsDomainsA: Record<string, Set<string>> = {};
  for (const d of regionA.domain_list) {
    if (!d.parent_cds_id) continue;
    (cdsDomainsA[d.parent_cds_id] ??= new Set()).add(d.accession);
  }
  const cdsDomainsB: Record<string, Set<string>> = {};
  for (const d of regionB.domain_list) {
    if (!d.parent_cds_id) continue;
    (cdsDomainsB[d.parent_cds_id] ??= new Set()).add(d.accession);
  }

  // Collect all shared accessions for color map
  const allSharedAccs: string[] = [];
  for (const domsA of Object.values(cdsDomainsA)) {
    for (const domsB of Object.values(cdsDomainsB)) {
      for (const acc of domsA) {
        if (domsB.has(acc)) allSharedAccs.push(acc);
      }
    }
  }
  const colorMap = makeDistinctColorMap(allSharedAccs);

  const links: CdsLink[] = [];
  for (const [cdsIdA, domsA] of Object.entries(cdsDomainsA)) {
    const xA = positionsA[cdsIdA];
    if (xA === undefined) continue;

    let bestCount = 0;
    let bestCdsIdB = "";
    let bestAcc = "";

    for (const [cdsIdB, domsB] of Object.entries(cdsDomainsB)) {
      const shared = [...domsA].filter((d) => domsB.has(d));
      if (shared.length > bestCount) {
        bestCount = shared.length;
        bestCdsIdB = cdsIdB;
        bestAcc = shared[0] ?? "";
      }
    }

    if (bestCount === 0) continue;
    const xB = positionsB[bestCdsIdB];
    if (xB === undefined) continue;

    links.push({
      fromFraction: xA,
      toFraction: xB,
      color: colorMap[bestAcc] ?? "#999",
    });
  }
  return links;
}

export function DomainArchitectureComparison({
  bgcId,
}: DomainArchitectureComparisonProps) {
  const isUploaded = bgcId < 0;
  const submittedRegion = useBgcRegion(isUploaded ? null : bgcId);

  const activeBgcId = useSelectionStore((s) => s.activeBgcId);
  const comparisonId =
    activeBgcId !== null && activeBgcId !== bgcId ? activeBgcId : null;
  const comparisonRegion = useBgcRegion(comparisonId);

  const [selectedCds, setSelectedCds] = useState<RegionCds | null>(null);
  const [positionsA, setPositionsA] = useState<Record<string, number>>({});
  const [positionsB, setPositionsB] = useState<Record<string, number>>({});

  const handleCdsClick = (cds: RegionCds) => {
    setSelectedCds((prev) =>
      prev?.protein_id === cds.protein_id ? null : cds,
    );
  };

  const handlePositionsA = useCallback((p: Record<string, number>) => setPositionsA(p), []);
  const handlePositionsB = useCallback((p: Record<string, number>) => setPositionsB(p), []);

  const links = useMemo(() => {
    if (
      !submittedRegion.data ||
      !comparisonRegion.data ||
      Object.keys(positionsA).length === 0 ||
      Object.keys(positionsB).length === 0
    )
      return [];
    return computeLinks(
      submittedRegion.data,
      comparisonRegion.data,
      positionsA,
      positionsB,
    );
  }, [submittedRegion.data, comparisonRegion.data, positionsA, positionsB]);

  if (!isUploaded && submittedRegion.isLoading) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const hasSubmittedRegion = !isUploaded && !!submittedRegion.data;

  if (isUploaded && !comparisonId) {
    return (
      <p className="py-4 text-sm text-muted-foreground">
        Region-level architecture is unavailable for uploaded BGCs — the
        upload bundle doesn't include CDS coordinates. Click a BGC in the
        roster above to show its architecture here.
      </p>
    );
  }

  if (!hasSubmittedRegion && !comparisonId) {
    return (
      <p className="py-4 text-sm text-muted-foreground">
        Region data not available for this BGC.
      </p>
    );
  }

  const showConnector =
    hasSubmittedRegion && !!comparisonRegion.data && links.length > 0;

  return (
    <div className="space-y-0">
      {/* Submitted BGC region */}
      {hasSubmittedRegion && (
        <div>
          <p className="mb-1 text-xs font-medium">Submitted BGC</p>
          <RegionPlot
            data={submittedRegion.data!}
            onCdsClick={handleCdsClick}
            selectedCdsId={selectedCds?.protein_id ?? null}
            onCdsPositions={handlePositionsA}
          />
        </div>
      )}

      {/* Connector lines between the two plots */}
      {showConnector && (
        <svg
          width="100%"
          height="36"
          viewBox="0 0 1 1"
          preserveAspectRatio="none"
          className="block"
          aria-hidden="true"
        >
          {links.map((link, i) => (
            <path
              key={i}
              d={`M ${link.fromFraction} 0 C ${link.fromFraction} 0.5, ${link.toFraction} 0.5, ${link.toFraction} 1`}
              fill="none"
              stroke={link.color}
              strokeWidth="0.004"
              opacity="0.65"
            />
          ))}
        </svg>
      )}

      {/* Comparison BGC — the row clicked in the BGC Roster. */}
      {comparisonId ? (
        <div>
          <p className="mb-1 text-xs font-medium">
            Compared against BGC #{comparisonId}
          </p>
          {comparisonRegion.isLoading ? (
            <div className="flex items-center justify-center py-4">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : comparisonRegion.data ? (
            <RegionPlot
              data={comparisonRegion.data}
              onCdsClick={handleCdsClick}
              selectedCdsId={selectedCds?.protein_id ?? null}
              onCdsPositions={handlePositionsB}
            />
          ) : (
            <p className="py-2 text-xs text-muted-foreground">
              Region data not available for the selected BGC.
            </p>
          )}
        </div>
      ) : (
        <p className="py-2 text-xs text-muted-foreground">
          Click a BGC in the roster above to compare its domain architecture
          against the submitted BGC.
        </p>
      )}

      {/* Protein details for the CDS clicked in either plot */}
      {selectedCds && (
        <CdsProteinInfo
          cds={selectedCds}
          onClose={() => setSelectedCds(null)}
        />
      )}
    </div>
  );
}
