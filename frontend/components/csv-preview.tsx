"use client";

import { motion } from "framer-motion";
import Papa from "papaparse";
import { useEffect, useState } from "react";

import { SmartText } from "@/components/smart-text";

const PREVIEW_ROWS = 10;

interface PreviewState {
  rows: string[];
  total: number;
  error: string | null;
  loading: boolean;
}

const INITIAL: PreviewState = { rows: [], total: 0, error: null, loading: false };

interface Props {
  file: File | null;
}

/**
 * Live preview of the first 10 question rows from a dropped CSV. Parses the
 * file in the browser via Papa Parse (handles quoted commas, multi-line
 * fields, BOMs). Doesn't validate — that's the server's job at upload time.
 *
 * Renders the question column through SmartText so math/HTML preview
 * matches what the comparison view will eventually show.
 */
export function CsvPreview({ file }: Props) {
  const [state, setState] = useState<PreviewState>(INITIAL);

  useEffect(() => {
    if (!file) {
      setState(INITIAL);
      return;
    }
    setState({ ...INITIAL, loading: true });
    Papa.parse<Record<string, string>>(file, {
      header: true,
      skipEmptyLines: "greedy",
      preview: 0,
      worker: false,
      complete: (result) => {
        const fields = result.meta.fields ?? [];
        const qCol = fields.find((c) => c.trim().toLowerCase() === "question");
        if (!qCol) {
          setState({
            rows: [],
            total: 0,
            error: "CSV is missing a 'question' column.",
            loading: false,
          });
          return;
        }
        const all = result.data
          .map((r) => (r[qCol] ?? "").trim())
          .filter((q) => q.length > 0);
        setState({
          rows: all.slice(0, PREVIEW_ROWS),
          total: all.length,
          error: null,
          loading: false,
        });
      },
      error: (err: Error) =>
        setState({ rows: [], total: 0, error: err.message, loading: false }),
    });
  }, [file]);

  if (!file) return null;

  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.18 }}
    >
      <div className="flex items-center justify-between mb-2">
        <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
          Preview
        </div>
        {state.total > 0 && (
          <div className="text-[12px] text-muted-foreground tabular">
            Showing first {Math.min(state.rows.length, PREVIEW_ROWS)} of{" "}
            <span className="font-semibold text-foreground">{state.total}</span> question
            {state.total === 1 ? "" : "s"}
          </div>
        )}
      </div>

      {state.loading && (
        <div className="rounded-xl border bg-card/40 p-6 text-center text-[13px] text-muted-foreground">
          Parsing CSV…
        </div>
      )}

      {state.error && (
        <div className="rounded-xl border border-[var(--verdict-repeat-bg)] bg-[var(--verdict-repeat-bg)]/60 px-4 py-3 text-[13px] text-[var(--verdict-repeat-fg)]">
          {state.error}
        </div>
      )}

      {!state.loading && !state.error && state.rows.length > 0 && (
        <div className="rounded-xl border bg-card divide-y overflow-hidden">
          {state.rows.map((q, i) => (
            <div
              key={i}
              className="flex items-start gap-3 px-4 py-2.5 text-[13.5px] leading-relaxed"
            >
              <span className="mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-muted text-[11px] font-semibold tabular text-muted-foreground">
                {i + 1}
              </span>
              <div className="flex-1 min-w-0">
                <SmartText>{q}</SmartText>
              </div>
            </div>
          ))}
          {state.total > state.rows.length && (
            <div className="px-4 py-2 text-center text-[12px] text-muted-foreground">
              and {state.total - state.rows.length} more…
            </div>
          )}
        </div>
      )}
    </motion.div>
  );
}
