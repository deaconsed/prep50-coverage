"""Pure-Python normalization for question text.

Two outputs per question:
    text_clean        -> HTML-stripped, whitespace-collapsed, math preserved.
                         Used as input to the embedding model.
    search_fingerprint -> Aggressively canonicalized: numbers and single-letter
                         variables become placeholders, common templated
                         phrasing is unified. Used for exact-template SQL
                         lookups.

This is intentionally rule-based and deterministic. No AI.
"""
import html
import re

# Order matters: strip tags, decode entities, then normalize whitespace.
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")

# Markdown stripping (run BEFORE HTML strip so we don't accidentally eat HTML).
# The DB schema has content_type IN ('html','markdown'); today the corpus is
# 100% html, but new ingestions may arrive as markdown and we want identical
# normalization regardless of source format.
_MD_FENCED_RE = re.compile(r"```[\s\S]*?```")          # ```code blocks```
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")     # [text](url) -> text
_MD_IMG_RE = re.compile(r"!\[([^\]]*)\]\([^)]+\)")     # ![alt](url) -> alt
_MD_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+", re.M)  # leading #/##/...
_MD_BOLD_AST_RE = re.compile(r"\*\*(.+?)\*\*", re.S)
_MD_BOLD_UND_RE = re.compile(r"__(.+?)__", re.S)
_MD_ITAL_AST_RE = re.compile(r"(?<!\*)\*(?!\s)([^*\n]+?)(?<!\s)\*(?!\*)")
_MD_ITAL_UND_RE = re.compile(r"(?<![A-Za-z0-9_])_([^_\n]+?)_(?![A-Za-z0-9_])")
_MD_CODE_RE = re.compile(r"`+([^`\n]+)`+")              # `inline code`
_MD_BLOCKQUOTE_RE = re.compile(r"^\s{0,3}>\s?", re.M)
_MD_LIST_RE = re.compile(r"^\s{0,3}(?:[-*+]|\d+\.)\s+", re.M)


def _strip_markdown(text: str) -> str:
    """Remove markdown syntax, keep human-readable content."""
    text = _MD_FENCED_RE.sub(" ", text)
    text = _MD_IMG_RE.sub(r"\1", text)
    text = _MD_LINK_RE.sub(r"\1", text)
    text = _MD_HEADING_RE.sub("", text)
    text = _MD_BLOCKQUOTE_RE.sub("", text)
    text = _MD_LIST_RE.sub("", text)
    text = _MD_BOLD_AST_RE.sub(r"\1", text)
    text = _MD_BOLD_UND_RE.sub(r"\1", text)
    text = _MD_ITAL_AST_RE.sub(r"\1", text)
    text = _MD_ITAL_UND_RE.sub(r"\1", text)
    text = _MD_CODE_RE.sub(r"\1", text)
    return text


def to_clean(raw: str) -> str:
    """Strip markdown + HTML, decode entities, collapse whitespace. Preserve math content."""
    if raw is None:
        return ""
    text = str(raw)
    text = _strip_markdown(text)
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = _WS_RE.sub(" ", text).strip()
    return text


# Number forms: ints, decimals, signed, scientific, percentages.
_NUM_RE = re.compile(
    r"(?<![A-Za-z_])"                # don't match inside identifiers like h2
    r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?%?"
)

# Standalone single-letter math variables: x, y, a, b, k, n, t, etc.
# Avoid matching real words: require word-boundary on both sides and no
# uppercase context (so we don't gut acronyms like "ATP" or "DNA").
_VAR_RE = re.compile(r"(?<![A-Za-z])([a-z])(?![A-Za-z])")

# Common WAEC stems that should collapse to one canonical form.
_STEM_PATTERNS = [
    (re.compile(r"\b(find|calculate|determine|compute|evaluate|work out)\b\s+the\s+value\s+of\b", re.I),
     "[STEM_VALUE_OF]"),
    (re.compile(r"\b(which|what)\s+of\s+the\s+following\b", re.I),
     "[STEM_WHICH_FOLLOWING]"),
    (re.compile(r"\bsolve\s+(?:for\s+)?[a-z]\b", re.I),
     "[STEM_SOLVE_FOR]"),
    (re.compile(r"\bif\s+", re.I),
     "[IF]"),
]

_PUNCT_RE = re.compile(r"[^\w\s\[\]]+")


def to_fingerprint(clean: str) -> str:
    """Canonical text for exact-template lookups.

    Pipeline:
      1. lowercase
      2. canonicalize common WAEC stems ("find the value of ..." -> token)
      3. replace numbers with [num]
      4. replace standalone single-letter variables with [var]
      5. strip punctuation (except [ and ])
      6. collapse whitespace
    """
    if not clean:
        return ""
    text = clean.lower()
    for pat, repl in _STEM_PATTERNS:
        text = pat.sub(repl.lower(), text)
    text = _NUM_RE.sub("[num]", text)
    text = _VAR_RE.sub("[var]", text)
    text = _PUNCT_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text).strip()
    return text


if __name__ == "__main__":
    samples = [
        "<p>Find the value of <b>x</b> in 3x + 5 = 20.</p>",
        "Calculate the value of x when 3x + 5 = 20.",
        "Find the value of y when 5y - 2 = 18.",
        "Which of the following is a prime number?",
        "What of the following is a prime number?",
        "If 2x = 10, find x.",
        # Markdown twins — should normalize to the same fingerprint as HTML versions.
        "**Find** the *value* of _x_ in 3x + 5 = 20.",
        "## Question 1\n\nFind the value of `x` in: `3x + 5 = 20`",
        "Which of __these__ is a **prime** number? See [the textbook](https://example.com).",
    ]
    for s in samples:
        c = to_clean(s)
        f = to_fingerprint(c)
        print(f"raw : {s}")
        print(f"clean: {c}")
        print(f"fp  : {f}")
        print()
