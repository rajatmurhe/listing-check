from __future__ import annotations

import asyncio
import os
import time
from collections import defaultdict, deque
from datetime import date, timedelta
from pathlib import Path

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

import engine
from extract import GEMINI_KEY, GEMINI_MODEL
from policy import ACTIONS
from store import Store

app = FastAPI(title="Listing Check")
store = Store()
lock = asyncio.Lock()
CRON_TOKEN = os.environ.get("CRON_TOKEN", "")
STATIC = Path(__file__).parent

_hits: dict[str, deque] = defaultdict(deque)
_day_count = {"day": None, "n": 0}
_last_manual = {"t": 0.0}
TRY_PER_HOUR = int(os.environ.get("TRY_PER_HOUR", "12"))
TRY_PER_DAY = int(os.environ.get("TRY_PER_DAY", "300"))


def _load() -> dict:
    st = store.get("state")
    if st is None or (engine.today() - date.fromisoformat(st["seeded_on"])).days > 7:
        st = engine.new_state()
        store.put("state", st)
    return st


def _ip(req: Request) -> str:
    return (req.headers.get("x-forwarded-for") or (req.client.host if req.client else "?")).split(",")[0].strip()


def _limit(req: Request):
    now = time.time()
    q = _hits[_ip(req)]
    while q and now - q[0] > 3600:
        q.popleft()
    if len(q) >= TRY_PER_HOUR:
        raise HTTPException(429, "You have tried a lot of notices in the last hour. Please wait a little and try again.")
    today = engine.today().isoformat()
    if _day_count["day"] != today:
        _day_count.update(day=today, n=0)
    if _day_count["n"] >= TRY_PER_DAY:
        raise HTTPException(429, "The demo has reached today's limit for new notices. The sample restaurants still work.")
    q.append(now)
    _day_count["n"] += 1


def _view(st: dict) -> dict:
    return {
        "today": engine.today().isoformat(),
        "ai": {"enabled": bool(GEMINI_KEY), "model": GEMINI_MODEL if GEMINI_KEY else None},
        "storage": store.kind,
        "restaurants": engine.listing_view(st),
        "messages": st["messages"][:60],
        "runs": st["runs"][:15],
        "decisions": st["decisions"],
        "sources": st["sources"],
        "actions": ACTIONS,
        "bookings": st.get("bookings", []),
    }


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


@app.get("/healthz")
async def health():
    return {"ok": True}


@app.get("/api/state")
async def state():
    async with lock:
        return _view(_load())


@app.post("/api/run-check")
async def run_check(x_cron_token: str | None = Header(default=None)):
    trigger = "manual"
    if x_cron_token:
        if not CRON_TOKEN or x_cron_token != CRON_TOKEN:
            raise HTTPException(403, "Bad token")
        trigger = "nightly schedule"
    else:
        if time.time() - _last_manual["t"] < 20:
            raise HTTPException(429, "A check just ran. Wait a few seconds and try again.")
        _last_manual["t"] = time.time()
    async with lock:
        st = _load()
        run = await engine.run_check(st, trigger)
        store.put("state", st)
        return {"run": run, "state": _view(st)}


@app.post("/api/answer")
async def answer(message_id: str = Form(...), choice: str = Form(...)):
    async with lock:
        st = _load()
        result = engine.answer(st, message_id, choice)
        store.put("state", st)
        return {"result": result, "state": _view(st)}


@app.post("/api/try")
async def try_notice(request: Request, restaurant_id: str = Form(...), kind: str = Form(...),
                     text: str = Form(""), posted_on: str = Form(""), photo: UploadFile | None = File(None)):
    if kind not in ("authorised", "public", "diner_report"):
        raise HTTPException(400, "Unknown source type")
    image = None
    if photo is not None and photo.filename:
        data = await photo.read()
        if len(data) > 4 * 1024 * 1024:
            raise HTTPException(400, "Please use a photo under 4 MB.")
        if photo.content_type not in ("image/jpeg", "image/png", "image/webp"):
            raise HTTPException(400, "Please upload a JPG, PNG or WEBP photo.")
        image = (data, photo.content_type)
    if not text.strip() and image is None:
        raise HTTPException(400, "Paste a notice or upload a photo first.")
    if len(text) > 2000:
        raise HTTPException(400, "Please keep the notice under 2,000 characters.")
    t = engine.today()
    try:
        p = date.fromisoformat(posted_on) if posted_on else t
    except ValueError:
        p = t
    p = min(max(p, t - timedelta(days=60)), t)
    _limit(request)
    async with lock:
        st = _load()
        if not any(r["id"] == restaurant_id for r in st["restaurants"]):
            raise HTTPException(400, "Unknown restaurant")
        res = await engine.try_notice(st, restaurant_id, kind, text, p.isoformat(), image)
        store.put("state", st)
        return {"result": res, "state": _view(st)}


@app.post("/api/reset")
async def reset():
    async with lock:
        old = store.get("state") or {}
        st = engine.new_state()
        st["runs"] = old.get("runs", [])  # keep the real run history
        store.put("state", st)
        return {"state": _view(st)}


@app.exception_handler(HTTPException)
async def http_err(_, exc: HTTPException):
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)
