"use client";

import { motion } from "framer-motion";
import { Sparkles } from "lucide-react";

import type { Summary } from "@/lib/types";

interface Props {
  /** Either the SSE-rolled summary (live) or the persisted Summary (saved). */
  summary: Pick<Summary, "total" | "REPEAT" | "NEAR_HIGH" | "NEAR" | "NEW">;
  subjectName?: string | null;
}

/**
 * The big sales-pitch number — "X% of these exam questions already exist in
 * the Prep50 corpus." Counts REPEAT + NEAR_HIGH + NEAR as "exists somewhere"
 * since all three flagged a corpus hit.
 *
 * Includes three small breakdowns so the reviewer can see what each bucket
 * contributes to the headline number.
 */
export function CoverageBanner({ summary, subjectName }: Props) {
  const matched = summary.REPEAT + summary.NEAR_HIGH + summary.NEAR;
  const pct = summary.total > 0 ? Math.round((matched / summary.total) * 100) : 0;

  const items: { label: string; count: number; cls: string }[] = [
    { label: "Exact match", count: summary.REPEAT, cls: "text-[var(--verdict-repeat)]" },
    { label: "Very similar", count: summary.NEAR_HIGH, cls: "text-[var(--verdict-near-high)]" },
    { label: "Similar", count: summary.NEAR, cls: "text-[var(--verdict-near)]" },
  ];

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="relative overflow-hidden rounded-2xl border bg-gradient-to-br from-[var(--brand-tint)] via-card to-card p-6 sm:p-8 shadow-[0_2px_4px_rgb(15_23_42_/_0.04),0_8px_28px_rgb(15_23_42_/_0.08)]"
    >
      <div
        aria-hidden
        className="pointer-events-none absolute -right-24 -top-24 h-[300px] w-[300px] rounded-full"
        style={{
          background:
            "radial-gradient(closest-side, color-mix(in oklab, var(--brand), transparent 85%) 0%, transparent 70%)",
        }}
      />

      <div className="relative grid gap-6 sm:grid-cols-[auto_1fr] sm:items-end">
        <div>
          <div className="inline-flex items-center gap-2 rounded-full border border-[var(--brand-soft)] bg-card px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--brand)]">
            <Sparkles className="h-3 w-3" />
            Archive coverage
          </div>
          <div className="mt-3 flex items-end gap-3">
            <div className="text-[72px] sm:text-[88px] font-bold tracking-[-0.04em] leading-[0.95] tabular">
              <span
                className="bg-clip-text text-transparent"
                style={{
                  backgroundImage:
                    "linear-gradient(135deg, var(--brand) 0%, #7c3aed 100%)",
                }}
              >
                {pct}%
              </span>
            </div>
            <div className="pb-2 sm:pb-3 text-[13.5px] leading-snug text-muted-foreground max-w-[260px]">
              <span className="font-semibold text-foreground">
                {matched.toLocaleString()}
              </span>{" "}
              of {summary.total.toLocaleString()} questions already exist in the
              Prep50 archive
              {subjectName ? (
                <>
                  {" "}
                  for <span className="font-semibold text-foreground">{subjectName}</span>
                </>
              ) : null}
              .
            </div>
          </div>
        </div>

        <div className="grid grid-cols-3 gap-3 sm:max-w-[420px] sm:ml-auto">
          {items.map((it) => {
            const itemPct =
              summary.total > 0 ? Math.round((it.count / summary.total) * 100) : 0;
            return (
              <div
                key={it.label}
                className="rounded-xl border bg-card px-3 py-3 shadow-sm"
              >
                <div className="text-[10.5px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
                  {it.label}
                </div>
                <div className={`mt-1 text-[24px] font-bold tabular leading-none ${it.cls}`}>
                  {it.count}
                </div>
                <div className="mt-0.5 text-[11.5px] tabular text-muted-foreground">
                  {itemPct}%
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </motion.div>
  );
}
