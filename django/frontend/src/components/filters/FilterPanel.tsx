import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import { SourceFilter } from "./SourceFilter";
import { DetectorFilter } from "./DetectorFilter";
import { TaxonomyFilter } from "./TaxonomyFilter";
import { BgcClassFilter } from "./BgcClassFilter";
import { ChemOntClassFilter } from "./ChemOntClassFilter";
import { AssemblyTypeFilter } from "./AssemblyTypeFilter";
import { DomainQueryBuilder } from "./DomainQueryBuilder";
import { SequenceSearch } from "./SequenceSearch";
import { ChemicalStructureSearch } from "./ChemicalStructureSearch";
import { useFilterStore } from "@/stores/filter-store";
import { useModeStore } from "@/stores/mode-store";
import { Label } from "@/components/ui/label";
import { Search, RotateCcw } from "lucide-react";
import { HelpTooltip } from "@/components/ui/help-tooltip";

export function FilterPanel() {
  const mode = useModeStore((s) => s.mode);
  const search = useFilterStore((s) => s.search);
  const setSearch = useFilterStore((s) => s.setSearch);
  const clearFilters = useFilterStore((s) => s.clearFilters);
  const biomeLineage = useFilterStore((s) => s.biomeLineage);
  const setBiomeLineage = useFilterStore((s) => s.setBiomeLineage);
  const bgcAccession = useFilterStore((s) => s.bgcAccession);
  const setBgcAccession = useFilterStore((s) => s.setBgcAccession);
  const assemblyAccession = useFilterStore((s) => s.assemblyAccession);
  const setAssemblyAccession = useFilterStore((s) => s.setAssemblyAccession);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="vf-section-header__heading" style={{ fontSize: "0.75rem", margin: 0, textTransform: "uppercase", letterSpacing: "0.05em" }}>
          Filters
        </h2>
        <Button
          variant="ghost"
          size="sm"
          className="h-7 gap-1 text-xs"
          onClick={clearFilters}
        >
          <RotateCcw className="h-3 w-3" />
          Reset
        </Button>
      </div>

      {/* Search */}
      <div className="relative">
        <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
        <Input
          placeholder="Search organisms..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="vf-form__input h-9 pl-9 text-sm"
        />
      </div>

      <SourceFilter />
      <DetectorFilter />
      <AssemblyTypeFilter />

      {mode === "query" ? (
        <Tabs defaultValue="filters">
          <TabsList className="w-full">
            <TabsTrigger value="filters" className="flex-1 text-xs">
              Filters
            </TabsTrigger>
            <TabsTrigger value="query" className="flex-1 text-xs">
              Query
            </TabsTrigger>
          </TabsList>
          <TabsContent value="filters" className="space-y-4">
            <TaxonomyFilter />
            <div className="space-y-1.5" data-tour="biome-lineage">
              <Label className="flex items-center gap-1 text-xs">Biome Lineage <HelpTooltip tooltipKey="biome_lineage" side="right" /></Label>
              <Input
                placeholder="e.g. root:Environmental:Soil"
                value={biomeLineage}
                onChange={(e) => setBiomeLineage(e.target.value)}
                className="vf-form__input h-8 text-xs"
              />
            </div>
            <BgcClassFilter />
            <ChemOntClassFilter />
            <div className="space-y-1.5">
              <Label className="text-xs">Assembly Accession</Label>
              <Input
                placeholder="e.g. ERZ..."
                value={assemblyAccession}
                onChange={(e) => setAssemblyAccession(e.target.value)}
                className="vf-form__input h-8 text-xs"
              />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">BGC Accession (MGYB)</Label>
              <Input
                placeholder="e.g. MGYB000000000001"
                value={bgcAccession}
                onChange={(e) => setBgcAccession(e.target.value)}
                className="vf-form__input h-8 text-xs"
              />
            </div>
          </TabsContent>
          <TabsContent value="query" className="space-y-6">
            <DomainQueryBuilder />
            <Separator />
            <SequenceSearch />
            <Separator />
            <ChemicalStructureSearch />
          </TabsContent>
        </Tabs>
      ) : (
        <div className="space-y-4">
          <TaxonomyFilter />
          <div className="space-y-1.5">
            <Label className="text-xs">Biome Lineage</Label>
            <Input
              placeholder="e.g. root:Environmental:Soil"
              value={biomeLineage}
              onChange={(e) => setBiomeLineage(e.target.value)}
              className="vf-form__input h-8 text-xs"
            />
          </div>
          <BgcClassFilter />
          <ChemOntClassFilter />
        </div>
      )}
    </div>
  );
}
