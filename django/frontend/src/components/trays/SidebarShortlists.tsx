import { AssemblySidebarShortlist } from "./AssemblySidebarShortlist";
import { BgcSidebarShortlist } from "./BgcSidebarShortlist";

export function SidebarShortlists() {
  return (
    <div className="rounded-md bg-explore/5 p-3 space-y-3" data-tour="shortlist-trays">
      <div data-tour="assembly-shortlist">
        <AssemblySidebarShortlist />
      </div>
      <div data-tour="bgc-shortlist">
        <BgcSidebarShortlist />
      </div>
    </div>
  );
}
