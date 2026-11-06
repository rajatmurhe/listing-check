"""Runs the check, applies policy decisions and handles partner answers."""
from __future__ import annotations

import hashlib
import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from data import build_seed, fmt
from extract import extract
from policy import decide

IST = ZoneInfo("Asia/Kolkata")
DAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def today() -> date:
    return datetime.now(IST).date()


def now_iso() -> str:
    return datetime.now(IST).isoformat(timespec="seconds")


def new_state() -> dict:
    return build_seed(today())


def _id(prefix: str) -> str:
    return prefix + uuid.uuid4().hex[:8]


def _rest(state, rid):
    return next(r for r in state["restaurants"] if r["id"] == rid)


def _range_text(s, e):
    s, e = date.fromisoformat(s), date.fromisoformat(e)
    return fmt(s) if s == e else f"{fmt(s)} to {fmt(e)}"


def _bookings_in(state, rid, s, e):
    return [b for b in state.get("bookings", []) if b["restaurant_id"] == rid and s <= b["date"] <= e]


def _msg(state, to, rid, kind, text, ref=None, buttons=None, urgent=False):
    m = {"id": _id("m"), "to": to, "restaurant_id": rid, "kind": kind, "text": text, "ref": ref,
         "buttons": buttons or [], "urgent": urgent, "at": now_iso(), "answered": None}
    state["messages"].insert(0, m)
    return m


def _source_hash(source):
    return hashlib.sha1(f"{source['restaurant_id']}|{source.get('kind')}|{source.get('posted_on')}|{source.get('text')}".encode()).hexdigest()


# ------------------------------------------------------------------ expiry
def expire(state, t: date) -> list[str]:
    notes = []
    for ex in state["exceptions"]:
        if ex["status"] in ("confirmed", "detected") and date.fromisoformat(ex["end"]) < t:
            ex["status"] = "ended"
            r = _rest(state, ex["restaurant_id"])
            notes.append(f"{r['name']}: temporary closure ended on {fmt(date.fromisoformat(ex['end']))}, back to regular hours")
            _msg(state, "partner", r["id"], "info",
                 f"Your temporary closure ({_range_text(ex['start'], ex['end'])}) has ended, so the listing is back to "
                 f"your regular hours. If you are still closed, reply here.")
    return notes


# ------------------------------------------------------------------ applying decisions
def apply_decision(state, source, ext, dec):
    r = _rest(state, source["restaurant_id"])
    rec = {"source_id": source["id"], "restaurant_id": r["id"], "extraction": ext, "decision": dec,
           "at": now_iso(), "hash": _source_hash(source)}
    state["decisions"][source["id"]] = rec
    action = dec["action"]
    quote = ext.get("quote") or ""
    s, e = ext.get("start_date"), ext.get("end_date")

    if ext.get("change_type") == "reopening_or_cancellation" and source.get("kind") == "authorised":
        for ex in state["exceptions"]:
            if ex["restaurant_id"] == r["id"] and ex["status"] in ("detected", "confirmed") and (
                    not s or (ex["start"] <= (e or s) and s <= ex["end"])):
                ex["status"] = "cancelled"
                _msg(state, "partner", r["id"], "info",
                     f"Your newer post cancels the closure on {_range_text(ex['start'], ex['end'])}, so it was removed from the listing.")
                for b in _bookings_in(state, r["id"], ex["start"], ex["end"]):
                    _msg(state, "diner", r["id"], "info",
                         f"{b['diner']}: good news, {r['name']} is open on {fmt(date.fromisoformat(b['date']))}. Your table at {b['time']} stands.")
        for p in state["proposals"]:
            if p["restaurant_id"] == r["id"] and p["status"] == "pending" and p["type"] == "temporary_closure":
                p["status"] = "withdrawn"

    if action == "auto_apply":
        ex = {"id": _id("e"), "restaurant_id": r["id"], "type": "temporary_closure", "start": s, "end": e,
              "status": "detected", "source_id": source["id"], "quote": quote, "created": now_iso()}
        state["exceptions"].append(ex)
        _msg(state, "partner", r["id"], "auto_applied",
             f"We saw your post on {source['channel']} and marked {r['name']} {r['branch']} closed on "
             f"{_range_text(s, e)}. Is that right?", ref=ex["id"],
             buttons=[["confirm", "Yes, that's right"], ["reject", "No, undo it"]])
        for b in _bookings_in(state, r["id"], s, e):
            _msg(state, "diner", r["id"], "confirming",
                 f"{b['diner']}: {r['name']} may be closed on {fmt(date.fromisoformat(b['date']))}. "
                 f"We are confirming with the restaurant and will update you before your {b['time']} table.")
    elif action in ("propose", "urgent_confirm"):
        p = {"id": _id("p"), "restaurant_id": r["id"], "type": ext["change_type"], "start": s, "end": e,
             "new_open": ext.get("new_open"), "new_close": ext.get("new_close"),
             "days": ext.get("applies_to_days") or [], "status": "pending", "urgent": action == "urgent_confirm",
             "source_id": source["id"], "quote": quote, "created": now_iso()}
        state["proposals"].append(p)
        _msg(state, "partner", r["id"], "proposal", _proposal_text(r, source, p), ref=p["id"],
             buttons=[["confirm", "Confirm"], ["reject", "Not right"]], urgent=p["urgent"])
    elif action == "investigate":
        when = fmt(date.fromisoformat(s)) if s else "recently"
        _msg(state, "partner", r["id"], "question",
             f"A diner says {r['name']} {r['branch']} was closed {when} during your listed hours: \"{quote}\" "
             f"Were you closed?", ref=source["id"],
             buttons=[["closed_once", "Yes, just that day"], ["hours_changed", "Yes, our hours changed"], ["was_open", "No, we were open"]])
    elif action == "clarify":
        if r["other_branches"] and not ext.get("branch_mentioned"):
            q = (f"Your post says: \"{quote}\" Which outlet does this apply to?")
            buttons = [["branch_this", r["branch"]]] + [["branch_other", b] for b in r["other_branches"]]
        else:
            q = f"We could not tell exactly what changes from your post: \"{quote}\" Could you tell us the dates and hours?"
            buttons = [["will_update", "I'll update my hours"]]
        p = {"id": _id("p"), "restaurant_id": r["id"], "type": "temporary_closure" if ext.get("change_type") == "temporary_closure" else ext.get("change_type"),
             "start": s, "end": e, "new_open": None, "new_close": None, "days": [], "status": "question",
             "urgent": False, "source_id": source["id"], "quote": quote, "created": now_iso()}
        state["proposals"].append(p)
        _msg(state, "partner", r["id"], "question", q, ref=p["id"], buttons=buttons)
    return rec


def _proposal_text(r, source, p):
    src = f"a post on {source['channel']}"
    if p["type"] == "hours_change":
        days = ", ".join(d.title() for d in p["days"]) or "every day"
        change = f"opening at {p['new_open']}" if p["new_open"] else ""
        if p["new_close"]:
            change += (" and " if change else "") + f"closing at {p['new_close']}"
        return f"{src.capitalize()} says {r['name']} is now {change} on {days}: \"{p['quote']}\" Should we update your listing?"
    if p["type"] == "permanent_closure":
        return f"{src.capitalize()} suggests {r['name']} {r['branch']} has closed permanently: \"{p['quote']}\" Is this true?"
    when = _range_text(p["start"], p["end"]) if p["start"] else "soon"
    return f"{src.capitalize()} says {r['name']} {r['branch']} will be closed on {when}: \"{p['quote']}\" Is this right?"


# ------------------------------------------------------------------ partner answers
def answer(state, msg_id: str, choice: str) -> str:
    m = next((x for x in state["messages"] if x["id"] == msg_id), None)
    if not m or m["answered"]:
        return "Already answered."
    m["answered"] = choice
    r = _rest(state, m["restaurant_id"])

    if m["kind"] == "auto_applied":
        ex = next(x for x in state["exceptions"] if x["id"] == m["ref"])
        if choice == "confirm" and ex["status"] == "detected":
            ex["status"] = "confirmed"
            for b in _bookings_in(state, r["id"], ex["start"], ex["end"]):
                _msg(state, "diner", r["id"], "reschedule",
                     f"{b['diner']}: {r['name']} has confirmed it is closed on {fmt(date.fromisoformat(b['date']))}. "
                     f"Pick another day or a similar restaurant nearby.", buttons=[["noop", "Reschedule"]])
            return "Confirmed. The listing now says the closure is confirmed by the restaurant."
        if choice == "reject":
            ex["status"] = "undone"
            for b in _bookings_in(state, r["id"], ex["start"], ex["end"]):
                _msg(state, "diner", r["id"], "info",
                     f"{b['diner']}: {r['name']} is open on {fmt(date.fromisoformat(b['date']))}. Your table at {b['time']} stands.")
            return "Undone. The listing is back to regular hours."
        return "No change."

    if m["kind"] == "proposal":
        p = next(x for x in state["proposals"] if x["id"] == m["ref"])
        if choice == "reject":
            p["status"] = "rejected"
            return "Noted. The listing stays as it is."
        p["status"] = "confirmed"
        if p["type"] == "hours_change":
            for d in (p["days"] or DAY_NAMES):
                if r["hours"].get(d):
                    o, c = r["hours"][d]
                    r["hours"][d] = [p["new_open"] or o, p["new_close"] or c]
            r["hours_note"] = f"Hours updated on {fmt(today())}, confirmed by the restaurant"
            return "Hours updated and marked as confirmed by the restaurant."
        if p["type"] == "permanent_closure":
            r["permanently_closed"] = True
            return "Listing marked as permanently closed, confirmed by the restaurant."
        if p["start"]:
            state["exceptions"].append({"id": _id("e"), "restaurant_id": r["id"], "type": "temporary_closure",
                                        "start": p["start"], "end": p["end"], "status": "confirmed",
                                        "source_id": p["source_id"], "quote": p["quote"], "created": now_iso()})
            for b in _bookings_in(state, r["id"], p["start"], p["end"]):
                _msg(state, "diner", r["id"], "reschedule",
                     f"{b['diner']}: {r['name']} has confirmed it is closed on {fmt(date.fromisoformat(b['date']))}. "
                     f"Pick another day or a similar restaurant nearby.", buttons=[["noop", "Reschedule"]])
        return "Closure added, confirmed by the restaurant."

    if m["kind"] == "question":
        p = next((x for x in state["proposals"] if x["id"] == m["ref"]), None)
        if choice == "branch_this" and p and p.get("start"):
            p["status"] = "confirmed"
            state["exceptions"].append({"id": _id("e"), "restaurant_id": r["id"], "type": "temporary_closure",
                                        "start": p["start"], "end": p["end"], "status": "confirmed",
                                        "source_id": p["source_id"], "quote": p["quote"], "created": now_iso()})
            for b in _bookings_in(state, r["id"], p["start"], p["end"]):
                _msg(state, "diner", r["id"], "reschedule",
                     f"{b['diner']}: {r['name']} has confirmed it is closed on {fmt(date.fromisoformat(b['date']))}. "
                     f"Pick another day or a similar restaurant nearby.", buttons=[["noop", "Reschedule"]])
            return f"Thanks. {r['branch']} is marked closed on {_range_text(p['start'], p['end'])}, confirmed by the restaurant."
        if choice == "branch_other":
            if p:
                p["status"] = "rejected"
            return f"Thanks. {r['branch']} stays open as listed."
        if choice == "hours_changed":
            return "Thanks. Please confirm your new hours and we will update the listing."
        if choice == "closed_once":
            return "Thanks. The listing stays the same, and this is noted for the next check."
        if choice == "was_open":
            return "Thanks. The report is noted and the listing stays as it is."
        if p:
            p["status"] = "waiting"
        return "Thanks. We will wait for your update."
    return "No change."


# ------------------------------------------------------------------ the check
async def run_check(state, trigger: str) -> dict:
    t = today()
    started = now_iso()
    expired = expire(state, t)
    pending = [s for s in state["sources"]
               if s["id"] not in state["decisions"] or state["decisions"][s["id"]]["hash"] != _source_hash(s)]
    pending.sort(key=lambda s: s.get("posted_on") or "")
    extracted = []
    for s in pending:
        ext = await extract(_rest(state, s["restaurant_id"]), s, t)
        extracted.append((s, ext))
    known = [(state_src, state["decisions"][state_src["id"]]["extraction"])
             for state_src in state["sources"] if state_src["id"] in state["decisions"] and state_src not in pending]
    everything = known + extracted
    counts = {}
    items = []
    for s, ext in extracted:
        dec = decide(_rest(state, s["restaurant_id"]), s, ext, t, everything)
        apply_decision(state, s, ext, dec)
        counts[dec["action"]] = counts.get(dec["action"], 0) + 1
        items.append({"restaurant": _rest(state, s["restaurant_id"])["name"], "action": dec["action"], "reason": dec["reason"],
                      "engine": ext.get("engine")})
    run = {"id": _id("r"), "trigger": trigger, "started": started, "finished": now_iso(),
           "listings": len(state["restaurants"]), "new_notices": len(extracted),
           "ai_reads": sum(1 for _, x in extracted if x.get("engine") == "ai"),
           "basic_reads": sum(1 for _, x in extracted if x.get("engine") == "basic"),
           "counts": counts, "expired": expired, "items": items}
    state["runs"].insert(0, run)
    state["runs"] = state["runs"][:30]
    return run


async def try_notice(state, rid: str, kind: str, text: str, posted_on: str, image=None) -> dict:
    t = today()
    r = _rest(state, rid)
    channel = {"authorised": r["authorised_sources"][0], "public": "someone else's page",
               "diner_report": "Diner report in app"}[kind]
    src = {"id": _id("u"), "restaurant_id": rid, "kind": kind, "channel": channel + " (added by a visitor)",
           "posted_on": posted_on, "text": text.strip(), "visitor": True}
    ext = await extract(r, src, t, image=image)
    if image and ext.get("transcript") and not src["text"]:
        src["text"] = ext["transcript"]
    others = [(s, state["decisions"][s["id"]]["extraction"]) for s in state["sources"] if s["id"] in state["decisions"]]
    dec = decide(r, src, ext, t, others)
    state["sources"].append(src)
    rec = apply_decision(state, src, ext, dec)
    state["tries"].insert(0, {"source_id": src["id"], "at": now_iso()})
    return {"source": src, "extraction": ext, "decision": dec, "record": rec}


# ------------------------------------------------------------------ views
def listing_view(state) -> list[dict]:
    t = today()
    horizon = (t + timedelta(days=14)).isoformat()
    out = []
    for r in state["restaurants"]:
        dn = DAY_NAMES[t.weekday()]
        reg = r["hours"].get(dn)
        exs = [x for x in state["exceptions"] if x["restaurant_id"] == r["id"]]
        active = [x for x in exs if x["status"] in ("detected", "confirmed") and x["end"] >= t.isoformat() and x["start"] <= horizon]
        today_closed = next((x for x in active if x["start"] <= t.isoformat() <= x["end"]), None)
        notes = []
        for x in sorted(active, key=lambda x: x["start"]):
            notes.append({"text": f"Closed {_range_text(x['start'], x['end'])}",
                          "label": "Confirmed by the restaurant" if x["status"] == "confirmed" else "Detected from the restaurant's published notice",
                          "status": x["status"]})
        ended = [x for x in exs if x["status"] == "ended" and (t - date.fromisoformat(x["end"])).days <= 7]
        for x in ended:
            notes.append({"text": f"Back to regular hours after {fmt(date.fromisoformat(x['end']))}",
                          "label": "Temporary closure ended. Regular hours shown, not separately verified", "status": "ended"})
        pending = [p for p in state["proposals"] if p["restaurant_id"] == r["id"] and p["status"] in ("pending", "question")]
        out.append({**r,
                    "today": "Permanently closed" if r.get("permanently_closed") else
                             ("Closed today" if today_closed or reg is None else f"Open today {reg[0]} to {reg[1]}"),
                    "notes": notes, "pending_count": len(pending)})
    return out
