import { useModeStore } from "@/stores/mode-store";
import { cn } from "@/lib/utils";

export function Header() {
  const mode = useModeStore((s) => s.mode);
  const setMode = useModeStore((s) => s.setMode);

  return (
    <header className="border-b px-6 py-2">
      <div className="vf-cluster">
        <div className="vf-cluster__inner" style={{ alignItems: "center", gap: "1rem" }}>
          <h2 className="vf-text-heading--5" style={{ margin: 0 }}>
            Discovery Platform
          </h2>
          <div className="vf-tabs">
            <ul className="vf-tabs__list" style={{ margin: 0 }}>
              <li className="vf-tabs__item">
                <a
                  className={cn(
                    "vf-tabs__link",
                    mode === "query" && "is-active"
                  )}
                  href="#query"
                  onClick={(e) => {
                    e.preventDefault();
                    setMode("query");
                  }}
                >
                  Search BGCs
                </a>
              </li>
              <li className="vf-tabs__item">
                <a
                  className={cn(
                    "vf-tabs__link",
                    mode === "explore" && "is-active"
                  )}
                  href="#explore"
                  onClick={(e) => {
                    e.preventDefault();
                    setMode("explore");
                  }}
                >
                  Explore Genomes
                </a>
              </li>
              <li className="vf-tabs__item">
                <a
                  className={cn(
                    "vf-tabs__link",
                    mode === "assess" && "is-active"
                  )}
                  href="#assess"
                  onClick={(e) => {
                    e.preventDefault();
                    setMode("assess");
                  }}
                >
                  Asset Evaluation
                </a>
              </li>
            </ul>
          </div>
        </div>
      </div>
    </header>
  );
}
