"use client";

import { useCorpusStats } from "@/lib/api";
import { TechDetailToggle } from "@/components/tech-detail-toggle";
import { ThemeToggle } from "@/components/theme-toggle";
import { useTechnicalMode } from "@/lib/hooks/use-technical-mode";

/**
 * Minimal footer with the technical-mode toggle and (when on) the model
 * provenance string — the kind of metadata that engineers want to confirm
 * a report is reproducible from.
 */
export function SiteFooter() {
  const { data } = useCorpusStats();
  const [tech] = useTechnicalMode();
  return (
    <footer className="border-t bg-background/60">
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-6 py-4 text-[12px] text-muted-foreground">
        <div className="tabular">
          {tech && data ? (
            <>
              <span className="font-mono">{data.model_name}</span> · {data.embed_dims}d ·{" "}
              <span className="font-mono">{data.model_version}</span>
            </>
          ) : (
            "Prep50 Coverage"
          )}
        </div>
        <div className="flex items-center gap-2">
          <ThemeToggle />
          <TechDetailToggle />
        </div>
      </div>
    </footer>
  );
}
