"""The evidence policy. Plain rules, no AI.

The AI extraction says what a notice claims. These rules decide what may happen
to the listing, based on who said it and how clear the evidence is.
"""
from __future__ import annotations

from datetime import date, timedelta

RECENT_DAYS = 21       # a notice older than this is treated as stale
WINDOW_DAYS = 60       # closures further ahead than this are not applied automatically

ACTIONS = {
    "auto_apply": "Applied to the listing as a temporary closure. Partner notified and can undo.",
    "urgent_confirm": "Flagged as urgent. Waiting for the restaurant to confirm.",
    "propose": "Proposed change. Waiting for the restaurant to confirm.",
    "investigate": "Checked early because of a diner report. Listing unchanged.",
    "clarify": "Unclear, so the restaurant was asked a question. Listing unchanged.",
    "no_change": "No change to the listing.",
}


def _d(s):
    return date.fromisoformat(s) if s else None


def _overlaps(a1, a2, b1, b2):
    return a1 and a2 and b1 and b2 and a1 <= b2 and b1 <= a2


def _branch_status(restaurant: dict, ext: dict) -> str:
    """'match', 'other' (names another outlet), 'unknown_name', or 'unnamed'."""
    named = (ext.get("branch_mentioned") or "").strip().lower()
    if not named:
        return "unnamed"
    if restaurant["branch"].lower() in named or named in restaurant["branch"].lower():
        return "match"
    for b in restaurant["other_branches"]:
        if b.lower() in named or named in b.lower():
            return "other"
    return "unknown_name"


def superseded_by(source: dict, ext: dict, others: list[tuple[dict, dict]]) -> dict | None:
    """A later notice from an authorised source that cancels this closure."""
    s1, e1 = _d(ext.get("start_date")), _d(ext.get("end_date"))
    for src, x in others:
        if src["id"] == source["id"] or src["restaurant_id"] != source["restaurant_id"]:
            continue
        if src.get("kind") != "authorised" or x.get("change_type") != "reopening_or_cancellation":
            continue
        if (src.get("posted_on") or "") <= (source.get("posted_on") or ""):
            continue
        s2, e2 = _d(x.get("start_date")), _d(x.get("end_date"))
        if s2 is None or _overlaps(s1, e1, s2, e2):
            return src
    return None


def decide(restaurant: dict, source: dict, ext: dict, today: date, others: list[tuple[dict, dict]] | None = None) -> dict:
    others = others or []
    ct = ext.get("change_type")
    start, end = _d(ext.get("start_date")), _d(ext.get("end_date"))
    posted = _d(source.get("posted_on"))
    branch = _branch_status(restaurant, ext)
    later = superseded_by(source, ext, others) if ct == "temporary_closure" else None

    branch_ok = branch == "match" or (branch == "unnamed" and not restaurant["other_branches"])
    checks = [
        ("Source is the restaurant's own authorised account", source.get("kind") == "authorised",
         source.get("channel", "")),
        ("Notice is about this restaurant", bool(ext.get("is_about_this_restaurant")), ""),
        ("Names this outlet, or the restaurant has only one", branch_ok,
         ext.get("branch_mentioned") or "no outlet named"),
        ("Dates are written out, not guessed", ext.get("date_certainty") == "explicit" and start is not None,
         f"{ext.get('start_date')} to {ext.get('end_date')}" if start else "no date"),
        ("Closure has not already ended", end is not None and end >= today, ""),
        (f"Starts within {WINDOW_DAYS} days", start is not None and start <= today + timedelta(days=WINDOW_DAYS), ""),
        (f"Posted in the last {RECENT_DAYS} days", posted is not None and today - timedelta(days=RECENT_DAYS) <= posted <= today,
         source.get("posted_on") or "unknown"),
        ("No later post cancels it", later is None, f"cancelled by post of {later['posted_on']}" if later else ""),
        ("Quoted words appear in the notice", bool(ext.get("quote_verified")), ""),
    ]
    checks = [{"name": n, "ok": bool(ok), "detail": det} for n, ok, det in checks]

    def out(action, reason):
        return {"action": action, "action_text": ACTIONS[action], "reason": reason, "checks": checks}

    if not ext.get("is_about_this_restaurant"):
        return out("no_change", "The notice is not about this restaurant.")
    if branch == "other":
        return out("no_change", f"The notice is about the {ext.get('branch_mentioned')} outlet, not {restaurant['branch']}.")
    if branch == "unknown_name":
        return out("clarify", f"The notice names '{ext.get('branch_mentioned')}', which is not a known outlet. Asking which outlet it means.")
    if ct == "unclear":
        return out("clarify", "The notice does not clearly say what changes. Asking the restaurant.")
    if ct == "no_change":
        return out("no_change", "The notice does not change opening hours.")
    if ct == "report_closed_during_hours":
        return out("investigate", "One diner report is a reason to check, not proof. Asking the restaurant what happened.")
    if ct == "reopening_or_cancellation":
        return out("no_change", "The notice says the restaurant is open as usual. Any earlier closure it cancels is withdrawn.")
    if ct == "permanent_closure":
        return out("urgent_confirm", "A permanent closure is never applied automatically. Asking the restaurant urgently.")
    if ct == "hours_change":
        who = "the restaurant's own account" if source.get("kind") == "authorised" else "someone other than the restaurant"
        return out("propose", f"Regular hours are only changed after the restaurant confirms. This came from {who}.")

    # temporary closure
    if later:
        return out("no_change", f"A later post from the restaurant ({later['posted_on']}) cancels this closure.")
    if end is not None and end < today:
        return out("no_change", "This closure has already ended.")
    if branch == "unnamed" and restaurant["other_branches"]:
        return out("clarify", f"The restaurant has more than one outlet and the notice does not say which. Asking whether it means {restaurant['branch']}.")
    if start is None:
        return out("clarify", "The notice does not give a date. Asking the restaurant which days.")
    if all(c["ok"] for c in checks):
        return out("auto_apply", "Every check passed: the restaurant's own account, this outlet, written dates, current and not cancelled.")
    if source.get("kind") != "authorised":
        return out("urgent_confirm", "The closure looks real, but it did not come from the restaurant's own account. Asking the restaurant urgently.")
    failed = [c["name"] for c in checks if not c["ok"]]
    return out("propose", "Not every check passed (" + "; ".join(failed).lower() + "), so the restaurant is asked to confirm.")
