import { Fragment } from "react";
import { MoreVertical } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useIbgcActions } from "@/hooks/use-ibgc-actions";

interface Props {
  ibgcId: number;
  ibgcLabel: string;
  /** Forwarded to ``useIbgcActions`` so the menu disables "Set as reference"
   *  when the card it lives on is already the reference. */
  variant?: "reference" | "compare";
  /** True when the iBGC is a projected partial — gates the find-similar
   *  action because the backend only accepts primary seeds. */
  isPartial?: boolean;
  /** True when the iBGC is sourced from an uploaded asset (negative id) —
   *  hides find-similar per the locked scope. */
  isAsset?: boolean;
}

/** Kebab dropdown surfacing the same actions as the iBGC roster right-click
 *  menu, sized for the dense ``CompactIbgcDetail`` header. */
export function IbgcActionsMenu({
  ibgcId,
  ibgcLabel,
  variant,
  isPartial,
  isAsset,
}: Props) {
  const items = useIbgcActions(ibgcId, ibgcLabel, { variant, isPartial, isAsset });

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7 shrink-0"
          aria-label="iBGC actions"
        >
          <MoreVertical className="h-4 w-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        {items.map((item) => {
          const Icon = item.icon;
          return (
            <Fragment key={item.key}>
              {item.separatorBefore && <DropdownMenuSeparator />}
              <DropdownMenuItem
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
              </DropdownMenuItem>
            </Fragment>
          );
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
