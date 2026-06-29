"""reimport_signups.py — restore the sign-ups lost when prod was rolled back to
the Jun 28 00:24 UTC snapshot, from the CSVs in Restored/.

Re-inserts, with their ORIGINAL ids (so all foreign keys line up):
    users          (from signups_<run>.csv)
    transactions   (from signups_transactions_<run>.csv)
    user_exams     (from signups_user_exams_<run>.csv)
    user_subjects  (from signups_user_subjects_<run>.csv)

Insert order respects FKs: users -> transactions -> user_exams -> user_subjects.
Every insert is ON CONFLICT (id) DO NOTHING, so the script is idempotent and
resumable. The whole run is one transaction: --commit writes it, otherwise it
rolls back (dry-run) and just reports what it WOULD insert.

PASSWORDS / forced reset:
    The original password hashes are gone (the secrets export ran after the
    restore). So every re-imported user gets a TEMPORARY password and must reset.
    There is no force-reset column on `users`, so enforcement is one of:
      * default        — set an UNUSABLE random hash per user; the only way back
                         in is the app's "Forgot password" flow (password_resets
                         table exists). Most secure.
      * --temp-password P — set all users to bcrypt(P) so they can sign in with P
                         and then change it. Use when you'll tell users the temp
                         password directly.
    Either way a notify list (id, username, email) is written so you can prompt
    the affected users to reset.

Usage:
    python scripts/reimport_signups.py                 # dry-run, default dir Restored/
    python scripts/reimport_signups.py --commit        # actually write
    python scripts/reimport_signups.py --commit --temp-password "Prep50-Reset!"
    python scripts/reimport_signups.py --dir Restored --commit
"""
import argparse
import csv
import glob
import os
import re
import secrets
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parents[1]

# (table, filename prefix). Order is FK-safe.
PLAN = [
    ("users",         "signups_"),               # the per-user summary file
    ("transactions",  "signups_transactions_"),
    ("user_exams",    "signups_user_exams_"),
    ("user_subjects", "signups_user_subjects_"),
]
# signups_ also prefixes the others, so disambiguate the users summary file.
USERS_EXCLUDE = ("signups_transactions_", "signups_user_exams_",
                 "signups_user_subjects_", "signups_subjects_")

TRUE = {"true", "t", "1", "yes", "y"}
FALSE = {"false", "f", "0", "no", "n"}


def connect():
    return psycopg2.connect(
        host=os.getenv("DB_HOST"), port=int(os.getenv("DB_PORT", "5432")),
        user=os.getenv("DB_USER"), password=os.getenv("DB_PASSWORD"),
        dbname=os.getenv("DB_NAME") or "prep50",
        sslmode=os.getenv("DB_SSLMODE", "prefer"))


def make_hasher():
    """Return (hash_fn, usable). usable=False means we can't make a real bcrypt
    hash, so passwords become unusable sentinels (forgot-password only)."""
    try:
        import bcrypt
        return (lambda pw: bcrypt.hashpw(pw.encode(), bcrypt.gensalt(rounds=12)).decode()), True
    except ImportError:
        try:
            from passlib.hash import bcrypt as pb
            return (lambda pw: pb.using(rounds=12).hash(pw)), True
        except ImportError:
            return (lambda pw: "RESET_REQUIRED$" + secrets.token_urlsafe(40)), False


def pick_file(dir_path, prefix, exclude=()):
    cands = [p for p in glob.glob(str(dir_path / f"{prefix}*.csv"))
             if not any(os.path.basename(p).startswith(x) for x in exclude)]
    if not cands:
        return None
    return max(cands, key=os.path.getmtime)        # newest run


def column_types(cur, table):
    cur.execute("""SELECT column_name, data_type, is_nullable
                   FROM information_schema.columns
                   WHERE table_schema='public' AND table_name=%s""", (table,))
    return {r[0]: (r[1], r[2] == "YES") for r in cur.fetchall()}


def coerce(value, spec):
    """Turn a CSV string into a typed Python value for the given (dtype, nullable)."""
    dtype, nullable = spec
    if value is None:
        return None
    v = value.strip()
    if dtype in ("boolean",):
        if v == "":
            return None
        low = v.lower()
        return True if low in TRUE else False if low in FALSE else None
    if dtype in ("integer", "bigint", "smallint"):
        return int(float(v)) if v != "" else None
    if dtype in ("numeric", "double precision", "real"):
        if v == "":
            return None
        try:
            return Decimal(v)
        except InvalidOperation:
            return None
    if "timestamp" in dtype or dtype == "date":
        return datetime.fromisoformat(v) if v != "" else None
    # text / varchar / uuid / USER-DEFINED: empty -> NULL when the column allows
    # it (fixes nullable FKs like user_exams.transaction_id stored as ''); empty
    # stays '' only where the column is NOT NULL.
    if v == "":
        return None if nullable else ""
    return v


def load_rows(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def insert_table(cur, table, rows, types, transform=None, force_cols=()):
    """Insert rows (list of CSV dicts) into table; ON CONFLICT (id) DO NOTHING.
    Only columns that exist in BOTH the CSV and the table are used, plus any
    force_cols (set by the transform, e.g. a password not present in the CSV).
    Returns number of rows actually inserted."""
    if not rows:
        return 0
    cols = [c for c in rows[0].keys() if c in types]
    for fc in force_cols:
        if fc in types and fc not in cols:
            cols.append(fc)
    if "id" not in cols:
        raise SystemExit(f"{table}: CSV has no 'id' column; cannot key inserts.")
    collist = ", ".join(f'"{c}"' for c in cols)
    ph = ", ".join(["%s"] * len(cols))
    sql = (f'INSERT INTO "{table}" ({collist}) VALUES ({ph}) '
           f'ON CONFLICT (id) DO NOTHING')
    inserted = 0
    for r in rows:
        if transform:
            r = transform(dict(r))
        vals = [coerce(r.get(c), types[c]) for c in cols]
        cur.execute(sql, vals)
        inserted += cur.rowcount
    return inserted


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=str(ROOT / "Restored"),
                    help="Folder with the Restored CSVs (default ./Restored).")
    ap.add_argument("--commit", action="store_true",
                    help="Actually write. Without it, dry-run (rolled back).")
    ap.add_argument("--temp-password",
                    help="Set all users to bcrypt(THIS) so they can log in with it "
                         "and change it. Default: unusable hash (forgot-password only).")
    args = ap.parse_args()

    dir_path = Path(args.dir)
    files = {}
    for table, prefix in PLAN:
        exclude = USERS_EXCLUDE if table == "users" else ()
        f = pick_file(dir_path, prefix, exclude)
        if f is None and table in ("users",):
            raise SystemExit(f"Required file for '{table}' not found in {dir_path}")
        files[table] = f

    hash_fn, usable = make_hasher()
    run = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    # Pre-compute the temp password (shared) or signal per-user random.
    shared_pw = args.temp_password
    notify = []  # (id, username, email)

    def users_transform(row):
        if shared_pw:
            row["password"] = hash_fn(shared_pw)
        else:
            # per-user unusable hash
            row["password"] = hash_fn(secrets.token_urlsafe(24))
        notify.append((row.get("id"), row.get("username"), row.get("email")))
        return row

    conn = connect()
    print(f"Connected: host={os.getenv('DB_HOST')} db={os.getenv('DB_NAME')}")
    print(f"Mode: {'COMMIT' if args.commit else 'DRY-RUN (rollback)'}")
    pw_mode = (f"shared temp password (bcrypt)" if shared_pw
               else ("unusable hash -> forgot-password" if usable
                     else "NO bcrypt lib -> sentinel hash, forgot-password only"))
    print(f"Password mode: {pw_mode}\n")

    # Load all CSVs and the table schemas up front.
    data, types = {}, {}
    with conn.cursor() as cur:
        for table, _ in PLAN:
            path = files.get(table)
            data[table] = load_rows(path) if path else []
            types[table] = column_types(cur, table)

        # Pre-flight: skip cohort users whose email already exists in the restored
        # DB (returning/duplicate accounts — email is the only unique constraint
        # besides id; username is NOT unique, so it must not gate the import).
        cohort = data["users"]
        emails = [u["email"] for u in cohort if u.get("email")]
        cur.execute("SELECT email FROM users WHERE email = ANY(%s)", (emails,))
        existing_emails = {r[0] for r in cur.fetchall()}

    skipped = []  # (id, username, email, reason)
    for u in cohort:
        if u.get("email") in existing_emails:
            skipped.append((u.get("id"), u.get("username"), u.get("email"), "email exists"))
    skip_ids = {s[0] for s in skipped}
    keep_ids = {u["id"] for u in cohort if u["id"] not in skip_ids}

    data["users"] = [u for u in cohort if u["id"] in keep_ids]
    for t in ("transactions", "user_exams", "user_subjects"):
        data[t] = [r for r in data[t] if r.get("user_id") in keep_ids]

    if skipped:
        print(f"Pre-flight: skipping {len(skipped)} user(s) that already exist "
              f"(and their dependent rows):")
        for uid, un, em, why in skipped[:10]:
            print(f"    - {un} <{em}>  [{why}]")
        if len(skipped) > 10:
            print(f"    …and {len(skipped) - 10} more")
        print()

    results = {}
    try:
        with conn:                       # commits on success, rolls back on error
            with conn.cursor() as cur:
                for table, _ in PLAN:
                    rows = data[table]
                    tf = users_transform if table == "users" else None
                    fc = ("password",) if table == "users" else ()
                    n = insert_table(cur, table, rows, types[table],
                                     transform=tf, force_cols=fc)
                    results[table] = n
                    src = os.path.basename(files[table]) if files.get(table) else "-"
                    print(f"  {table:14} : {n:>4} inserted (of {len(rows)} to import; {src})")
                if not args.commit:
                    raise _DryRun()
    except _DryRun:
        print("\n[DRY-RUN] rolled back — no changes written. Re-run with --commit.")
    finally:
        conn.close()

    # Persist the skip list for review.
    if skipped:
        sp = dir_path / f"reimport_skipped_{run}.csv"
        with open(sp, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["id", "username", "email", "reason"])
            w.writerows(skipped)
        print(f"\nSkipped list ({len(skipped)}) -> {sp}")

    # Write the notify list regardless (who needs to reset).
    if notify:
        out = dir_path / f"reimport_password_resets_{run}.csv"
        with open(out, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["id", "username", "email", "action"])
            for uid, un, em in notify:
                w.writerow([uid, un, em, "must_reset_password"])
        print(f"\nNotify list ({len(notify)} users) -> {out}")

    print("\nSummary:", ", ".join(f"{t}={results.get(t,0)}" for t, _ in PLAN))
    if args.commit:
        if shared_pw:
            print(f"\nTemp password for all re-imported users: {shared_pw!r}")
            print("Tell users to log in with it and change it immediately.")
        else:
            print("\nRe-imported users CANNOT log in with an old/temp password — "
                  "they must use 'Forgot password' to set a new one.")


class _DryRun(Exception):
    pass


if __name__ == "__main__":
    main()
