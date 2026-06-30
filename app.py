import os
import uuid
import json
import shutil
import secrets
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, File, UploadFile, HTTPException, Query, Body, Request, Response, Cookie
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import database as db
import excel_parser
import ai_service

# ── Init ───────────────────────────────────────────────────────────────────
load_dotenv()

UPLOAD_DIR = Path(__file__).parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
STATIC_DIR = Path(__file__).parent / "static"

db.init_db()

app = FastAPI(title="Sobify", version="1.0.0")

# Chrome 확장에서 localhost로 POST할 수 있도록 CORS 허용
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 확장 프로그램은 chrome-extension:// origin 사용
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

# ── Auth ───────────────────────────────────────────────────────────────────
# 메모리 내 세션 저장소 {token: expires_at}
_sessions: dict[str, datetime] = {}
SESSION_TTL_DAYS = 30
SYNC_PATHS = {"/api/sync/coupang", "/api/sync/naverpay", "/api/health"}

def _get_password() -> str:
    return os.environ.get("APP_PASSWORD", "2016")

def _make_token() -> str:
    return secrets.token_hex(32)

def _is_valid_session(token: str | None) -> bool:
    if not token:
        return False
    exp = _sessions.get(token)
    if not exp:
        return False
    if datetime.utcnow() > exp:
        _sessions.pop(token, None)
        return False
    return True

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    # 인증 없이 허용: 정적 파일, 인증 엔드포인트, 확장 동기화/헬스
    if (path.startswith("/static")
            or path.startswith("/api/auth")
            or path in SYNC_PATHS):
        return await call_next(request)

    # 루트(/)는 항상 index.html 반환 (프론트엔드가 인증 처리)
    if path == "/":
        return await call_next(request)

    token = request.cookies.get("sobify_session")
    if not _is_valid_session(token):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)

    return await call_next(request)

# ── Pydantic models ────────────────────────────────────────────────────────

class CategoryUpdate(BaseModel):
    cat: str
    subcat: str = "미분류"
    memo: Optional[str] = None

class BulkCategoryUpdate(BaseModel):
    updates: list[dict]  # [{id, cat, subcat}]
    source: str = "manual"

class RuleCreate(BaseModel):
    keyword: str
    field: str = "desc"
    cat: str
    subcat: str = "미분류"
    apply_existing: bool = False
    exclude_from_dashboard: bool = False

class ChatMessage(BaseModel):
    message: str
    session_id: Optional[str] = None

# ── Static files ───────────────────────────────────────────────────────────
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/")
def root():
    return FileResponse(str(STATIC_DIR / "index.html"))

# ── Files API ──────────────────────────────────────────────────────────────

@app.get("/api/files")
def list_files():
    return db.list_files()

@app.post("/api/files/upload")
async def upload_excel(file: UploadFile = File(...)):
    if not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(400, "Excel 파일(.xlsx)만 업로드 가능합니다.")

    ext = Path(file.filename).suffix
    saved_name = f"{uuid.uuid4().hex}{ext}"
    dest = UPLOAD_DIR / saved_name

    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        rows = excel_parser.parse_banksalad_excel(dest)
    except Exception as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, f"Excel 파싱 오류: {e}")

    if not rows:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, "데이터가 없습니다.")

    date_from, date_to = excel_parser.get_date_range(rows)

    with db.get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO files (name, original_name, uploaded_at, active) VALUES (?,?,?,1)",
            (saved_name, file.filename, datetime.now().isoformat()),
        )
        file_id = cur.lastrowid
        conn.execute("UPDATE files SET active=0 WHERE id!=?", (file_id,))

    db.insert_transactions(file_id, rows)

    # 저장된 규칙 자동 적용
    applied = db.apply_rules_to_file(file_id)

    return {
        "file_id": file_id,
        "original_name": file.filename,
        "row_count": len(rows),
        "date_from": date_from,
        "date_to": date_to,
        "rules_applied": applied,
    }

@app.post("/api/files/{file_id}/activate")
def activate_file(file_id: int):
    db.set_active_file(file_id)
    return {"ok": True}

@app.delete("/api/files/{file_id}")
def delete_file(file_id: int):
    files = db.list_files()
    target = next((f for f in files if f["id"] == file_id), None)
    if target:
        (UPLOAD_DIR / target["name"]).unlink(missing_ok=True)
        db.delete_file(file_id)
    return {"ok": True}

@app.delete("/api/source/{source}")
def delete_source(source: str):
    """출처별 데이터 전체 삭제 (banksalad=활성 파일, coupang/naverpay=동기화 파일)."""
    if source not in ("banksalad", "coupang", "naverpay"):
        raise HTTPException(400, "지원하지 않는 출처입니다.")
    deleted = db.delete_source_data(source)
    return {"ok": True, "deleted": deleted}

@app.get("/api/source/{source}/stats")
def source_stats(source: str):
    """출처별 데이터 건수 조회."""
    count = db.get_source_count(source)
    return {"source": source, "count": count}

# ── Transactions API ───────────────────────────────────────────────────────

@app.get("/api/transactions")
def get_transactions(
    file_id: Optional[int] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    tx_type: Optional[str] = Query(None),
    cat: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    method_search: Optional[str] = Query(None),
    amount_sign: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    exclude_transfer: bool = Query(True),
    weekend_only: bool = Query(False),
    sort: Optional[str] = Query(None),
    sort_dir: int = Query(-1),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
):
    fids = db.get_visible_file_ids(file_id)
    if not fids:
        return {"items": [], "total": 0, "total_expense": 0, "total_income": 0}
    rows, total, total_expense, total_income = db.query_transactions(
        file_ids=fids, date_from=date_from, date_to=date_to,
        tx_type=tx_type, cat=cat, search=search, method_search=method_search,
        amount_sign=amount_sign, source=source, exclude_transfer=exclude_transfer,
        weekend_only=weekend_only, sort=sort, sort_dir=sort_dir, limit=limit, offset=offset,
    )
    return {"items": rows, "total": total, "total_expense": total_expense, "total_income": total_income}

@app.put("/api/transactions/{tx_id}/category")
def update_category(tx_id: int, body: CategoryUpdate):
    tx = db.get_transaction(tx_id)
    if not tx:
        raise HTTPException(404, "거래를 찾을 수 없습니다.")
    db.update_transaction_category(tx_id, body.cat, body.subcat, "manual", memo=body.memo)
    return {"ok": True}

@app.put("/api/transactions/{tx_id}/type")
def update_type(tx_id: int, body: dict):
    new_type = body.get("type", "")
    if new_type not in ("수입", "지출", "이체", "취소"):
        raise HTTPException(400, "유효하지 않은 유형입니다.")
    with db.get_conn() as conn:
        conn.execute("UPDATE transactions SET type=? WHERE id=?", (new_type, tx_id))
    return {"ok": True}

@app.put("/api/transactions/{tx_id}/memo")
def update_memo(tx_id: int, body: dict):
    memo = body.get("memo", "")
    with db.get_conn() as conn:
        conn.execute("UPDATE transactions SET memo=? WHERE id=?", (memo, tx_id))
    return {"ok": True}

@app.put("/api/transactions/bulk-category")
def bulk_category_by_desc(body: CategoryUpdate, desc: str = Query(...), amount: Optional[int] = Query(None)):
    """같은 사용처(desc) 전체에 카테고리 일괄 적용. amount 지정 시 금액도 일치하는 건만."""
    count = db.bulk_update_category_by_desc(desc, body.cat, body.subcat, amount)
    return {"ok": True, "count": count}

@app.post("/api/transactions/bulk-update")
def bulk_update(body: BulkCategoryUpdate):
    db.bulk_update_categories(body.updates, body.source)
    return {"ok": True, "count": len(body.updates)}

@app.get("/api/transactions/{tx_id}/cancel-partner")
def cancel_partner(tx_id: int):
    """취소된 거래의 상대 쌍 반환 (같은 desc, 반대 부호, ±30일, type='취소')."""
    from datetime import datetime, timedelta
    tx = db.get_transaction(tx_id)
    if not tx:
        raise HTTPException(404, "거래를 찾을 수 없습니다.")
    d = datetime.strptime(tx["date"], "%Y-%m-%d")
    date_from = (d - timedelta(days=30)).strftime("%Y-%m-%d")
    date_to   = (d + timedelta(days=30)).strftime("%Y-%m-%d")
    with db.get_conn() as conn:
        row = conn.execute(
            """SELECT * FROM transactions
               WHERE id != ? AND type='취소'
                 AND desc=? AND ABS(amount)=ABS(?)
                 AND (amount * ? < 0)
                 AND date BETWEEN ? AND ?
               ORDER BY ABS(julianday(date) - julianday(?))
               LIMIT 1""",
            (tx_id, tx["desc"], tx["amount"], tx["amount"],
             date_from, date_to, tx["date"]),
        ).fetchone()
    return dict(row) if row else {}

@app.get("/api/transactions/{tx_id}/link-candidates")
def link_candidates(tx_id: int):
    """일반 거래에 수동으로 연결할 취소 후보 반환 (반대 부호, ±45일)."""
    from datetime import datetime, timedelta
    tx = db.get_transaction(tx_id)
    if not tx:
        raise HTTPException(404, "거래를 찾을 수 없습니다.")
    d = datetime.strptime(tx["date"], "%Y-%m-%d")
    date_from = (d - timedelta(days=45)).strftime("%Y-%m-%d")
    date_to   = (d + timedelta(days=45)).strftime("%Y-%m-%d")
    fids = db.get_visible_file_ids()
    fid_ph = ','.join('?'*len(fids))
    with db.get_conn() as conn:
        rows = conn.execute(
            f"""SELECT * FROM transactions
                WHERE id != ? AND file_id IN ({fid_ph})
                  AND (amount * ? < 0)
                  AND date BETWEEN ? AND ?
                ORDER BY ABS(ABS(amount) - ABS(?)), ABS(julianday(date) - julianday(?))
                LIMIT 30""",
            (tx_id, *fids, tx["amount"], date_from, date_to, tx["amount"], tx["date"]),
        ).fetchall()
    return [dict(r) for r in rows]

@app.get("/api/transactions/{tx_id}/match-candidates")
def match_candidates(tx_id: int):
    """뱅크샐러드 거래와 금액이 같거나 bundle 합산이 같은 쿠팡/네이버페이 후보 반환."""
    from datetime import datetime, timedelta
    tx = db.get_transaction(tx_id)
    if not tx:
        raise HTTPException(404, "거래를 찾을 수 없습니다.")
    amt = abs(tx["amount"])
    date = tx["date"]
    d = datetime.strptime(date, "%Y-%m-%d")
    fids = db.get_visible_file_ids()
    fid_ph = ','.join('?'*len(fids))

    def _single(days):
        df = (d - timedelta(days=days)).strftime("%Y-%m-%d")
        dt = (d + timedelta(days=days)).strftime("%Y-%m-%d")
        with db.get_conn() as conn:
            rows = conn.execute(
                f"""SELECT *, NULL AS bundle_items FROM transactions
                    WHERE file_id IN ({fid_ph})
                      AND source IN ('coupang','naverpay')
                      AND amount=? AND date>=? AND date<=? AND type!='취소'
                    ORDER BY ABS(julianday(date)-julianday(?)), date DESC""",
                fids + [amt, df, dt, date],
            ).fetchall()
        return [dict(r) for r in rows]

    def _bundle(days):
        """bundle_id가 있는 쿠팡 묶음에서 합산금액이 일치하는 그룹 찾기."""
        df = (d - timedelta(days=days)).strftime("%Y-%m-%d")
        dt = (d + timedelta(days=days)).strftime("%Y-%m-%d")
        with db.get_conn() as conn:
            groups = conn.execute(
                f"""SELECT bundle_id, SUM(amount) AS total, MIN(date) AS date,
                           GROUP_CONCAT(desc, ' / ') AS bundle_items,
                           MIN(cat) AS cat, MIN(subcat) AS subcat
                    FROM transactions
                    WHERE file_id IN ({fid_ph})
                      AND source='coupang' AND bundle_id IS NOT NULL
                      AND date>=? AND date<=? AND type!='취소'
                    GROUP BY bundle_id
                    HAVING total=?""",
                fids + [df, dt, amt],
            ).fetchall()
        return [dict(g) for g in groups]

    # 1) 정확히 금액 일치하는 개별 항목 (±3일 → ±30일)
    singles = _single(3) or _single(30)
    # 2) 배송 묶음 합산 일치 (±3일 → ±30일)
    bundles = _bundle(3) or _bundle(30)

    # 묶음 결과에 is_bundle 플래그 추가
    for b in bundles:
        b["is_bundle"] = True
    for s in singles:
        s["is_bundle"] = False

    # 중복 제거: 이미 single로 잡힌 건 bundle에서 제외
    single_bundle_ids = {s.get("bundle_id") for s in singles if s.get("bundle_id")}
    bundles = [b for b in bundles if b.get("bundle_id") not in single_bundle_ids]

    return bundles + singles

class CancelPairBody(BaseModel):
    ids: list[int]
    cancel: bool = True  # False면 취소 해제

@app.post("/api/transactions/cancel-pair")
def cancel_pair(body: CancelPairBody):
    if len(body.ids) < 1:
        raise HTTPException(400, "id가 필요합니다.")
    with db.get_conn() as conn:
        if body.cancel:
            for tx_id in body.ids:
                tx = conn.execute("SELECT amount FROM transactions WHERE id=?", (tx_id,)).fetchone()
                if not tx:
                    raise HTTPException(404, f"id {tx_id} 없음")
            conn.execute(
                f"UPDATE transactions SET type='취소' WHERE id IN ({','.join('?'*len(body.ids))})",
                body.ids,
            )
        else:
            for tx_id in body.ids:
                tx = conn.execute("SELECT amount FROM transactions WHERE id=?", (tx_id,)).fetchone()
                if tx:
                    new_type = "수입" if tx["amount"] > 0 else "지출"
                    conn.execute("UPDATE transactions SET type=? WHERE id=?", (new_type, tx_id))
    return {"ok": True}

@app.delete("/api/transactions/{tx_id}")
def delete_transaction(tx_id: int):
    with db.get_conn() as conn:
        r = conn.execute("DELETE FROM transactions WHERE id=?", (tx_id,))
    if r.rowcount == 0:
        raise HTTPException(404, "거래를 찾을 수 없습니다.")
    return {"ok": True}

@app.post("/api/transactions/redetect-cancel")
def redetect_cancel():
    """기존 거래 전체에 취소 쌍 재감지 실행."""
    fids = db.get_visible_file_ids()
    total = sum(db.mark_cancelled_pairs(fid) for fid in fids)
    return {"ok": True, "marked": total}

# ── Stats API ──────────────────────────────────────────────────────────────

@app.get("/api/stats/monthly")
def monthly_stats(file_id: Optional[int] = Query(None), source: Optional[str] = Query(None),
                  date_from: Optional[str] = Query(None), date_to: Optional[str] = Query(None)):
    fids = db.get_visible_file_ids(file_id)
    if not fids:
        return []
    return db.get_monthly_stats(file_ids=fids, source=source, date_from=date_from, date_to=date_to)

@app.get("/api/stats/categories")
def category_stats(
    file_id: Optional[int] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
):
    fids = db.get_visible_file_ids(file_id)
    if not fids:
        return []
    return db.get_category_stats(date_from=date_from, date_to=date_to, file_ids=fids, source=source)

@app.get("/api/stats/methods")
def method_stats(
    file_id: Optional[int] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
):
    fids = db.get_visible_file_ids(file_id)
    if not fids:
        return []
    return db.get_method_stats(date_from=date_from, date_to=date_to, file_ids=fids, source=source)

@app.get("/api/stats/merchants")
def merchant_stats(
    file_id: Optional[int] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
):
    fids = db.get_visible_file_ids(file_id)
    if not fids:
        return []
    return db.get_merchant_stats(date_from=date_from, date_to=date_to, file_ids=fids, source=source)

@app.get("/api/stats/sources")
def source_stats(
    file_id: Optional[int] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
):
    fids = db.get_visible_file_ids(file_id)
    if not fids:
        return []
    return db.get_source_stats(date_from=date_from, date_to=date_to, file_ids=fids)

# ── Category Rules API ─────────────────────────────────────────────────────

@app.get("/api/rules")
def list_rules():
    return db.list_rules()

@app.post("/api/rules")
def create_rule(body: RuleCreate):
    db.add_rule(body.keyword, body.field, body.cat, body.subcat, body.exclude_from_dashboard)
    count = 0
    if body.apply_existing:
        for fid in db.get_visible_file_ids():
            count += db.apply_rules_to_file(fid)
    return {"ok": True, "applied": count}

@app.put("/api/rules/{rule_id}")
def update_rule(rule_id: int, body: RuleCreate):
    db.update_rule(rule_id, body.keyword, body.field, body.cat, body.subcat, body.exclude_from_dashboard)
    if body.apply_existing:
        fids = db.get_visible_file_ids(None)
        if fids:
            db.apply_rules_to_file(fids)
    return {"ok": True}

@app.post("/api/rules/{rule_id}/apply")
def apply_single_rule(rule_id: int):
    fids = db.get_visible_file_ids(None)
    if not fids:
        raise HTTPException(400, "활성 파일이 없습니다.")
    count = db.apply_single_rule(rule_id, fids)
    return {"ok": True, "count": count}

@app.delete("/api/rules/{rule_id}")
def delete_rule(rule_id: int):
    db.delete_rule(rule_id)
    return {"ok": True}

@app.post("/api/rules/apply")
def apply_rules(file_id: Optional[int] = None):
    fids = db.get_visible_file_ids(file_id)
    if not fids:
        raise HTTPException(400, "활성 파일이 없습니다.")
    count = sum(db.apply_rules_to_file(fid) for fid in fids)
    return {"ok": True, "count": count}

# ── AI API ─────────────────────────────────────────────────────────────────

def _ai_key_error(e: Exception):
    from ai_service import AIKeyMissingError
    if isinstance(e, AIKeyMissingError):
        raise HTTPException(503, str(e))
    raise HTTPException(500, f"AI 오류: {e}")

@app.post("/api/ai/analyze-image")
async def analyze_image(file: UploadFile = File(...)):
    ext = Path(file.filename).suffix.lower()
    if ext not in (".png", ".jpg", ".jpeg", ".webp"):
        raise HTTPException(400, "이미지 파일만 업로드 가능합니다.")

    saved_name = f"img_{uuid.uuid4().hex}{ext}"
    dest = UPLOAD_DIR / saved_name
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        result = ai_service.analyze_payment_image(dest)
    except Exception as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(500, f"AI 분석 오류: {e}")

    # DB 거래와 매칭
    fids = db.get_visible_file_ids()
    matches = []
    if fids and result.get("transactions"):
        # 매칭 범위: 이미지 거래 날짜 ±5일
        all_dates = [t.get("date", "") for t in result["transactions"] if t.get("date")]
        if all_dates:
            d_from = min(all_dates)
            d_to = max(all_dates)
            # 여유 있게 ±7일
            from datetime import datetime, timedelta
            df = (datetime.strptime(d_from, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")
            dt = (datetime.strptime(d_to, "%Y-%m-%d") + timedelta(days=7)).strftime("%Y-%m-%d")
            db_txs, _ = db.query_transactions(file_ids=fids, date_from=df, date_to=dt, limit=500)
            matches = ai_service.match_image_transactions(result["transactions"], db_txs)

    dest.unlink(missing_ok=True)
    return {"analysis": result, "matches": matches}

@app.post("/api/ai/suggest-categories")
def suggest_categories(
    file_id: Optional[int] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    only_online_shopping: bool = Query(True),
):
    fids = db.get_visible_file_ids(file_id)
    if not fids:
        raise HTTPException(400, "활성 파일이 없습니다.")

    cat_filter = "온라인쇼핑" if only_online_shopping else None
    txs, _ = db.query_transactions(
        file_ids=fids, date_from=date_from, date_to=date_to,
        cat=cat_filter, amount_sign="pos", limit=50,
    )
    if not txs:
        return {"suggestions": []}

    try:
        suggestions = ai_service.suggest_categories_for_transactions(txs)
    except Exception as e:
        _ai_key_error(e)
    return {"suggestions": suggestions}

@app.get("/api/ai/session/{session_id}")
def get_ai_session(session_id: int):
    session = db.get_ai_session(session_id)
    if not session:
        raise HTTPException(404, "세션 없음")
    return session

@app.post("/api/ai/chat")
def ai_chat(body: ChatMessage):
    fids = db.get_visible_file_ids()

    # context 구성
    context: dict = {"total": 0, "total_expense": 0, "total_income": 0, "cat_summary": ""}
    if fids:
        monthly = db.get_monthly_stats(file_ids=fids)
        cats = db.get_category_stats(file_ids=fids)
        if monthly:
            context["date_from"] = monthly[0]["month"]
            context["date_to"] = monthly[-1]["month"]
            context["total_expense"] = sum(m["expense"] - m["refund"] for m in monthly)
            context["total_income"] = sum(m["income"] for m in monthly)
        if cats:
            lines = [f"{c['cat']}: {c['total']:,}원 ({c['cnt']}건)" for c in cats[:10]]
            context["cat_summary"] = "\n".join(lines)

    # 세션 관리
    session_id = body.session_id
    if not session_id:
        session_id = db.create_ai_session()
    session = db.get_ai_session(session_id)
    if not session:
        session_id = db.create_ai_session()
        session = db.get_ai_session(session_id)
    session_msgs = session["messages"] if session else []

    try:
        reply = ai_service.chat_with_data(session_msgs, body.message, context)
    except Exception as e:
        _ai_key_error(e)
    db.append_ai_message(session_id, "user", body.message)
    db.append_ai_message(session_id, "assistant", reply)

    # ACTION 파싱
    action_result = None
    if "ACTION: UPDATE_CATEGORIES" in reply and "UPDATES:" in reply:
        try:
            m = __import__("re").search(r"UPDATES:\s*(\[[\s\S]*?\])", reply)
            if m:
                updates_raw = json.loads(m.group(1))
                # 키워드 기반 업데이트
                if fids:
                    for u in updates_raw:
                        kw = u.get("keyword", "")
                        if kw:
                            db.add_rule(kw, u.get("field", "desc"), u["cat"], u.get("subcat", "미분류"))
                    count = sum(db.apply_rules_to_file(f) for f in fids)
                    action_result = {"type": "category_update", "count": count}
        except Exception:
            pass

    return {
        "reply": reply,
        "session_id": session_id,
        "action_result": action_result,
    }

# ── Sync API (Chrome Extension) ───────────────────────────────────────────

class SyncTransaction(BaseModel):
    date: str
    time: str = ""
    desc: str
    amount: int
    type: str = "지출"
    cat: str = "온라인쇼핑"
    subcat: str = "미분류"
    method: str = ""
    memo: str = ""
    external_id: Optional[str] = None

class SyncPayload(BaseModel):
    transactions: list[SyncTransaction]

@app.post("/api/sync/coupang")
def sync_coupang(payload: SyncPayload):
    rows = [t.model_dump() for t in payload.transactions]
    result = db.upsert_sync_transactions("coupang", rows)
    return result

@app.post("/api/sync/naverpay")
def sync_naverpay(payload: SyncPayload):
    rows = [t.model_dump() for t in payload.transactions]
    result = db.upsert_sync_transactions("naverpay", rows)
    return result

@app.get("/api/sync/status")
def sync_status():
    sources = ["coupang", "naverpay"]
    result = {}
    for source in sources:
        with db.get_conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) as cnt, MAX(date) as last_date "
                "FROM transactions WHERE source=?", (source,)
            ).fetchone()
            result[source] = {"count": row["cnt"], "last_date": row["last_date"]}
    return result

# ── Misc ───────────────────────────────────────────────────────────────────

@app.get("/api/categories")
def get_categories():
    db.seed_subcats_if_empty(ai_service.SUBCAT_MAP)
    db_subcats = db.get_all_subcats()
    # merge: built-in cats first, then custom cats; DB subcats override built-in
    merged_map = {**ai_service.SUBCAT_MAP, **{k: v for k, v in db_subcats.items() if k not in ai_service.SUBCAT_MAP}}
    for cat, subs in db_subcats.items():
        if cat in ai_service.SUBCAT_MAP:
            merged_map[cat] = subs  # DB is source of truth after seeding
    custom_cats = db.get_custom_categories()
    all_cats = list(ai_service.CATEGORY_LIST) + [c["name"] for c in custom_cats if c["name"] not in ai_service.CATEGORY_LIST]
    return {
        "categories": all_cats,
        "subcat_map": merged_map,
        "custom_categories": custom_cats,
    }

class SubcatBody(BaseModel):
    subcat_name: str

class CustomCatBody(BaseModel):
    name: str
    icon: str = "📦"

@app.post("/api/categories")
def create_custom_category(name: str = Query(None), icon: str = Query("📦"), body: Optional[CustomCatBody] = None):
    n = name or (body.name if body else None)
    i = icon or (body.icon if body else "📦")
    if not n:
        raise HTTPException(400, "name required")
    db.add_custom_category(n, i)
    return {"ok": True}

@app.delete("/api/categories/custom")
def remove_custom_category(cat: str = Query(...)):
    if cat in ai_service.CATEGORY_LIST:
        raise HTTPException(400, "기본 카테고리는 삭제할 수 없습니다")
    db.delete_custom_category(cat)
    return {"ok": True}

@app.post("/api/categories/subcats")
def add_subcat(cat: str = Query(...), body: SubcatBody = ...):
    db.seed_subcats_if_empty(ai_service.SUBCAT_MAP)
    db.add_subcat(cat, body.subcat_name)
    return {"ok": True}

@app.delete("/api/categories/subcats")
def remove_subcat(cat: str = Query(...), subcat: str = Query(...)):
    db.delete_subcat(cat, subcat)
    return {"ok": True}

@app.get("/api/health")
def health():
    return {"ok": True, "active_file": db.get_active_file_id()}

# ── Auth API ───────────────────────────────────────────────────────────────

class LoginBody(BaseModel):
    password: str

class ChangePasswordBody(BaseModel):
    current: str
    new_password: str

@app.post("/api/auth/login")
def login(body: LoginBody, response: Response):
    if body.password != _get_password():
        raise HTTPException(status_code=401, detail="패스워드가 올바르지 않습니다")
    token = _make_token()
    _sessions[token] = datetime.utcnow() + timedelta(days=SESSION_TTL_DAYS)
    response.set_cookie(
        key="sobify_session",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=SESSION_TTL_DAYS * 86400,
    )
    return {"ok": True}

@app.post("/api/auth/logout")
def logout(response: Response, sobify_session: str = Cookie(default=None)):
    if sobify_session:
        _sessions.pop(sobify_session, None)
    response.delete_cookie("sobify_session")
    return {"ok": True}

@app.get("/api/auth/check")
def auth_check(sobify_session: str = Cookie(default=None)):
    return {"authenticated": _is_valid_session(sobify_session)}

@app.post("/api/auth/change-password")
def change_password(body: ChangePasswordBody, sobify_session: str = Cookie(default=None)):
    if not _is_valid_session(sobify_session):
        raise HTTPException(status_code=401, detail="Unauthorized")
    if body.current != _get_password():
        raise HTTPException(status_code=400, detail="현재 패스워드가 올바르지 않습니다")

    env_path = Path(__file__).parent / ".env"
    content = env_path.read_text(encoding="utf-8")
    import re
    new_content = re.sub(r"^APP_PASSWORD=.*$", f"APP_PASSWORD={body.new_password}", content, flags=re.MULTILINE)
    if "APP_PASSWORD=" not in new_content:
        new_content += f"\nAPP_PASSWORD={body.new_password}\n"
    env_path.write_text(new_content, encoding="utf-8")
    os.environ["APP_PASSWORD"] = body.new_password
    return {"ok": True}
