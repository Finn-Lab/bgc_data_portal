import type Shepherd from "shepherd.js";

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
      id: "sidebar-filters",
      text: `<strong>Sidebar Filters & Query</strong>
<p>Narrow your results here. Use <b>filters</b> to restrict by taxonomy, BGC class, chemical class, biome, or assembly type. A <b>Query tab</b> lets you build advanced searches by protein domain, sequence similarity, or chemical structure. Set as many or as few as you need — then hit Run Query.</p>`,
      attachTo: { element: '[data-tour="sidebar"]', on: "right" },
      buttons: [
        { text: "Skip tour", action: function (this: Shepherd.Tour) { this.cancel(); }, secondary: true },
        { text: "Next", action: function (this: Shepherd.Tour) { this.next(); } },
      ],
    },
    {
      id: "run-query",
      text: `<strong>Run Query</strong>
<p>Nothing loads until you press <b>Run Query</b>. Change any filter or query criterion, then click here to refresh your results. Active criteria appear as <b>status indicators</b> in the sidebar so you always know what’s applied.</p>`,
      attachTo: { element: '[data-tour="run-query"]', on: "bottom" },
      buttons: [
        { text: "Back", action: function (this: Shepherd.Tour) { this.back(); }, secondary: true },
        { text: "Next", action: function (this: Shepherd.Tour) { this.next(); } },
      ],
    },
    {
      id: "shortlist-trays",
      text: `<strong>Shortlist Trays</strong>
<p>Pin iBGCs by <b>right-clicking</b> rows in any roster — up to <b>20</b>. The <b>iBGC Shortlist</b> exports as <b>GenBank (.gbk)</b> files ready for cloning or synthesis. Persists across sessions. This is your main finding.</p>`,
      attachTo: { element: '[data-tour="shortlist-trays"]', on: "right" },
      beforeShowPromise: scrollSidebarTo('[data-tour="shortlist-trays"]'),
      buttons: [
        { text: "Back", action: function (this: Shepherd.Tour) { this.back(); }, secondary: true },
        { text: "Finish", action: function (this: Shepherd.Tour) { this.complete(); } },
      ],
    },
  ];
}
