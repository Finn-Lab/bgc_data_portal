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
import { Compass, Search, Pin } from "lucide-react";

interface Slide {
  icon: typeof Compass;
  headline: string;
  body: ReactNode;
}

const slides: Slide[] = [
  {
    icon: Compass,
    headline: "Find promising organisms for your bioprospecting effort, faster.",
    body: "The Discovery Platform helps you search thousands of sequenced assemblies — from isolated bacteria to environmental metagenomes — for integrated BGCs (iBGCs) worth testing, ranked by novelty and diversity.",
  },
  {
    icon: Search,
    headline: "Search BGCs.",
    body: "Filter and query the catalogue by protein domain, sequence similarity, chemical structure, or taxonomy. Build a hypothesis, run a query, and refine your shortlist.",
  },
  {
    icon: Pin,
    headline: "Pin iBGCs as you explore. Export when ready.",
    body: "Use the iBGC Shortlist (up to 20) to collect specific clusters — export as GenBank (.gbk) files ready for downstream workflows.",
  },
];

export function WelcomeModal() {
  const showWelcome = useOnboardingStore((s) => s.showWelcome);
  const dismissWelcome = useOnboardingStore((s) => s.dismissWelcome);
  const startTour = useOnboardingStore((s) => s.startTour);
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
