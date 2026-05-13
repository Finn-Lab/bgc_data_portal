import { ReactNode } from "react";
import { Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { DomainQueryBuilder } from "./DomainQueryBuilder";
import { SequenceSearch } from "./SequenceSearch";
import { ChemicalStructureSearch } from "./ChemicalStructureSearch";
import { useQueryStore } from "@/stores/query-store";
import { cn } from "@/lib/utils";

interface Props {
  trigger?: ReactNode;
}

export function AdvancedQuerySheet({ trigger }: Props) {
  const domainCount = useQueryStore((s) => s.domainConditions.length);
  const smiles = useQueryStore((s) => s.smilesQuery);
  const sequence = useQueryStore((s) => s.sequenceQuery);
  const activeBuilders =
    (domainCount > 0 ? 1 : 0) + (smiles ? 1 : 0) + (sequence ? 1 : 0);

  return (
    <Sheet>
      <SheetTrigger asChild>
        {trigger ?? (
          <Button
            variant="outline"
            size="sm"
            className={cn(
              "h-8 gap-1.5 rounded-full px-3 text-xs font-medium",
              activeBuilders > 0 && "border-primary/60 bg-primary/5",
            )}
          >
            <Sparkles className="h-3.5 w-3.5" />
            Advanced query
            {activeBuilders > 0 && (
              <Badge
                variant="secondary"
                className="ml-0.5 h-4 min-w-4 rounded-full px-1 text-[10px]"
              >
                {activeBuilders}
              </Badge>
            )}
          </Button>
        )}
      </SheetTrigger>
      <SheetContent
        side="right"
        className="flex w-full flex-col gap-0 overflow-hidden p-0 sm:max-w-lg"
      >
        <SheetHeader className="border-b p-4">
          <SheetTitle>Advanced query</SheetTitle>
          <SheetDescription>
            Compose domain, sequence and chemical-structure searches.
            Results are intersected with the filter strip.
          </SheetDescription>
        </SheetHeader>
        <div className="flex-1 space-y-6 overflow-y-auto p-4">
          <DomainQueryBuilder />
          <Separator />
          <SequenceSearch />
          <Separator />
          <ChemicalStructureSearch />
        </div>
      </SheetContent>
    </Sheet>
  );
}
