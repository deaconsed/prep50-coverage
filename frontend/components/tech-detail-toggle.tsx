"use client";

import { Eye, EyeOff } from "lucide-react";

import { useTechnicalMode } from "@/lib/hooks/use-technical-mode";

/**
 * Reviewer-facing toggle: flips the verdict labels + hides cosine numbers and
 * fingerprint badges.
 *
 * The hook owns the persisted state (URL + localStorage). This component is
 * just the UI control.
 */
export function TechDetailToggle() {
  const [tech, setTech] = useTechnicalMode();
  return (
    <button
      type="button"
      onClick={() => setTech(!tech)}
      title={
        tech
          ? "Hide technical detail (cosine scores, model strings)"
          : "Show technical detail (cosine scores, model strings)"
      }
      className={[
        "inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-[12px] font-semibold transition-colors",
        tech
          ? "border-[var(--brand-soft)] bg-[var(--brand-tint)] text-[var(--brand)]"
          : "border-border bg-card text-muted-foreground hover:text-foreground",
      ].join(" ")}
    >
      {tech ? <EyeOff className="h-3 w-3" /> : <Eye className="h-3 w-3" />}
      {tech ? "Technical detail on" : "Technical detail off"}
    </button>
  );
}
