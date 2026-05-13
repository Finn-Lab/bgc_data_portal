import { ReactNode } from "react";
import { ChevronDown, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { cn } from "@/lib/utils";

interface FilterChipProps {
  label: string;
  count?: number;
  active?: boolean;
  onClear?: () => void;
  width?: "auto" | "sm" | "md" | "lg";
  align?: "start" | "center" | "end";
  children: ReactNode;
  dataTour?: string;
}

const WIDTH_MAP: Record<NonNullable<FilterChipProps["width"]>, string> = {
  auto: "w-72",
  sm: "w-64",
  md: "w-80",
  lg: "w-96",
};

export function FilterChip({
  label,
  count,
  active,
  onClear,
  width = "auto",
  align = "start",
  children,
  dataTour,
}: FilterChipProps) {
  const isActive = active ?? (count != null && count > 0);
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          data-tour={dataTour}
          className={cn(
            "h-8 gap-1.5 rounded-full px-3 text-xs font-medium",
            isActive && "border-primary/60 bg-primary/5 text-foreground",
          )}
        >
          <span>{label}</span>
          {count != null && count > 0 && (
            <Badge
              variant="secondary"
              className="ml-0.5 h-4 min-w-4 rounded-full px-1 text-[10px]"
            >
              {count}
            </Badge>
          )}
          {isActive && onClear ? (
            <button
              type="button"
              aria-label={`Clear ${label}`}
              className="ml-0.5 rounded-full p-0.5 hover:bg-muted"
              onClick={(e) => {
                e.preventDefault();
                e.stopPropagation();
                onClear();
              }}
            >
              <X className="h-3 w-3" />
            </button>
          ) : (
            <ChevronDown className="ml-0.5 h-3 w-3 opacity-60" />
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align={align}
        className={cn("p-3", WIDTH_MAP[width])}
        onOpenAutoFocus={(e) => e.preventDefault()}
      >
        {children}
      </PopoverContent>
    </Popover>
  );
}
