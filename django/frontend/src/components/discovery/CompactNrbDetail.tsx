import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchNrbDetail } from "@/api/nrbs";
import { fetchBgcRegion } from "@/api/bgcs";
import { RegionPlot } from "@/components/bgc/RegionPlot";
import { useDiscoveryStore } from "@/stores/discovery-store";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import {
  FlaskConical,
  FileText,
  Sparkles,
  Pin,
  Loader2,
  ChevronRight,
} from "lucide-react";
import { cn } from "@/lib/utils";

interface Props {
  nrbId: number | null;
  variant: "reference" | "compare";
}

function fmt(v: number | null | undefined, digits = 3): string {
  return v == null ? "—" : v.toFixed(digits);
}

/**
 * Inline KPI strip + "… More" sheet (locked design round 3).
 *
 * Reference variant pins to a sticky header, compare variant shows a hint
 * that the slot reflects the last left-clicked NRB.
 */
export function CompactNrbDetail({ nrbId, variant }: Props) {
  const { data: nrb, isLoading, isError } = useQuery({
    queryKey: ["nrb-detail", nrbId],
    queryFn: () => fetchNrbDetail(nrbId as number),
    enabled: nrbId !== null,
  });

  const accent =
    variant === "reference"
      ? "border-primary/60"
      : "border-muted-foreground/30";

  if (nrbId === null) {
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
            Right-click a result and choose “Set as reference NRB”
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

  if (isLoading || !nrb) {
    return (
      <Card
        className={cn("flex h-full items-center justify-center", accent)}
      >
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
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
        Failed to load NRB detail
      </Card>
    );
  }

  const compoundsCount = nrb.natural_products.length;
  const parentAcc = nrb.parent_assembly?.accession ?? "—";
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
          <h3 className="font-mono text-sm font-semibold">{nrb.label}</h3>
          {nrb.is_validated && (
            <Badge variant="default" className="text-[10px]">
              MIBiG
            </Badge>
          )}
          {nrb.umap_projected && (
            <Badge variant="outline" className="text-[10px]">
              projected
            </Badge>
          )}
        </div>
        <NrbMoreSheet nrb={nrb} />
      </CardHeader>

      <CardContent className="flex min-h-0 flex-1 flex-col gap-2 overflow-hidden p-3 pt-0">
        <KpiStrip
          compounds={compoundsCount}
          parentAcc={parentAcc}
          novelty={nrb.novelty_score}
          domainNovelty={nrb.domain_novelty}
        />

        <div className="rounded border bg-muted/20 p-2 text-xs text-muted-foreground">
          <div className="font-mono">
            {nrb.contig_accession ?? "no contig"} ·{" "}
            {nrb.start_position.toLocaleString()}–
            {nrb.end_position.toLocaleString()} ({nrb.size_kb.toFixed(1)} kb)
          </div>
          <div className="mt-1">
            <strong>{nrb.member_bgcs.length}</strong> source BGC(s) ·{" "}
            <strong>{nrb.source_tools.join(", ") || "—"}</strong>
          </div>
        </div>

        <RegionStrip
          representativeBgcId={nrb.representative_bgc_id}
        />

        <MemberBgcStrip memberBgcs={nrb.member_bgcs} />
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
  const { data, isLoading } = useQuery({
    queryKey: ["bgc-region", representativeBgcId],
    queryFn: () => fetchBgcRegion(representativeBgcId as number),
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
  compounds: number;
  parentAcc: string;
  novelty: number | null;
  domainNovelty: number | null;
}

function KpiStrip({
  compounds,
  parentAcc,
  novelty,
  domainNovelty,
}: KpiStripProps) {
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs">
      <Kpi
        icon={<FlaskConical className="h-3.5 w-3.5" />}
        label="cpds"
        value={String(compounds)}
      />
      <Kpi
        icon={<FileText className="h-3.5 w-3.5" />}
        label="parent"
        value={parentAcc}
      />
      <Kpi
        icon={<Sparkles className="h-3.5 w-3.5" />}
        label="N"
        value={fmt(novelty, 2)}
      />
      <Kpi
        icon={<Sparkles className="h-3.5 w-3.5" />}
        label="DN"
        value={fmt(domainNovelty, 2)}
      />
    </div>
  );
}

function Kpi({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
}) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 font-mono">
      {icon}
      <span className="text-muted-foreground">{label}</span>
      <span className="font-semibold">{value}</span>
    </span>
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

function NrbMoreSheet({
  nrb,
}: {
  nrb: import("@/api/types").NrbDetail;
}) {
  const [open, setOpen] = useState(false);
  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>
        <Button variant="ghost" size="sm" className="text-xs">
          … More
        </Button>
      </SheetTrigger>
      <SheetContent className="w-[480px] sm:max-w-md">
        <SheetHeader>
          <SheetTitle>{nrb.label}</SheetTitle>
          <SheetDescription>
            Full NRB detail · {nrb.classification_path || "(unclassified)"}
          </SheetDescription>
        </SheetHeader>
        <div className="mt-4 space-y-4 text-sm">
          <Section label="Chemical compounds">
            {nrb.natural_products.length === 0 ? (
              <span className="text-muted-foreground">None reported</span>
            ) : (
              <ul className="space-y-1">
                {nrb.natural_products.map((np) => (
                  <li key={np.id} className="font-mono text-xs">
                    {np.name || "(unnamed)"}{" "}
                    {np.np_class_path && (
                      <span className="text-muted-foreground">
                        — {np.np_class_path}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </Section>
          <Section label="Parent assembly">
            {nrb.parent_assembly ? (
              <div className="space-y-1">
                <div className="font-mono text-xs">
                  {nrb.parent_assembly.accession}
                </div>
                {nrb.parent_assembly.organism_name && (
                  <div className="text-xs text-muted-foreground">
                    {nrb.parent_assembly.organism_name}
                  </div>
                )}
              </div>
            ) : (
              <span className="text-muted-foreground">No parent assembly</span>
            )}
          </Section>
          <Section label="Novelty">
            <div className="grid grid-cols-2 gap-2 text-xs">
              <div>
                <div className="text-muted-foreground">Novelty</div>
                <div className="font-mono">{fmt(nrb.novelty_score)}</div>
              </div>
              <div>
                <div className="text-muted-foreground">Domain novelty</div>
                <div className="font-mono">{fmt(nrb.domain_novelty)}</div>
              </div>
            </div>
          </Section>
          <Section label="Domain architecture">
            <div className="flex flex-wrap gap-1">
              {nrb.domain_architecture.slice(0, 40).map((d) => (
                <Badge
                  key={`${d.domain_acc}-${d.start}`}
                  variant="outline"
                  className="font-mono text-[10px]"
                >
                  {d.domain_acc}
                </Badge>
              ))}
              {nrb.domain_architecture.length > 40 && (
                <Badge variant="outline" className="text-[10px]">
                  +{nrb.domain_architecture.length - 40}
                </Badge>
              )}
            </div>
          </Section>
        </div>
      </SheetContent>
    </Sheet>
  );
}

function Section({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      {children}
    </div>
  );
}
