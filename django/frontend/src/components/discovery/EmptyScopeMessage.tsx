import { Filter } from "lucide-react";

/**
 * Empty-state placeholder shown when the dashboard has no active scope —
 * i.e. no filter chip is set and no Run Query result is loaded.
 *
 * The roster, UMAP map and Variables map all render this in lieu of
 * firing an unbounded fetch on landing, since at multi-million-iBGC scale
 * "show everything" is not a meaningful default.
 */
export function EmptyScopeMessage({ surface }: { surface: string }) {
  return (
    <div className="flex h-full flex-1 items-center justify-center p-6 text-center text-sm text-muted-foreground">
      <div className="max-w-xs">
        <Filter className="mx-auto mb-2 h-6 w-6 opacity-50" />
        <p>
          Pick a filter chip above, or run a query, to populate the {surface}.
        </p>
      </div>
    </div>
  );
}
