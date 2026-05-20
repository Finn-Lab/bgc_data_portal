import { Button } from "@/components/ui/button";
import { FileArchive, FileJson, FileSpreadsheet } from "lucide-react";

interface Props {
  /** Stable identifier for the report (used in download filename). */
  token: string;
  /** Optional human label, e.g. number of iBGCs. */
  label?: string;
}

const basePath =
  (typeof document !== "undefined" &&
    document.querySelector('meta[name="base-path"]')?.getAttribute("content")) ||
  "";
const REPORT_API = `${basePath}/api/dashboard/report`;

/**
 * Server-side export buttons for the Shortlist Report: analyst JSON,
 * GBK zip, and assembly TSV. Each link points at a token-scoped Django
 * endpoint that streams the file with ``Content-Disposition: attachment``.
 */
export function ReportDownloadButtons({ token }: Props) {
  return (
    <div className="flex flex-wrap items-center gap-2" data-print-hide>
      <Button variant="outline" size="sm" asChild>
        <a href={`${REPORT_API}/${token}/export.json`} download>
          <FileJson className="mr-1 h-4 w-4" />
          JSON
        </a>
      </Button>
      <Button variant="outline" size="sm" asChild>
        <a href={`${REPORT_API}/${token}/export.gbk.zip`} download>
          <FileArchive className="mr-1 h-4 w-4" />
          GBKs (zip)
        </a>
      </Button>
      <Button variant="outline" size="sm" asChild>
        <a href={`${REPORT_API}/${token}/export.assemblies.tsv`} download>
          <FileSpreadsheet className="mr-1 h-4 w-4" />
          Assemblies (TSV)
        </a>
      </Button>
    </div>
  );
}
