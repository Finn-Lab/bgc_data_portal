import { useState, type ReactNode } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { useOnboardingStore } from "@/stores/onboarding-store";
import { useModeStore } from "@/stores/mode-store";
import { Compass, Layers, Search, FlaskConical, Pin } from "lucide-react";

interface Slide {
  icon: typeof Compass;
  headline: string;
  body: ReactNode;
}

const slides: Slide[] = [
  {
    icon: Compass,
    headline: "Find promising organisms for your bioprospecting effort, faster.",
    body: "The Discovery Platform helps you explore thousands of sequenced assemblies — from isolated bacteria to environmental metagenomes — to identify samples or type strains worth testing, based on the novelty and diversity of their biosynthetic gene clusters (BGCs).",
  },
  {
    icon: Layers,
    headline: "Three modes, one platform.",
    body: (
      <ul className="mt-2 space-y-2 text-left text-sm text-muted-foreground">
        <li><strong className="text-foreground">Explore Assemblies</strong> — Browse and filter the full assembly catalogue. Best when you have no prior hypothesis.</li>
        <li><strong className="text-foreground">Search BGCs</strong> — Search by protein domain, sequence similarity, or chemical structure. Best when tracking a specific compound or enzymatic family.</li>
        <li><strong className="text-foreground">Evaluate Asset</strong> — Submit your own assembly or BGC and get a structured comparison against the full database.</li>
      </ul>
    ),
  },
  {
    icon: Search,
    headline: "Two levels, always in view.",
    body: (
      <ul className="mt-2 space-y-2 text-left text-sm text-muted-foreground">
        <li><strong className="text-foreground">Assemblies</strong> — The organisms or environmental samples. Filter, sort, and shortlist them for screening decisions.</li>
        <li><strong className="text-foreground">BGCs</strong> — The gene clusters that make natural products. Selecting an assembly populates its BGC panel automatically.</li>
        <li><strong className="text-foreground">Linked panels</strong> — Shortlisting multiple assemblies merges their BGCs into one view.</li>
      </ul>
    ),
  },
  {
    icon: Pin,
    headline: "Pin assemblies and BGCs as you explore. Export when ready.",
    body: "Use the Assembly Shortlist (up to 20) for screening decisions — export as CSV. Use the BGC Shortlist (up to 20) for specific clusters — export as GenBank (.gbk) files ready for downstream workflows.",
  },
  {
    icon: FlaskConical,
    headline: "Where would you like to begin?",
    body: null,
  },
];

export function WelcomeModal() {
  const showWelcome = useOnboardingStore((s) => s.showWelcome);
  const dismissWelcome = useOnboardingStore((s) => s.dismissWelcome);
  const startTour = useOnboardingStore((s) => s.startTour);
  const setMode = useModeStore((s) => s.setMode);
  const [step, setStep] = useState(0);
  const slide = slides[step]!;
  const Icon = slide.icon;
  const isLast = step === slides.length - 1;

  function handleOpenChange(open: boolean) {
    if (!open) dismissWelcome();
  }

  return (
    <Dialog open={showWelcome} onOpenChange={handleOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader className="items-center text-center">
          <div className="mb-3 flex h-16 w-16 items-center justify-center rounded-full bg-primary/10">
            <Icon className="h-8 w-8 text-primary" />
          </div>
          <DialogTitle className="text-xl">{slide.headline}</DialogTitle>
          {slide.body && (
            typeof slide.body === "string" ? (
              <p className="text-sm leading-relaxed text-muted-foreground">{slide.body}</p>
            ) : (
              slide.body
            )
          )}
        </DialogHeader>

        {/* Final slide: mode buttons */}
        {isLast && (
          <div className="flex flex-col gap-2 pt-2">
            <Button
              variant="outline"
              className="w-full justify-start gap-2"
              onClick={() => {
                setMode("explore");
                dismissWelcome();
              }}
            >
              <Compass className="h-4 w-4" />
              Explore Assemblies
            </Button>
            <Button
              variant="outline"
              className="w-full justify-start gap-2"
              onClick={() => {
                setMode("query");
                dismissWelcome();
              }}
            >
              <Search className="h-4 w-4" />
              Search BGCs
            </Button>
            <Button
              variant="outline"
              className="w-full justify-start gap-2"
              onClick={() => {
                setMode("assess");
                dismissWelcome();
              }}
            >
              <FlaskConical className="h-4 w-4" />
              Evaluate Asset
            </Button>
          </div>
        )}

        {/* Dot indicators */}
        <div className="flex justify-center gap-1.5 py-1">
          {slides.map((_, i) => (
            <button
              key={i}
              className={`h-1.5 rounded-full transition-all ${
                i === step
                  ? "w-4 bg-primary"
                  : "w-1.5 bg-muted-foreground/30"
              }`}
              onClick={() => setStep(i)}
              aria-label={`Go to slide ${i + 1}`}
            />
          ))}
        </div>

        <DialogFooter className="gap-2 sm:justify-between">
          {isLast ? (
            <>
              <Button variant="outline" onClick={() => dismissWelcome()}>
                Start exploring
              </Button>
              <Button onClick={() => startTour()}>
                Take interactive tour
              </Button>
            </>
          ) : (
            <>
              <Button variant="ghost" size="sm" onClick={() => dismissWelcome()}>
                Skip
              </Button>
              <div className="flex gap-2">
                {step > 0 && (
                  <Button variant="outline" size="sm" onClick={() => setStep(step - 1)}>
                    Back
                  </Button>
                )}
                <Button size="sm" onClick={() => setStep(step + 1)}>
                  Next
                </Button>
              </div>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
