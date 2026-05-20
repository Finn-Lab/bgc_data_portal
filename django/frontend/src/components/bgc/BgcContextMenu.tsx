import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuTrigger,
} from "@/components/ui/context-menu";
import { useShortlistStore } from "@/stores/shortlist-store";
import { Plus, Replace } from "lucide-react";
import { toast } from "sonner";
import type { ReactNode } from "react";

interface BgcContextMenuProps {
  children: ReactNode;
  bgcId: number;
  label: string;
}

/**
 * Legacy `/legacy/*` context menu. "Find similar BGCs" (embedding) and
 * "Evaluate BGC" (Assessment) were retired in v2 (P1.4b). The new dashboard
 * uses ``components/discovery/IbgcContextMenu`` instead.
 */
export function BgcContextMenu({ children, bgcId, label }: BgcContextMenuProps) {
  const addBgc = useShortlistStore((s) => s.addBgc);
  const replaceBgcs = useShortlistStore((s) => s.replaceBgcs);

  return (
    <ContextMenu>
      <ContextMenuTrigger asChild>{children}</ContextMenuTrigger>
      <ContextMenuContent>
        <ContextMenuItem
          onClick={() => {
            const ok = addBgc({ id: bgcId, label });
            if (!ok) toast.error("Shortlist full");
          }}
        >
          <Plus className="mr-2 h-4 w-4" />
          Add to BGC shortlist
        </ContextMenuItem>
        <ContextMenuItem onClick={() => replaceBgcs({ id: bgcId, label })}>
          <Replace className="mr-2 h-4 w-4" />
          Clear shortlist and add
        </ContextMenuItem>
      </ContextMenuContent>
    </ContextMenu>
  );
}
