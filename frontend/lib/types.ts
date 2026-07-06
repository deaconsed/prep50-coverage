/**
 * TypeScript mirrors of the FastAPI Pydantic schemas in api/schemas.py.
 *
 * Keep these in sync — if you change the API response shape, change this too.
 * Source of truth for field meanings: ingestion_batches/*.json on disk.
 */

export type Verdict = "REPEAT" | "NEAR_HIGH" | "NEAR" | "NEW";

export interface Subject {
  id: number;
  name: string;
  tag: string;
  corpus_count: number;
}

export interface CorpusStats {
  total: number;
  by_subject: Record<number, number>;
  model_name: string;
  model_version: string;
  embed_dims: number;
}

export interface InsightSubject {
  id: number;
  name: string;
  tag: string;
  total: number;
  topic_count: number;
  year_min: number | null;
  year_max: number | null;
}

export interface TopicStat {
  topic: string;
  /** Total questions ever asked on this topic. */
  n: number;
  /** Distinct exam years (1990-2026) it appears in. */
  years: number;
  /** Reach in WAEC (tag W or JW). */
  ssce: number;
  /** Reach in UTME (tag J or JW). */
  utme: number;
}

export interface InsightQuestion {
  id: number;
  question: string;
  options: (string | null)[];
  year: number | null;
  /** 0 = WAEC, 1 = UTME, 2 = both. */
  exam: number;
  /** 1-4 = correct option, 0 = unknown. */
  answer: number;
}

export interface InsightQuestions {
  total: number;
  years: number[];
  items: InsightQuestion[];
}

export interface FingerprintMatch {
  question_id: number;
  question_year: number | null;
  question_year_number: number | null;
  text_clean: string;
  option_1: string | null;
  option_2: string | null;
  option_3: string | null;
  option_4: string | null;
}

export interface TopKItem {
  question_id: number;
  cosine: number;
  question_year: number | null;
  question_year_number: number | null;
  text_clean: string;
  fingerprint_match: boolean;
  option_1: string | null;
  option_2: string | null;
  option_3: string | null;
  option_4: string | null;
  /** Gemini's 0-100 score that this candidate asks the same question. */
  ai_score: number | null;
  /** Gemini's one-line reason for the score. */
  ai_reason: string | null;
}

export interface InputData {
  subject_id: number;
  subject_name: string | null;
  question_year: number | null;
  question_raw: string;
  text_clean: string;
  search_fingerprint: string;
  options: (string | null)[];
  short_answer: string | null;
}

export interface VerdictItem {
  input_index: number;
  input_id: string | null;
  input: InputData;
  verdict: Verdict;
  reason: string;
  fingerprint_matches: FingerprintMatch[];
  top_k: TopKItem[];
  reviewer_decision: string | null;
  reviewer_notes: string | null;
  reviewed_at: string | null;
  reviewed_by: string | null;
}

export interface Summary {
  total: number;
  REPEAT: number;
  NEAR_HIGH: number;
  NEAR: number;
  NEW: number;
  by_subject: Record<string, Record<string, number>>;
  intra_batch_duplicate_groups: number;
}

export interface IntraBatchDup {
  search_fingerprint: string;
  input_indices: number[];
}

export interface BatchMeta {
  batch_id: string;
  ingested_at: string;
  source_file: string;
  model_name: string;
  model_version: string;
  embed_dims: number;
  task_type_query: string;
  thresholds: { hard: number; soft: number };
  top_k: number;
  status: string;
}

export interface BatchReport {
  meta: BatchMeta;
  summary: Summary;
  intra_batch_duplicates: IntraBatchDup[];
  items: VerdictItem[];
}

export interface BatchCreated {
  batch_id: string;
  total_questions: number;
  subject_id: number;
  subject_name: string;
}

export interface BatchSummaryRow {
  batch_id: string;
  ingested_at: string;
  subject_id: number | null;
  subject_name: string | null;
  total: number;
  counts: Record<string, number>;
  status: string;
}

export interface SingleCheckRequest {
  question: string;
  subject_id: number;
}

export interface SingleCheckResponse {
  input: InputData;
  verdict: Verdict;
  reason: string;
  fingerprint_matches: FingerprintMatch[];
  top_k: TopKItem[];
}

/** Server-Sent Events streamed from /api/batches/{id}/events. */
export type SseEvent =
  | { event: "started"; data: { total: number } }
  | { event: "phase"; data: { phase: "embedding" | "scoring" } }
  | { event: "intra_dups"; data: { groups: IntraBatchDup[] } }
  | {
      event: "item";
      data: {
        index: number;
        total: number;
        counts: Record<Verdict, number>;
        item: VerdictItem;
      };
    }
  | { event: "done"; data: { summary: Summary; report_path: string } }
  | { event: "error"; data: { error: string } }
  | { event: "ping"; data: Record<string, never> };
