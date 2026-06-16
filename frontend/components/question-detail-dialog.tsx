"use client";

import { ChevronLeft, ChevronRight, Sparkles } from "lucide-react";
import { useEffect } from "react";

import { SmartText } from "@/components/smart-text";
import { SideBySide } from "@/components/side-by-side";
import { VerdictPill } from "@/components/verdict-pill";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useTechnicalMode } from "@/lib/hooks/use-technical-mode";
import { cosineQualitative, fmtCosine, yearQLabel } from "@/lib/format";
import { useQuestionDetail } from "@/lib/stores/question-detail";
import type { TopKItem } from "@/lib/types";

const OTHER_CANDIDATES_THRESHOLD = 0.65;

/**
 * Global question detail modal.
 *
 * Opens at a specific position within an items array (whatever the page is
 * currently rendering — filtered or not). Prev / Next walk through that list
 * with the side arrow buttons or with arrow keys on the keyboard.
 */
export function QuestionDetailDialog() {
  const items = useQuestionDetail((s) => s.items);
  const position = useQuestionDetail((s) => s.position);
  const total = useQuestionDetail((s) => s.total);
  const next = useQuestionDetail((s) => s.next);
  const prev = useQuestionDetail((s) => s.prev);
  const close = useQuestionDetail((s) => s.close);

  const open = items.length > 0;
  const item = open ? items[position] : null;
  const atStart = position <= 0;
  const atEnd = position >= items.length - 1;

  // Keyboard nav while the dialog is open.
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      // Ignore when typing in inputs/textareas (e.g. inside the dialog body).
      const tgt = e.target as HTMLElement | null;
      if (tgt && ["INPUT", "TEXTAREA"].includes(tgt.tagName)) return;
      if (e.key === "ArrowRight") {
        e.preventDefault();
        next();
      } else if (e.key === "ArrowLeft") {
        e.preventDefault();
        prev();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, next, prev]);

  return (
    <Dialog open={open} onOpenChange={(o) => !o && close()}>
      <DialogContent className="relative w-[96vw] sm:!max-w-[1100px] max-h-[92vh] overflow-y-auto p-6">
        {item && (
          <>
            <NavButton side="left" onClick={prev} disabled={atStart} />
            <NavButton side="right" onClick={next} disabled={atEnd} />

            <DialogHeader>
              <DialogTitle className="flex flex-wrap items-center gap-3">
                <VerdictPill verdict={item.verdict} />
                <span className="text-[15px] font-semibold">
                  Question {item.input_index + 1}
                  {total ? ` of ${total}` : ""}
                </span>
                <span className="text-[12.5px] font-normal text-muted-foreground">
                  {item.reason}
                </span>
                {items.length > 1 && (
                  <span className="ml-auto text-[12px] font-normal text-muted-foreground tabular">
                    {position + 1} / {items.length}
                  </span>
                )}
              </DialogTitle>
            </DialogHeader>

            <Body />

            {items.length > 1 && (
              <div className="mt-2 text-center text-[11.5px] text-muted-foreground">
                <span className="inline-flex items-center gap-1">
                  <kbd className="rounded border bg-muted px-1.5 py-0.5 font-mono text-[10.5px]">
                    ←
                  </kbd>
                  <kbd className="rounded border bg-muted px-1.5 py-0.5 font-mono text-[10.5px]">
                    →
                  </kbd>
                  to navigate
                </span>
              </div>
            )}
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}

function NavButton({
  side,
  onClick,
  disabled,
}: {
  side: "left" | "right";
  onClick: () => void;
  disabled: boolean;
}) {
  const Icon = side === "left" ? ChevronLeft : ChevronRight;
  const pos = side === "left" ? "left-2 sm:-left-5" : "right-2 sm:-right-5";
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={side === "left" ? "Previous question" : "Next question"}
      className={[
        "absolute top-1/2 -translate-y-1/2 z-10",
        "flex h-11 w-11 items-center justify-center rounded-full",
        "bg-card border shadow-md text-foreground",
        "hover:bg-[var(--brand)] hover:text-[var(--brand-foreground)] hover:border-[var(--brand)]",
        "transition-all disabled:opacity-30 disabled:cursor-not-allowed disabled:hover:bg-card disabled:hover:text-foreground disabled:hover:border-border",
        pos,
      ].join(" ")}
    >
      <Icon className="h-5 w-5" />
    </button>
  );
}

function Body() {
  const item = useQuestionDetail((s) => s.items[s.position])!;

  const primary =
    item.verdict === "REPEAT" && item.fingerprint_matches.length > 0
      ? item.fingerprint_matches[0]
      : item.top_k[0] ?? null;
  const primaryKind =
    item.verdict === "REPEAT" ? ("fingerprint" as const) : item.top_k[0] ? ("cosine" as const) : null;
  const primaryCosine =
    item.verdict !== "REPEAT" && item.top_k[0] ? item.top_k[0].cosine : undefined;

  const primaryId = primary && "question_id" in primary ? primary.question_id : null;
  const others = item.top_k.filter(
    (c) => c.question_id !== primaryId && c.cosine >= OTHER_CANDIDATES_THRESHOLD,
  );

  return (
    <div className="mt-4 space-y-6">
      <SideBySide
        newInput={item.input}
        match={primary}
        kind={primaryKind}
        cosine={primaryCosine}
      />

      {others.length > 0 && (
        <section className="space-y-3 pt-2 border-t">
          <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
            Other matches in the corpus
            <span className="ml-2 normal-case tracking-normal text-[12px] text-muted-foreground/70">
              cosine ≥ {OTHER_CANDIDATES_THRESHOLD}
            </span>
          </div>
          <div className="space-y-2">
            {others.map((c, i) => (
              <CandidateRow key={`${c.question_id}-${i}`} candidate={c} />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function AiScoreChip({ score }: { score: number }) {
  // Color the chip by tier so reviewers can scan the AI's confidence without reading the number.
  const cls =
    score >= 80
      ? "bg-[var(--verdict-repeat-bg)] text-[var(--verdict-repeat-fg)]"
      : score >= 55
      ? "bg-[var(--verdict-near-bg)] text-[var(--verdict-near-fg)]"
      : "bg-muted text-muted-foreground";
  return (
    <span
      className={[
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold",
        cls,
      ].join(" ")}
      title="Gemini's confidence that this candidate asks the same question"
    >
      <Sparkles className="h-2.5 w-2.5" />
      AI {score}
    </span>
  );
}


function CandidateRow({ candidate: c }: { candidate: TopKItem }) {
  const [tech] = useTechnicalMode();
  const yearLbl = yearQLabel(c.question_year, c.question_year_number);
  return (
    <div className="rounded-xl border bg-card/60 p-4 hover:bg-card transition-colors">
      <div className="flex items-center justify-between gap-3 mb-2">
        <div className="flex items-center gap-2 text-[12px]">
          {yearLbl && (
            <span className="italic font-medium text-[var(--verdict-repeat)]">
              {yearLbl}
            </span>
          )}
          {c.fingerprint_match && (
            <span className="inline-block bg-[var(--verdict-repeat-bg)] text-[var(--verdict-repeat-fg)] px-2 py-0.5 rounded-md text-[10.5px] font-semibold">
              fingerprint match
            </span>
          )}
        </div>
        <div className="flex items-center gap-1.5">
          {c.ai_score !== null && c.ai_score !== undefined && (
            <AiScoreChip score={c.ai_score} />
          )}
          {tech ? (
            <span className="rounded-full bg-foreground px-2.5 py-0.5 font-mono text-[11px] font-medium text-background">
              cosine {fmtCosine(c.cosine)}
            </span>
          ) : (
            <span className="text-[12px] font-medium text-muted-foreground">
              {cosineQualitative(c.cosine)}
            </span>
          )}
        </div>
      </div>
      <div className="text-[14px] leading-relaxed text-foreground/90">
        <SmartText>{c.text_clean}</SmartText>
      </div>
      {c.ai_reason && (
        <div className="mt-2 text-[12px] italic text-muted-foreground">
          AI: {c.ai_reason}
        </div>
      )}
      {(c.option_1 || c.option_2 || c.option_3 || c.option_4) && (
        <ol className="mt-2 space-y-0.5 pl-6 [list-style-type:upper-alpha] marker:font-semibold marker:text-muted-foreground/80 text-[12.5px] text-muted-foreground">
          {[c.option_1, c.option_2, c.option_3, c.option_4]
            .filter(Boolean)
            .map((o, i) => (
              <li key={i}>
                <SmartText>{o as string}</SmartText>
              </li>
            ))}
        </ol>
      )}
    </div>
  );
}
