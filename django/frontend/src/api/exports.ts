import { apiPostBlob, downloadBlob, apiGet } from "./client";
import type { ShortlistExportRequest } from "./types";
import type { GenomeStatsParams } from "./genomes";
import type { BgcStatsParams } from "./bgcs";

export async function exportGenomeShortlist(ids: number[]) {
  const body: ShortlistExportRequest = { ids };
  const blob = await apiPostBlob("/shortlist/genome/export/", body);
  downloadBlob(blob, "genome_shortlist.csv");
}

export async function exportBgcShortlist(ids: number[]) {
  const body: ShortlistExportRequest = { ids };
  const blob = await apiPostBlob("/shortlist/bgc/export/", body);
  downloadBlob(blob, "bgc_shortlist.gbk");
}

export async function exportGenomeStats(
  params: GenomeStatsParams,
  format: "json" | "tsv" = "json"
) {
  const data = await apiGet<string>("/stats/genomes/export/", {
    ...params,
    format,
  } as Record<string, string | number | boolean | undefined>);
  const blob = new Blob([typeof data === "string" ? data : JSON.stringify(data)], {
    type: format === "tsv" ? "text/tab-separated-values" : "application/json",
  });
  downloadBlob(blob, `genome_stats.${format}`);
}

export async function exportBgcStats(
  params: BgcStatsParams,
  format: "json" | "tsv" = "json"
) {
  const data = await apiGet<string>("/stats/bgcs/export/", {
    ...params,
    format,
  } as Record<string, string | number | boolean | undefined>);
  const blob = new Blob([typeof data === "string" ? data : JSON.stringify(data)], {
    type: format === "tsv" ? "text/tab-separated-values" : "application/json",
  });
  downloadBlob(blob, `bgc_stats.${format}`);
}
