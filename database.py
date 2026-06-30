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

        CREATE TABLE IF NOT EXISTS custom_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            icon TEXT DEFAULT '📦'
        );

        CREATE TABLE IF NOT EXISTS cat_subcats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cat_name TEXT NOT NULL,
            subcat_name TEXT NOT NULL,
            sort_order INTEGER DEFAULT 0,
            UNIQUE(cat_name, subcat_name)
        );

        CREATE TABLE IF NOT EXISTS ai_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            messages TEXT NOT NULL DEFAULT '[]'
        );

        CREATE INDEX IF NOT EXISTS idx_tx_date ON transactions(date);
        CREATE INDEX IF NOT EXISTS idx_tx_file ON transactions(file_id);
        CREATE INDEX IF NOT EXISTS idx_tx_cat ON transactions(cat);
        """)
        # 기존 DB에 새 컬럼 마이그레이션 (인덱스 생성 전에 컬럼이 있어야 함)
        for col, definition in [("source", "TEXT DEFAULT 'banksalad'"), ("external_id", "TEXT"), ("bundle_id", "TEXT")]:
            try:
                conn.execute(f"ALTER TABLE transactions ADD COLUMN {col} {definition}")
            except Exception:
                pass
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_tx_external ON transactions(source, external_id)
            WHERE external_id IS NOT NULL
        """)
        # 기존 rules에서 'merchant' field 값을 'desc'로 정규화
        conn.execute("UPDATE category_rules SET field='desc' WHERE field='merchant'")
        # category_rules 신규 컬럼 마이그레이션
        try:
            conn.execute("ALTER TABLE category_rules ADD COLUMN exclude_from_dashboard INTEGER NOT NULL DEFAULT 0")
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


def delete_source_data(source: str) -> int:
    """출처별 데이터 전체 삭제. 삭제된 건수 반환."""
    with get_conn() as conn:
        if source == "banksalad":
            active_id = get_active_file_id()
            if not active_id:
                return 0
            cnt = conn.execute(
                "SELECT COUNT(*) FROM transactions WHERE file_id=?", (active_id,)
            ).fetchone()[0]
            conn.execute("DELETE FROM transactions WHERE file_id=?", (active_id,))
            conn.execute("DELETE FROM files WHERE id=?", (active_id,))
        else:
            cnt = conn.execute(
                "SELECT COUNT(*) FROM transactions WHERE source=?", (source,)
            ).fetchone()[0]
            conn.execute("DELETE FROM transactions WHERE source=?", (source,))
            conn.execute("DELETE FROM files WHERE name=?", (f"_sync_{source}",))
        return cnt


def get_source_count(source: str) -> int:
    with get_conn() as conn:
        if source == "banksalad":
            active_id = get_active_file_id()
            if not active_id:
                return 0
            return conn.execute(
                "SELECT COUNT(*) FROM transactions WHERE file_id=?", (active_id,)
            ).fetchone()[0]
        return conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE source=?", (source,)
        ).fetchone()[0]


def get_visible_file_ids(file_id: Optional[int] = None) -> list[int]:
    """대시보드에 표시할 file_id 목록.
    명시적으로 file_id가 지정되면 그것만, 아니면 활성 파일 + 모든 동기화 소스(쿠팡/네이버페이)를 합쳐서 반환.
    """
    if file_id:
        return [file_id]
    ids = []
    active = get_active_file_id()
    if active:
        ids.append(active)
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id FROM files WHERE name LIKE '_sync_%'"
        ).fetchall()
        ids += [r["id"] for r in rows]
    return ids


def get_synced_sources() -> set[str]:
    """동기화 데이터가 1건 이상 존재하는 소스 반환 (coupang, naverpay 등)."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT source FROM transactions WHERE source IN ('coupang','naverpay')"
        ).fetchall()
    return {r["source"] for r in rows}


def banksalad_dedup_clause(synced: set[str]) -> str:
    """전체 조회 시 뱅크샐러드 중복 제외 조건.
    동기화된 소스가 있으면, 뱅크샐러드의 해당 결제수단 항목을 제외.
    """
    excludes = []
    if "coupang" in synced:
        excludes.append("method LIKE '%쿠팡%'")
    if "naverpay" in synced:
        excludes.append("method LIKE '%네이버페이%'")
    if not excludes:
        return ""
    return "NOT (source='banksalad' AND (" + " OR ".join(excludes) + "))"


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


_CAT_KEYWORDS: list[tuple[str, str, list[str]]] = [
    # (cat, subcat, keywords)
    ("식비", "마트",       ["쌀", "계란", "달걀", "우유", "두부", "콩나물", "고구마", "감자", "양파", "마늘", "당근", "파", "배추", "된장", "간장", "고추장", "참기름", "들기름", "식용유", "밀가루", "설탕", "소금", "식초", "올리브", "버터", "치즈", "요거트", "요구르트"]),
    ("식비", "마트",       ["돼지국밥", "닭가슴살", "닭안심", "삼겹살", "목살", "소고기", "한우", "돼지고기", "닭고기", "오리고기", "생선", "연어", "참치", "고등어", "새우", "오징어", "전복"]),
    ("식비", "마트",       ["냉동", "즉석밥", "즉석식품", "간편식", "컵라면", "라면", "김치", "깍두기", "나물", "반찬", "도시락", "샐러드드레싱"]),
    ("식비", "배달",       ["배달", "치킨", "피자", "햄버거", "버거", "샌드위치", "도넛", "떡볶이", "순대", "핫도그", "족발", "보쌈", "찜닭", "훠궈"]),
    ("카페/간식", "카페",  ["커피", "아메리카노", "라떼", "에스프레소", "카푸치노", "콜드브루", "스타벅스", "메가커피", "빽다방", "이디야", "할리스", "투썸"]),
    ("카페/간식", "간식",  ["쿠키", "케이크", "빵", "베이커리", "마카롱", "초콜릿", "사탕", "젤리", "아이스크림", "빙수", "떡", "한과"]),
    ("의료/건강", "건강식품", ["루테인", "비타민", "오메가", "프로바이오틱스", "유산균", "콜라겐", "글루코사민", "코엔자임", "커큐민", "마그네슘", "칼슘", "아연", "철분", "엽산", "홍삼", "인삼", "밀크씨슬", "피토솔", "피토섬"]),
    ("의료/건강", "의약품", ["약", "영양제", "건강기능식품", "보충제", "단백질쉐이크", "프로틴", "whey", "크레아틴"]),
    ("의료/건강", "기타",  ["마스크", "손소독제", "소독", "밴드", "파스", "연고", "체온계", "혈압계", "혈당"]),
    ("생활", "생활용품",   ["세제", "샴푸", "린스", "컨디셔너", "바디워시", "비누", "치약", "칫솔", "면도", "생리대", "기저귀", "물티슈", "화장지", "티슈", "청소", "세탁", "섬유유연제", "방향제", "탈취제"]),
    ("생활", "주방",       ["냄비", "프라이팬", "그릇", "컵", "수저", "도마", "칼", "주방", "조리", "용기", "밀폐"]),
    ("패션/쇼핑", "의류",  ["티셔츠", "반팔", "긴팔", "셔츠", "블라우스", "원피스", "청바지", "바지", "반바지", "치마", "코트", "자켓", "점퍼", "패딩", "니트", "가디건", "후드", "맨투맨", "수영복", "속옷"]),
    ("패션/쇼핑", "신발",  ["운동화", "구두", "슬리퍼", "샌들", "부츠", "스니커즈"]),
    ("패션/쇼핑", "가방",  ["가방", "백팩", "토트백", "숄더백", "지갑", "파우치"]),
    ("뷰티/미용", "스킨케어", ["크림", "세럼", "앰플", "토너", "에센스", "선크림", "선스크린", "마스크팩", "클렌징", "스킨케어", "로션"]),
    ("뷰티/미용", "메이크업", ["파운데이션", "쿠션", "비비크림", "립스틱", "립밤", "아이섀도", "마스카라", "아이라이너", "블러셔", "파우더"]),
    ("전자제품", "가전",   ["청소기", "세탁기", "냉장고", "에어컨", "건조기", "공기청정기", "가습기", "제습기", "선풍기", "전기밥솥", "전자레인지", "에어프라이어"]),
    ("전자제품", "IT기기", ["노트북", "태블릿", "스마트폰", "키보드", "마우스", "모니터", "이어폰", "헤드폰", "스피커", "충전기", "케이블", "USB", "SSD", "HDD"]),
    ("문화/여가", "도서",  ["책", "도서", "소설", "만화", "잡지", "참고서", "교재"]),
    ("문화/여가", "운동",  ["요가", "필라테스", "헬스", "덤벨", "바벨", "매트", "폼롤러", "운동용품"]),
    ("반려동물", "사료",   ["사료", "간식", "펫", "강아지", "고양이", "애완"]),
    ("교육/학습", "기타",  ["교재", "문구", "노트", "펜", "볼펜", "연필", "스케치북"]),
]

def smart_categorize(desc: str) -> tuple[str, str]:
    """상품명 키워드로 카테고리를 추론. 매칭 없으면 ('온라인쇼핑', '미분류') 반환."""
    lower = desc.lower()
    for cat, subcat, keywords in _CAT_KEYWORDS:
        if any(kw in lower for kw in keywords):
            return cat, subcat
    return "온라인쇼핑", "미분류"


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
            else:
                # external_id 없는 경우 날짜+사용처+금액으로 중복 체크
                exists = conn.execute(
                    "SELECT id FROM transactions WHERE source=? AND date=? AND desc=? AND amount=?",
                    (source, r.get("date", ""), r.get("desc", ""), r.get("amount", 0)),
                ).fetchone()
            if exists:
                skipped += 1
                continue
            desc = r.get("desc", "")
            auto_cat, auto_subcat = smart_categorize(desc)
            conn.execute(
                """INSERT INTO transactions
                   (file_id, date, time, type, cat, subcat, desc, amount,
                    currency, method, memo, source, external_id, bundle_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    file_id,
                    r.get("date", ""),
                    r.get("time", ""),
                    r.get("type", "지출"),
                    r.get("cat") or auto_cat,
                    r.get("subcat") if r.get("subcat") not in ("미분류", "", None) else auto_subcat,
                    desc,
                    r.get("amount", 0),
                    r.get("currency", "KRW"),
                    r.get("method", source),
                    r.get("memo", ""),
                    source,
                    external_id,
                    r.get("bundle_id"),
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
    mark_cancelled_pairs(file_id)


def mark_cancelled_pairs(file_id: int) -> int:
    """환불(양수) 시점 기준 과거 30일 내 동일 (desc, |amount|) 지출(음수)과 쌍이면 type='취소' 마킹.
    당일 거래도 포함 — 수입 시간 >= 지출 시간인 경우 환불로 인정."""
    from datetime import datetime, timedelta
    from collections import defaultdict

    with get_conn() as conn:
        rows = conn.execute(
            """SELECT id, date, time, desc, amount FROM transactions
               WHERE file_id=? AND type IN ('지출','수입')
               ORDER BY date, time""",
            (file_id,),
        ).fetchall()

    def datetime_key(r):
        return (r["date"] or ""), (r["time"] or "")

    # 음수(지출) 풀: (desc, abs_amount) → datetime 내림차순 — 가장 최근 지출을 우선 매칭
    expense_pool: dict = defaultdict(list)
    for r in rows:
        if r["amount"] < 0:
            expense_pool[(r["desc"], abs(r["amount"]))].append(
                [r["date"], r["time"] or "", r["id"], False]  # [date, time, id, matched]
            )
    for entries in expense_pool.values():
        entries.sort(key=lambda e: (e[0], e[1]), reverse=True)  # 최신순

    cancel_ids = []
    for r in rows:
        if r["amount"] <= 0:
            continue  # 양수(환불)만 처리
        key = (r["desc"], r["amount"])
        refund_dt = (r["date"] or ""), (r["time"] or "")
        cutoff_date = (datetime.strptime(r["date"], "%Y-%m-%d") - timedelta(days=30)).strftime("%Y-%m-%d")

        for entry in expense_pool.get(key, []):
            if entry[3]:  # 이미 매칭됨
                continue
            exp_date, exp_time = entry[0], entry[1]
            # 지출이 환불보다 이전이어야 함 (당일은 시간 비교, 다른 날은 날짜만)
            exp_dt = (exp_date, exp_time)
            if exp_date >= cutoff_date and exp_dt <= refund_dt:
                entry[3] = True
                cancel_ids.append(entry[2])  # 지출 id
                cancel_ids.append(r["id"])   # 환불 id
                break

    if not cancel_ids:
        return 0

    with get_conn() as conn:
        conn.execute(
            f"UPDATE transactions SET type='취소' WHERE id IN ({','.join('?'*len(cancel_ids))})",
            cancel_ids,
        )
    return len(cancel_ids)


_TX_TYPE_MAP = {"income": "수입", "expense": "지출"}


def query_transactions(
    file_id: Optional[int] = None,
    file_ids: Optional[list[int]] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    tx_type: Optional[str] = None,
    cat: Optional[str] = None,
    search: Optional[str] = None,
    method_search: Optional[str] = None,
    amount_sign: Optional[str] = None,  # 'pos' | 'neg'
    source: Optional[str] = None,  # 'banksalad' | 'coupang' | 'naverpay'
    exclude_transfer: bool = False,
    weekend_only: bool = False,
    sort: Optional[str] = None,     # 'date' | 'amount' | 'desc'
    sort_dir: int = -1,             # -1=DESC, 1=ASC
    limit: int = 200,
    offset: int = 0,
) -> tuple[list[dict], int]:
    clauses = []
    params: list = []

    ids = file_ids if file_ids is not None else ([file_id] if file_id else None)
    if ids:
        clauses.append(f"file_id IN ({','.join('?' * len(ids))})"); params += ids
    if date_from:
        clauses.append("date>=?"); params.append(date_from)
    if date_to:
        clauses.append("date<=?"); params.append(date_to)
    if tx_type:
        # 콤마 구분 다중 유형 지원 ("income,expense" 등)
        types = [_TX_TYPE_MAP.get(t.strip(), t.strip()) for t in tx_type.split(",") if t.strip()]
        if types:
            clauses.append(f"type IN ({','.join('?'*len(types))})"); params += types
    if cat:
        clauses.append("cat=?"); params.append(cat)
    if search:
        clauses.append("(UPPER(desc) LIKE UPPER(?) OR UPPER(memo) LIKE UPPER(?))"); params += [f"%{search}%", f"%{search}%"]
    if method_search:
        # 네이버페이 검색 시 네이버파이낸셜도 포함
        aliases = [method_search]
        if "네이버페이" in method_search:
            aliases.append("네이버파이낸셜")
        method_clause = " OR ".join("UPPER(method) LIKE UPPER(?)" for _ in aliases)
        clauses.append(f"({method_clause})")
        params += [f"%{a}%" for a in aliases]
    if amount_sign == "pos":
        clauses.append("amount>0")
    elif amount_sign == "neg":
        clauses.append("amount<0")
    if source:
        clauses.append("source=?"); params.append(source)
    else:
        dedup = banksalad_dedup_clause(get_synced_sources())
        if dedup:
            clauses.append(dedup)
    if exclude_transfer:
        clauses.append("type!='이체'")
    if weekend_only:
        clauses.append("strftime('%w', date) IN ('0','5','6')")  # 0=일, 5=금, 6=토

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    _SORT_COLS = {"date": "date", "amount": "ABS(amount)", "desc": "desc"}
    sort_col = _SORT_COLS.get(sort or "date", "date")
    direction = "ASC" if sort_dir == 1 else "DESC"
    order = f"{sort_col} {direction}" + ("" if sort_col == "date" else ", date DESC")

    with get_conn() as conn:
        agg = conn.execute(f"""
            SELECT COUNT(*) as cnt,
                   SUM(CASE
                     WHEN type='지출' AND amount<0 THEN ABS(amount)
                     WHEN type='지출' AND amount>0 AND source IN ('coupang','naverpay') THEN amount
                     ELSE 0 END) AS total_expense,
                   SUM(CASE WHEN type='수입' AND amount>0 THEN amount ELSE 0 END) AS total_income
            FROM transactions {where}
        """, params).fetchone()
        rows = conn.execute(
            f"SELECT * FROM transactions {where} ORDER BY {order} LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()
        return [dict(r) for r in rows], agg["cnt"], int(agg["total_expense"] or 0), int(agg["total_income"] or 0)


def get_transaction(tx_id: int) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM transactions WHERE id=?", (tx_id,)
        ).fetchone()
        return dict(row) if row else None


def update_transaction_category(tx_id: int, cat: str, subcat: str, source: str = "manual", memo: str = None):
    with get_conn() as conn:
        orig = conn.execute(
            "SELECT cat, cat_original FROM transactions WHERE id=?", (tx_id,)
        ).fetchone()
        if orig:
            cat_original = orig["cat_original"] or orig["cat"]
            if memo is not None:
                conn.execute(
                    """UPDATE transactions SET cat=?, subcat=?, corrected=1,
                       cat_original=?, correction_source=?, memo=? WHERE id=?""",
                    (cat, subcat, cat_original, source, memo, tx_id),
                )
            else:
                conn.execute(
                    """UPDATE transactions SET cat=?, subcat=?, corrected=1,
                       cat_original=?, correction_source=? WHERE id=?""",
                    (cat, subcat, cat_original, source, tx_id),
                )


def bulk_update_category_by_desc(desc: str, cat: str, subcat: str, amount: int | None = None) -> int:
    """같은 desc(사용처)를 가진 모든 거래에 카테고리 일괄 적용. amount 지정 시 금액까지 일치하는 건만."""
    with get_conn() as conn:
        if amount is not None:
            rows = conn.execute(
                "SELECT id, cat FROM transactions WHERE desc=? AND ABS(amount)=?", (desc, abs(amount))
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, cat FROM transactions WHERE desc=?", (desc,)
            ).fetchall()
        for row in rows:
            cat_original = row["cat"] or cat
            conn.execute(
                """UPDATE transactions SET cat=?, subcat=?, corrected=1,
                   cat_original=?, correction_source='manual' WHERE id=?""",
                (cat, subcat, cat_original, row["id"]),
            )
        return len(rows)

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

def get_monthly_stats(file_id: int = None, file_ids: list[int] = None, source: str = None,
                      date_from: str = None, date_to: str = None) -> list[dict]:
    ids = file_ids if file_ids is not None else ([file_id] if file_id else [])
    if not ids:
        return []
    placeholders = ','.join('?' * len(ids))
    params = list(ids)
    clauses = []
    if source:
        clauses.append("source=?")
        params.append(source)
    else:
        dedup = banksalad_dedup_clause(get_synced_sources())
        if dedup:
            clauses.append(dedup)
    if date_from:
        clauses.append("date>=?"); params.append(date_from)
    if date_to:
        clauses.append("date<=?"); params.append(date_to)
    extra = (" AND " + " AND ".join(clauses)) if clauses else ""
    with get_conn() as conn:
        rows = conn.execute(f"""
            SELECT substr(date,1,7) AS month,
                   SUM(CASE WHEN type='수입' AND amount>0 THEN amount ELSE 0 END) AS income,
                   SUM(CASE
                     WHEN type='지출' AND amount<0 THEN ABS(amount)
                     WHEN type='지출' AND amount>0 AND source IN ('coupang','naverpay') THEN amount
                     ELSE 0
                   END) AS expense,
                   0 AS refund
            FROM transactions WHERE file_id IN ({placeholders}){extra}
            GROUP BY month ORDER BY month
        """, params).fetchall()
        return [dict(r) for r in rows]


def _build_clauses(ids, date_from, date_to, source, extra=None):
    # 뱅크샐러드: 음수 지출만, 동기화(쿠팡/네이버페이): 양수 지출만
    expense_filter = "(type='지출' AND (amount<0 OR source IN ('coupang','naverpay')))"
    clauses = [f"file_id IN ({','.join('?' * len(ids))})", expense_filter]
    params = list(ids)
    if extra:
        clauses += extra
    if date_from:
        clauses.append("date>=?"); params.append(date_from)
    if date_to:
        clauses.append("date<=?"); params.append(date_to)
    if source:
        clauses.append("source=?"); params.append(source)
    else:
        dedup = banksalad_dedup_clause(get_synced_sources())
        if dedup:
            clauses.append(dedup)
    return "WHERE " + " AND ".join(clauses), params


def get_category_stats(file_id: int = None, date_from: str = None, date_to: str = None, file_ids: list[int] = None, source: str = None) -> list[dict]:
    ids = file_ids if file_ids is not None else ([file_id] if file_id else [])
    if not ids:
        return []
    where, params = _build_clauses(ids, date_from, date_to, source)
    with get_conn() as conn:
        rows = conn.execute(f"""
            SELECT cat, SUM(ABS(amount)) AS total, COUNT(*) AS cnt
            FROM transactions {where}
            GROUP BY cat ORDER BY total DESC
        """, params).fetchall()
        return [dict(r) for r in rows]


def get_method_stats(file_id: int = None, date_from: str = None, date_to: str = None, file_ids: list[int] = None, source: str = None) -> list[dict]:
    ids = file_ids if file_ids is not None else ([file_id] if file_id else [])
    if not ids:
        return []
    where, params = _build_clauses(ids, date_from, date_to, source)
    with get_conn() as conn:
        rows = conn.execute(f"""
            SELECT method, SUM(ABS(amount)) AS total, COUNT(*) AS cnt
            FROM transactions {where}
            GROUP BY method ORDER BY total DESC LIMIT 15
        """, params).fetchall()
        return [dict(r) for r in rows]


def get_merchant_stats(file_id: int = None, date_from: str = None, date_to: str = None, file_ids: list[int] = None, source: str = None) -> list[dict]:
    ids = file_ids if file_ids is not None else ([file_id] if file_id else [])
    if not ids:
        return []
    where, params = _build_clauses(ids, date_from, date_to, source)
    with get_conn() as conn:
        rows = conn.execute(f"""
            SELECT desc, SUM(ABS(amount)) AS total, COUNT(*) AS cnt
            FROM transactions {where}
            GROUP BY desc ORDER BY total DESC LIMIT 200
        """, params).fetchall()
        return [{"merchant": r["desc"], "total": r["total"], "count": r["cnt"]} for r in rows]


def get_source_stats(file_id: int = None, date_from: str = None, date_to: str = None, file_ids: list[int] = None) -> list[dict]:
    """뱅크샐러드/쿠팡/네이버페이 등 데이터 출처별 지출 합계."""
    ids = file_ids if file_ids is not None else ([file_id] if file_id else [])
    if not ids:
        return []
    expense_filter = "(type='지출' AND (amount<0 OR source IN ('coupang','naverpay')))"
    clauses = [f"file_id IN ({','.join('?' * len(ids))})", expense_filter]
    params = list(ids)
    if date_from:
        clauses.append("date>=?"); params.append(date_from)
    if date_to:
        clauses.append("date<=?"); params.append(date_to)
    where = "WHERE " + " AND ".join(clauses)
    with get_conn() as conn:
        rows = conn.execute(f"""
            SELECT source, SUM(ABS(amount)) AS total, COUNT(*) AS cnt
            FROM transactions {where}
            GROUP BY source ORDER BY total DESC
        """, params).fetchall()
        return [dict(r) for r in rows]


# ── Category rules ─────────────────────────────────────────────────────────

def list_rules() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM category_rules ORDER BY id DESC").fetchall()
        return [dict(r) for r in rows]


def add_rule(keyword: str, field: str, cat: str, subcat: str = "미분류", exclude_from_dashboard: bool = False):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO category_rules (keyword, field, cat, subcat, exclude_from_dashboard, created_at) VALUES (?,?,?,?,?,?)",
            (keyword, field, cat, subcat, int(exclude_from_dashboard), datetime.now().isoformat()),
        )


def update_rule(rule_id: int, keyword: str, field: str, cat: str, subcat: str = "미분류", exclude_from_dashboard: bool = False):
    with get_conn() as conn:
        conn.execute(
            "UPDATE category_rules SET keyword=?, field=?, cat=?, subcat=?, exclude_from_dashboard=? WHERE id=?",
            (keyword, field, cat, subcat, int(exclude_from_dashboard), rule_id)
        )

def delete_rule(rule_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM category_rules WHERE id=?", (rule_id,))


def _rule_val(tx, field: str) -> str:
    """규칙 필드 이름을 트랜잭션 컬럼 값으로 변환. desc/merchant 둘 다 제품명 컬럼."""
    if field in ("desc", "merchant"):
        return tx["desc"] or ""
    if field == "memo":
        return tx["memo"] or ""
    return tx["method"] or ""

def apply_rules_to_file(file_id: int) -> int:
    """Apply all saved rules to transactions of a file. Returns count of updates."""
    rules = list_rules()
    if not rules:
        return 0
    count = 0
    with get_conn() as conn:
        txs = conn.execute(
            "SELECT id, desc, method, memo FROM transactions WHERE file_id=?", (file_id,)
        ).fetchall()
        for tx in txs:
            for rule in rules:
                val = _rule_val(tx, rule["field"])
                if rule["keyword"].lower() in val.lower():
                    conn.execute(
                        """UPDATE transactions SET cat=?, subcat=?, corrected=1,
                           cat_original=COALESCE(cat_original, cat),
                           correction_source='rule' WHERE id=?""",
                        (rule["cat"], rule["subcat"], tx["id"]),
                    )
                    count += 1
                    break
    return count


def seed_subcats_if_empty(subcat_map: dict):
    """cat_subcats 테이블이 비어있을 때 SUBCAT_MAP으로 초기화"""
    with get_conn() as conn:
        count = conn.execute("SELECT COUNT(*) FROM cat_subcats").fetchone()[0]
        if count == 0:
            for cat, subs in subcat_map.items():
                for i, sub in enumerate(subs):
                    conn.execute(
                        "INSERT OR IGNORE INTO cat_subcats(cat_name, subcat_name, sort_order) VALUES(?,?,?)",
                        (cat, sub, i)
                    )

def get_all_subcats() -> dict:
    with get_conn() as conn:
        rows = conn.execute("SELECT cat_name, subcat_name FROM cat_subcats ORDER BY cat_name, sort_order").fetchall()
    result: dict = {}
    for r in rows:
        result.setdefault(r["cat_name"], []).append(r["subcat_name"])
    return result

def add_subcat(cat_name: str, subcat_name: str):
    with get_conn() as conn:
        max_order = conn.execute(
            "SELECT COALESCE(MAX(sort_order),0) FROM cat_subcats WHERE cat_name=?", (cat_name,)
        ).fetchone()[0]
        conn.execute(
            "INSERT OR IGNORE INTO cat_subcats(cat_name, subcat_name, sort_order) VALUES(?,?,?)",
            (cat_name, subcat_name, max_order + 1)
        )

def delete_subcat(cat_name: str, subcat_name: str):
    with get_conn() as conn:
        conn.execute("DELETE FROM cat_subcats WHERE cat_name=? AND subcat_name=?", (cat_name, subcat_name))

def get_custom_categories() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT name, icon FROM custom_categories ORDER BY id").fetchall()
    return [dict(r) for r in rows]

def add_custom_category(name: str, icon: str = "📦"):
    with get_conn() as conn:
        conn.execute("INSERT OR IGNORE INTO custom_categories(name, icon) VALUES(?,?)", (name, icon))

def delete_custom_category(name: str):
    with get_conn() as conn:
        conn.execute("DELETE FROM custom_categories WHERE name=?", (name,))
        conn.execute("DELETE FROM cat_subcats WHERE cat_name=?", (name,))

def apply_single_rule(rule_id: int, file_ids: list[int]) -> int:
    """특정 규칙 하나만 기존 데이터에 적용"""
    rules = list_rules()
    rule = next((r for r in rules if r["id"] == rule_id), None)
    if not rule:
        return 0
    placeholders = ','.join('?' * len(file_ids))
    count = 0
    with get_conn() as conn:
        txs = conn.execute(
            f"SELECT id, desc, method, memo FROM transactions WHERE file_id IN ({placeholders})", file_ids
        ).fetchall()
        for tx in txs:
            val = _rule_val(tx, rule["field"])
            if rule["keyword"].lower() in val.lower():
                conn.execute(
                    """UPDATE transactions SET cat=?, subcat=?, corrected=1,
                       cat_original=COALESCE(cat_original, cat),
                       correction_source='rule' WHERE id=?""",
                    (rule["cat"], rule["subcat"], tx["id"]),
                )
                count += 1
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
