import os
import uuid
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, UploadFile, HTTPException, Query, Body
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import database as db
import excel_parser
import ai_service

# ── Init ───────────────────────────────────────────────────────────────────
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
)

# ── Pydantic models ────────────────────────────────────────────────────────

class CategoryUpdate(BaseModel):
    cat: str
    subcat: str = "미분류"

class BulkCategoryUpdate(BaseModel):
    updates: list[dict]  # [{id, cat, subcat}]
    source: str = "manual"

class RuleCreate(BaseModel):
    keyword: str
    field: str = "desc"
    cat: str
    subcat: str = "미분류"

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

# ── Transactions API ───────────────────────────────────────────────────────

@app.get("/api/transactions")
def get_transactions(
    file_id: Optional[int] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    tx_type: Optional[str] = Query(None),
    cat: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    amount_sign: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
):
    fids = db.get_visible_file_ids(file_id)
    if not fids:
        return {"items": [], "total": 0}
    rows, total = db.query_transactions(
        file_ids=fids, date_from=date_from, date_to=date_to,
        tx_type=tx_type, cat=cat, search=search,
        amount_sign=amount_sign, source=source, limit=limit, offset=offset,
    )
    return {"items": rows, "total": total}

@app.put("/api/transactions/{tx_id}/category")
def update_category(tx_id: int, body: CategoryUpdate):
    tx = db.get_transaction(tx_id)
    if not tx:
        raise HTTPException(404, "거래를 찾을 수 없습니다.")
    db.update_transaction_category(tx_id, body.cat, body.subcat, "manual")
    return {"ok": True}

@app.post("/api/transactions/bulk-update")
def bulk_update(body: BulkCategoryUpdate):
    db.bulk_update_categories(body.updates, body.source)
    return {"ok": True, "count": len(body.updates)}

# ── Stats API ──────────────────────────────────────────────────────────────

@app.get("/api/stats/monthly")
def monthly_stats(file_id: Optional[int] = Query(None), source: Optional[str] = Query(None)):
    fids = db.get_visible_file_ids(file_id)
    if not fids:
        return []
    return db.get_monthly_stats(file_ids=fids, source=source)

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
    db.add_rule(body.keyword, body.field, body.cat, body.subcat)
    for fid in db.get_visible_file_ids():
        db.apply_rules_to_file(fid)
    return {"ok": True}

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

    suggestions = ai_service.suggest_categories_for_transactions(txs)
    return {"suggestions": suggestions}

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
    session_msgs = session["messages"] if session else []

    reply = ai_service.chat_with_data(session_msgs, body.message, context)
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
    return {
        "categories": ai_service.CATEGORY_LIST,
        "subcat_map": ai_service.SUBCAT_MAP,
    }

@app.get("/api/health")
def health():
    return {"ok": True, "active_file": db.get_active_file_id()}
