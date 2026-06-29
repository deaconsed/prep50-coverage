"""export_signups.py — back up users who SIGNED UP in a time window, together
with their user_exams (subscriptions) and user_subjects (subject combinations).

"Signed in from yesterday to today" is exported as new registrations: users whose
users.created_at falls in the window. (Prod has no login-event log — no last_login,
no sessions/Sanctum tables — so created_at is the chosen signal.)

Writes four CSVs into --out-dir (default: ./backups), all stamped with one run id:
    signups_<run>.csv                one row per user; subjects collapsed into a
                                     "subjects" column, plus exam_count,
                                     payment_statuses and a `subscribed` flag.
    signups_user_exams_<run>.csv     one row per user_exams row for these users
                                     (full columns + exam name/amount).
    signups_user_subjects_<run>.csv  one row per user_subjects row for these users
                                     (full columns + subject name/tag + the parent
                                     exam's payment_status).
    signups_subjects_<run>.csv       legacy flat user×subject view (kept for compat).

Window (server time is UTC):
    default            start of yesterday 00:00 UTC -> now
    --days N           last N*24h up to now (fractions ok, e.g. 0.5 = 12h)
    --since / --until  explicit ISO timestamps (e.g. 2026-06-28T01:25:00)

Safety:
    The bcrypt password hash is EXCLUDED by default. Pass --include-secrets to
    include it (writes credential hashes to a plaintext CSV — handle with care).

Usage:
    python scripts/export_signups.py
    python scripts/export_signups.py --days 0.5
    python scripts/export_signups.py --since 2026-06-28T01:25:00
    python scripts/export_signups.py --out-dir D:/backups --include-secrets
"""
import argparse
import csv
import os
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parents[1]
SUBJECT_SEP = " | "
SECRET_COLS = ("password",)            # excluded unless --include-secrets
SUBSCRIBED_STATUSES = ("completed",)   # payment_status values that count as subscribed


def connect():
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT", "5432")),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        dbname=os.getenv("DB_NAME") or "prep50",
        sslmode=os.getenv("DB_SSLMODE", "prefer"),
    )


def resolve_window(cur, args):
    """Return (start, end) as tz-aware datetimes resolved on the DB (UTC)."""
    if args.since or args.until:
        cur.execute("SELECT %s::timestamptz, COALESCE(%s::timestamptz, NOW())",
                    (args.since, args.until))
    elif args.days:
        cur.execute("SELECT NOW() - (%s || ' days')::interval, NOW()", (args.days,))
    else:
        cur.execute("SELECT date_trunc('day', NOW()) - INTERVAL '1 day', NOW()")
    return cur.fetchone()


# All the cohort filters key off the same window on users.created_at.
USERS_SQL = """
    SELECT u.* FROM users u
    WHERE u.created_at >= %(start)s AND u.created_at < %(end)s
    ORDER BY u.created_at, u.id
"""

USER_EXAMS_SQL = """
    SELECT ue.*, e.name AS exam_name, e.amount AS exam_amount
    FROM user_exams ue
    JOIN users u  ON u.id = ue.user_id
    LEFT JOIN exams e ON e.id = ue.exam_id
    WHERE u.created_at >= %(start)s AND u.created_at < %(end)s
    ORDER BY ue.user_id, ue.created_at
"""

USER_SUBJECTS_SQL = """
    SELECT us.*, s.name AS subject_name, s.tag AS subject_tag,
           ue.payment_status AS exam_payment_status, ue.exam_id AS exam_id
    FROM user_subjects us
    JOIN users u  ON u.id = us.user_id
    LEFT JOIN subjects s    ON s.id = us.subject_id
    LEFT JOIN user_exams ue ON ue.id = us.user_exam_id
    WHERE u.created_at >= %(start)s AND u.created_at < %(end)s
    ORDER BY us.user_id, s.name
"""

# Every transaction belonging to a cohort user who has a completed (subscribed)
# user_exam. Filtered to subscribed users per the request.
TRANSACTIONS_SQL = """
    SELECT t.*
    FROM transactions t
    JOIN users u ON u.id = t.user_id
    WHERE u.created_at >= %(start)s AND u.created_at < %(end)s
      AND t.user_id IN (
          SELECT ue.user_id FROM user_exams ue
          WHERE ue.payment_status IN %(subscribed_statuses)s
      )
    ORDER BY t.user_id, t.created_at
"""


def fetch(conn, sql, params):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def write_csv(path, rows, cols, secret_cols=()):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            if secret_cols:
                r = {**r, **{c: None for c in secret_cols}}
            w.writerow(r)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=float, help="Window = last N days up to now.")
    ap.add_argument("--since", help="ISO start timestamp (UTC), overrides --days.")
    ap.add_argument("--until", help="ISO end timestamp (UTC); default now.")
    ap.add_argument("--out-dir", default=str(ROOT / "backups"),
                    help="Directory for the CSVs (default ./backups).")
    ap.add_argument("--include-secrets", action="store_true",
                    help="Include the password hash column (sensitive).")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    conn = connect()
    print(f"Connected: host={os.getenv('DB_HOST')} db={os.getenv('DB_NAME')}")
    with conn.cursor() as cur0:
        start, end = resolve_window(cur0, args)
    print(f"Window (UTC): {start}  ->  {end}")

    params = {"start": start, "end": end}
    users = fetch(conn, USERS_SQL, params)
    exams = fetch(conn, USER_EXAMS_SQL, params)
    subjects = fetch(conn, USER_SUBJECTS_SQL, params)
    transactions = fetch(conn, TRANSACTIONS_SQL,
                         {**params, "subscribed_statuses": tuple(SUBSCRIBED_STATUSES)})
    conn.close()

    if not users:
        print("No sign-ups in this window. Nothing written.")
        return

    secret = () if args.include_secrets else SECRET_COLS
    user_cols = [c for c in users[0].keys() if c not in secret]
    run = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    # --- user_exams dump ---
    exams_path = out_dir / f"signups_user_exams_{run}.csv"
    exam_cols = (list(exams[0].keys()) if exams
                 else ["id", "user_id", "exam_id", "transaction_id", "session",
                       "payment_status", "created_at", "expires_at",
                       "exam_name", "exam_amount"])
    write_csv(exams_path, exams, exam_cols)

    # --- user_subjects dump ---
    subj_path = out_dir / f"signups_user_subjects_{run}.csv"
    subj_cols = (list(subjects[0].keys()) if subjects
                 else ["id", "user_id", "user_exam_id", "subject_id",
                       "subject_name", "subject_tag", "exam_payment_status", "exam_id"])
    write_csv(subj_path, subjects, subj_cols)

    # --- transactions dump (subscribed users only) ---
    tx_path = out_dir / f"signups_transactions_{run}.csv"
    tx_cols = (list(transactions[0].keys()) if transactions
               else ["id", "user_id", "item", "amount", "reference", "provider",
                     "status", "session", "response", "created_at", "updated_at"])
    write_csv(tx_path, transactions, tx_cols)

    # --- aggregate per-user rollups ---
    by_user_subj, by_user_exam = {}, {}
    for s in subjects:
        by_user_subj.setdefault(s["user_id"], []).append(s)
    for e in exams:
        by_user_exam.setdefault(e["user_id"], []).append(e)

    # --- summary CSV: one row per user, with subscription + subject rollup ---
    summary_path = out_dir / f"signups_{run}.csv"
    summary_cols = user_cols + ["subscribed", "exam_count", "payment_statuses",
                                "subject_count", "subjects", "subject_ids"]
    summary_rows = []
    n_subscribed = 0
    for u in users:
        ue = by_user_exam.get(u["id"], [])
        statuses = [e["payment_status"] for e in ue if e["payment_status"]]
        subscribed = any(st in SUBSCRIBED_STATUSES for st in statuses)
        n_subscribed += subscribed
        us = by_user_subj.get(u["id"], [])
        names, ids = [], []
        for s in us:
            if s["subject_name"] and s["subject_name"] not in names:
                names.append(s["subject_name"])
                ids.append(str(s["subject_id"]))
        row = {k: u.get(k) for k in user_cols}
        row.update(subscribed="yes" if subscribed else "no",
                   exam_count=len(ue),
                   payment_statuses=SUBJECT_SEP.join(dict.fromkeys(statuses)),
                   subject_count=len(names),
                   subjects=SUBJECT_SEP.join(names),
                   subject_ids=SUBJECT_SEP.join(ids))
        summary_rows.append(row)
    write_csv(summary_path, summary_rows, summary_cols)

    # --- legacy flat user×subject view ---
    legacy_path = out_dir / f"signups_subjects_{run}.csv"
    legacy_cols = user_cols + ["user_subject_id", "user_exam_id", "subject_id",
                               "subject_name", "subject_tag", "exam_payment_status"]
    legacy_rows = []
    users_by_id = {u["id"]: u for u in users}
    for s in subjects:
        base = {k: users_by_id[s["user_id"]].get(k) for k in user_cols}
        base.update(user_subject_id=s["id"], user_exam_id=s["user_exam_id"],
                    subject_id=s["subject_id"], subject_name=s["subject_name"],
                    subject_tag=s["subject_tag"],
                    exam_payment_status=s["exam_payment_status"])
        legacy_rows.append(base)
    write_csv(legacy_path, legacy_rows, legacy_cols)

    tx_users = len({t["user_id"] for t in transactions})
    print(f"\nSign-ups (users):   {len(users)}")
    print(f"  subscribed:       {n_subscribed}")
    print(f"  user_exams rows:  {len(exams)}")
    print(f"  user_subjects rows:{len(subjects)}")
    print(f"  transactions rows:{len(transactions)}  (for {tx_users} subscribed users)")
    print(f"\n  summary       -> {summary_path}")
    print(f"  user_exams    -> {exams_path}")
    print(f"  user_subjects -> {subj_path}")
    print(f"  transactions  -> {tx_path}")
    print(f"  flat view     -> {legacy_path}")
    if not args.include_secrets:
        print("  (password hash excluded; pass --include-secrets to keep it)")


if __name__ == "__main__":
    main()
