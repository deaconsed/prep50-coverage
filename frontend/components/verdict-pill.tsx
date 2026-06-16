"use client";

import { useTechnicalMode } from "@/lib/hooks/use-technical-mode";
import { verdictLabel, VERDICT_CLASS, VERDICT_META } from "@/lib/verdict";
import type { Verdict } from "@/lib/types";

interface Props {
  verdict: Verdict;
  /** Force a display mode (override the hook). */
  forceTechnical?: boolean;
  className?: string;
  size?: "sm" | "md";
}

/**
 * Small pill rendering the verdict. Switches label between technical
 * ("REPEAT", "NEAR (high)", ...) and simple ("Exact match", "Very similar")
 * based on the technical-mode toggle.
 */
export function VerdictPill({ verdict, forceTechnical, className, size = "md" }: Props) {
  const [tech] = useTechnicalMode();
  const technical = forceTechnical ?? tech;
  const label = verdictLabel(verdict, technical);
  const cls = VERDICT_CLASS[verdict];
  const sizeCls =
    size === "sm" ? "text-[10.5px] px-2 py-[1px] gap-1" : "text-[11.5px] px-2.5 py-[3px] gap-1.5";
  return (
    <span
      className={[
        "inline-flex items-center font-semibold tracking-wide rounded-full",
        cls.pill,
        sizeCls,
        className ?? "",
      ].join(" ")}
      title={VERDICT_META[verdict].description}
    >
      <span aria-hidden className={["h-1.5 w-1.5 rounded-full", cls.dot].join(" ")} />
      {label}
    </span>
  );
}
