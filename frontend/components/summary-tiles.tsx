"use client";

import { motion } from "framer-motion";

import { VerdictPill } from "@/components/verdict-pill";
import { VERDICT_ORDER } from "@/lib/verdict";
import type { Verdict } from "@/lib/types";

interface Props {
  counts: Record<Verdict, number>;
  filter: Verdict | "ALL";
  onFilter: (next: Verdict | "ALL") => void;
}

/**
 * Four tiles, one per verdict. Click toggles the filter — second click on the
 * same tile clears back to ALL. Used on both the live review and the saved
 * batch detail page so the filtering UX is consistent.
 */
export function SummaryTiles({ counts, filter, onFilter }: Props) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {VERDICT_ORDER.map((v) => {
        const active = filter === v;
        return (
          <motion.button
            type="button"
            key={v}
            layout
            onClick={() => onFilter(active ? "ALL" : v)}
            className={[
              "rounded-2xl border bg-card px-4 py-4 text-left shadow-sm transition-all",
              "hover:shadow-md hover:-translate-y-px",
              active ? "ring-2 ring-[var(--brand)] border-[var(--brand)]" : "",
            ].join(" ")}
          >
            <VerdictPill verdict={v} size="sm" />
            <div className="mt-2 text-[28px] font-bold tabular leading-none">
              {counts[v]}
            </div>
            <div className="mt-0.5 text-[12px] text-muted-foreground">
              {active ? "Filtering ·" : "Click to filter"}
            </div>
          </motion.button>
        );
      })}
    </div>
  );
}
