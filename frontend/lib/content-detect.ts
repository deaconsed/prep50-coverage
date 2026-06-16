/**
 * Detect what kind of markup a piece of question text contains.
 *
 * The WAEC corpus mixes:
 *   - plain text (most common)
 *   - HTML (esp. <sup> / <sub> for chemistry notation, <b>/<i>)
 *   - inline LaTeX math wrapped in $...$ (chemistry equations, equilibria)
 *   - occasional markdown (bold/italic) in user-uploaded CSVs
 *
 * The SmartText component uses the same react-markdown pipeline regardless,
 * so this helper is mostly informational — it tells us whether to allow
 * raw HTML in the rehype pipeline (security tradeoff).
 */
const HTML_RE = /<\/?[a-z][a-z0-9]*[^>]*>/i;
const LATEX_INLINE_RE = /\$[^$\n]+\$/;
const LATEX_DISPLAY_RE = /\$\$[\s\S]+?\$\$/;
const MARKDOWN_HINTS = [
  /\*\*[^*]+\*\*/,   // **bold**
  /(?:^|[^_])__[^_]+__(?:[^_]|$)/, // __bold__
  /(?:^|\s)\*[^*\s][^*]*\*/, // *italic*
  /^#{1,6}\s+/m,     // # heading
  /^[-*+]\s+/m,      // list
  /\[[^\]]+\]\([^)]+\)/, // [link](url)
  /`[^`\n]+`/,       // `code`
];

export type ContentKind = "html" | "markdown" | "latex" | "plain";

export function detectContentKind(text: string): Set<ContentKind> {
  const kinds = new Set<ContentKind>();
  if (HTML_RE.test(text)) kinds.add("html");
  if (LATEX_INLINE_RE.test(text) || LATEX_DISPLAY_RE.test(text)) kinds.add("latex");
  if (MARKDOWN_HINTS.some((re) => re.test(text))) kinds.add("markdown");
  if (kinds.size === 0) kinds.add("plain");
  return kinds;
}

export function containsHtml(text: string): boolean {
  return HTML_RE.test(text);
}
