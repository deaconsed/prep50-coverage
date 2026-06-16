"""Prep50 Coverage — legacy Streamlit dashboard.

A polished Streamlit interface over the ingestion pipeline.

Run from project root:
    streamlit run dashboard/app.py
"""
import io
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

# Re-use the ingestion pipeline pieces directly. No new logic here — the
# dashboard is just a presentation layer on top of ingest_batch.
from ingest_batch import (  # noqa: E402
    connect_pg, init_genai_client, embed_query_texts, lookup_one,
    verdict_for, find_intra_batch_duplicates, chunked,
    MODEL_NAME, MODEL_VERSION, EMBED_MODEL, EMBED_BATCH,
    TASK_TYPE_QUERY, THRESHOLD_HARD, THRESHOLD_SOFT, EMBED_DIMS,
)
from normalize import to_clean, to_fingerprint  # noqa: E402

# ---------------------------------------------------------------------------
# Page config + global styling
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Prep50 Coverage",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Verdict color tokens (Apple system palette tints — restrained, accent-only).
VERDICT_COLORS = {
    "REPEAT":    {"label": "REPEAT",     "tone": "danger",  "accent": "#ff3b30", "bg": "#ffe5e3", "fg": "#c81100"},
    "NEAR_HIGH": {"label": "NEAR (high)", "tone": "warning", "accent": "#ff9500", "bg": "#fff4e5", "fg": "#b06a00"},
    "NEAR":      {"label": "NEAR",        "tone": "caution", "accent": "#d4a017", "bg": "#fff9d6", "fg": "#8a6d00"},
    "NEW":       {"label": "NEW",         "tone": "success", "accent": "#34c759", "bg": "#dff5e1", "fg": "#1f7a32"},
}

# Modern product-app stylesheet — Vercel/Linear/Stripe-inspired.
# Layered surfaces, confident accent usage, real depth, no chrome, no emojis.
# Font is set on .stApp only so Streamlit's Material Symbols (icon ligatures)
# keep working — overriding font on universal selectors causes "uploadupload"
# style icon bugs.
CUSTOM_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap');

:root {
  --bg:            #ffffff;
  --bg-soft:       #fafafa;
  --surface-1:     #f7f8fa;
  --surface-2:     #eef0f4;
  --surface-3:     #e6e8ee;
  --text:          #0a0a0f;
  --text-2:        #3a3a44;
  --text-3:        #61616b;
  --text-4:        #8a8a93;
  --border:        #e3e5eb;
  --border-strong: #cdd0d8;
  --accent:        #2563eb;
  --accent-hover:  #1d4ed8;
  --accent-deep:   #1e3a8a;
  --accent-tint:   #eff4ff;
  --accent-soft:   #dbeafe;
  --danger:        #e11d48;
  --danger-bg:     #ffe4e6;
  --danger-fg:     #9f1239;
  --warning:       #f59e0b;
  --warning-bg:    #fef3c7;
  --warning-fg:    #92400e;
  --caution:       #d97706;
  --caution-bg:    #fed7aa;
  --caution-fg:    #7c2d12;
  --success:       #10b981;
  --success-bg:    #d1fae5;
  --success-fg:    #065f46;
  --radius-sm:     8px;
  --radius:        12px;
  --radius-lg:     16px;
  --radius-xl:     20px;
  --shadow-sm:     0 1px 2px rgba(15,23,42,0.04), 0 1px 1px rgba(15,23,42,0.03);
  --shadow:        0 2px 4px rgba(15,23,42,0.04), 0 6px 16px rgba(15,23,42,0.06);
  --shadow-lg:     0 4px 8px rgba(15,23,42,0.05), 0 16px 32px rgba(15,23,42,0.10);
  --shadow-accent: 0 4px 14px rgba(37,99,235,0.18), 0 1px 3px rgba(37,99,235,0.10);
}

/* Font ONLY on .stApp — avoids breaking Material Symbols icon ligatures. */
.stApp {
  background-color: var(--bg-soft);
  background-image:
    radial-gradient(60% 50% at 50% -10%, rgba(37,99,235,0.06) 0%, transparent 60%),
    linear-gradient(180deg, #ffffff 0%, var(--bg-soft) 280px);
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  color: var(--text);
}

.main .block-container {
  max-width: 1200px;
  padding-top: 2.5rem;
  padding-bottom: 4rem;
}

/* Headings */
.stApp h1, .stApp h2, .stApp h3, .stApp h4 {
  font-family: 'Inter', sans-serif;
  letter-spacing: -0.025em;
  font-weight: 700;
  color: var(--text);
}
.stApp h2 { font-size: 22px; line-height: 1.25; margin: 1.4rem 0 0.6rem 0; font-weight: 700; }
.stApp h3 { font-size: 17px; line-height: 1.3; margin: 1.2rem 0 0.4rem 0; font-weight: 600; }

.stMarkdown p, .stMarkdown li { font-size: 15px; line-height: 1.6; color: var(--text-2); }

/* ── Hero / Header ─────────────────────────────────────────────────────── */
.app-header {
  background: linear-gradient(180deg, #ffffff 0%, var(--bg) 100%);
  border: 1px solid var(--border);
  border-radius: var(--radius-xl);
  padding: 36px 40px;
  margin: 0 0 28px 0;
  box-shadow: var(--shadow);
  position: relative;
  overflow: hidden;
}
.app-header::before {
  content: ""; position: absolute; right: -120px; top: -120px;
  width: 360px; height: 360px; border-radius: 999px;
  background: radial-gradient(circle, rgba(37,99,235,0.10) 0%, transparent 70%);
  pointer-events: none;
}
.app-header .eyebrow {
  display: inline-flex; align-items: center; gap: 8px;
  font-size: 11.5px; font-weight: 700; letter-spacing: 0.14em; text-transform: uppercase;
  color: var(--accent);
  background: var(--accent-tint);
  padding: 5px 11px; border-radius: 999px;
  margin-bottom: 18px;
  border: 1px solid var(--accent-soft);
}
.app-header .eyebrow .pulse {
  width: 7px; height: 7px; border-radius: 999px; background: var(--accent);
  box-shadow: 0 0 0 0 rgba(37,99,235, 0.6);
  animation: pulse 2.4s infinite;
}
@keyframes pulse {
  0% { box-shadow: 0 0 0 0 rgba(37,99,235, 0.6); }
  70% { box-shadow: 0 0 0 8px rgba(37,99,235, 0); }
  100% { box-shadow: 0 0 0 0 rgba(37,99,235, 0); }
}
.app-header h1 {
  font-size: 40px; line-height: 1.08; letter-spacing: -0.032em; font-weight: 800;
  color: var(--text); margin: 0 0 12px 0;
  max-width: 760px;
}
.app-header h1 .accent {
  background: linear-gradient(135deg, var(--accent) 0%, #7c3aed 100%);
  -webkit-background-clip: text; background-clip: text;
  -webkit-text-fill-color: transparent;
}
.app-header .subtitle {
  font-size: 16.5px; color: var(--text-3); line-height: 1.55;
  max-width: 660px; margin: 0;
}
.app-header .stats-row {
  display: flex; gap: 12px; margin-top: 22px; flex-wrap: wrap;
}
.app-header .stat-chip {
  display: inline-flex; flex-direction: column;
  background: var(--bg); border: 1px solid var(--border);
  padding: 10px 16px; border-radius: var(--radius);
  box-shadow: var(--shadow-sm);
  min-width: 140px;
}
.app-header .stat-chip .label {
  font-size: 11px; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase;
  color: var(--text-4); margin-bottom: 4px;
}
.app-header .stat-chip .value {
  font-size: 22px; font-weight: 700; color: var(--text);
  font-variant-numeric: tabular-nums; line-height: 1.1;
  letter-spacing: -0.02em;
}
.app-header .stat-chip .value .unit {
  font-size: 13px; color: var(--text-3); font-weight: 500; margin-left: 4px;
}

/* ── Stepper ───────────────────────────────────────────────────────────── */
.stepper {
  display: flex; align-items: center; gap: 4px;
  margin: 8px 0 32px 0;
}
.stepper .step {
  display: flex; align-items: center; gap: 10px;
  padding: 9px 16px; background: var(--bg);
  border-radius: 999px; border: 1px solid var(--border);
  font-size: 13.5px; font-weight: 600; color: var(--text-3);
  box-shadow: var(--shadow-sm);
  transition: all 0.18s ease;
}
.stepper .step.active {
  background: var(--accent); color: white;
  border-color: var(--accent);
  box-shadow: var(--shadow-accent);
}
.stepper .step.done {
  background: var(--accent-tint); color: var(--accent);
  border-color: var(--accent-soft);
}
.stepper .step .num {
  display: inline-flex; align-items: center; justify-content: center;
  width: 22px; height: 22px; border-radius: 999px;
  background: var(--surface-2); color: var(--text-3); font-weight: 700;
  font-size: 12px;
}
.stepper .step.active .num { background: rgba(255,255,255,0.25); color: white; }
.stepper .step.done .num { background: var(--accent); color: white; }
.stepper .connector {
  width: 36px; height: 2px; background: var(--border);
  margin: 0 -2px; align-self: center;
}
.stepper .connector.done { background: var(--accent-soft); }

/* ── Section labels ────────────────────────────────────────────────────── */
.section-label {
  font-size: 11px; font-weight: 700; letter-spacing: 0.14em;
  text-transform: uppercase; color: var(--text-4);
  margin: 28px 0 12px 0;
  display: flex; align-items: center; gap: 10px;
}
.section-label::after {
  content: ""; flex: 1; height: 1px; background: var(--border);
}

/* ── Cards ─────────────────────────────────────────────────────────────── */
.card {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 22px 24px;
  box-shadow: var(--shadow);
  transition: box-shadow 0.18s ease, transform 0.18s ease, border-color 0.18s ease;
}
.card:hover {
  box-shadow: var(--shadow-lg);
  border-color: var(--border-strong);
}
.card-accent {
  background: linear-gradient(135deg, var(--accent-tint) 0%, var(--bg) 100%);
  border: 1px solid var(--accent-soft);
}
.card-title {
  font-size: 16px; font-weight: 700; color: var(--text);
  margin: 0 0 6px 0; letter-spacing: -0.01em;
}
.card-desc {
  font-size: 13.5px; color: var(--text-3); line-height: 1.55;
  margin: 0 0 16px 0;
}

/* ── Verdict badge ─────────────────────────────────────────────────────── */
.verdict-badge {
  display: inline-flex; align-items: center; gap: 7px;
  padding: 4px 12px; border-radius: 999px;
  font-size: 11.5px; font-weight: 700; letter-spacing: 0.06em;
  border: 1px solid transparent;
}
.verdict-badge .dot {
  width: 7px; height: 7px; border-radius: 999px;
}

/* ── Verdict card (result item) ───────────────────────────────────────── */
.verdict-card {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 20px 24px;
  margin-bottom: 14px;
  box-shadow: var(--shadow-sm);
  transition: box-shadow 0.18s ease, transform 0.18s ease, border-color 0.18s ease;
  position: relative;
  overflow: hidden;
}
.verdict-card::before {
  content: ""; position: absolute; left: 0; top: 0; bottom: 0;
  width: 4px; background: var(--card-accent, var(--border));
}
.verdict-card.repeat::before     { background: var(--danger); }
.verdict-card.near-high::before  { background: var(--warning); }
.verdict-card.near::before       { background: var(--caution); }
.verdict-card.new::before        { background: var(--success); }
.verdict-card:hover { box-shadow: var(--shadow); transform: translateY(-1px); }
.verdict-card .row-top {
  display: flex; justify-content: space-between; align-items: center;
  gap: 16px; margin-bottom: 12px;
}
.verdict-card .row-meta {
  font-size: 12.5px; color: var(--text-4); font-variant-numeric: tabular-nums;
}
.verdict-card .q-label {
  font-size: 10.5px; font-weight: 700; letter-spacing: 0.12em;
  text-transform: uppercase; color: var(--text-4); margin-bottom: 5px;
}
.verdict-card .q-text {
  font-size: 15px; line-height: 1.55; color: var(--text); margin: 0;
}
.verdict-card .match {
  margin-top: 16px; padding: 16px 18px;
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: var(--radius);
}
.verdict-card .match .meta {
  font-size: 12px; color: var(--text-3);
  display: flex; align-items: center; gap: 10px; margin-bottom: 8px;
  flex-wrap: wrap;
}
.verdict-card .match .q-text { font-size: 14.5px; color: var(--text-2); }
.qmeta { color: var(--danger); font-style: italic; font-weight: 600; }

/* ── Pills inside cards ────────────────────────────────────────────────── */
.cosine-pill {
  display: inline-block; background: var(--text); color: white;
  padding: 2px 10px; border-radius: 999px;
  font-family: 'JetBrains Mono', ui-monospace, "SF Mono", Menlo, Consolas, monospace;
  font-size: 11.5px; font-variant-numeric: tabular-nums; font-weight: 500;
}
.fp-pill {
  display: inline-block; background: var(--danger); color: white;
  padding: 2px 10px; border-radius: 999px;
  font-size: 11px; font-weight: 600;
  box-shadow: 0 1px 2px rgba(225,29,72,0.25);
}

/* ── Metric cards ──────────────────────────────────────────────────────── */
[data-testid="stMetric"] {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 20px 22px;
  box-shadow: var(--shadow);
  position: relative;
  overflow: hidden;
}
[data-testid="stMetric"]::before {
  content: ""; position: absolute; left: 0; top: 0; right: 0; height: 3px;
  background: linear-gradient(90deg, var(--accent) 0%, #7c3aed 100%);
  opacity: 0.6;
}
[data-testid="stMetricLabel"] {
  font-size: 11.5px !important; font-weight: 700 !important;
  letter-spacing: 0.10em !important; text-transform: uppercase !important;
  color: var(--text-3) !important;
}
[data-testid="stMetricValue"] {
  font-size: 38px !important; font-weight: 800 !important;
  color: var(--text) !important; letter-spacing: -0.03em !important;
  font-variant-numeric: tabular-nums !important; line-height: 1.05 !important;
}

/* ── Buttons ───────────────────────────────────────────────────────────── */
.stButton > button, .stDownloadButton > button {
  border-radius: var(--radius) !important;
  font-weight: 600 !important;
  font-size: 14.5px !important;
  padding: 0.7rem 1.5rem !important;
  border: 1px solid var(--border) !important;
  background: var(--bg) !important;
  color: var(--text) !important;
  transition: all 0.15s ease !important;
  box-shadow: var(--shadow-sm) !important;
  letter-spacing: -0.005em !important;
}
.stButton > button:hover, .stDownloadButton > button:hover {
  background: var(--surface-1) !important;
  border-color: var(--border-strong) !important;
  color: var(--text) !important;
  transform: translateY(-1px);
  box-shadow: var(--shadow) !important;
}
.stButton > button[kind="primary"] {
  background: var(--accent) !important;
  color: white !important;
  border-color: var(--accent) !important;
  box-shadow: var(--shadow-accent) !important;
}
.stButton > button[kind="primary"]:hover {
  background: var(--accent-hover) !important;
  border-color: var(--accent-hover) !important;
  transform: translateY(-1px);
}

/* ── File uploader ─────────────────────────────────────────────────────── */
[data-testid="stFileUploaderDropzone"] {
  background: var(--surface-1) !important;
  border: 2px dashed var(--border-strong) !important;
  border-radius: var(--radius-lg) !important;
  transition: all 0.18s ease;
  padding: 32px 24px !important;
  min-height: 180px;
}
[data-testid="stFileUploaderDropzone"]:hover {
  border-color: var(--accent) !important;
  background: var(--accent-tint) !important;
}
[data-testid="stFileUploaderDropzoneInstructions"] { color: var(--text-2) !important; }

/* ── Selectbox ─────────────────────────────────────────────────────────── */
[data-baseweb="select"] > div {
  border-radius: var(--radius) !important;
  border: 1px solid var(--border) !important;
  background: var(--bg) !important;
  box-shadow: var(--shadow-sm) !important;
  min-height: 46px !important;
}
[data-baseweb="select"] > div:hover { border-color: var(--border-strong) !important; }

/* ── Expander ──────────────────────────────────────────────────────────── */
[data-testid="stExpander"] {
  border: 1px solid var(--border) !important;
  border-radius: var(--radius-lg) !important;
  background: var(--bg) !important;
  box-shadow: var(--shadow-sm) !important;
  margin-bottom: 10px;
  overflow: hidden;
}
[data-testid="stExpander"] summary {
  padding: 16px 20px !important;
  font-weight: 600 !important;
  font-size: 14px !important;
  color: var(--text) !important;
}
[data-testid="stExpander"] summary:hover { background: var(--surface-1) !important; }

/* ── Progress bar ──────────────────────────────────────────────────────── */
[data-testid="stProgress"] > div > div > div {
  background: var(--surface-2) !important;
  border-radius: 999px !important;
  height: 6px !important;
}
[data-testid="stProgress"] > div > div > div > div {
  background: linear-gradient(90deg, var(--accent) 0%, #7c3aed 100%) !important;
  border-radius: 999px !important;
}

/* ── Info / warning / error boxes ──────────────────────────────────────── */
[data-testid="stAlert"] {
  border-radius: var(--radius) !important;
  border: 1px solid var(--border) !important;
  background: var(--surface-1) !important;
  box-shadow: var(--shadow-sm) !important;
}

/* ── Captions / dividers ───────────────────────────────────────────────── */
.stCaption, [data-testid="stCaptionContainer"] {
  color: var(--text-4) !important; font-size: 12.5px !important;
}
hr { border: 0; border-top: 1px solid var(--border); margin: 1.8rem 0; }

/* ── Dataframe ─────────────────────────────────────────────────────────── */
[data-testid="stDataFrame"] {
  border-radius: var(--radius) !important;
  border: 1px solid var(--border) !important;
  overflow: hidden;
  box-shadow: var(--shadow-sm);
}

/* ── Utility ───────────────────────────────────────────────────────────── */
.muted { color: var(--text-4); font-size: 13px; }
.muted-sm { color: var(--text-4); font-size: 12px; }
.tabular { font-variant-numeric: tabular-nums; }
.tag-inline {
  display: inline-block; background: var(--surface-2); color: var(--text-2);
  padding: 1px 8px; border-radius: 6px; font-family: 'JetBrains Mono', monospace;
  font-size: 12px; border: 1px solid var(--border);
}
.tag-required { background: var(--accent-tint); color: var(--accent-deep); border-color: var(--accent-soft); }
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Cached resources
# ---------------------------------------------------------------------------

@st.cache_resource
def _make_db_conn():
    """Underlying cached connection. Wrap with get_db_conn() to ensure liveness."""
    return connect_pg()


def get_db_conn():
    """Return a live connection.

    DigitalOcean managed Postgres closes idle connections after ~30s.
    Streamlit's @st.cache_resource keeps reusing the same connect_pg() result,
    so a session that sits idle (e.g. user picking a subject) will hand us a
    dead handle. Detect that and reconnect.
    """
    import psycopg2 as _pg
    conn = _make_db_conn()
    if not conn.closed:
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            return conn
        except (_pg.InterfaceError, _pg.OperationalError):
            pass
    # Stale or dead — drop the cache entry and reconnect.
    _make_db_conn.clear()
    return _make_db_conn()


@st.cache_resource
def get_vertex_client():
    return init_genai_client()


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_subjects():
    conn = get_db_conn()
    with conn.cursor() as cur:
        cur.execute("SELECT id, name, tag FROM subjects WHERE tag IN ('W','JW') ORDER BY name;")
        rows = cur.fetchall()
    return [{"id": r[0], "name": r[1], "tag": str(r[2])} for r in rows]


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_corpus_stats():
    conn = get_db_conn()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM question_embeddings WHERE model_name=%s AND model_version=%s",
            (MODEL_NAME, MODEL_VERSION),
        )
        total = cur.fetchone()[0]
        cur.execute(
            "SELECT subject_id, COUNT(*) FROM question_embeddings "
            "WHERE model_name=%s AND model_version=%s GROUP BY subject_id",
            (MODEL_NAME, MODEL_VERSION),
        )
        by_subj = {r[0]: r[1] for r in cur.fetchall()}
    return {"total": total, "by_subject": by_subj}


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------

def reset_state():
    for k in ("step", "df", "subject", "result_items", "summary", "intra_dups",
             "batch_id", "results_report", "report_path", "q_col"):
        st.session_state.pop(k, None)


if "step" not in st.session_state:
    st.session_state.step = "upload"


# ---------------------------------------------------------------------------
# UI rendering helpers
# ---------------------------------------------------------------------------

def render_header(corpus_total):
    st.markdown(
        f"""
        <div class="app-header">
          <div class="eyebrow"><span class="pulse"></span>Prep50 · Coverage</div>
          <h1>Verify every new exam paper<br/>against the <span class="accent">WAEC corpus</span>.</h1>
          <p class="subtitle">
            New questions are normalized, embedded with Gemini text-embedding-005,
            and checked against the full historical corpus using semantic similarity
            plus exact-template matching.
          </p>
          <div class="stats-row">
            <div class="stat-chip">
              <div class="label">Historical questions</div>
              <div class="value">{corpus_total:,}</div>
            </div>
            <div class="stat-chip">
              <div class="label">Embedding model</div>
              <div class="value" style="font-size:15px; font-weight:600;">text-embedding-005</div>
            </div>
            <div class="stat-chip">
              <div class="label">Vector dimensions</div>
              <div class="value">768<span class="unit">d</span></div>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_stepper(current: str):
    """current ∈ {'upload','processing','done'}"""
    steps = [("upload", "Upload"), ("processing", "Check"), ("done", "Review")]
    order = {k: i for i, (k, _) in enumerate(steps)}
    cur_i = order[current]
    parts = []
    for i, (k, label) in enumerate(steps):
        if i < cur_i:
            cls = "step done"
        elif i == cur_i:
            cls = "step active"
        else:
            cls = "step"
        parts.append(f'<div class="{cls}"><span class="num">{i+1}</span>{label}</div>')
        if i < len(steps) - 1:
            conn_cls = "connector done" if i < cur_i else "connector"
            parts.append(f'<div class="{conn_cls}"></div>')
    st.markdown(f'<div class="stepper">{"".join(parts)}</div>', unsafe_allow_html=True)


def render_verdict_badge(verdict):
    c = VERDICT_COLORS[verdict]
    return (
        f'<span class="verdict-badge" '
        f'style="background:{c["bg"]}; color:{c["fg"]};">'
        f'<span class="dot" style="background:{c["accent"]}"></span>'
        f'{c["label"]}</span>'
    )


_VERDICT_CARD_CLASS = {
    "REPEAT": "repeat",
    "NEAR_HIGH": "near-high",
    "NEAR": "near",
    "NEW": "new",
}


def render_item_card(item, idx, total):
    v = item["verdict"]
    card_cls = _VERDICT_CARD_CLASS[v]
    top1 = item["top_k"][0] if item["top_k"] else None
    qpreview = item["input"]["question_raw"][:240] + ("…" if len(item["input"]["question_raw"]) > 240 else "")

    top_match_html = ""
    if v != "NEW" and top1:
        cos_pct = f"{top1['cosine']:.3f}"
        fp_badge = '<span class="fp-pill">fingerprint match</span>' if top1.get("fingerprint_match") else ""
        match_preview = top1["text_clean"][:240] + ("…" if len(top1["text_clean"]) > 240 else "")
        year = top1.get("question_year") or "—"
        qnum = top1.get("question_year_number")
        year_lbl = f"{year}, Q{qnum}" if qnum else f"{year}"
        top_match_html = f"""
        <div class="match">
            <div class="meta">
                <span>Matched historical question · id {top1['question_id']} · year <strong>{year_lbl}</strong></span>
                <span class="cosine-pill">cosine {cos_pct}</span>
                {fp_badge}
            </div>
            <p class="q-text">{match_preview} <span class="qmeta">({year_lbl})</span></p>
        </div>
        """

    st.markdown(
        f"""
        <div class="verdict-card {card_cls}">
            <div class="row-top">
                <div>
                    {render_verdict_badge(v)}
                    <span class="muted" style="margin-left:10px;">Question {idx} of {total}</span>
                </div>
                <div class="row-meta">{item['reason']}</div>
            </div>
            <div class="q-label">New question</div>
            <p class="q-text">{qpreview}</p>
            {top_match_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Step: Upload
# ---------------------------------------------------------------------------

def step_upload(subjects, corpus_stats):
    render_stepper("upload")

    st.markdown('<div class="section-label">Upload</div>', unsafe_allow_html=True)
    st.markdown("Provide a CSV with the new exam questions. Each row is one question.")

    col_l, col_r = st.columns([3, 2], gap="large")

    with col_l:
        uploaded = st.file_uploader(
            "Drop a CSV here, or click to browse",
            type=["csv"],
            help="The CSV must have a 'question' column. Other columns are optional.",
            label_visibility="visible",
        )

    with col_r:
        template_bytes = (ROOT / "dashboard" / "template.csv").read_bytes()
        st.markdown(
            """
            <div class="card card-accent">
              <div class="card-title">Need a starting point?</div>
              <div class="card-desc">
                Download a template with the expected columns and five sample rows.
                Edit it in Excel or any text editor, then drop it back in here.
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.download_button(
            label="Download template CSV",
            data=template_bytes,
            file_name="prep50_question_template.csv",
            mime="text/csv",
            use_container_width=True,
        )
        st.markdown(
            '<div style="margin-top:18px; font-size:12.5px; line-height:1.9;">'
            '<div><span class="muted-sm" style="font-weight:600; text-transform:uppercase; letter-spacing:0.08em;">Required</span>&nbsp;&nbsp;'
            '<span class="tag-inline tag-required">question</span></div>'
            '<div style="margin-top:6px;"><span class="muted-sm" style="font-weight:600; text-transform:uppercase; letter-spacing:0.08em;">Optional</span>&nbsp;&nbsp;'
            '<span class="tag-inline">question_year</span> '
            '<span class="tag-inline">option_1</span> '
            '<span class="tag-inline">…</span> '
            '<span class="tag-inline">option_4</span> '
            '<span class="tag-inline">short_answer</span></div>'
            '</div>',
            unsafe_allow_html=True,
        )

    if uploaded is None:
        return

    # Excel on Windows defaults to saving CSV as Windows-1252 (cp1252), not
    # UTF-8 — its smart quotes become byte 0x92 which UTF-8 rejects. Try the
    # common encodings in order; latin-1 never fails (every byte is valid).
    df = None
    last_err = None
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            uploaded.seek(0)
            df = pd.read_csv(uploaded, encoding=enc)
            if enc not in ("utf-8", "utf-8-sig"):
                st.info(
                    f"CSV was not UTF-8 — read it as `{enc}` instead. "
                    "Tip: in Excel, save as 'CSV UTF-8 (Comma delimited)' to avoid surprises."
                )
            break
        except UnicodeDecodeError as e:
            last_err = e
            continue
        except Exception as e:
            st.error(f"Could not read CSV: {e}")
            return
    if df is None:
        st.error(f"Could not decode CSV with utf-8 / cp1252 / latin-1. Last error: {last_err}")
        return

    df.columns = [c.strip() for c in df.columns]
    df_cols_lower = {c.lower(): c for c in df.columns}
    if "question" not in df_cols_lower:
        st.error("CSV is missing a 'question' column.")
        st.dataframe(df.head())
        return
    q_col = df_cols_lower["question"]
    df = df[df[q_col].astype(str).str.strip() != ""].reset_index(drop=True)
    if df.empty:
        st.error("CSV has no usable rows (all question cells are empty).")
        return

    st.success(f"Loaded {len(df)} questions from {uploaded.name}")

    st.markdown('<div class="section-label">Subject</div>', unsafe_allow_html=True)
    subj_idx = st.selectbox(
        "These questions belong to which subject?",
        options=list(range(len(subjects))),
        format_func=lambda i: f"{subjects[i]['name']}  ·  {subjects[i]['tag']}  ·  "
                              f"{corpus_stats['by_subject'].get(subjects[i]['id'], 0):,} historical questions",
        index=None,
        placeholder="Select a subject…",
    )
    if subj_idx is None:
        return

    subject = subjects[subj_idx]
    pool = corpus_stats["by_subject"].get(subject["id"], 0)
    st.markdown(
        f"""
        <div class="bordered-card" style="background:var(--surface-1);">
          <div style="font-size:14px; color:var(--text-2); line-height:1.55;">
            Each of the <strong style="color:var(--text);">{len(df)} new questions</strong>
            will be checked against
            <strong style="color:var(--text);">{pool:,} historical {subject['name']} questions</strong>
            using semantic embeddings and fingerprint matching.
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<div class="section-label">Preview</div>', unsafe_allow_html=True)
    preview_cols = [q_col] + [c for c in ["question_year", "option_1", "option_2", "option_3", "option_4", "short_answer"]
                              if c in df.columns]
    st.dataframe(df[preview_cols].head(10), use_container_width=True, hide_index=True)
    if len(df) > 10:
        st.caption(f"Showing first 10 of {len(df)} rows.")

    st.markdown('<br>', unsafe_allow_html=True)
    if st.button("Run coverage check", type="primary", use_container_width=True):
        st.session_state.df = df
        st.session_state.q_col = q_col
        st.session_state.subject = subject
        st.session_state.step = "processing"
        st.session_state.batch_id = (
            f"ingest_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_"
            f"{uuid.uuid4().hex[:6]}"
        )
        st.rerun()


# ---------------------------------------------------------------------------
# Step: Processing (the live-update centerpiece)
# ---------------------------------------------------------------------------

def step_processing(subjects_by_id):
    df = st.session_state.df
    q_col = st.session_state.q_col
    subject = st.session_state.subject

    render_stepper("processing")
    st.markdown(
        f'<h2>Checking {len(df)} questions · {subject["name"]}</h2>',
        unsafe_allow_html=True,
    )

    # Normalize.
    inputs = []
    for i, row in df.reset_index(drop=True).iterrows():
        raw = str(row[q_col])
        inputs.append({
            "input_index": int(i),
            "input_id": str(row["id"]) if "id" in df.columns and pd.notna(row.get("id")) else None,
            "subject_id": subject["id"],
            "question_year": int(row["question_year"]) if "question_year" in df.columns and pd.notna(row.get("question_year")) else None,
            "question_raw": raw,
            "options": [row.get(f"option_{k}") for k in range(1, 5) if f"option_{k}" in df.columns],
            "short_answer": row.get("short_answer") if "short_answer" in df.columns else None,
            "text_clean": to_clean(raw),
            "search_fingerprint": to_fingerprint(to_clean(raw)),
        })

    intra_dups = find_intra_batch_duplicates(inputs)

    # Embed all queries upfront — fast batched call (~5s for 60 questions).
    embed_status = st.empty()
    embed_status.info(f"Embedding {len(inputs)} questions with Vertex AI · model {EMBED_MODEL}")
    client = get_vertex_client()
    for batch in chunked(inputs, EMBED_BATCH):
        with_text = [r for r in batch if r["text_clean"].strip()]
        if not with_text:
            continue
        vectors = embed_query_texts(client, [r["text_clean"] for r in with_text])
        for r, v in zip(with_text, vectors):
            r["embedding"] = v
    embed_status.empty()

    # Live metrics + progress.
    st.markdown('<div class="section-label">Live tally</div>', unsafe_allow_html=True)
    metric_cols = st.columns(4)
    metric_slots = {}
    for v, col in zip(("REPEAT", "NEAR_HIGH", "NEAR", "NEW"), metric_cols):
        with col:
            metric_slots[v] = st.empty()
            metric_slots[v].metric(VERDICT_COLORS[v]["label"], 0)

    progress = st.progress(0, text="Starting…")
    current_q = st.empty()
    st.markdown('<div class="section-label">Live results</div>', unsafe_allow_html=True)
    results_stream = st.container()

    # Loop: per question fingerprint + ANN lookup. Display + throttle.
    items = []
    counts = {"REPEAT": 0, "NEAR_HIGH": 0, "NEAR": 0, "NEW": 0}
    conn = get_db_conn()

    THROTTLE_MIN_S = 0.15  # ensures the audience can actually see each card appear

    import psycopg2 as _pg

    def _lookup_with_retry(r):
        """Run lookup_one; on a stale-connection error, reconnect once and retry."""
        nonlocal conn
        try:
            return lookup_one(
                conn, r["subject_id"], r["search_fingerprint"], r["embedding"], top_k=5
            )
        except (_pg.InterfaceError, _pg.OperationalError):
            # Server-side idle timeout or transient drop — get a fresh connection.
            _make_db_conn.clear()
            conn = get_db_conn()
            return lookup_one(
                conn, r["subject_id"], r["search_fingerprint"], r["embedding"], top_k=5
            )

    for i, r in enumerate(inputs):
        loop_start = time.time()
        if "embedding" not in r:
            verdict, reason = "NEW", "empty text after normalization"
            fp_hits, ann = [], []
        else:
            fp_hits, ann = _lookup_with_retry(r)
            verdict, reason = verdict_for(fp_hits, ann, THRESHOLD_HARD, THRESHOLD_SOFT)

        item = {
            "input_index": r["input_index"],
            "input_id": r["input_id"],
            "input": {
                "subject_id": r["subject_id"],
                "subject_name": subject["name"],
                "question_year": r["question_year"],
                "question_raw": r["question_raw"],
                "text_clean": r["text_clean"],
                "search_fingerprint": r["search_fingerprint"],
                "options": r["options"],
                "short_answer": r["short_answer"],
            },
            "verdict": verdict,
            "reason": reason,
            "fingerprint_matches": [
                {"question_id": h["question_id"], "question_year": h["question_year"],
                 "question_year_number": h.get("question_year_number"),
                 "text_clean": h["text_clean"]} for h in fp_hits
            ],
            "top_k": [
                {"question_id": a["question_id"], "cosine": float(a["cosine"]),
                 "question_year": a["question_year"],
                 "question_year_number": a.get("question_year_number"),
                 "text_clean": a["text_clean"],
                 "fingerprint_match": a["question_id"] in {h["question_id"] for h in fp_hits}}
                for a in ann
            ],
            "query_embedding": r.get("embedding"),
            "reviewer_decision": None,
            "reviewer_notes": None,
            "reviewed_at": None,
            "reviewed_by": None,
        }
        items.append(item)
        counts[verdict] += 1

        # Update live UI.
        for v in counts:
            metric_slots[v].metric(VERDICT_COLORS[v]["label"], counts[v])
        progress.progress((i + 1) / len(inputs), text=f"Checked {i + 1} of {len(inputs)}")
        current_q.markdown(
            f'<div class="muted">Just checked · {r["question_raw"][:160]}…</div>',
            unsafe_allow_html=True,
        )

        # Stream the new card at the top of the results list.
        with results_stream:
            placeholder = st.container()
            with placeholder:
                render_item_card(item, idx=i + 1, total=len(inputs))

        elapsed = time.time() - loop_start
        if elapsed < THROTTLE_MIN_S:
            time.sleep(THROTTLE_MIN_S - elapsed)

    # Persist report + summary, then advance.
    summary = {"total": len(items), **counts, "by_subject": {
        subject["name"]: {"total": len(items), **counts}
    }, "intra_batch_duplicate_groups": len(intra_dups)}

    report = {
        "meta": {
            "batch_id": st.session_state.batch_id,
            "ingested_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source_file": "dashboard upload",
            "model_name": MODEL_NAME, "model_version": MODEL_VERSION,
            "embed_dims": EMBED_DIMS, "task_type_query": TASK_TYPE_QUERY,
            "thresholds": {"hard": THRESHOLD_HARD, "soft": THRESHOLD_SOFT},
            "top_k": 5, "status": "pending_review",
        },
        "summary": summary,
        "intra_batch_duplicates": intra_dups,
        "items": items,
    }

    # Save report to disk.
    ingest_dir = ROOT / "ingestion_batches"
    ingest_dir.mkdir(exist_ok=True)
    out_path = ingest_dir / f"{st.session_state.batch_id}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)

    st.session_state.result_items = items
    st.session_state.summary = summary
    st.session_state.intra_dups = intra_dups
    st.session_state.results_report = report
    st.session_state.report_path = str(out_path)
    st.session_state.step = "done"
    time.sleep(0.3)
    st.rerun()


# ---------------------------------------------------------------------------
# Step: Done — summary + filterable detail
# ---------------------------------------------------------------------------

def step_done():
    summary = st.session_state.summary
    items = st.session_state.result_items
    subject = st.session_state.subject
    intra_dups = st.session_state.intra_dups

    render_stepper("done")

    # Summary banner.
    st.markdown('<div class="section-label">Results</div>', unsafe_allow_html=True)
    cols = st.columns(4)
    for v, col in zip(("REPEAT", "NEAR_HIGH", "NEAR", "NEW"), cols):
        with col:
            st.metric(VERDICT_COLORS[v]["label"], summary[v])

    if intra_dups:
        st.warning(
            f"{len(intra_dups)} group(s) of repeated questions detected — "
            f"the same question appears more than once in your uploaded CSV."
        )
        with st.expander("Show repeated-question groups"):
            for g in intra_dups:
                st.markdown(f"- input indices `{g['input_indices']}` share the same fingerprint")

    # Filter + drilldown.
    st.markdown('<div class="section-label">Browse</div>', unsafe_allow_html=True)
    filter_cols = st.columns([1, 3])
    with filter_cols[0]:
        verdict_filter = st.multiselect(
            "Filter by verdict",
            options=["REPEAT", "NEAR_HIGH", "NEAR", "NEW"],
            default=["REPEAT", "NEAR_HIGH", "NEAR", "NEW"],
        )
    with filter_cols[1]:
        st.markdown(
            f'<div style="padding-top:30px; color:var(--text-3); font-size:13.5px;">'
            f'<strong style="color:var(--text);">{subject["name"]}</strong> · '
            f'{summary["total"]} questions total'
            f'</div>',
            unsafe_allow_html=True,
        )

    filtered = [it for it in items if it["verdict"] in verdict_filter]
    st.caption(f"Showing {len(filtered)} of {summary['total']} questions")

    # Side-by-side detail expanders.
    for idx, item in enumerate(filtered, 1):
        v = item["verdict"]
        c = VERDICT_COLORS[v]
        with st.expander(
            f"{c['label']}  ·  Q{item['input_index'] + 1}  ·  "
            f"{item['input']['question_raw'][:90]}{'…' if len(item['input']['question_raw']) > 90 else ''}",
            expanded=False,
        ):
            left, right = st.columns(2)
            with left:
                st.markdown(
                    '<div class="q-label" style="font-size:11px; font-weight:600; '
                    'letter-spacing:0.1em; text-transform:uppercase; color:var(--text-4);">'
                    'New question (uploaded)</div>',
                    unsafe_allow_html=True,
                )
                st.markdown(item["input"]["question_raw"])
                if item["input"]["options"]:
                    for k, opt in enumerate(item["input"]["options"], 1):
                        if opt and str(opt).strip() and str(opt).lower() != "nan":
                            st.markdown(f"- **{k}.** {opt}")
                if item["input"]["short_answer"]:
                    st.caption(f"Correct option: {item['input']['short_answer']}")
            with right:
                if not item["top_k"]:
                    st.info("No matching historical question.")
                else:
                    top1 = item["top_k"][0]
                    year = top1.get("question_year") or "—"
                    qnum = top1.get("question_year_number")
                    year_lbl = f"{year}, Q{qnum}" if qnum else f"{year}"
                    st.markdown(
                        '<div class="q-label" style="font-size:11px; font-weight:600; '
                        'letter-spacing:0.1em; text-transform:uppercase; color:var(--text-4);">'
                        'Top historical match</div>',
                        unsafe_allow_html=True,
                    )
                    st.markdown(
                        f"`cosine {top1['cosine']:.4f}`  ·  year **{year_lbl}**"
                    )
                    st.markdown(
                        f"{top1['text_clean']} <span class='qmeta'>({year_lbl})</span>",
                        unsafe_allow_html=True,
                    )
                    if top1.get("fingerprint_match"):
                        st.markdown('<span class="fp-pill">exact fingerprint match</span>',
                                    unsafe_allow_html=True)
                    if len(item["top_k"]) > 1:
                        st.markdown("&nbsp;", unsafe_allow_html=True)
                        st.caption(f"Other top-{len(item['top_k']) - 1} candidates:")
                        for cand in item["top_k"][1:]:
                            cy = cand.get("question_year") or "—"
                            cq = cand.get("question_year_number")
                            cy_lbl = f"{cy}, Q{cq}" if cq else f"{cy}"
                            st.markdown(
                                f'<div class="match" style="margin-top:6px;">'
                                f'<div class="meta">'
                                f'<span class="cosine-pill">cosine {cand["cosine"]:.4f}</span>'
                                f'<span class="muted">id {cand["question_id"]} · year <strong>{cy_lbl}</strong></span>'
                                f'</div>'
                                f'<div class="q-text">{cand["text_clean"][:220]}{"…" if len(cand["text_clean"]) > 220 else ""} '
                                f'<span class="qmeta">({cy_lbl})</span></div>'
                                f'</div>',
                                unsafe_allow_html=True,
                            )
            st.caption(f"Reason: {item['reason']}")

    # Downloads.
    st.markdown('<div class="section-label">Export</div>', unsafe_allow_html=True)
    dl_l, dl_r, _ = st.columns([1, 1, 2])
    with dl_l:
        st.download_button(
            "Download full report (JSON)",
            data=json.dumps(st.session_state.results_report, ensure_ascii=False, indent=2, default=str),
            file_name=f"{st.session_state.batch_id}.json",
            mime="application/json",
            use_container_width=True,
        )
    with dl_r:
        # Summary CSV: one row per question with verdict + top1 cosine + reason.
        csv_rows = []
        for it in items:
            top1 = it["top_k"][0] if it["top_k"] else None
            csv_rows.append({
                "input_index": it["input_index"],
                "input_id": it["input_id"],
                "question": it["input"]["question_raw"],
                "verdict": it["verdict"],
                "reason": it["reason"],
                "top1_question_id": top1["question_id"] if top1 else "",
                "top1_cosine": f"{top1['cosine']:.4f}" if top1 else "",
                "top1_year": top1.get("question_year") if top1 else "",
                "fingerprint_match": "yes" if it["fingerprint_matches"] else "no",
            })
        csv_buf = io.StringIO()
        pd.DataFrame(csv_rows).to_csv(csv_buf, index=False)
        st.download_button(
            "Download results (CSV)",
            data=csv_buf.getvalue(),
            file_name=f"{st.session_state.batch_id}.csv",
            mime="text/csv",
            use_container_width=True,
        )

    st.caption(f"Saved to disk: {st.session_state.report_path}")

    st.markdown('<br>', unsafe_allow_html=True)
    if st.button("Start a new check"):
        reset_state()
        st.rerun()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    subjects = fetch_subjects()
    subjects_by_id = {s["id"]: s for s in subjects}
    corpus_stats = fetch_corpus_stats()
    render_header(corpus_stats["total"])

    step = st.session_state.step
    if step == "upload":
        step_upload(subjects, corpus_stats)
    elif step == "processing":
        step_processing(subjects_by_id)
    elif step == "done":
        step_done()
    else:
        st.error(f"Unknown step: {step}")


if __name__ == "__main__":
    main()
