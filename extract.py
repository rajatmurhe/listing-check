"""Turn a notice (text or photo) into structured claims.

The AI only extracts. It never decides what happens to a listing; policy.py does.
If the AI is unavailable, a basic parser runs instead and the result says so.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import re
from datetime import date, timedelta

import httpx

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")

CHANGE_TYPES = [
    "temporary_closure", "hours_change", "reopening_or_cancellation",
    "permanent_closure", "report_closed_during_hours", "no_change", "unclear",
]

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "transcript": {"type": "STRING", "description": "The full text of the notice. For a photo, the words visible in it."},
        "is_about_this_restaurant": {"type": "BOOLEAN"},
        "branch_mentioned": {"type": "STRING", "nullable": True, "description": "Outlet or area the notice names, exactly as written, or null if none"},
        "change_type": {"type": "STRING", "enum": CHANGE_TYPES},
        "start_date": {"type": "STRING", "nullable": True, "description": "YYYY-MM-DD"},
        "end_date": {"type": "STRING", "nullable": True, "description": "YYYY-MM-DD, same as start for a single day"},
        "date_certainty": {"type": "STRING", "enum": ["explicit", "relative", "missing"],
                            "description": "explicit if a calendar date is written, relative if worked out from words like 'this Saturday', missing if no date"},
        "new_open": {"type": "STRING", "nullable": True, "description": "HH:MM 24 hour"},
        "new_close": {"type": "STRING", "nullable": True, "description": "HH:MM 24 hour"},
        "applies_to_days": {"type": "ARRAY", "items": {"type": "STRING", "enum": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]}},
        "quote": {"type": "STRING", "description": "The exact words from the transcript that support the claim, copied verbatim"},
        "summary": {"type": "STRING", "description": "One short plain sentence"},
    },
    "required": ["transcript", "is_about_this_restaurant", "change_type", "date_certainty", "quote", "summary"],
}


def _prompt(restaurant: dict, source: dict, today: date) -> str:
    hours = ", ".join(f"{k}: {'closed' if v is None else v[0] + ' to ' + v[1]}" for k, v in restaurant["hours"].items())
    others = ", ".join(restaurant["other_branches"]) or "none"
    return f"""You extract facts from a notice about a restaurant's opening hours. You do not decide anything.

Restaurant on the listing: {restaurant['name']}, {restaurant['branch']} outlet.
Its other outlets: {others}.
Listed regular hours: {hours}.
Today is {today.isoformat()} ({today.strftime('%A')}). The notice was posted on {source.get('posted_on') or 'an unknown date'}.
Where it came from: {source.get('channel', 'unknown')}.

Rules:
- Report only what the notice says. Do not guess a date, outlet or time that is not written.
- branch_mentioned: the outlet or area named in the notice, or null if it names none.
- Use change_type report_closed_during_hours when a diner says they found it closed.
- Use reopening_or_cancellation when the notice cancels a closure or says it is open as usual.
- Resolve a written day and month to the nearest matching date to the posted date. Use date_certainty relative for words like 'tomorrow' or 'this Saturday'.
- quote must be copied word for word from the transcript.
- Reply with JSON only, using these keys: transcript, is_about_this_restaurant, branch_mentioned, change_type
  (one of {', '.join(CHANGE_TYPES)}), start_date, end_date, date_certainty (explicit, relative or missing),
  new_open, new_close, applies_to_days, quote, summary.

Notice:
{source.get('text') or '(see the attached photo)'}"""


async def extract(restaurant: dict, source: dict, today: date, image: tuple[bytes, str] | None = None) -> dict:
    """Return the extraction plus which engine produced it."""
    if GEMINI_KEY:
        try:
            out = await _gemini(restaurant, source, today, image)
            out["engine"] = "ai"
            out["engine_note"] = f"Read by {_model['name']}"
            return _check_quote(out)
        except GeminiError as e:
            note = f"The AI could not read this ({e}), so the basic parser was used."
        except Exception as e:  # noqa: BLE001
            note = f"The AI could not read this ({type(e).__name__}), so the basic parser was used."
    else:
        note = "No AI key is set on this server, so the basic parser was used."
    if image and not source.get("text"):
        return {"engine": "none", "engine_note": note + " A photo needs the AI, so nothing could be read.",
                "transcript": "", "is_about_this_restaurant": False, "branch_mentioned": None,
                "change_type": "unclear", "start_date": None, "end_date": None, "date_certainty": "missing",
                "new_open": None, "new_close": None, "applies_to_days": [], "quote": "", "summary": "Photo could not be read."}
    out = basic_parse(restaurant, source, today)
    out["engine"] = "basic"
    out["engine_note"] = note
    return _check_quote(out)


class GeminiError(Exception):
    pass


# Google retires model names now and then, and free keys have small per-minute limits.
# If the configured model is gone or out of quota, try the other Flash models this key can use.
_model = {"name": GEMINI_MODEL}
API = "https://generativelanguage.googleapis.com/v1beta/models"


async def _candidates(client) -> list[str]:
    r = await client.get(API, params={"key": GEMINI_KEY, "pageSize": 200})
    if r.status_code >= 400:
        return []
    names = [m["name"].split("/")[-1] for m in r.json().get("models", [])
             if "generateContent" in m.get("supportedGenerationMethods", [])]
    skip = ("image", "tts", "live", "audio", "thinking")
    flash = [n for n in names if "flash" in n and not any(w in n for w in skip)]
    stable = sorted([n for n in flash if "preview" not in n and "exp" not in n and "lite" not in n], reverse=True)
    lite = sorted([n for n in flash if "lite" in n and "preview" not in n], reverse=True)
    rest = sorted([n for n in flash if n not in stable and n not in lite], reverse=True)
    return stable + lite + rest


async def _post(client, model, body):
    url = f"{API}/{model}:generateContent"
    r = await client.post(url, params={"key": GEMINI_KEY}, json=body)
    if r.status_code == 429:
        m = re.search(r'"retryDelay":\s*"(\d+)', r.text)
        await asyncio.sleep(min(int(m.group(1)) if m else 6, 20))
        r = await client.post(url, params={"key": GEMINI_KEY}, json=body)
    if r.status_code == 400 and "responseSchema" in body["generationConfig"]:
        # some model versions reject parts of the schema, so fall back to plain JSON mode
        body["generationConfig"].pop("responseSchema", None)
        r = await client.post(url, params={"key": GEMINI_KEY}, json=body)
    return r


async def _gemini(restaurant, source, today, image):
    parts = [{"text": _prompt(restaurant, source, today)}]
    if image:
        data, mime = image
        parts.append({"inline_data": {"mime_type": mime, "data": base64.b64encode(data).decode()}})
    body = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {"temperature": 0, "responseMimeType": "application/json", "responseSchema": SCHEMA},
    }
    async with httpx.AsyncClient(timeout=45) as client:
        r = await _post(client, _model["name"], body)
        if r.status_code in (404, 429):
            for name in await _candidates(client):
                if name == _model["name"]:
                    continue
                r = await _post(client, name, body)
                if r.status_code < 400:
                    _model["name"] = name
                    break
        if r.status_code >= 400:
            raise GeminiError(f"HTTP {r.status_code}: {r.text[:160]}")
        txt = r.json()["candidates"][0]["content"]["parts"][0]["text"]
    txt = txt.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    out = json.loads(txt)
    return _normalise(out)


def _normalise(out: dict) -> dict:
    base = {"transcript": "", "is_about_this_restaurant": True, "branch_mentioned": None, "change_type": "unclear",
            "start_date": None, "end_date": None, "date_certainty": "missing", "new_open": None, "new_close": None,
            "applies_to_days": [], "quote": "", "summary": ""}
    base.update({k: v for k, v in out.items() if k in base})
    if base["change_type"] not in CHANGE_TYPES:
        base["change_type"] = "unclear"
    for k in ("start_date", "end_date"):
        try:
            if base[k]:
                date.fromisoformat(base[k])
        except ValueError:
            base[k] = None
    if base["start_date"] and not base["end_date"]:
        base["end_date"] = base["start_date"]
    return base


def _check_quote(out: dict) -> dict:
    """A quote only counts as evidence if it really appears in the notice."""
    t = re.sub(r"\s+", " ", (out.get("transcript") or "")).lower()
    q = re.sub(r"\s+", " ", (out.get("quote") or "")).lower().strip(" .")
    out["quote_verified"] = bool(q) and q in t
    return out


# ---------------------------------------------------------------- basic parser
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
DATE_RE = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b", re.I)
TIME_RE = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm|noon)\b", re.I)


def _nearest(day: int, month: int, anchor: date) -> date | None:
    best = None
    for y in (anchor.year - 1, anchor.year, anchor.year + 1):
        try:
            c = date(y, month, day)
        except ValueError:
            continue
        if best is None or abs((c - anchor).days) < abs((best - anchor).days):
            best = c
    return best


def _to24(h: str, m: str | None, ap: str) -> str:
    h_i, m_i = int(h), int(m or 0)
    ap = ap.lower()
    if ap == "noon":
        h_i = 12
    elif ap == "pm" and h_i != 12:
        h_i += 12
    elif ap == "am" and h_i == 12:
        h_i = 0
    return f"{h_i:02d}:{m_i:02d}"


def basic_parse(restaurant: dict, source: dict, today: date) -> dict:
    text = source.get("text") or ""
    low = text.lower()
    anchor = date.fromisoformat(source["posted_on"]) if source.get("posted_on") else today
    dates = [d for d in (_nearest(int(a), MONTHS[b[:3].lower()], anchor) for a, b in DATE_RE.findall(text)) if d]

    branch = None
    for b in [restaurant["branch"], *restaurant["other_branches"]]:
        if b.lower() in low:
            branch = b
            break

    sentences = re.split(r"(?<=[.!?])\s+", text)

    def sentence_with(*words):
        for s in sentences:
            if any(w in s.lower() for w in words):
                return s.strip()
        return sentences[0].strip() if sentences else ""

    out = {"transcript": text, "is_about_this_restaurant": True, "branch_mentioned": branch, "change_type": "unclear",
           "start_date": None, "end_date": None, "date_certainty": "explicit" if dates else "missing",
           "new_open": None, "new_close": None, "applies_to_days": [], "quote": "", "summary": ""}

    if source.get("kind") == "diner_report" or re.search(r"shutters? (were |was )?down|found it closed|was closed when", low):
        out.update(change_type="report_closed_during_hours", quote=sentence_with("closed", "shut", "down"),
                   summary="A diner says the restaurant was closed during listed hours.")
        if not dates:
            out["date_certainty"] = "relative" if "yesterday" in low or "today" in low else "missing"
            if "yesterday" in low:
                out["start_date"] = out["end_date"] = (anchor - timedelta(days=1)).isoformat()
        return out
    closure_words = re.search(r"\b(closed|shut|stay closed|will be closed)\b", low)
    if re.search(r"cancel+ed|open after all", low) or (not closure_words and re.search(r"open as usual|we are open|we're open", low)):
        out.update(change_type="reopening_or_cancellation", quote=sentence_with("cancel", "open as usual", "open"),
                   summary="The notice says the restaurant is open as usual.")
        if dates:
            out["start_date"] = out["end_date"] = dates[0].isoformat()
        return out
    if re.search(r"permanently closed|closing down|shut down for good", low):
        out.update(change_type="permanent_closure", quote=sentence_with("permanent", "closing", "shut"),
                   summary="The notice suggests a permanent closure.")
        return out
    if re.search(r"\b(closed|shut|stay closed|will be closed)\b", low):
        out.update(change_type="temporary_closure", quote=sentence_with("closed", "shut"),
                   summary="The notice announces a temporary closure.")
        if dates:
            first = dates[0]
            last = dates[1] if len(dates) > 1 and re.search(r"\bto\b|till|until|-", low) else dates[0]
            # "We reopen on X" is not part of the closure.
            if len(dates) > 2 or (len(dates) == 2 and "reopen" in low and not re.search(r"from .* to ", low)):
                last = dates[1] if "to" in low else dates[0]
            out["start_date"], out["end_date"] = first.isoformat(), max(first, last).isoformat()
        elif re.search(r"this (saturday|sunday|weekend)|tomorrow", low):
            out["date_certainty"] = "relative"
        return out
    times = TIME_RE.findall(text)
    if re.search(r"open(s)? (only )?(at|from)|now open|new timings|timings", low) and times:
        h, m, ap = times[0]
        out.update(change_type="hours_change", new_open=_to24(h, m, ap), quote=sentence_with("open", "timing"),
                   summary=f"The notice says it now opens at {_to24(h, m, ap)}.")
        if "weekday" in low:
            out["applies_to_days"] = ["mon", "tue", "wed", "thu", "fri"]
        return out
    out.update(change_type="no_change", quote=sentences[0].strip() if sentences else "",
               summary="No change to hours found.")
    return out
