"use client";

import "katex/dist/katex.min.css";

import ReactMarkdown, { type Components } from "react-markdown";
import rehypeKatex from "rehype-katex";
import rehypeRaw from "rehype-raw";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";

import { containsHtml } from "@/lib/content-detect";

interface Props {
  /** The question text to render. */
  children: string;
  /** When true (default), avoid block-level wrapping so the output flows inline. */
  inline?: boolean;
  className?: string;
}

/**
 * Renders WAEC question text the way it was authored:
 *   - Plain text → as-is
 *   - HTML (sub/sup/b/i/em/strong/span etc.) → rendered, sanitized
 *   - Markdown (**bold**, _italic_, lists, …) → rendered
 *   - Inline LaTeX in $...$ and block LaTeX in $$...$$ → typeset via KaTeX
 *
 * Pipeline:
 *   remark: gfm → math
 *   rehype: raw (only when source has HTML) → sanitize → katex
 *
 * The HTML allow-list is the rehype-sanitize default plus the chemistry-relevant
 * tags (sub/sup, b/i for legacy content). KaTeX outputs deeply-nested spans
 * with classes — those go through after sanitize, applied by rehype-katex.
 */
export function SmartText({ children, inline = true, className }: Props) {
  const text = children ?? "";
  const allowHtml = containsHtml(text);

  // Strip wrapping <p> tags from output when used inline, so the rendered
  // content can live inside a parent <p> without producing invalid HTML.
  const components: Components = inline
    ? {
        p: ({ children }) => <>{children}</>,
      }
    : {};

  const schema = {
    ...defaultSchema,
    tagNames: [
      ...(defaultSchema.tagNames ?? []),
      "sub", "sup", "b", "i", "u", "em", "strong", "mark", "small", "span",
    ],
    attributes: {
      ...defaultSchema.attributes,
      // Permit class attribute on common inline tags so KaTeX classes survive.
      "*": [...(defaultSchema.attributes?.["*"] ?? []), "className", "class"],
    },
  };

  return (
    <span className={className}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={
          allowHtml
            ? [rehypeRaw, [rehypeSanitize, schema], rehypeKatex]
            : [[rehypeSanitize, schema], rehypeKatex]
        }
        components={components}
      >
        {text}
      </ReactMarkdown>
    </span>
  );
}
