import { ReactNode, useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

interface PanelContainerProps {
  title: string;
  children: ReactNode;
  className?: string;
  collapsible?: boolean;
  defaultCollapsed?: boolean;
  actions?: ReactNode;
}

export function PanelContainer({
  title,
  children,
  className,
  collapsible = false,
  defaultCollapsed = false,
  actions,
}: PanelContainerProps) {
  const [collapsed, setCollapsed] = useState(defaultCollapsed);

  return (
    <article
      className={cn(
        "vf-card vf-card--brand vf-card--bordered flex flex-col",
        className
      )}
    >
      <div className="vf-card__content | vf-stack vf-stack--200 flex-1 flex flex-col min-h-0">
        <div className="flex items-center justify-between">
          <h3 className="vf-card__heading" style={{ margin: 0 }}>{title}</h3>
          <div className="flex items-center gap-2">
            {actions}
            {collapsible && (
              <Button
                variant="ghost"
                size="sm"
                className="h-6 w-6 p-0"
                onClick={() => setCollapsed(!collapsed)}
              >
                {collapsed ? (
                  <ChevronDown className="h-4 w-4" />
                ) : (
                  <ChevronUp className="h-4 w-4" />
                )}
              </Button>
            )}
          </div>
        </div>
        {!collapsed && <div className="flex-1 overflow-auto">{children}</div>}
      </div>
    </article>
  );
}
