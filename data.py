"""Sample restaurants, sources and bookings for the demo.

Every restaurant here is fictional. Dates are written relative to "today" so the
demo never goes stale: each scenario tests one rule of the evidence policy.
"""
from datetime import date, timedelta

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def fmt(d: date) -> str:
    """Human style date used inside notices, e.g. 14 Nov."""
    return f"{d.day} {d.strftime('%b')}"


def regular(open_t: str, close_t: str, closed_days=()):
    return {d: (None if d in closed_days else [open_t, close_t]) for d in WEEKDAYS}


def build_seed(today: date) -> dict:
    d = lambda n: today + timedelta(days=n)  # noqa: E731

    restaurants = [
        {
            "id": "kaveri",
            "name": "Kaveri Kitchen",
            "branch": "Indiranagar",
            "other_branches": [],
            "cuisine": "South Indian",
            "hours": regular("12:00", "23:00"),
            "authorised_sources": ["Instagram @kaverikitchen.blr"],
            "scenario": "Clear closure posted on the restaurant's own linked account",
        },
        {
            "id": "brass",
            "name": "Brass Lantern",
            "branch": "Koramangala",
            "other_branches": [],
            "cuisine": "North Indian",
            "hours": regular("12:00", "23:30"),
            "authorised_sources": ["Instagram @brasslantern"],
            "scenario": "Hours change mentioned by someone else, not the restaurant",
        },
        {
            "id": "mango",
            "name": "Little Mango Cafe",
            "branch": "HSR Layout",
            "other_branches": [],
            "cuisine": "Cafe",
            "hours": regular("09:00", "23:00"),
            "authorised_sources": ["Google business updates"],
            "scenario": "A diner says it was shut during listed hours",
        },
        {
            "id": "tandoor",
            "name": "Tandoor Street",
            "branch": "Jayanagar",
            "other_branches": ["Whitefield"],
            "cuisine": "Mughlai",
            "hours": regular("12:00", "23:00"),
            "authorised_sources": ["Instagram @tandoorstreet"],
            "scenario": "Closure notice that does not say which outlet",
        },
        {
            "id": "pepper",
            "name": "Pepper and Pine",
            "branch": "MG Road",
            "other_branches": [],
            "cuisine": "Continental",
            "hours": regular("12:00", "00:00"),
            "authorised_sources": ["Instagram @pepperandpine"],
            "scenario": "Closure that a later post cancels",
        },
        {
            "id": "saffron",
            "name": "Saffron Steps",
            "branch": "Malleshwaram",
            "other_branches": [],
            "cuisine": "Thali",
            "hours": regular("11:30", "22:30", closed_days=("mon",)),
            "authorised_sources": ["Instagram @saffronsteps"],
            "scenario": "Temporary closure that has already ended",
        },
    ]

    sources = [
        {
            "id": "s1", "restaurant_id": "kaveri", "kind": "authorised",
            "channel": "Instagram @kaverikitchen.blr", "posted_on": d(-1).isoformat(),
            "text": (f"Dear guests, Kaveri Kitchen Indiranagar will stay closed from {fmt(d(2))} to {fmt(d(4))} "
                     f"while we renovate our kitchen. We reopen on {fmt(d(5))} at 12 noon. Thank you for your patience!"),
        },
        {
            "id": "s2", "restaurant_id": "brass", "kind": "public",
            "channel": "a food blog (not the restaurant)", "posted_on": d(-2).isoformat(),
            "text": ("Tried Brass Lantern in Koramangala last week. Heads up: they have stopped lunch service and "
                     "now open only at 6 pm on weekdays. The butter chicken is still the best in the area."),
        },
        {
            "id": "s3", "restaurant_id": "mango", "kind": "diner_report",
            "channel": "Diner report in app", "posted_on": d(-1).isoformat(),
            "text": ("Reached Little Mango Cafe at 9:15 pm yesterday and the shutters were down. "
                     "The listing said open till 11 pm."),
        },
        {
            "id": "s4", "restaurant_id": "tandoor", "kind": "authorised",
            "channel": "Instagram @tandoorstreet", "posted_on": d(-1).isoformat(),
            "text": (f"Our outlet will be closed on {fmt(d(3))} for a staff celebration. "
                     "Our other outlet stays open as usual. See you soon!"),
        },
        {
            "id": "s5a", "restaurant_id": "pepper", "kind": "authorised",
            "channel": "Instagram @pepperandpine", "posted_on": d(-3).isoformat(),
            "text": f"Pepper and Pine MG Road is closed on {fmt(d(1))} for a private event.",
        },
        {
            "id": "s5b", "restaurant_id": "pepper", "kind": "authorised",
            "channel": "Instagram @pepperandpine", "posted_on": d(-1).isoformat(),
            "text": (f"Update: the private event on {fmt(d(1))} has been cancelled. "
                     "Pepper and Pine MG Road is open as usual that day, 12 noon to midnight."),
        },
    ]

    # A temporary closure that was confirmed earlier and has now ended.
    exceptions = [
        {
            "id": "e0", "restaurant_id": "saffron", "type": "temporary_closure",
            "start": d(-4).isoformat(), "end": d(-1).isoformat(),
            "status": "confirmed", "source_id": None,
            "quote": f"Closed {fmt(d(-4))} to {fmt(d(-1))} for a family function.",
            "created": d(-6).isoformat(),
        }
    ]

    bookings = [
        {"id": "b1", "restaurant_id": "kaveri", "diner": "Ananya", "date": d(3).isoformat(), "time": "20:00", "guests": 4},
        {"id": "b2", "restaurant_id": "kaveri", "diner": "Rohit", "date": d(6).isoformat(), "time": "13:00", "guests": 2},
        {"id": "b3", "restaurant_id": "tandoor", "diner": "Sana", "date": d(3).isoformat(), "time": "21:00", "guests": 6},
        {"id": "b4", "restaurant_id": "brass", "diner": "Vikram", "date": d(1).isoformat(), "time": "13:30", "guests": 3},
        {"id": "b5", "restaurant_id": "pepper", "diner": "Meera", "date": d(1).isoformat(), "time": "20:30", "guests": 2},
    ]

    return {
        "seeded_on": today.isoformat(),
        "restaurants": restaurants,
        "sources": sources,
        "exceptions": exceptions,
        "bookings": bookings,
        "proposals": [],
        "messages": [],
        "decisions": {},
        "runs": [],
        "tries": [],
    }
