/**
 * Typed REST client + TanStack Query hooks for the FastAPI backend.
 *
 * The base URL comes from NEXT_PUBLIC_API_URL. Components should prefer the
 * hooks (`useSubjects`, `useCorpusStats`, etc.) over direct calls.
 *
 * SSE consumption lives in `lib/sse.ts` (see streamBatchEvents).
 */
import { useQuery } from "@tanstack/react-query";

import type {
  BatchCreated,
  BatchReport,
  BatchSummaryRow,
  CorpusStats,
  SingleCheckRequest,
  SingleCheckResponse,
  Subject,
} from "./types";

export const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

async function jsonFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText} — ${body}`);
  }
  return (await res.json()) as T;
}

// ── REST helpers ────────────────────────────────────────────────────────────

export async function fetchSubjects(): Promise<Subject[]> {
  return jsonFetch<Subject[]>("/api/subjects");
}

export async function fetchCorpusStats(): Promise<CorpusStats> {
  return jsonFetch<CorpusStats>("/api/corpus/stats");
}

export async function fetchBatches(limit = 50): Promise<BatchSummaryRow[]> {
  return jsonFetch<BatchSummaryRow[]>(`/api/batches?limit=${limit}`);
}

export async function fetchBatch(id: string): Promise<BatchReport> {
  return jsonFetch<BatchReport>(`/api/batches/${id}`);
}

export async function checkSingle(
  req: SingleCheckRequest,
): Promise<SingleCheckResponse> {
  return jsonFetch<SingleCheckResponse>("/api/check-single", {
    method: "POST",
    body: JSON.stringify(req),
  });
}

export async function deleteBatch(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/batches/${id}`, { method: "DELETE" });
  if (!res.ok && res.status !== 204) {
    const body = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText} — ${body}`);
  }
}


export async function createBatch(
  file: File,
  subjectId: number,
): Promise<BatchCreated> {
  const fd = new FormData();
  fd.append("file", file);
  fd.append("subject_id", String(subjectId));
  const res = await fetch(`${API_BASE}/api/batches`, {
    method: "POST",
    body: fd,
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText} — ${body}`);
  }
  return (await res.json()) as BatchCreated;
}

// ── Query hooks ─────────────────────────────────────────────────────────────

export function useSubjects() {
  return useQuery({
    queryKey: ["subjects"],
    queryFn: fetchSubjects,
    staleTime: 60 * 60 * 1000, // 1 hour — subject list rarely changes
  });
}

export function useCorpusStats() {
  return useQuery({
    queryKey: ["corpus", "stats"],
    queryFn: fetchCorpusStats,
    staleTime: 5 * 60 * 1000, // 5 minutes
  });
}

export function useBatches(limit = 50) {
  return useQuery({
    queryKey: ["batches", limit],
    queryFn: () => fetchBatches(limit),
    staleTime: 30 * 1000,
  });
}

export function useBatch(id: string | null | undefined) {
  return useQuery({
    queryKey: ["batches", id],
    queryFn: () => fetchBatch(id!),
    enabled: !!id,
  });
}
