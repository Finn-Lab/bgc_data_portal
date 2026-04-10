import { create } from "zustand";

const STORAGE_KEY = "bgc-discovery-welcome-seen";

function shouldShowWelcome(): boolean {
  const params = new URLSearchParams(window.location.search);
  if (params.get("tour") === "welcome") {
    params.delete("tour");
    const qs = params.toString();
    const newUrl =
      window.location.pathname + (qs ? `?${qs}` : "") + window.location.hash;
    window.history.replaceState({}, "", newUrl);
    return true;
  }
  return localStorage.getItem(STORAGE_KEY) !== "true";
}

interface OnboardingState {
  showWelcome: boolean;
  tourActive: boolean;
  openWelcome: () => void;
  dismissWelcome: () => void;
  startTour: () => void;
  endTour: () => void;
}

export const useOnboardingStore = create<OnboardingState>((set) => ({
  showWelcome: shouldShowWelcome(),
  tourActive: false,

  openWelcome: () => set({ showWelcome: true }),

  dismissWelcome: () => {
    localStorage.setItem(STORAGE_KEY, "true");
    set({ showWelcome: false });
  },

  startTour: () => {
    localStorage.setItem(STORAGE_KEY, "true");
    set({ showWelcome: false, tourActive: true });
  },

  endTour: () => set({ tourActive: false }),
}));
