"use client";

import { useMemo } from "react";

import { SmartText } from "@/components/smart-text";
import { wordDiff } from "@/lib/diff";

interface Props {
  /** The text being rendered. */
  text: string;
  /** The other text to diff against. */
  against: string;
  /** Which side this is rendering — controls which kind of changes get highlighted. */
  side: "new" | "match";
  className?: string;
}

/**
 * Renders `text` with subtle word-level highlights showing the parts that
 * differ from `against`. Math blocks ($...$) survive the diff intact and
 * still render via KaTeX inside whichever segment they end up in.
 *
 * On the "new" side: words present here but missing in the matched question
 *   get a green wash (additions of the new question).
 * On the "match" side: words present here but missing in the new question
 *   get a red wash (the corpus question's extras).
 *
 * Words that appear in both sides render plain so the eye locks onto the
 * differences naturally.
 */
export function DiffHighlight({ text, against, side, className }: Props) {
  const segments = useMemo(() => {
    // diffWords expects (old, new). We always treat "match" as old, "new" as new.
    if (side === "new") return wordDiff(against, text);
    return wordDiff(text, against);
  }, [text, against, side]);

  return (
    <span className={className}>
      {segments.map((seg, i) => {
        if (seg.kind === "common") {
          return (
            <span key={i}>
              <SmartText>{seg.text}</SmartText>
            </span>
          );
        }
        const showOnNewSide = side === "new" && seg.kind === "added";
        const showOnMatchSide = side === "match" && seg.kind === "removed";
        if (!(showOnNewSide || showOnMatchSide)) {
          // The other side's exclusive segment — skip rendering to avoid
          // doubling the content.
          return null;
        }
        const style = showOnNewSide
          ? "bg-[var(--verdict-new-bg)]/70 text-[var(--verdict-new-fg)] rounded px-0.5"
          : "bg-[var(--verdict-repeat-bg)]/70 text-[var(--verdict-repeat-fg)] rounded px-0.5";
        return (
          <span key={i} className={style}>
            <SmartText>{seg.text}</SmartText>
          </span>
        );
      })}
    </span>
  );
}
