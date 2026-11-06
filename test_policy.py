import asyncio
from datetime import date, timedelta

import engine
from data import build_seed
from policy import decide

T = date(2026, 11, 6)


def ext(**kw):
    base = {"transcript": "x", "is_about_this_restaurant": True, "branch_mentioned": None, "change_type": "temporary_closure",
            "start_date": (T + timedelta(days=2)).isoformat(), "end_date": (T + timedelta(days=4)).isoformat(),
            "date_certainty": "explicit", "new_open": None, "new_close": None, "applies_to_days": [], "quote": "x",
            "summary": "", "quote_verified": True}
    base.update(kw)
    return base


def rest(**kw):
    r = {"id": "r", "name": "R", "branch": "Indiranagar", "other_branches": [], "hours": {}, "authorised_sources": ["ig"]}
    r.update(kw)
    return r


def src(**kw):
    s = {"id": "s", "restaurant_id": "r", "kind": "authorised", "channel": "ig", "posted_on": (T - timedelta(days=1)).isoformat()}
    s.update(kw)
    return s


def test_authorised_clear_closure_is_applied():
    assert decide(rest(), src(), ext(), T)["action"] == "auto_apply"


def test_unauthorised_closure_needs_urgent_confirmation():
    assert decide(rest(), src(kind="public"), ext(), T)["action"] == "urgent_confirm"


def test_diner_report_only_triggers_investigation():
    assert decide(rest(), src(kind="diner_report"), ext(change_type="report_closed_during_hours"), T)["action"] == "investigate"


def test_unnamed_outlet_with_several_branches_asks():
    assert decide(rest(other_branches=["Whitefield"]), src(), ext(), T)["action"] == "clarify"


def test_other_outlet_is_ignored():
    assert decide(rest(other_branches=["Whitefield"]), src(), ext(branch_mentioned="Whitefield"), T)["action"] == "no_change"


def test_relative_dates_are_not_applied_automatically():
    assert decide(rest(), src(), ext(date_certainty="relative"), T)["action"] == "propose"


def test_stale_post_is_not_applied_automatically():
    assert decide(rest(), src(posted_on=(T - timedelta(days=40)).isoformat()), ext(), T)["action"] == "propose"


def test_unverified_quote_is_not_applied_automatically():
    assert decide(rest(), src(), ext(quote_verified=False), T)["action"] == "propose"


def test_later_cancellation_supersedes():
    later = (src(id="s2", posted_on=T.isoformat()), ext(change_type="reopening_or_cancellation"))
    assert decide(rest(), src(), ext(), T, [later])["action"] == "no_change"


def test_hours_change_always_needs_confirmation():
    assert decide(rest(), src(), ext(change_type="hours_change", new_open="18:00"), T)["action"] == "propose"


def test_permanent_closure_never_automatic():
    assert decide(rest(), src(), ext(change_type="permanent_closure"), T)["action"] == "urgent_confirm"


def test_ended_closure_is_ignored():
    e = ext(start_date=(T - timedelta(days=5)).isoformat(), end_date=(T - timedelta(days=1)).isoformat())
    assert decide(rest(), src(), e, T)["action"] == "no_change"


def test_full_run_on_sample_data_with_basic_parser(monkeypatch):
    monkeypatch.setattr(engine, "today", lambda: T)
    st = build_seed(T)
    run = asyncio.run(engine.run_check(st, "test"))
    by = {i["restaurant"]: i["action"] for i in run["items"]}
    assert by["Kaveri Kitchen"] == "auto_apply"
    assert by["Brass Lantern"] == "propose"
    assert by["Little Mango Cafe"] == "investigate"
    assert by["Tandoor Street"] == "clarify"
    assert run["expired"] and "Saffron Steps" in run["expired"][0]
    pepper = [i["action"] for i in run["items"] if i["restaurant"] == "Pepper and Pine"]
    assert pepper == ["no_change", "no_change"]
    # nothing is applied twice on the next run
    run2 = asyncio.run(engine.run_check(st, "test"))
    assert run2["new_notices"] == 0
    # partner confirms the auto applied closure; diners booked that day are told
    msg = next(m for m in st["messages"] if m["kind"] == "auto_applied")
    engine.answer(st, msg["id"], "confirm")
    assert any(m["kind"] == "reschedule" and "Ananya" in m["text"] for m in st["messages"])
