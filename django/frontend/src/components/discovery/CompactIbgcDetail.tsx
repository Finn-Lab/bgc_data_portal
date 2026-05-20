import { useQuery } from "@tanstack/react-query";
import { fetchIbgcDetail } from "@/api/ibgcs";
import { fetchBgcRegion } from "@/api/bgcs";
import { RegionPlot } from "@/components/bgc/RegionPlot";
import { IbgcActionsMenu } from "./IbgcActionsMenu";
import { useDiscoveryStore } from "@/stores/discovery-store";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  Pin,
  Loader2,
  ChevronRight,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type {
  ChemOntAnnotationNode,
  NaturalProductSummary,
  ParentAssemblySummary,
} from "@/api/types";

function collectLeaves(node: ChemOntAnnotationNode): ChemOntAnnotationNode[] {
  if (node.children.length === 0) return [node];
  return node.children.flatMap(collectLeaves);
}

function molviewHref(smiles: string): string {
  return `https://app.molview.com/?smiles=${encodeURIComponent(smiles)}`;
}

interface Props {
  ibgcId: number | null;
  variant: "reference" | "compare";
}

function fmt(v: number | null | undefined, digits = 3): string {
  return v == null ? "—" : v.toFixed(digits);
}

export function CompactIbgcDetail({ ibgcId, variant }: Props) {
  const assetToken = useDiscoveryStore((s) => s.assetToken);
  const { data: ibgc, isLoading, isError } = useQuery({
    queryKey: ["ibgc-detail", ibgcId, ibgcId !== null && ibgcId < 0 ? assetToken : null],
    queryFn: () => fetchIbgcDetail(ibgcId as number, assetToken),
    enabled: ibgcId !== null,
  });

  const accent =
    variant === "reference"
      ? "border-primary/60"
      : "border-muted-foreground/30";

  if (ibgcId === null) {
    return (
      <Card
        className={cn(
          "flex h-full items-center justify-center border-2 border-dashed text-sm text-muted-foreground",
          accent,
        )}
      >
        {variant === "reference" ? (
          <span>
            <Pin className="mr-2 inline h-4 w-4" />
            Right-click a result and choose “Set as reference iBGC”
          </span>
        ) : (
          <span>
            <ChevronRight className="mr-2 inline h-4 w-4" />
            Left-click a result to load it here
          </span>
        )}
      </Card>
    );
  }

  if (isError) {
    return (
      <Card
        className={cn(
          "flex h-full items-center justify-center text-destructive",
          accent,
        )}
      >
        Failed to load iBGC detail
      </Card>
    );
  }

  if (isLoading || !ibgc) {
    return (
      <Card
        className={cn("flex h-full items-center justify-center", accent)}
      >
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </Card>
    );
  }

  const variantLabel = variant === "reference" ? "Reference" : "Compare";

  return (
    <Card className={cn("flex h-full flex-col overflow-hidden border-2", accent)}>
      <CardHeader className="flex flex-row items-center justify-between gap-2 p-3">
        <div className="flex items-center gap-2">
          <Badge
            variant={variant === "reference" ? "default" : "outline"}
            className="text-[10px] uppercase tracking-wide"
          >
            {variantLabel}
          </Badge>
          <h3 className="font-mono text-sm font-semibold">{ibgc.label}</h3>
          {ibgc.is_validated && (
            <Badge variant="default" className="text-[10px]">
              Validated
            </Badge>
          )}
          {ibgc.is_type_strain && (
            <Badge
              className="text-[10px] text-white border-transparent"
              style={{ backgroundColor: "#018786" }}
            >
              Type Strain
            </Badge>
          )}
          {ibgc.umap_projected && (
            <Badge variant="outline" className="text-[10px]">
              projected
            </Badge>
          )}
        </div>
        <IbgcActionsMenu
          ibgcId={ibgc.id}
          ibgcLabel={ibgc.label}
          variant={variant}
          isPartial={ibgc.umap_projected}
          isAsset={ibgc.id < 0}
        />
      </CardHeader>

      <CardContent className="flex min-h-0 flex-1 flex-col gap-2 overflow-hidden p-3 pt-0">
        <KpiStrip
          naturalProducts={ibgc.natural_products}
          chemontTree={ibgc.chemont_tree}
          parentAssembly={ibgc.parent_assembly}
          novelty={ibgc.novelty_score}
          domainNovelty={ibgc.domain_novelty}
        />

        <div className="rounded border bg-muted/20 p-2 text-xs text-muted-foreground">
          <div className="font-mono">
            {ibgc.contig_accession ?? "no contig"} ·{" "}
            {ibgc.start_position.toLocaleString()}–
            {ibgc.end_position.toLocaleString()} ({ibgc.size_kb.toFixed(1)} kb)
          </div>
          <div className="mt-1">
            <strong>{ibgc.member_bgcs.length}</strong> source BGC(s) ·{" "}
            <strong>{ibgc.source_tools.join(", ") || "—"}</strong>
          </div>
        </div>

        <RegionStrip
          representativeBgcId={ibgc.representative_bgc_id}
        />

        <MemberBgcStrip memberBgcs={ibgc.member_bgcs} />
      </CardContent>
    </Card>
  );
}

function RegionStrip({
  representativeBgcId,
}: {
  representativeBgcId: number | null;
}) {
  const setSelectedCds = useDiscoveryStore((s) => s.setSelectedCds);
  const selectedCds = useDiscoveryStore((s) => s.selectedCds);
  const assetToken = useDiscoveryStore((s) => s.assetToken);
  const isAssetBgc =
    representativeBgcId !== null && representativeBgcId < 0;
  const { data, isLoading } = useQuery({
    queryKey: [
      "bgc-region",
      representativeBgcId,
      isAssetBgc ? assetToken : null,
    ],
    queryFn: () =>
      fetchBgcRegion(representativeBgcId as number, assetToken),
    enabled: representativeBgcId !== null,
  });

  if (representativeBgcId === null) return null;
  if (isLoading) {
    return (
      <div className="flex h-12 items-center justify-center rounded border bg-muted/20 text-xs text-muted-foreground">
        <Loader2 className="mr-2 h-3 w-3 animate-spin" />
        Loading region…
      </div>
    );
  }
  if (!data) return null;

  return (
    <div className="min-h-0 flex-1 overflow-auto rounded border bg-card">
      <RegionPlot
        data={data}
        onCdsClick={(cds) => setSelectedCds(cds)}
        selectedCdsId={selectedCds?.protein_id ?? null}
      />
    </div>
  );
}

interface KpiStripProps {
  naturalProducts: NaturalProductSummary[];
  chemontTree: ChemOntAnnotationNode[];
  parentAssembly: ParentAssemblySummary | null;
  novelty: number | null;
  domainNovelty: number | null;
}

const CHIP_BASE =
  "inline-flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 font-mono";
const CHIP_CLICKABLE = "cursor-pointer transition-colors hover:bg-muted/60";

function KpiStrip({
  naturalProducts,
  chemontTree,
  parentAssembly,
  novelty,
  domainNovelty,
}: KpiStripProps) {
  // Compounds chip count = distinct deepest ChemOnt classes seen across the
  // iBGC's CDSs, plus any curated NP names (deduped). Treat curated names
  // (e.g. MIBiG compounds) and CHAMOIS classes as a single conceptual count.
  const leaves = chemontTree.flatMap(collectLeaves);
  const compoundsCount = naturalProducts.length + leaves.length;
  const firstSmiles = naturalProducts.find((np) => np.smiles)?.smiles;
  const parentAcc = parentAssembly?.accession ?? "—";

  return (
    <TooltipProvider delayDuration={150}>
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <CompoundsChip
          count={compoundsCount}
          naturalProducts={naturalProducts}
          chemontTree={chemontTree}
          molviewSmiles={firstSmiles}
        />

        {parentAssembly?.url ? (
          <a
            href={parentAssembly.url}
            target="_blank"
            rel="noopener noreferrer"
            title={parentAssembly.organism_name ?? parentAssembly.accession}
            className={cn(CHIP_BASE, CHIP_CLICKABLE, "text-foreground")}
          >
            <span className="text-muted-foreground">parent</span>
            <span className="font-semibold">{parentAcc}</span>
          </a>
        ) : (
          <span className={CHIP_BASE}>
            <span className="text-muted-foreground">parent</span>
            <span className="font-semibold">{parentAcc}</span>
          </span>
        )}

        <span className={CHIP_BASE}>
          <span className="text-muted-foreground">Novelty</span>
          <span className="font-semibold">{fmt(novelty, 2)}</span>
        </span>

        <span className={CHIP_BASE}>
          <span className="text-muted-foreground">Domain Novelty</span>
          <span className="font-semibold">{fmt(domainNovelty, 2)}</span>
        </span>
      </div>
    </TooltipProvider>
  );
}

function CompoundsChip({
  count,
  naturalProducts,
  chemontTree,
  molviewSmiles,
}: {
  count: number;
  naturalProducts: NaturalProductSummary[];
  chemontTree: ChemOntAnnotationNode[];
  molviewSmiles: string | undefined;
}) {
  const chipBody = (
    <>
      <span className="text-muted-foreground">compound features</span>
      <span className="font-semibold">{String(count)}</span>
    </>
  );

  const trigger = molviewSmiles ? (
    <a
      href={molviewHref(molviewSmiles)}
      target="_blank"
      rel="noopener noreferrer"
      className={cn(CHIP_BASE, CHIP_CLICKABLE, "text-foreground")}
    >
      {chipBody}
    </a>
  ) : (
    <span className={CHIP_BASE}>{chipBody}</span>
  );

  if (count === 0) return trigger;

  return (
    <Tooltip>
      <TooltipTrigger asChild>{trigger}</TooltipTrigger>
      <TooltipContent
        side="bottom"
        className="max-w-sm border bg-popover text-popover-foreground shadow-md"
      >
        <CompoundsTooltipBody
          naturalProducts={naturalProducts}
          chemontTree={chemontTree}
        />
      </TooltipContent>
    </Tooltip>
  );
}

function CompoundsTooltipBody({
  naturalProducts,
  chemontTree,
}: {
  naturalProducts: NaturalProductSummary[];
  chemontTree: ChemOntAnnotationNode[];
}) {
  return (
    <div className="space-y-3 text-xs">
      {naturalProducts.length > 0 && (
        <div className="space-y-2">
          <div className="text-[10px] font-semibold uppercase text-muted-foreground">
            Curated compounds
          </div>
          {naturalProducts.map((np) => (
            <div
              key={np.id}
              className="space-y-1 border-b border-border/40 pb-2 last:border-0 last:pb-0"
            >
              <div className="font-medium">{np.name || "(unnamed)"}</div>
              {np.np_class_path && (
                <div className="text-[10px] text-muted-foreground">
                  {np.np_class_path.replace(/\./g, " > ")}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {chemontTree.length > 0 && (
        <div className="space-y-1">
          <div className="text-[10px] font-semibold uppercase text-muted-foreground">
            CHAMOIS ChemOnt classes (aggregated across CDSs)
          </div>
          {chemontTree.map((root) => (
            <ChemontGroup key={root.chemont_id} node={root} indent={0} />
          ))}
        </div>
      )}
    </div>
  );
}

function ChemontGroup({
  node,
  indent,
}: {
  node: ChemOntAnnotationNode;
  indent: number;
}) {
  const isLeaf = node.children.length === 0;
  return (
    <div style={{ paddingLeft: `${indent * 8}px` }} className="space-y-0.5">
      <div
        title={node.chemont_id}
        className={cn(
          "flex flex-wrap items-center gap-1",
          isLeaf ? "font-medium" : "text-muted-foreground",
        )}
      >
        <span>{node.name}</span>
        {node.n_cds > 0 && (
          <span className="rounded-sm bg-muted px-1 text-[10px] font-normal">
            {node.n_cds} CDS
          </span>
        )}
        {node.probability != null && (
          <span className="text-[10px] font-normal text-muted-foreground">
            {(node.probability * 100).toFixed(0)}%
          </span>
        )}
      </div>
      {node.children.map((child) => (
        <ChemontGroup key={child.chemont_id} node={child} indent={indent + 1} />
      ))}
    </div>
  );
}

function MemberBgcStrip({
  memberBgcs,
}: {
  memberBgcs: { id: number; accession: string }[];
}) {
  if (memberBgcs.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-1 overflow-hidden">
      {memberBgcs.slice(0, 6).map((m) => (
        <Badge key={m.id} variant="outline" className="font-mono text-[10px]">
          {m.accession}
        </Badge>
      ))}
      {memberBgcs.length > 6 && (
        <Badge variant="outline" className="text-[10px]">
          +{memberBgcs.length - 6}
        </Badge>
      )}
    </div>
  );
}

