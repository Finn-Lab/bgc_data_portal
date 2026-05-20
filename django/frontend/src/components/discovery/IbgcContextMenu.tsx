import { Fragment } from "react";
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuTrigger,
} from "@/components/ui/context-menu";
import { useIbgcActions } from "@/hooks/use-ibgc-actions";

interface Props {
  ibgcId: number;
  ibgcLabel: string;
  /** True when the iBGC is a projected partial — gates the find-similar
   *  action because the backend only accepts primary seeds. */
  isPartial?: boolean;
  /** True when the iBGC is sourced from an uploaded asset (negative id) —
   *  hides find-similar and sequence-search per the locked scope. */
  isAsset?: boolean;
  children: React.ReactNode;
}

/**
 * Shared right-click menu for the Results card across all three tabs
 * (roster row, variables-map point, UMAP point). The action set is owned by
 * the ``useIbgcActions`` hook; this component is just the right-click shell.
 */
export function IbgcContextMenu({
  ibgcId,
  ibgcLabel,
  isPartial,
  isAsset,
  children,
}: Props) {
  const items = useIbgcActions(ibgcId, ibgcLabel, { isPartial, isAsset });

  return (
    <ContextMenu>
      <ContextMenuTrigger asChild>{children}</ContextMenuTrigger>
      <ContextMenuContent>
        {items.map((item) => {
          const Icon = item.icon;
          return (
            <Fragment key={item.key}>
              {item.separatorBefore && <ContextMenuSeparator />}
              <ContextMenuItem
                onClick={item.onClick}
                disabled={item.disabled}
              >
                <Icon className="mr-2 h-4 w-4" />
                <span className="flex-1">{item.label}</span>
                {item.disabledHint && (
                  <span className="ml-2 text-[10px] text-muted-foreground">
                    {item.disabledHint}
                  </span>
                )}
              </ContextMenuItem>
            </Fragment>
          );
        })}
      </ContextMenuContent>
    </ContextMenu>
  );
}
