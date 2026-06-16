# Prep50 Vector — Product Plan

Last revised: 2026-06-03

This document is the single reference for what we're building, how the pieces fit, and where the project is in the build order. It supersedes the earlier plan that included classification — that work was done one-time in the upstream project and is OUT of scope here.

---

## 1. Vision

We are building a **WAEC question intelligence layer** on top of an already-classified question corpus. It does **two things**:

### 1.1 Repeat detection ("how much of this year's exam is recycled?")

Given a new WAEC paper (typically ~60 objective questions per subject), produce a report:

> "Of these 60 Physics questions: 18 are exact template repeats of historical questions, 22 are semantic near-duplicates worth flagging, 20 are genuinely new."

This is the primary feature. It runs every time a new paper is acquired. Examiners reuse questions more often than published policy suggests; this tool quantifies that.

### 1.2 Exam prediction ("what is next year's exam likely to contain?")

Based on the multi-year distribution of questions across topics and objectives — plus template-recurrence patterns — produce a forecast per subject:

> "For Physics next year we estimate: 25-30% Mechanics, 18-22% Waves, 10-15% Heat. Top likely-to-recur objectives: [list with probabilities]. Templates with high reuse: [list]."

This is the secondary feature, driven by the same data we use for repeat detection plus the existing classification.

### Scope clarification — what this project does NOT do

- It does **not** classify questions. The 40K-question prod corpus already has `objective_questions` (and through it, `topic_objectives`) populated. We consume that as input.
- It does **not** parse DOCX/PDF intake. New papers arrive as structured CSV from upstream tooling.
- It does **not** manage the taxonomy. Topics, objectives, and their tags are owned by the parent system.

### Users

- **Content team** — uploads each new exam paper, reviews the repeat report, accepts or overrides flagged questions before adding to the corpus.
- **Curriculum analysts** — read the prediction reports to decide where to focus question-bank investment.
- **Internal devs / admins** — operate the pipeline, tune similarity thresholds and prediction parameters.

---

## 2. Architecture at a glance

```
┌─────────────────────────────────────────────────────────┐
│  Production Postgres (prep50, pgvector 0.8.2)           │
│                                                         │
│  Existing (read-only from our perspective):             │
│    subjects, topics, objectives, topic_objectives       │
│    questions, objective_questions                       │
│                                                         │
│  New (this project writes):                             │
│    question_embeddings                                  │
│      - text_clean, search_fingerprint                   │
│      - embedding vector(768)                            │
│      - subject_id, tag, question_year  [denormalized]   │
└────────┬──────────────────────────────────────┬─────────┘
         │ enrich                              │ query
         ▼                                     ▼
┌────────────────────────────┐    ┌──────────────────────────────┐
│  Backfill + ongoing fill   │    │  Repeat detection            │
│  enrich_questions.py       │    │  check_duplicates.py         │
│  - normalize text_clean    │    │  - exact fingerprint match   │
│  - compute fingerprint     │    │  - cosine ANN top-K          │
│  - embed via Gemini        │    │  - REJECT/FLAG/OK per row    │
│  - INSERT                  │    │                              │
└────────────────────────────┘    └──────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│  Exam prediction                                             │
│  predict_next_exam.py                                        │
│   1. Topic share trend per subject (linear regression on     │
│      yearly share). Output: expected share + confidence.     │
│   2. Objective share trend within each topic.                │
│   3. Template recurrence (group by fingerprint, count        │
│      distinct years). Output: high-probability templates.    │
│   4. Hot/cold objectives: rolling 3-year share delta.        │
│                                                              │
│  Output: per-subject prediction JSON consumed by the         │
│  dashboard.                                                  │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│  Intake (a single command for a new exam paper)              │
│  ingest_batch.py                                             │
│   1. Parse CSV of questions for one subject + year.          │
│   2. Normalize, embed.                                       │
│   3. check_duplicates against historical corpus.             │
│   4. Emit batch report.                                      │
│   5. Route: OK → insert into question_embeddings (and        │
│      optionally into prod questions + objective_questions    │
│      after human review); FLAG/REJECT → review queue.        │
└──────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
                  ┌──────────────────────────────┐
                  │  Dashboard tabs              │
                  │   /repeats   batch reports   │
                  │   /predict   prediction view │
                  │   /patterns  distributions   │
                  └──────────────────────────────┘
```

---

## 3. Data model

### Existing prod tables (consumed, not modified)

| Table | What we use it for |
|---|---|
| `questions` | Source of text, year, options, classification linkages. |
| `objective_questions` | Pivot: question → objective. Drives topic via topic_objectives. |
| `topic_objectives` | Pivot: topic → objective. Walked when aggregating per-topic. |
| `topics`, `objectives`, `subjects` | Labels for reports. Filtered to `tag IN ('W','JW')`. |

### New table: `question_embeddings` (only thing this project writes)

Schema in [migrations/prod_001_question_embeddings.sql](migrations/prod_001_question_embeddings.sql).

| Column | Type | Purpose |
|---|---|---|
| `id` | `BIGSERIAL` | pk |
| `question_id` | `BIGINT FK → questions(id)` | parent, ON DELETE CASCADE |
| `subject_id` | `BIGINT` | denorm — fast filter, no JOIN |
| `tag` | `tag` enum | denorm — W/J/JW filter |
| `question_year` | `BIGINT` | denorm — temporal slicing, prediction input |
| `text_clean` | `TEXT` | embedding input |
| `search_fingerprint` | `TEXT` | exact-template SQL lookups |
| `embedding` | `vector(768)` | Gemini text-embedding-005 |
| `model_name`, `model_version` | varchars | provenance for model upgrades |
| `created_at`, `updated_at` | timestamptz | |

Indexes: HNSW on `embedding` (cosine ANN), composite B-trees on `(subject_id, tag)`, `(subject_id, question_year)`, `(subject_id, search_fingerprint)`, plus B-tree on `question_id` (resume marker for enricher). UNIQUE on `(question_id, model_name, model_version)`.

---

## 4. Normalization — deep dive

Two stages per question, both pure Python, deterministic, no AI. Live in [normalize.py](normalize.py).

### Stage A: `text_clean`

Goal: produce the input to the embedding model. Strip presentation noise; preserve semantics.

Rules:
1. Strip HTML tags (`<b>`, `<p>`, `<sub>`, `<sup>`, etc.) but keep inner text.
2. Decode HTML entities (`&amp;`, `&deg;`, `&times;`).
3. Collapse whitespace.
4. Preserve numbers, units, variables, operators, symbols (`x`, `=`, `→`, `π`, `°C`, `kg/m³`).

We do NOT lowercase or strip punctuation at this stage — the embedding model handles those representations internally.

### Stage B: `search_fingerprint`

Goal: a canonical form that catches "same template, different numbers/variable names". When two fingerprints match exactly, we have a high-confidence template repeat.

Rules in order:
1. Lowercase.
2. Canonicalize WAEC stems — "find/calculate/determine/compute/evaluate the value of" → `[stem_value_of]`. Likewise for "which of the following", "solve for x", "if …".
3. Replace numbers with `[num]` (int, decimal, signed, scientific, percentage).
4. Replace standalone single-letter math variables with `[var]` (don't touch words or acronyms).
5. Strip punctuation except `[` and `]`.
6. Collapse whitespace.

Worked example:

| Raw | text_clean | search_fingerprint |
|---|---|---|
| `<p>Find the value of <b>x</b> in 3x + 5 = 20.</p>` | `Find the value of x in 3x + 5 = 20.` | `[stem_value_of] [var] in [num][var] [num] [num]` |
| `Calculate the value of x when 3x + 5 = 20.` | same shape | same fingerprint |
| `Find the value of y when 5y - 2 = 18.` | different numbers/var | **same fingerprint** — caught as repeat |
| `Which of the following is a prime number?` | same | `[stem_which_following] is a prime number` |

The first three examples have **identical fingerprints** even with different numbers and variables — exactly the template-repeat we need to catch.

### Why rule-based, not LLM-based

- **Deterministic** — same input → same fingerprint, every time. SQL exact-match works.
- **Free** — no API cost on a hot path.
- **Fast** — microseconds.
- **Auditable** — read the regex, understand the rule.

LLMs are reserved for the prediction layer (where probabilistic judgement is appropriate). Normalization is plumbing.

### Subject-specific refinement (planned, after first sample)

Likely candidates:

- **Math/Physics** — unit suffix handling (`5kg` vs `5 kg`), fraction normalization.
- **Chemistry** — preserve element symbols (`H2O`, `CO2`) — they ARE content. Today's `[a-z]` rule may bite on `O` or `H` standalone; we add guards.
- **English / Literature** — fewer numbers, more proper nouns; mostly stem canonicalization suffices.
- **CRK / Civic Ed** — simplest, stem rules likely sufficient.

Each rule gets a unit test in `test_normalize.py` so changes are safe.

---

## 5. Embedding strategy

### Model

**Gemini `text-embedding-005`** via Vertex AI.

- 768 dimensions.
- Free up to 5 RPM with a generous monthly cap.
- Same SDK as the parent project's classifier; no new credentials.
- Supports `task_type="RETRIEVAL_DOCUMENT"` (for stored vectors) and `RETRIEVAL_QUERY` (for incoming questions during dup-check). Using the right task type materially affects retrieval quality.

### Input

We embed `text_clean`. The raw HTML carries presentational noise; the fingerprint discards too much content.

### Batching & cost

- 50 inputs per Vertex call.
- ~40K backfill ≈ 800 calls ≈ under 5 minutes when threaded (16 workers).
- Effectively free at our volume.

### Storage and versioning

`vector(768)` column in `question_embeddings`. HNSW index for cosine. The `model_name` + `model_version` columns let us re-embed without dropping old vectors when we upgrade — old version stays queryable, new version coexists, we switch reads only after the new corpus is fully populated and audited.

---

## 6. Repeat detection (primary feature)

### Decision tree per incoming question

```
1. EXACT: search_fingerprint match within same subject?
       YES → REJECT, attach matched question IDs.
       NO  → continue.

2. SEMANTIC: cosine top-5 nearest within same subject (and same tag bucket).
       max similarity ≥ 0.92 → FLAG (hard).
       max similarity 0.80-0.92 → FLAG (soft).
       max similarity < 0.80 → OK.
```

Thresholds tunable, start with these, adjust after observing real-world precision/recall on the first batch.

### SQL shapes

```sql
-- Exact fingerprint within subject
SELECT qe.question_id, q.question, q.question_year
FROM question_embeddings qe
JOIN questions q ON q.id = qe.question_id
WHERE qe.subject_id = $1
  AND qe.search_fingerprint = $2;

-- Semantic top-K (HNSW-backed)
SELECT qe.question_id,
       1 - (qe.embedding <=> $vec::vector(768)) AS cosine,
       q.question, q.question_year
FROM question_embeddings qe
JOIN questions q ON q.id = qe.question_id
WHERE qe.subject_id = $1
  AND qe.tag IN ('W','JW')
ORDER BY qe.embedding <=> $vec
LIMIT 5;
```

### Output shape

```json
{
  "batch_id": "2025_physics",
  "subject": "Physics",
  "total": 60,
  "summary": { "REJECT": 18, "FLAG": 22, "OK": 20 },
  "items": [
    {
      "question_index": 1,
      "question": "Find the value of x in 4x + 3 = 19.",
      "recommendation": "REJECT",
      "exact_matches": [{ "question_id": 12451, "year": 2017, "text_clean": "Find the value of x in 3x + 5 = 20." }],
      "near_matches": []
    },
    {
      "question_index": 2,
      "question": "A 5 kg object falls from rest...",
      "recommendation": "FLAG",
      "exact_matches": [],
      "near_matches": [
        { "question_id": 9123, "year": 2019, "similarity": 0.94, "text_clean": "..." }
      ]
    }
  ]
}
```

This report is the dashboard's input and the content team's source of truth.

---

## 7. Exam prediction (secondary feature)

Built on top of the same data + classification linkages. **No embeddings strictly required** — most of it is SQL aggregation + a thin trend layer.

### Components

1. **Topic share trend per subject**
   - For each (subject, topic), compute yearly question share (proportion of that year's paper assigned to the topic).
   - Fit a simple linear regression (slope = trend). Output: predicted share for next year ± confidence interval.
   - Edge case: gaps (year with no exam). Skip, don't interpolate.

2. **Objective share trend within each topic**
   - Same as above but at objective granularity.
   - Output the top-K objectives by predicted share.

3. **Template recurrence ranking**
   - Group by `search_fingerprint` within subject. Count distinct years it appears.
   - Templates that recurred in ≥ N out of last M years are high-probability candidates for next year.

4. **Hot vs cold objectives**
   - Rolling 3-year share delta per objective.
   - "Hot" = share increased ≥ 5 pp; "Cold" = share decreased ≥ 5 pp; "Stable" = within ±5 pp.

### Output shape (per subject)

```json
{
  "subject": "Physics",
  "predicted_year": 2026,
  "topic_distribution": [
    { "topic_id": 354, "title": "Mechanics", "predicted_share_pct": 27.4, "ci_low": 23.0, "ci_high": 31.8, "trend": "stable" },
    ...
  ],
  "top_objectives": [
    { "objective_id": 1278, "title": "Boyle's Law", "predicted_share_pct": 4.1, "trend": "hot", "yoy_delta_pp": 1.5 },
    ...
  ],
  "high_recurrence_templates": [
    { "fingerprint": "[stem_value_of] [var] in [num][var] [num] [num]", "example": "Find the value of x in 3x + 5 = 20.", "years_observed": [2017, 2019, 2021, 2023], "frequency": 0.8 }
  ],
  "hot_objectives": [...],
  "cold_objectives": [...]
}
```

### Honest disclaimer

This is a forecast based on past examiner behaviour. It can't predict policy changes, new curriculum sections, or anything that breaks the trend. We surface confidence intervals and trend labels prominently so analysts can apply judgement.

---

## 8. Pattern analytics (supports prediction)

Mostly SQL templates wrapped in Python, exported as JSON/CSV. The same data underpins both prediction and analyst-facing reports.

Reports:

1. **Topic distribution by year** — for each subject, % per topic per year.
2. **Objective distribution within a topic**.
3. **Year-over-year drift** — for each objective, share delta vs previous year. Highlight ±20% movements.
4. **Most-repeated templates** — group by fingerprint, count distinct years, sort desc.
5. **Cohort heatmap** — subject × objective × year.
6. **Examiner concentration index** — Gini-like coefficient on the topic-share distribution per year. High = crammed one area; low = balanced.

These reports drive both the dashboard `/patterns` tab AND the inputs to `predict_next_exam.py`.

---

## 9. Intake pipeline

`ingest_batch.py` accepts a CSV of new questions for ONE subject + year:

```
question, option_1, option_2, option_3, option_4, short_answer,
question_year, question_year_number
```

(Subject is supplied via CLI: `--subject 10`.)

Pipeline per question:

1. **Normalize** — `text_clean` + `search_fingerprint`.
2. **Embed** — Gemini `text-embedding-005`, batched 50 at a time, `RETRIEVAL_QUERY` task type.
3. **Repeat-check** — exact fingerprint + cosine ANN as in §6.
4. **Emit batch report** to `batches/<batch_id>/report.json`.

The script does **NOT** automatically insert into prod. New questions stay in the report; a separate human-review step (dashboard `/repeats` page) lets the content team accept, override, or reject before any DB write.

For accepted-new questions, a thin "confirm" endpoint inserts into prod `questions` + `objective_questions` + `question_embeddings` with the year and tag pre-set. (Classification — choosing topic/objective for a new question — is OUT of scope for this project. If a new question can't be matched to an existing objective, the workflow escalates to the original classification tooling in the parent project.)

---

## 10. Dashboard (extends an existing FastAPI app or a new one)

Tabs to add:

### `/repeats`

- List of batches by upload date.
- Per-batch view: report rendered as a table. Each row expandable to show the question, exact/near matches with similarity scores, year of each match, and accept/override/reject buttons.

### `/predict`

- Filter: subject, target year.
- Renders the prediction JSON as a stacked bar (topic share), a table of top objectives with confidence intervals, a list of high-recurrence templates with the fingerprint and example, hot/cold lists.

### `/patterns`

- Filter: subject, year range, topic.
- Renders the pattern reports from §8 as charts.
- Export buttons (CSV, PNG).

Auth: reuse the existing login flow from the parent project (or stand up a minimal one).

---

## 11. Tech stack

| Layer | Choice | Notes |
|---|---|---|
| Prod DB | PostgreSQL 17 + pgvector 0.8.2 | Side table for embeddings. |
| Local dev DB | Postgres 17 + pgvector in Docker (`pgvector/pgvector:pg17`) | Mirrors prod on host port 5433. |
| Backend | FastAPI (new app or fork of parent) | Routes for `/repeats`, `/predict`, `/patterns`, plus accept-question confirm endpoint. |
| Embedding model | Gemini `text-embedding-005` via Vertex AI | 768d, free tier. |
| Prediction | scikit-learn (linear regression) + pandas | Tiny dependency for the trend modeling. |
| Frontend | Server-rendered HTML + lightweight JS / Chart.js | Same style as parent's `/browser`. |
| Data files | JSON / CSV / JSONL | Tracked in git for small reference; gitignored for batch dumps. |

No new infra introduced beyond Docker for local dev.

---

## 12. Build phases (roadmap)

| Phase | Deliverable | Outcome |
|---|---|---|
| **0 (done upstream)** | Corpus is classified + migrated | Prod `questions` + `objective_questions` populated. Assumption, not work in this project. |
| **1 (current)** | Side-table migration + `normalize.py` + sampler test | Schema ready, normalization rules drafted, embedding API validated on 240-question sample. |
| **2** | `enrich_questions.py` backfill | Every prod question has `text_clean` + `search_fingerprint` + `embedding` in `question_embeddings`. ~5 min wall time threaded. |
| **3** | `check_duplicates.py` | Standalone CLI that takes a CSV of new questions (or a single question via stdin) and emits the repeat report. |
| **4** | `patterns/` + `predict_next_exam.py` | SQL analytics + the prediction layer. JSON output consumable by the dashboard. |
| **5** | `ingest_batch.py` | Single-command intake for a new exam paper. End-to-end: normalize → embed → repeat-check → report. |
| **6** | Dashboard tabs `/repeats`, `/predict`, `/patterns` | Reviewer + analyst UI. |
| **7** | Polish | Recovery flows (failed enrichments), audit log, RBAC if multi-user, alerting on prediction-vs-actual drift after each new exam. |

Phases 1-5 are all scripts; Phase 6 is the UI; Phase 7 is operational hardening.

---

## 13. Risks and obstacles

### Data risks

- **Coverage of historical years** — the prediction quality scales with how many years of WAEC data we have classified. If we have only 2-3 years, trend lines are noisy. Mitigation: surface confidence intervals prominently; flag low-data subjects.
- **Sparse subjects** — Mathematics and Security Education have very thin taxonomy data (handful of topics/objectives). Their dup-check and prediction will be coarse. Mitigation: prediction reports flag subjects with < threshold data points.
- **Image-bearing questions** — questions with no `pre50/`-prefixed image path were excluded upstream. For dup-check of new questions with diagrams, text-only embedding may miss visual duplicates. Mitigation: phase 7 explores image embeddings; for now flag manually.

### Pipeline risks

- **AI inconsistency on near-duplicates** — two paraphrases might embed differently enough to slip below 0.92 threshold. The 0.80-0.92 soft-flag band catches most; ongoing threshold tuning required.
- **Threshold drift across subjects** — what "similar" means in Mathematics ≠ Literature. Phase 4 introduces per-subject thresholds if necessary.
- **Network failures during long runs** — scripts are resumable via `question_embeddings.question_id IS NULL` filter; re-runs pick up where they left off.

### Schema risks

- **pgvector availability** — confirmed on prod (0.8.2) and local Docker. Future Postgres major upgrades may require pgvector recompile.
- **Re-embed cost on model upgrade** — `(question_id, model_name, model_version)` uniqueness supports parallel versions, but storage doubles during the transition. Mitigation: documented re-embed runbook with old-version drop after audit period.

### Prediction risks

- **Examiner policy shift** — WAEC could change syllabus weighting; trends become stale. Mitigation: dashboard shows "confidence vs last year's prediction accuracy" — if predictions consistently miss, we know to retrain assumptions.
- **Over-fitting on small samples** — linear regression on 3-4 years per (subject, topic) is unstable. Mitigation: shrinkage toward the global mean for low-sample topics.
- **Survivorship bias** — questions that were rejected or excluded never enter the corpus, biasing the "what examiners pick" signal. Probably minor but worth documenting.

### Operational risks

- **Concurrent ingestion + enrichment** — if a batch ingests while a backfill runs, ordering is fine (separate operations), but Postgres connection load needs monitoring. Mitigation: serialize during initial rollout.
- **Image storage assumptions** — `pre50/` images live on prod S3. If new ingestions include images, an upload step is needed before the question insert (currently a manual step).
- **Embedding cost at scale** — Gemini's free tier covers ~5 RPM. Bulk backfill stays under at 16 threads × 50 inputs = 1 call per ~10 seconds. Brand-new WAEC year drop of 12 subjects × 60 questions = ~720 questions, 14 calls, trivial.

### Maintainability risks

- **No active classifier in this project** — if we ever do need to classify a brand-new question (one with no matching prod objective), we have to dispatch to the parent project. Document this seam.
- **Two project codebases** — the parent (parsing + classification + migration) and this one (vectors + dup + prediction). The boundary is the prod `questions` + `objective_questions` tables. Keep that boundary clean — neither project should silently reach across.

---

## 14. Open questions

1. **Acceptable similarity thresholds per subject** — we start at 0.92 / 0.80 / 0.00 globally. After the first real batch, we tune.
2. **Prediction confidence display** — show CI as a number, a bar, both? Get analyst feedback after first report.
3. **Re-embed cadence** — when Gemini ships text-embedding-006 (expected 2026), do we re-embed all 40K immediately or wait until a meaningful recall gap shows up?
4. **New-question classification** — if a new exam question has no matching existing objective, do we (a) refuse to ingest, (b) auto-create a placeholder, (c) bounce to the parent classification tool? Probably (c) is cleanest; needs documenting.
5. **Image embedding strategy** — for diagram-heavy questions, do we add a parallel `question_image_embeddings` table later? Probably yes, but out of scope until repeat-check on text shows it's needed.

---

## 15. Glossary

| Term | Meaning |
|---|---|
| **subject** | Top-level academic subject (Physics, Biology, ...). |
| **topic** | Broad chapter within a subject (Mechanics, Heat). |
| **objective** | Granular learning point within a subject (Boyle's Law, Projectile Motion). Equivalent to "subtopic" in older docs. |
| **tag** | One of `W` (WAEC), `J` (JAMB), `JW` (both). We use W and JW. |
| **text_clean** | Normalized question text — embedding input. |
| **search_fingerprint** | Canonicalized text — exact-template SQL lookups. |
| **embedding** | 768-dim Gemini vector. |
| **HNSW** | pgvector's preferred ANN index for cosine top-k. |
| **repeat** | Exact-fingerprint match — same template, possibly different numbers/variable names. |
| **near-duplicate** | High-cosine semantic match — same idea, different wording. |
| **review queue** | JSON store of FLAG/REJECT decisions awaiting human triage. |
| **trend** | The slope of a topic or objective's yearly share over time. |
| **recurrence** | How many distinct years a given fingerprint has appeared in. |

---

## 16. Where the code lives

```
PRODUCT_PLAN.md                     # this file
docker-compose.yml                  # local pgvector PG17 container
normalize.py                        # to_clean + to_fingerprint (Phase 1)
enrich_questions.py                 # Phase 2 — to write
check_duplicates.py                 # Phase 3 — to write
patterns/                           # Phase 4 — SQL templates + Python
predict_next_exam.py                # Phase 4 — to write
ingest_batch.py                     # Phase 5 — to write
app.py                              # Phase 6 — to write or fork
migrations/
    prod_001_question_embeddings.sql
scripts/
    apply_prod_migration.py
    inspect_prod_enums.py
    inspect_prod_schema.py
    sample_for_embedding_test.py
test_data/                          # generated samples, gitignored
subjects_link.json                  # for reference if we need to map names
topics.csv, objectives.csv,
topic_objectives.csv,
objective_questions.csv             # taxonomy reference (read-only)
```

---

## 17. Next concrete steps

1. **Apply the migration** to local Docker DB to create `question_embeddings`.
2. **Run `scripts/sample_for_embedding_test.py`** to dump 240 questions worth of embeddings to JSONL and eyeball quality.
3. **Refine `normalize.py`** based on the sample — likely subject-specific tweaks.
4. **Write `enrich_questions.py`** and backfill the local mirror.
5. **Write `check_duplicates.py`**, seed with a known historical question, verify it surfaces.
6. **Run on prod** after local validation.
7. **Phase 4 onward** — pattern analytics, prediction, intake, dashboard.

After Phase 5 we have the core product. Phase 6 makes it usable; Phase 7 makes it operable.
