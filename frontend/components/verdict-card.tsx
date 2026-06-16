"use client";

import { motion } from "framer-motion";
import { ChevronRight } from "lucide-react";

import { SmartText } from "@/components/smart-text";
import { VerdictPill } from "@/components/verdict-pill";
import { useTechnicalMode } from "@/lib/hooks/use-technical-mode";
import { cosineQualitative, fmtCosine, yearQLabel } from "@/lib/format";
import { useQuestionDetail } from "@/lib/stores/question-detail";
import type { VerdictItem } from "@/lib/types";

interface Props {
  item: VerdictItem;
  index: number;
  total?: number;
  animate?: boolean;
  /**
   * The list this card belongs to + its position in that list. Used to power
   * Prev/Next inside the question-detail modal. Falls back to a single-item
   * list if omitted (no navigation).
   */
  items?: VerdictItem[];
  position?: number;
}

/**
 * One result row. Click anywhere on the row → opens the question-detail
 * modal (see QuestionDetailDialog). Replaces the previous inline expansion
 * so the comparison happens in a focused, full-attention popup.
 *
 * The left bar color + verdict pill make the verdict scannable at a glance;
 * the right side shows the best-match year (red italic) + qualitative cosine
 * label so reviewers know the strength of the match without opening it.
 */
export function VerdictCard({
  item,
  index,
  total,
  animate = true,
  items,
  position,
}: Props) {
  const openDetail = useQuestionDetail((s) => s.open);
  const [tech] = useTechnicalMode();

  const top = item.top_k[0] ?? null;
  const primary =
    item.verdict === "REPEAT" && item.fingerprint_matches.length > 0
      ? { ...item.fingerprint_matches[0], _kind: "fingerprint" as const, cosine: 1 }
      : top
      ? { ...top, _kind: "cosine" as const }
      : null;

  const barColor = `var(--verdict-${item.verdict.replace("_", "-").toLowerCase()})`;

  const meta =
    item.verdict === "REPEAT"
      ? "Exact template match"
      : primary
      ? tech
        ? `cosine ${fmtCosine((primary as { cosine: number }).cosine)}`
        : cosineQualitative((primary as { cosine: number }).cosine)
      : "—";

  const yearLbl = primary ? yearQLabel(primary.question_year, primary.question_year_number) : "";
  const preview =
    item.input.question_raw.length > 200
      ? `${item.input.question_raw.slice(0, 197)}…`
      : item.input.question_raw;

  const content = (
    <button
      type="button"
      onClick={() =>
        openDetail(
          items ?? [item],
          items ? position ?? 0 : 0,
          total ?? items?.length ?? 1,
        )
      }
      className="relative w-full overflow-hidden rounded-2xl border bg-card text-left shadow-sm hover:shadow-md hover:border-[var(--border-strong,var(--border))] transition-all"
    >
      <div
        aria-hidden
        className="absolute left-0 top-0 bottom-0 w-1"
        style={{ background: barColor }}
      />
      <div className="flex w-full items-start gap-4 pl-6 pr-5 py-4">
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-2.5">
            <VerdictPill verdict={item.verdict} />
            <span className="text-[12px] text-muted-foreground">
              Question {index + 1}
              {total ? ` of ${total}` : ""}
            </span>
            {yearLbl && (
              <span className="text-[12px] italic text-[var(--verdict-repeat)]">
                match {yearLbl}
              </span>
            )}
          </div>
          <div className="mt-2 text-[14px] leading-relaxed text-foreground/90">
            <SmartText>{preview}</SmartText>
          </div>
        </div>
        <div className="flex flex-col items-end gap-1 pt-0.5 text-[12px]">
          <span className="tabular text-muted-foreground">{meta}</span>
          <ChevronRight className="h-4 w-4 text-muted-foreground/70" />
        </div>
      </div>
    </button>
  );

  if (!animate) return content;

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, ease: "easeOut" }}
    >
      {content}
    </motion.div>
  );
}
