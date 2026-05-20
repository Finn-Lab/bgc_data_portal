import { useOnboardingStore } from "@/stores/onboarding-store";
import { HelpCircle, BookOpen } from "lucide-react";

export function Header() {
  const openWelcome = useOnboardingStore((s) => s.openWelcome);

  return (
    <header className="border-b px-6 py-2">
      <div className="flex items-center gap-4">
        <h2 className="vf-text-heading--5 shrink-0" style={{ margin: 0 }}>
          Discovery Platform
        </h2>
        <a
          href="/docs/"
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex shrink-0 items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
        >
          <BookOpen className="h-3.5 w-3.5" />
          Docs
        </a>
        <button
          type="button"
          className="inline-flex shrink-0 items-center justify-center rounded-full p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground"
          onClick={openWelcome}
          aria-label="Help and tour"
          data-tour="help-button"
        >
          <HelpCircle className="h-4 w-4" />
        </button>
      </div>
    </header>
  );
}
