/**
 * Word-level diff between the new question and the matched corpus question.
 *
 * Wraps `diff.diffWords` and returns a normalized list of "segments" that
 * the renderer can map directly to span tags.
 *
 * Math-aware mode (enabled by default):
 *   Inline `$...$` blocks are tokenized to opaque sentinel strings before
 *   the diff runs, then restored in the resulting segments. That keeps each
 *   formula as a single atomic unit (the diff can't split `$CH_3CH_2OH$`
 *   across "common" and "added" segments), AND the renderer can hand the
 *   restored math text to SmartText for KaTeX rendering.
 *
 *   Identical math content in both sides shares one token, so common
 *   formulas stay marked common — not removed+added.
 */
import { diffWords } from "diff";

export type DiffKind = "common" | "added" | "removed";

export interface DiffSegment {
  kind: DiffKind;
  text: string;
}

// Private Use Area sentinel — never appears in real exam content.
const TOKEN_OPEN = "";
const TOKEN_CLOSE = "";
const MATH_RE = /\$[^$\n]+\$/g;

interface TokenizeResult {
  tokenize(text: string): string;
  restore(text: string): string;
}

function createMathTokenizer(): TokenizeResult {
  const forward = new Map<string, string>(); // math content → token
  const reverse = new Map<string, string>(); // token → math content
  let counter = 0;

  function tokenize(text: string): string {
    return text.replace(MATH_RE, (m) => {
      let token = forward.get(m);
      if (!token) {
        token = `${TOKEN_OPEN}M${counter++}${TOKEN_CLOSE}`;
        forward.set(m, token);
        reverse.set(token, m);
      }
      return token;
    });
  }

  function restore(text: string): string {
    if (!text.includes(TOKEN_OPEN)) return text;
    let result = text;
    for (const [token, original] of reverse) {
      if (result.includes(token)) {
        result = result.split(token).join(original);
      }
    }
    return result;
  }

  return { tokenize, restore };
}

export function wordDiff(oldText: string, newText: string): DiffSegment[] {
  const t = createMathTokenizer();
  const raw = diffWords(t.tokenize(oldText ?? ""), t.tokenize(newText ?? ""), {
    ignoreCase: false,
  });
  const out: DiffSegment[] = [];
  for (const part of raw) {
    const restored = t.restore(part.value);
    if (part.added) out.push({ kind: "added", text: restored });
    else if (part.removed) out.push({ kind: "removed", text: restored });
    else out.push({ kind: "common", text: restored });
  }
  return mergeWhitespaceChanges(out);
}

/**
 * If an added/removed segment is pure whitespace, swallow it into the
 * preceding common segment. Otherwise the diff highlight will render
 * isolated colored spaces that look like rendering bugs.
 */
function mergeWhitespaceChanges(segments: DiffSegment[]): DiffSegment[] {
  const out: DiffSegment[] = [];
  for (const seg of segments) {
    if (seg.kind !== "common" && /^\s+$/.test(seg.text)) {
      if (out.length > 0) {
        out[out.length - 1] = { ...out[out.length - 1], text: out[out.length - 1].text + seg.text };
      } else {
        out.push({ kind: "common", text: seg.text });
      }
      continue;
    }
    out.push(seg);
  }
  return out;
}
