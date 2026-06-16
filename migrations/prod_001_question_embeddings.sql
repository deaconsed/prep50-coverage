-- prod_001_question_embeddings.sql
-- Target: production Postgres (prep50).
-- Adds the question_embeddings side table for normalized text + Gemini embeddings.
--
-- Safe to re-run: every DDL uses IF NOT EXISTS.
-- No changes to the existing `questions` table.

BEGIN;

-- pgvector must be installed by an admin first:
--   CREATE EXTENSION IF NOT EXISTS vector;
-- We don't run that here so a non-superuser can apply this migration.

CREATE TABLE IF NOT EXISTS question_embeddings (
    id                  BIGSERIAL    PRIMARY KEY,
    question_id         BIGINT       NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    -- Denormalized from questions for query-time filtering without JOIN.
    -- These attributes don't change after a question is created.
    subject_id          BIGINT       NOT NULL,
    tag                 tag          NOT NULL,
    question_year       BIGINT,
    -- Derived text artifacts.
    text_clean          TEXT         NOT NULL,
    search_fingerprint  TEXT         NOT NULL,
    -- Embedding + provenance.
    embedding           vector(768)  NOT NULL,
    model_name          VARCHAR(64)  NOT NULL,
    model_version       VARCHAR(32)  NOT NULL,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_qe_question_model UNIQUE (question_id, model_name, model_version)
);

-- Resume marker for the enricher (find questions still needing embeddings).
CREATE INDEX IF NOT EXISTS idx_qe_question_id ON question_embeddings (question_id);

-- Common filter path: subject + tag for scoped duplicate checks.
CREATE INDEX IF NOT EXISTS idx_qe_subject_tag ON question_embeddings (subject_id, tag);

-- Year-scoped queries ("is this 2024 question a repeat of an older one").
CREATE INDEX IF NOT EXISTS idx_qe_subject_year ON question_embeddings (subject_id, question_year);

-- Exact-template lookups within a subject.
CREATE INDEX IF NOT EXISTS idx_qe_subject_fp ON question_embeddings (subject_id, search_fingerprint);

-- Approximate nearest-neighbour search over the embedding vector.
-- HNSW gives sub-second top-k on 100k+ rows; pgvector applies WHERE filters
-- inline so a query like "WHERE subject_id=? ORDER BY embedding <=> ? LIMIT 5"
-- is the fast path.
CREATE INDEX IF NOT EXISTS idx_qe_embedding_hnsw
    ON question_embeddings
    USING hnsw (embedding vector_cosine_ops);

COMMIT;
