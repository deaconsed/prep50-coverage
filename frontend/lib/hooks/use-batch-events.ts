/**
 * Custom hook that subscribes to the SSE stream for one batch and exposes
 * the running state (items, counts, phase, summary) to the UI.
 *
 * The hook owns the EventSource. It opens on mount, closes when the batch
 * reaches `done` or `error`, and reopens cleanly if the batchId changes.
 */
"use client";

import { useEffect, useRef, useState } from "react";

import { streamBatchEvents } from "@/lib/sse";
import type { IntraBatchDup, Summary, Verdict, VerdictItem } from "@/lib/types";

export type BatchPhase = "idle" | "started" | "embedding" | "scoring" | "done" | "error";

interface BatchState {
  phase: BatchPhase;
  total: number;
  items: VerdictItem[];
  counts: Record<Verdict, number>;
  intraDups: IntraBatchDup[];
  summary: Summary | null;
  reportPath: string | null;
  error: string | null;
  /** Rolling per-second throughput samples; last 30 entries. */
  throughput: { t: number; n: number }[];
}

const INITIAL: BatchState = {
  phase: "idle",
  total: 0,
  items: [],
  counts: { REPEAT: 0, NEAR_HIGH: 0, NEAR: 0, NEW: 0 },
  intraDups: [],
  summary: null,
  reportPath: null,
  error: null,
  throughput: [],
};

export function useBatchEvents(batchId: string | null | undefined): BatchState {
  const [state, setState] = useState<BatchState>(INITIAL);
  const lastTickRef = useRef<{ sec: number; count: number } | null>(null);

  useEffect(() => {
    if (!batchId) {
      setState(INITIAL);
      return;
    }
    setState(INITIAL);
    lastTickRef.current = null;

    const unsubscribe = streamBatchEvents(batchId, (ev) => {
      setState((prev) => {
        const next = { ...prev };
        switch (ev.event) {
          case "started":
            next.phase = "started";
            next.total = ev.data.total;
            break;
          case "phase":
            next.phase = ev.data.phase;
            break;
          case "intra_dups":
            next.intraDups = ev.data.groups;
            break;
          case "item": {
            const v = ev.data.item.verdict as Verdict;
            next.items = [ev.data.item, ...prev.items]; // newest first
            next.counts = ev.data.counts;
            // Throughput: bucket per second.
            const sec = Math.floor(Date.now() / 1000);
            if (lastTickRef.current && lastTickRef.current.sec === sec) {
              lastTickRef.current.count += 1;
            } else {
              const t = lastTickRef.current;
              if (t) {
                next.throughput = [...prev.throughput, { t: t.sec, n: t.count }].slice(-30);
              }
              lastTickRef.current = { sec, count: 1 };
            }
            // Silence unused-var warning while keeping the helpful let-binding.
            void v;
            break;
          }
          case "done":
            // Flush any pending throughput sample.
            if (lastTickRef.current) {
              next.throughput = [
                ...prev.throughput,
                { t: lastTickRef.current.sec, n: lastTickRef.current.count },
              ].slice(-30);
              lastTickRef.current = null;
            }
            next.phase = "done";
            next.summary = ev.data.summary;
            next.reportPath = ev.data.report_path;
            break;
          case "error":
            next.phase = "error";
            next.error = ev.data.error;
            break;
          case "ping":
            // keepalive — no UI change
            break;
        }
        return next;
      });
    });

    return unsubscribe;
  }, [batchId]);

  return state;
}
