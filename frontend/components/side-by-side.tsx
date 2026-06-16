"use client";

import { useState } from "react";
import { Diff, Sparkles, X } from "lucide-react";

import { DiffHighlight } from "@/components/diff-highlight";
import { SmartText } from "@/components/smart-text";
import { useTechnicalMode } from "@/lib/hooks/use-technical-mode";
import { cosineQualitative, fmtCosine, yearQLabel } from "@/lib/format";
import type { FingerprintMatch, InputData, TopKItem } from "@/lib/types";

interface Props {
  newInput: InputData;
  match: FingerprintMatch | TopKItem | null;
  /** When set, shows "cosine" for top_k matches, "Exact" for fingerprint. */
  kind: "fingerprint" | "cosine" | null;
  cosine?: number;
}

/**
 * Two-card comparison: the new question on the left, the matched historical
 * question on the right. Year/Q-number rendered in red italic per the
 * boss-approved spec.
 *
 * In simple mode the cosine number is replaced by a qualitative label.
 */
export function SideBySide({ newInput, match, kind, cosine }: Props) {
  const [tech] = useTechnicalMode();
  // Diff highlight is off by default for EXACT (where the texts match) and on
  // by default otherwise — that's when the differences are useful to scan.
  const [showDiff, setShowDiff] = useState<boolean>(kind === "cosine");

  // Only meaningful when both sides have text.
  const canDiff = !!match;
  const matchText = match?.text_clean ?? "";
  const newText = newInput.question_raw;

  return (
    <div className="space-y-3">
      {canDiff && (
        <div className="flex items-center justify-end">
          <button
            type="button"
            onClick={() => setShowDiff((v) => !v)}
            className={[
              "inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[11.5px] font-semibold transition-colors",
              showDiff
                ? "bg-[var(--brand-tint)] text-[var(--brand)] border border-[var(--brand-soft)]"
                : "bg-muted text-muted-foreground hover:bg-muted/80 border border-transparent",
            ].join(" ")}
          >
            {showDiff ? <X className="h-3 w-3" /> : <Diff className="h-3 w-3" />}
            {showDiff ? "Hide word differences" : "Show word differences"}
          </button>
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        <QuestionCard
          eyebrow="New question"
          text={newText}
          against={matchText}
          showDiff={showDiff && canDiff}
          side="new"
          options={(newInput.options ?? []).filter(Boolean) as string[]}
        />
        {match ? (
          <QuestionCard
            eyebrow="Best match in corpus"
            text={matchText}
            against={newText}
            showDiff={showDiff}
            side="match"
            options={
              [match.option_1, match.option_2, match.option_3, match.option_4]
                .filter(Boolean) as string[]
            }
            yearLabel={yearQLabel(match.question_year, match.question_year_number)}
            footer={
              kind === "fingerprint" ? (
                <span className="inline-flex items-center gap-1.5 rounded-md bg-[var(--verdict-repeat-bg)] px-2 py-0.5 text-[11.5px] font-semibold text-[var(--verdict-repeat-fg)]">
                  Exact template match
                </span>
              ) : (
                <div className="flex flex-wrap items-center gap-2">
                  {"ai_score" in (match ?? {}) && (match as TopKItem).ai_score !== null && (match as TopKItem).ai_score !== undefined && (
                    <PrimaryAiChip score={(match as TopKItem).ai_score as number} reason={(match as TopKItem).ai_reason ?? null} />
                  )}
                  {cosine != null &&
                    (tech ? (
                      <span className="rounded-full bg-foreground px-2.5 py-0.5 font-mono text-[11.5px] font-medium text-background">
                        cosine {fmtCosine(cosine)}
                      </span>
                    ) : (
                      <span className="text-[12.5px] font-medium text-muted-foreground">
                        {cosineQualitative(cosine)}
                      </span>
                    ))}
                </div>
              )
            }
          />
        ) : (
          <div className="flex items-center justify-center rounded-2xl border border-dashed bg-muted/40 px-6 py-8 text-[13.5px] italic text-muted-foreground">
            No corpus match above the similarity threshold — this question appears new.
          </div>
        )}
      </div>
    </div>
  );
}

function PrimaryAiChip({ score, reason }: { score: number; reason: string | null }) {
  const cls =
    score >= 80
      ? "bg-[var(--verdict-repeat-bg)] text-[var(--verdict-repeat-fg)]"
      : score >= 55
      ? "bg-[var(--verdict-near-bg)] text-[var(--verdict-near-fg)]"
      : "bg-muted text-muted-foreground";
  return (
    <span
      className={[
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[11.5px] font-semibold",
        cls,
      ].join(" ")}
      title={reason || "Gemini's same-question confidence"}
    >
      <Sparkles className="h-3 w-3" />
      AI {score}
    </span>
  );
}


function QuestionCard({
  eyebrow,
  text,
  against,
  showDiff,
  side,
  options,
  yearLabel,
  footer,
}: {
  eyebrow: string;
  text: string;
  against: string;
  showDiff: boolean;
  side: "new" | "match";
  options: string[];
  yearLabel?: string;
  footer?: React.ReactNode;
}) {
  return (
    <div className="rounded-2xl border bg-card p-5 shadow-sm">
      <div className="mb-2 text-[10.5px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
        {eyebrow}
      </div>
      <div className="text-[14.5px] leading-relaxed text-foreground">
        {showDiff ? (
          <DiffHighlight text={text} against={against} side={side} />
        ) : (
          <SmartText>{text}</SmartText>
        )}
        {yearLabel && (
          <>
            {" "}
            <span className="italic font-medium text-[var(--verdict-repeat)]">
              {yearLabel}
            </span>
          </>
        )}
      </div>
      {options.length > 0 && (
        <ol className="mt-3 space-y-1 pl-6 [list-style-type:upper-alpha] marker:font-semibold marker:text-muted-foreground/80 text-[13.5px] text-muted-foreground">
          {options.map((o, i) => (
            <li key={i}>
              <SmartText>{o}</SmartText>
            </li>
          ))}
        </ol>
      )}
      {footer && <div className="mt-4">{footer}</div>}
    </div>
  );
}
