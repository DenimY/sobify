import sqlite3
import json
from pathlib import Path
from datetime import datetime
from typing import Optional

DB_PATH = Path(__file__).parent / "bank.db"


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            original_name TEXT NOT NULL,
            uploaded_at TEXT NOT NULL,
            row_count INTEGER DEFAULT 0,
            active INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id INTEGER REFERENCES files(id) ON DELETE CASCADE,
            date TEXT NOT NULL,
            time TEXT,
            type TEXT,
            cat TEXT,
            subcat TEXT,
            desc TEXT,
            amount INTEGER,
            currency TEXT DEFAULT 'KRW',
            method TEXT,
            memo TEXT,
            cat_original TEXT,
            corrected INTEGER DEFAULT 0,
            correction_source TEXT,
            source TEXT DEFAULT 'banksalad',
            external_id TEXT
        );

        CREATE TABLE IF NOT EXISTS category_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            keyword TEXT NOT NULL,
            field TEXT NOT NULL DEFAULT 'desc',
            cat TEXT NOT NULL,
            subcat TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS ai_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            messages TEXT NOT NULL DEFAULT '[]'
        );

        CREATE INDEX IF NOT EXISTS idx_tx_date ON transactions(date);
        CREATE INDEX IF NOT EXISTS idx_tx_file ON transactions(file_id);
        CREATE INDEX IF NOT EXISTS idx_tx_cat ON transactions(cat);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_tx_external ON transactions(source, external_id)
            WHERE external_id IS NOT NULL;
        """)
        # 기존 DB에 새 컬럼 마이그레이션
        for col, definition in [("source", "TEXT DEFAULT 'banksalad'"), ("external_id", "TEXT")]:
            try:
                conn.execute(f"ALTER TABLE transactions ADD COLUMN {col} {definition}")
            except Exception:
                pass


# ── Files ──────────────────────────────────────────────────────────────────

def list_files():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM files ORDER BY uploaded_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def get_active_file_id() -> Optional[int]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM files WHERE active=1 ORDER BY uploaded_at DESC LIMIT 1"
        ).fetchone()
        return row["id"] if row else None


def set_active_file(file_id: int):
    with get_conn() as conn:
        conn.execute("UPDATE files SET active=0")
        conn.execute("UPDATE files SET active=1 WHERE id=?", (file_id,))


def delete_file(file_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM files WHERE id=?", (file_id,))


def get_or_create_sync_file(source: str) -> int:
    """쿠팡/네이버페이 동기화용 가상 파일 레코드를 가져오거나 생성."""
    name_map = {"coupang": "쿠팡 동기화", "naverpay": "네이버페이 동기화"}
    display = name_map.get(source, source)
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM files WHERE name=?", (f"_sync_{source}",)
        ).fetchone()
        if row:
            return row["id"]
        cur = conn.execute(
            "INSERT INTO files (name, original_name, uploaded_at, active) VALUES (?,?,?,0)",
            (f"_sync_{source}", display, datetime.now().isoformat()),
        )
        return cur.lastrowid


def upsert_sync_transactions(source: str, rows: list[dict]) -> dict:
    """Chrome 확장에서 수집한 거래를 삽입(중복 시 건너뜀). inserted/skipped 카운트 반환."""
    file_id = get_or_create_sync_file(source)
    inserted = 0
    skipped = 0
    with get_conn() as conn:
        for r in rows:
            external_id = r.get("external_id")
            if external_id:
                exists = conn.execute(
                    "SELECT id FROM transactions WHERE source=? AND external_id=?",
                    (source, external_id),
                ).fetchone()
                if exists:
                    skipped += 1
                    continue
            conn.execute(
                """INSERT INTO transactions
                   (file_id, date, time, type, cat, subcat, desc, amount,
                    currency, method, memo, source, external_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    file_id,
                    r.get("date", ""),
                    r.get("time", ""),
                    r.get("type", "지출"),
                    r.get("cat", "온라인쇼핑"),
                    r.get("subcat", "미분류"),
                    r.get("desc", ""),
                    r.get("amount", 0),
                    r.get("currency", "KRW"),
                    r.get("method", source),
                    r.get("memo", ""),
                    source,
                    external_id,
                ),
            )
            inserted += 1
        conn.execute(
            "UPDATE files SET row_count=(SELECT COUNT(*) FROM transactions WHERE file_id=?), "
            "uploaded_at=? WHERE id=?",
            (file_id, datetime.now().isoformat(), file_id),
        )
    if inserted:
        apply_rules_to_file(file_id)
    return {"inserted": inserted, "skipped": skipped, "file_id": file_id}


# ── Transactions ───────────────────────────────────────────────────────────

def insert_transactions(file_id: int, rows: list[dict]):
    with get_conn() as conn:
        conn.executemany(
            """INSERT INTO transactions
               (file_id, date, time, type, cat, subcat, desc, amount, currency, method, memo)
               VALUES (:file_id,:date,:time,:type,:cat,:subcat,:desc,:amount,:currency,:method,:memo)""",
            [{**r, "file_id": file_id} for r in rows],
        )
        conn.execute(
            "UPDATE files SET row_count=? WHERE id=?",
            (len(rows), file_id),
        )


def query_transactions(
    file_id: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    tx_type: Optional[str] = None,
    cat: Optional[str] = None,
    search: Optional[str] = None,
    amount_sign: Optional[str] = None,  # 'pos' | 'neg'
    limit: int = 200,
    offset: int = 0,
) -> tuple[list[dict], int]:
    clauses = []
    params: list = []

    if file_id:
        clauses.append("file_id=?"); params.append(file_id)
    if date_from:
        clauses.append("date>=?"); params.append(date_from)
    if date_to:
        clauses.append("date<=?"); params.append(date_to)
    if tx_type:
        clauses.append("type=?"); params.append(tx_type)
    if cat:
        clauses.append("cat=?"); params.append(cat)
    if search:
        clauses.append("(desc LIKE ? OR method LIKE ?)"); params += [f"%{search}%", f"%{search}%"]
    if amount_sign == "pos":
        clauses.append("amount>0")
    elif amount_sign == "neg":
        clauses.append("amount<0")

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    with get_conn() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM transactions {where}", params
        ).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM transactions {where} ORDER BY date DESC, time DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()
        return [dict(r) for r in rows], total


def get_transaction(tx_id: int) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM transactions WHERE id=?", (tx_id,)
        ).fetchone()
        return dict(row) if row else None


def update_transaction_category(tx_id: int, cat: str, subcat: str, source: str = "manual"):
    with get_conn() as conn:
        orig = conn.execute(
            "SELECT cat, cat_original FROM transactions WHERE id=?", (tx_id,)
        ).fetchone()
        if orig:
            cat_original = orig["cat_original"] or orig["cat"]
            conn.execute(
                """UPDATE transactions SET cat=?, subcat=?, corrected=1,
                   cat_original=?, correction_source=? WHERE id=?""",
                (cat, subcat, cat_original, source, tx_id),
            )


def bulk_update_categories(updates: list[dict], source: str = "ai"):
    """updates: [{id, cat, subcat}, ...]"""
    with get_conn() as conn:
        for u in updates:
            orig = conn.execute(
                "SELECT cat, cat_original FROM transactions WHERE id=?", (u["id"],)
            ).fetchone()
            if orig:
                cat_original = orig["cat_original"] or orig["cat"]
                conn.execute(
                    """UPDATE transactions SET cat=?, subcat=?, corrected=1,
                       cat_original=?, correction_source=? WHERE id=?""",
                    (u["cat"], u.get("subcat", "미분류"), cat_original, source, u["id"]),
                )


# ── Stats ──────────────────────────────────────────────────────────────────

def get_monthly_stats(file_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT substr(date,1,7) AS month,
                   SUM(CASE WHEN type='수입' AND amount>0 THEN amount ELSE 0 END) AS income,
                   SUM(CASE WHEN type='지출' AND amount>0 THEN amount ELSE 0 END) AS expense,
                   SUM(CASE WHEN type='지출' AND amount<0 THEN ABS(amount) ELSE 0 END) AS refund
            FROM transactions WHERE file_id=?
            GROUP BY month ORDER BY month
        """, (file_id,)).fetchall()
        return [dict(r) for r in rows]


def get_category_stats(file_id: int, date_from: str = None, date_to: str = None) -> list[dict]:
    clauses = ["file_id=?", "type='지출'", "amount>0"]
    params = [file_id]
    if date_from:
        clauses.append("date>=?"); params.append(date_from)
    if date_to:
        clauses.append("date<=?"); params.append(date_to)
    where = "WHERE " + " AND ".join(clauses)
    with get_conn() as conn:
        rows = conn.execute(f"""
            SELECT cat, SUM(amount) AS total, COUNT(*) AS cnt
            FROM transactions {where}
            GROUP BY cat ORDER BY total DESC
        """, params).fetchall()
        return [dict(r) for r in rows]


def get_method_stats(file_id: int, date_from: str = None, date_to: str = None) -> list[dict]:
    clauses = ["file_id=?", "type='지출'", "amount>0"]
    params = [file_id]
    if date_from:
        clauses.append("date>=?"); params.append(date_from)
    if date_to:
        clauses.append("date<=?"); params.append(date_to)
    where = "WHERE " + " AND ".join(clauses)
    with get_conn() as conn:
        rows = conn.execute(f"""
            SELECT method, SUM(amount) AS total, COUNT(*) AS cnt
            FROM transactions {where}
            GROUP BY method ORDER BY total DESC LIMIT 15
        """, params).fetchall()
        return [dict(r) for r in rows]


def get_merchant_stats(file_id: int, date_from: str = None, date_to: str = None) -> list[dict]:
    clauses = ["file_id=?", "type='지출'", "amount>0"]
    params = [file_id]
    if date_from:
        clauses.append("date>=?"); params.append(date_from)
    if date_to:
        clauses.append("date<=?"); params.append(date_to)
    where = "WHERE " + " AND ".join(clauses)
    with get_conn() as conn:
        rows = conn.execute(f"""
            SELECT desc, cat, SUM(amount) AS total, COUNT(*) AS cnt
            FROM transactions {where}
            GROUP BY desc, cat ORDER BY total DESC LIMIT 100
        """, params).fetchall()
        return [dict(r) for r in rows]


# ── Category rules ─────────────────────────────────────────────────────────

def list_rules() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM category_rules ORDER BY id").fetchall()
        return [dict(r) for r in rows]


def add_rule(keyword: str, field: str, cat: str, subcat: str = "미분류"):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO category_rules (keyword, field, cat, subcat, created_at) VALUES (?,?,?,?,?)",
            (keyword, field, cat, subcat, datetime.now().isoformat()),
        )


def delete_rule(rule_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM category_rules WHERE id=?", (rule_id,))


def apply_rules_to_file(file_id: int) -> int:
    """Apply all saved rules to transactions of a file. Returns count of updates."""
    rules = list_rules()
    if not rules:
        return 0
    count = 0
    with get_conn() as conn:
        txs = conn.execute(
            "SELECT id, desc, method FROM transactions WHERE file_id=?", (file_id,)
        ).fetchall()
        for tx in txs:
            for rule in rules:
                val = tx["desc"] if rule["field"] == "desc" else tx["method"]
                if rule["keyword"].lower() in (val or "").lower():
                    conn.execute(
                        """UPDATE transactions SET cat=?, subcat=?, corrected=1,
                           cat_original=COALESCE(cat_original, cat),
                           correction_source='rule' WHERE id=?""",
                        (rule["cat"], rule["subcat"], tx["id"]),
                    )
                    count += 1
                    break
    return count


# ── AI sessions ────────────────────────────────────────────────────────────

def create_ai_session() -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO ai_sessions (created_at, messages) VALUES (?,?)",
            (datetime.now().isoformat(), "[]"),
        )
        return cur.lastrowid


def get_ai_session(session_id: int) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM ai_sessions WHERE id=?", (session_id,)
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["messages"] = json.loads(d["messages"])
        return d


def append_ai_message(session_id: int, role: str, content: str):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT messages FROM ai_sessions WHERE id=?", (session_id,)
        ).fetchone()
        msgs = json.loads(row["messages"])
        msgs.append({"role": role, "content": content})
        conn.execute(
            "UPDATE ai_sessions SET messages=? WHERE id=?",
            (json.dumps(msgs, ensure_ascii=False), session_id),
        )
