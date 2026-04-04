import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Check, Copy, ExternalLink, X } from "lucide-react";
import type { RegionCds } from "@/api/types";

interface CdsProteinInfoProps {
  cds: RegionCds;
  onClose: () => void;
}

export function CdsProteinInfo({ cds, onClose }: CdsProteinInfoProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    if (!cds.sequence) return;
    await navigator.clipboard.writeText(cds.sequence);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="mt-3 rounded-md border bg-background p-3 text-xs animate-in fade-in-50 slide-in-from-top-2 duration-200">
      {/* Header */}
      <div className="flex items-center justify-between mb-2">
        <h6 className="font-semibold text-sm">
          Protein Information — {cds.protein_id}
        </h6>
        <Button variant="ghost" size="sm" className="h-6 w-6 p-0" onClick={onClose}>
          <X className="h-3.5 w-3.5" />
        </Button>
      </div>

      <Separator className="mb-2" />

      {/* Summary grid */}
      <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 mb-3">
        <div>
          <span className="text-muted-foreground">Cluster Representative</span>
          <div className="font-medium">
            {cds.cluster_representative ? (
              <a
                href={cds.cluster_representative_url ?? "#"}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-blue-600 hover:underline"
              >
                {cds.cluster_representative}
                <ExternalLink className="h-2.5 w-2.5" />
              </a>
            ) : (
              "N/A"
            )}
          </div>
        </div>
        <div>
          <span className="text-muted-foreground">Protein Length</span>
          <div className="font-medium">{cds.protein_length} aa</div>
        </div>
        <div>
          <span className="text-muted-foreground">Gene Caller</span>
          <div className="font-medium">{cds.gene_caller || "N/A"}</div>
        </div>
        <div>
          <span className="text-muted-foreground">Strand</span>
          <div className="font-medium">{cds.strand >= 0 ? "+" : "−"}</div>
        </div>
        <div>
          <span className="text-muted-foreground">Start</span>
          <div className="font-medium font-mono">{cds.start}</div>
        </div>
        <div>
          <span className="text-muted-foreground">End</span>
          <div className="font-medium font-mono">{cds.end}</div>
        </div>
      </div>

      {/* Pfam annotations table */}
      <div className="mb-3">
        <h6 className="font-semibold text-xs mb-1">Pfam Annotations</h6>
        {cds.pfam.length === 0 ? (
          <p className="text-muted-foreground italic">No Pfam annotations</p>
        ) : (
          <div className="max-h-48 overflow-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="text-[10px] h-7 px-1.5">PFAM</TableHead>
                  <TableHead className="text-[10px] h-7 px-1.5">Description</TableHead>
                  <TableHead className="text-[10px] h-7 px-1.5">GO Slim</TableHead>
                  <TableHead className="text-[10px] h-7 px-1.5">Start</TableHead>
                  <TableHead className="text-[10px] h-7 px-1.5">End</TableHead>
                  <TableHead className="text-[10px] h-7 px-1.5">E-value</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {cds.pfam.map((pf, i) => (
                  <TableRow key={`${pf.accession}-${i}`}>
                    <TableCell className="text-[10px] px-1.5 py-1">
                      {pf.url ? (
                        <a
                          href={pf.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-blue-600 hover:underline"
                        >
                          {pf.accession}
                        </a>
                      ) : (
                        pf.accession
                      )}
                    </TableCell>
                    <TableCell className="text-[10px] px-1.5 py-1">{pf.description}</TableCell>
                    <TableCell className="text-[10px] px-1.5 py-1">{pf.go_slim || "—"}</TableCell>
                    <TableCell className="text-[10px] px-1.5 py-1 font-mono">{pf.envelope_start}</TableCell>
                    <TableCell className="text-[10px] px-1.5 py-1 font-mono">{pf.envelope_end}</TableCell>
                    <TableCell className="text-[10px] px-1.5 py-1 font-mono">{pf.e_value ?? "—"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </div>

      {/* Protein sequence */}
      <div>
        <div className="flex items-center justify-between mb-1">
          <h6 className="font-semibold">Protein Sequence</h6>
          {cds.sequence && (
            <Button
              variant="outline"
              size="sm"
              className="h-5 gap-1 px-2 text-[10px]"
              onClick={handleCopy}
            >
              {copied ? (
                <>
                  <Check className="h-2.5 w-2.5" /> Copied
                </>
              ) : (
                <>
                  <Copy className="h-2.5 w-2.5" /> Copy
                </>
              )}
            </Button>
          )}
        </div>
        {cds.sequence ? (
          <pre className="max-h-48 overflow-y-auto rounded-md bg-emerald-50 p-2 font-mono text-[10px] leading-relaxed break-all whitespace-pre-wrap">
            {cds.sequence}
          </pre>
        ) : (
          <p className="text-muted-foreground italic">Sequence not available</p>
        )}
      </div>
    </div>
  );
}
