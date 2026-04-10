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
      text: `<strong>Mode Tabs</strong>
<p>Three modes, one platform. <b>Explore Assemblies</b> browses the full catalogue. <b>Search BGCs</b> queries by domain, sequence, or structure. <b>Evaluate Asset</b> benchmarks a single assembly or BGC against the database. Your <b>filters</b> and <b>shortlists</b> carry over when you switch.</p>`,
      attachTo: { element: '[data-tour="mode-tabs"]', on: "bottom" },
      beforeShowPromise: () => switchMode("explore") as Promise<unknown>,
      buttons: [
        { text: "Skip tour", action: function (this: Shepherd.Tour) { this.cancel(); }, secondary: true },
        { text: "Next", action: function (this: Shepherd.Tour) { this.next(); } },
      ],
    },
    {
      id: "sidebar-filters",
      text: `<strong>Sidebar Filters & Query</strong>
<p>Narrow your results here. Use <b>filters</b> to restrict by taxonomy, BGC class, chemical class, biome, or assembly type. In Search mode, a <b>Query tab</b> lets you build advanced searches by protein domain, sequence similarity, or chemical structure. Set as many or as few as you need \u2014 then hit Run Query.</p>`,
      attachTo: { element: '[data-tour="sidebar"]', on: "right" },
      buttons: [
        { text: "Back", action: function (this: Shepherd.Tour) { this.back(); }, secondary: true },
        { text: "Next", action: function (this: Shepherd.Tour) { this.next(); } },
      ],
    },
    {
      id: "run-query",
      text: `<strong>Run Query</strong>
<p>Nothing loads until you press <b>Run Query</b>. Change any filter or query criterion, then click here to refresh your results. Active criteria appear as <b>status indicators</b> in the sidebar so you always know what\u2019s applied.</p>`,
      attachTo: { element: '[data-tour="run-query"]', on: "bottom" },
      buttons: [
        { text: "Back", action: function (this: Shepherd.Tour) { this.back(); }, secondary: true },
        { text: "Next", action: function (this: Shepherd.Tour) { this.next(); } },
      ],
    },
    {
      id: "assembly-triad",
      text: `<strong>Assembly Panels</strong>
<p>Assembly results live here in three linked panels. The <b>Roster</b> lists every matching assembly with its scores. The <b>Space Map</b> plots them so you can spot outliers visually. The <b>Stats</b> panel summarises the result set. Click any row to open a <b>detail panel</b> below; right-click for more actions. In <b>Explore Assemblies</b> mode, these panels show your query results. In <b>Search BGCs</b> mode, they show assemblies from your shortlist.</p>`,
      attachTo: { element: '[data-tour="assembly-triad"]', on: "left" },
      buttons: [
        { text: "Back", action: function (this: Shepherd.Tour) { this.back(); }, secondary: true },
        { text: "Next", action: function (this: Shepherd.Tour) { this.next(); } },
      ],
    },
    {
      id: "bgc-triad",
      text: `<strong>BGC Panels</strong>
<p>Same three panels \u2014 <b>Roster</b>, <b>Space Map</b>, and <b>Stats</b> \u2014 now scoped to BGCs. Click any row to open a <b>detail panel</b> below; right-click for more actions. In <b>Search BGCs</b> mode, these panels show your query results. In <b>Explore Assemblies</b> mode, they show BGCs from your shortlisted assemblies.</p>`,
      attachTo: { element: '[data-tour="bgc-triad"]', on: "left" },
      buttons: [
        { text: "Back", action: function (this: Shepherd.Tour) { this.back(); }, secondary: true },
        { text: "Next", action: function (this: Shepherd.Tour) { this.next(); } },
      ],
    },
    {
      id: "shortlist-trays",
      text: `<strong>Shortlist Trays</strong>
<p>Pin assemblies and BGCs by <b>right-clicking</b> rows in any roster \u2014 up to <b>20 each</b>. The <b>Assembly Shortlist</b> exports as <b>CSV</b> for purchase decisions. The <b>BGC Shortlist</b> exports as <b>GenBank (.gbk)</b> files ready for cloning or synthesis. Both persist across sessions and mode switches. These are your main findings.</p>`,
      attachTo: { element: '[data-tour="shortlist-trays"]', on: "right" },
      beforeShowPromise: scrollSidebarTo('[data-tour="shortlist-trays"]'),
      buttons: [
        { text: "Back", action: function (this: Shepherd.Tour) { this.back(); }, secondary: true },
        { text: "Finish", action: function (this: Shepherd.Tour) { this.complete(); } },
      ],
    },
  ];
}
