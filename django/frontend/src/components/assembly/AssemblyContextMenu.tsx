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

interface AssemblyContextMenuProps {
  children: ReactNode;
  assemblyId: number;
  label: string;
}

/**
 * Legacy `/legacy/*` context menu. "Evaluate Assembly" was retired in v2
 * (P1.4b) along with the Assessment service.
 */
export function AssemblyContextMenu({
  children,
  assemblyId,
  label,
}: AssemblyContextMenuProps) {
  const addAssembly = useShortlistStore((s) => s.addAssembly);
  const replaceAssemblies = useShortlistStore((s) => s.replaceAssemblies);

  return (
    <ContextMenu>
      <ContextMenuTrigger asChild>{children}</ContextMenuTrigger>
      <ContextMenuContent>
        <ContextMenuItem
          onClick={() => {
            const ok = addAssembly({ id: assemblyId, label });
            if (!ok) toast.error("Shortlist full");
          }}
        >
          <Plus className="mr-2 h-4 w-4" />
          Add to shortlist
        </ContextMenuItem>
        <ContextMenuItem
          onClick={() => replaceAssemblies({ id: assemblyId, label })}
        >
          <Replace className="mr-2 h-4 w-4" />
          Clear shortlist and add
        </ContextMenuItem>
      </ContextMenuContent>
    </ContextMenu>
  );
}
