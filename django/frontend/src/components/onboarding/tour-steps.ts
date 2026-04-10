import type Shepherd from "shepherd.js";
import { useModeStore } from "@/stores/mode-store";

function waitForElement(
  selector: string,
  timeout = 2000
): Promise<Element | null> {
  return new Promise((resolve) => {
    const el = document.querySelector(selector);
    if (el) return resolve(el);
    const observer = new MutationObserver(() => {
      const found = document.querySelector(selector);
      if (found) {
        observer.disconnect();
        resolve(found);
      }
    });
    observer.observe(document.body, { childList: true, subtree: true });
    setTimeout(() => {
      observer.disconnect();
      resolve(null);
    }, timeout);
  });
}

function switchMode(mode: "explore" | "query" | "assess") {
  useModeStore.getState().setMode(mode);
  return waitForElement(`[data-tour]`, 500);
}

function scrollSidebarTo(selector: string): () => Promise<unknown> {
  return () =>
    new Promise<void>((resolve) => {
      const el = document.querySelector(selector);
      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "center" });
        setTimeout(resolve, 250);
      } else {
        resolve();
      }
    });
}

type StepDef = Shepherd.Step.StepOptions;

export function getTourSteps(): StepDef[] {
  return [
    {
      id: "mode-tabs",
      text: "<strong>Mode tabs</strong><p>Switch between Explore Assemblies, Search BGCs, and Evaluate Asset. Your filters and shortlists are preserved when you switch.</p>",
      attachTo: { element: '[data-tour="mode-tabs"]', on: "bottom" },
      beforeShowPromise: () => switchMode("explore") as Promise<unknown>,
      buttons: [
        { text: "Skip tour", action: function (this: Shepherd.Tour) { this.cancel(); }, secondary: true },
        { text: "Next", action: function (this: Shepherd.Tour) { this.next(); } },
      ],
    },
    {
      id: "sidebar-filters",
      text: "<strong>Filters & Query</strong><p>Use the sidebar to set filters (taxonomy, BGC class, ChemOnt, biome, type strain) or switch to the Query tab to build advanced searches by protein domain, sequence similarity, or chemical structure.</p>",
      attachTo: { element: '[data-tour="sidebar"]', on: "right" },
      buttons: [
        { text: "Back", action: function (this: Shepherd.Tour) { this.back(); }, secondary: true },
        { text: "Next", action: function (this: Shepherd.Tour) { this.next(); } },
      ],
    },
    {
      id: "run-query",
      text: "<strong>Run Query</strong><p>Once your filters are set, click Run Query to load matching assemblies and their BGCs into the panels below.</p>",
      attachTo: { element: '[data-tour="run-query"]', on: "bottom" },
      buttons: [
        { text: "Back", action: function (this: Shepherd.Tour) { this.back(); }, secondary: true },
        { text: "Next", action: function (this: Shepherd.Tour) { this.next(); } },
      ],
    },
    {
      id: "assembly-triad",
      text: "<strong>Assembly Triad</strong><p>The Roster table, Space Map scatter plot, and Stats panel for assemblies. Click any row or point to select an assembly and see its BGCs below.</p>",
      attachTo: { element: '[data-tour="assembly-triad"]', on: "left" },
      buttons: [
        { text: "Back", action: function (this: Shepherd.Tour) { this.back(); }, secondary: true },
        { text: "Next", action: function (this: Shepherd.Tour) { this.next(); } },
      ],
    },
    {
      id: "bgc-triad",
      text: "<strong>BGC Triad</strong><p>All BGCs from the selected assembly. Sort by Novelty or Domain Novelty. Click a row for the full detail panel with domain architecture and chemical annotations.</p>",
      attachTo: { element: '[data-tour="bgc-triad"]', on: "left" },
      buttons: [
        { text: "Back", action: function (this: Shepherd.Tour) { this.back(); }, secondary: true },
        { text: "Next", action: function (this: Shepherd.Tour) { this.next(); } },
      ],
    },
    {
      id: "shortlist-trays",
      text: "<strong>Shortlist Trays</strong><p>Pin up to 20 assemblies (export as CSV) and 20 BGCs (export as GenBank) as you explore. Shortlists persist across mode switches.</p>",
      attachTo: { element: '[data-tour="shortlist-trays"]', on: "right" },
      beforeShowPromise: scrollSidebarTo('[data-tour="shortlist-trays"]'),
      buttons: [
        { text: "Back", action: function (this: Shepherd.Tour) { this.back(); }, secondary: true },
        { text: "Finish", action: function (this: Shepherd.Tour) { this.complete(); } },
      ],
    },
  ];
}
