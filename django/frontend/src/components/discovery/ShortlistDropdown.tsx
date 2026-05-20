import { useState } from "react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ListChecks, FileBarChart, X, Trash2, Loader2 } from "lucide-react";
import { useShortlistStore } from "@/stores/shortlist-store";
import { useDiscoveryStore } from "@/stores/discovery-store";
import { useReportSnapshot } from "@/hooks/use-report";
import { buildAppUrl } from "@/lib/router-base";
import { toast } from "sonner";

/**
 * Header-bar shortlist menu (v2). Replaces the right-rail sidebar
 * shortlist tray.
 *
 *   - Shows the BGC/iBGC count as a badge on the trigger.
 *   - "Generate Report" mints a snapshot and opens ``/report?token=…`` in
 *     a new tab. The same shortlist always resolves to the same token so
 *     re-runs are cheap.
 *   - Items can be individually removed; "Clear all" empties the list.
 */
export function ShortlistDropdown() {
  const [open, setOpen] = useState(false);
  const bgcs = useShortlistStore((s) => s.bgcs);
  const removeBgc = useShortlistStore((s) => s.removeBgc);
  const clearBgcs = useShortlistStore((s) => s.clearBgcs);
  const assetToken = useDiscoveryStore((s) => s.assetToken);
  const snapshot = useReportSnapshot();

  const onGenerate = () => {
    if (bgcs.length === 0) {
      toast.info("Shortlist is empty — add iBGCs via right-click");
      return;
    }
    const ibgcIds = bgcs.map((b) => b.id);
    const hasAssetIds = ibgcIds.some((id) => id < 0);
    if (hasAssetIds && !assetToken) {
      toast.error(
        "Asset upload no longer in cache — re-upload to include those iBGCs in a report.",
      );
      return;
    }
    snapshot.mutate(
      { ibgcIds, assetToken },
      {
        onSuccess: (resp) => {
          // window.open bypasses React Router, so we need the absolute
          // URL including the basePath (/dashboard/...) — buildAppUrl
          // mirrors BrowserRouter's basename so the new tab loads the SPA
          // instead of Django's 404.
          window.open(
            buildAppUrl("/report", { token: resp.token }),
            "_blank",
          );
          setOpen(false);
        },
        onError: (err) => {
          toast.error(`Failed to mint report: ${(err as Error).message}`);
        },
      },
    );
  };

  return (
    <DropdownMenu open={open} onOpenChange={setOpen}>
      <DropdownMenuTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          className="gap-2"
          data-testid="shortlist-trigger"
        >
          <ListChecks className="h-4 w-4" />
          iBGC Shortlist
          <Badge
            variant="secondary"
            className="ml-1 px-1.5 font-mono"
            data-testid="shortlist-count"
          >
            {bgcs.length}
          </Badge>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="end"
        className="w-72"
        data-testid="shortlist-menu"
      >
        <div className="px-2 py-1.5">
          <Button
            size="sm"
            className="w-full gap-2"
            onClick={onGenerate}
            disabled={snapshot.isPending}
            data-testid="generate-report"
          >
            {snapshot.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <FileBarChart className="h-4 w-4" />
            )}
            Generate Report
          </Button>
        </div>
        <DropdownMenuSeparator />
        {bgcs.length === 0 && (
          <div className="px-3 py-3 text-xs text-muted-foreground">
            Shortlist is empty. Right-click an iBGC → "Add to shortlist".
          </div>
        )}
        {bgcs.length > 0 && (
          <>
            <div className="max-h-64 overflow-y-auto">
              {bgcs.map((b) => (
                <DropdownMenuItem
                  key={b.id}
                  className="flex items-center justify-between"
                  onSelect={(e) => e.preventDefault()}
                >
                  <span className="truncate font-mono text-xs">{b.label}</span>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-5 w-5"
                    onClick={(e) => {
                      e.stopPropagation();
                      removeBgc(b.id);
                    }}
                  >
                    <X className="h-3 w-3" />
                  </Button>
                </DropdownMenuItem>
              ))}
            </div>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              className="text-destructive"
              onSelect={(e) => {
                e.preventDefault();
                clearBgcs();
              }}
            >
              <Trash2 className="mr-2 h-4 w-4" />
              Clear all
            </DropdownMenuItem>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
