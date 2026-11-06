# Listing Check: Catching Restaurant Closures Before Diners Make a Wasted Trip

[![Live Demo](https://img.shields.io/badge/Live%20Demo-Listing%20Check-C8442A?style=for-the-badge&logo=render&logoColor=white)](https://listing-check.onrender.com)
[![Python](https://img.shields.io/badge/Python-FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Gemini](https://img.shields.io/badge/Gemini-Notice%20Reader-8E75B2?style=for-the-badge&logo=google&logoColor=white)](https://ai.google.dev/)
[![SQLite](https://img.shields.io/badge/SQLite-Demo%20State-003B57?style=for-the-badge&logo=sqlite&logoColor=white)](https://sqlite.org/)
[![Tests](https://img.shields.io/badge/Tests-pytest-0A9EDC?style=for-the-badge&logo=pytest&logoColor=white)](test_policy.py)
[![CI](https://img.shields.io/badge/CI-GitHub%20Actions-2088FF?style=for-the-badge&logo=githubactions&logoColor=white)](https://github.com/rajatmurhe/listing-check/actions)

**Live application:** https://listing-check.onrender.com/

Listing Check keeps restaurant opening hours honest. Restaurants often announce a closure or new timings on Instagram, a signboard or Google, and forget to update their Dineout listing. A diner books a table, crosses the city and finds the shutters down.

Every night, Listing Check reads what each restaurant has posted, pulls out the dates with the exact words as evidence, and decides what may change on the listing using fixed rules. Clear closures from the restaurant's own account are applied and can be undone in one tap. Anything uncertain becomes a quick question to the restaurant, never a guess. Diners who already booked on an affected date hear about it before they travel.

> This is a concept prototype I built for the Swiggy Dineout Product Innovation with GenAI role. The six restaurants, their posts and the bookings are fictional. It does not connect to Swiggy's systems.

## The Problem

A listing is only as good as its last update. Restaurants close for festivals, renovations, private events and staff days, and change their timings when business is slow. They usually tell their regulars on Instagram or put up a sign, but updating every platform is easy to forget.

The cost lands on the diner, who makes a wasted trip, and on the platform, which loses that diner's trust in every other listing.

## How It Works

    Nightly schedule (GitHub Actions)  or  "Run tonight's check"
                    |
                    v
    For each restaurant: new posts and diner reports since the last run
                    |
                    v
    Gemini reads each notice
      |-- outlet named, dates, closed or new hours
      |-- the exact quote it relied on
      |-- how certain the dates are (written, worked out, or missing)
                    |
                    v
    Quote check: the quote must really appear in the notice
                    |
                    v
    Evidence rules (policy.py, plain Python, no AI)
      |-- apply a temporary closure
      |-- ask the restaurant to confirm (urgent or normal)
      |-- ask a clarifying question
      |-- open an early check after a diner report
      |-- no change
                    |
          +---------+----------+
          |                    |
          v                    v
    Partner inbox          Diners with bookings
    one tap answers        heads up, then reschedule

The AI only reads. It never decides what happens to a listing. That keeps the risky part, changing what diners see, in rules that are easy to read, test and explain.

## The Evidence Rules

| Evidence | What happens |
|---|---|
| The restaurant's own linked account, this outlet, dates written out, posted in the last 21 days, not cancelled by a later post, quote found in the notice | Temporary closure added as "Detected from the restaurant's published notice". The partner is notified and can undo it. Booked diners are told it is being confirmed. |
| A closure from anyone else, or a permanent closure | Urgent request for the restaurant to confirm. Listing unchanged until then. |
| A change to regular hours | Proposed, waits for the restaurant's one tap. |
| A single diner report | An early check with the restaurant. Never treated as proof. |
| Unclear outlet, unclear dates, or conflicting posts | A question to the restaurant. Nothing changes. |
| A temporary closure reaches its end date | Back to regular hours, shown as not separately verified. |

A listing is never marked "verified open" by the system. Only the restaurant's own confirmation earns the "Confirmed by the restaurant" label.

## Sample Restaurants

Each fictional restaurant tests one rule, so a reviewer can see the whole policy in one run.

| Restaurant | What it tests | Expected result |
|---|---|---|
| Kaveri Kitchen, Indiranagar | Clear closure posted on the restaurant's own account | Applied, partner can undo |
| Brass Lantern, Koramangala | New hours mentioned on a food blog, not by the restaurant | Proposed, waits for the restaurant |
| Little Mango Cafe, HSR Layout | A diner says it was shut during listed hours | Early check, listing unchanged |
| Tandoor Street, Jayanagar | Closure notice that does not say which outlet | Clarifying question |
| Pepper and Pine, MG Road | Closure that a later post cancels | No change |
| Saffron Steps, Malleshwaram | Temporary closure that has already ended | Back to regular hours |

Dates in the sample posts are written relative to today, so the demo never goes stale.

## Project Structure

    main.py          FastAPI app: page, state, run check, partner answers, try a notice
    engine.py        runs the check, applies decisions, handles partner answers, builds the listing view
    extract.py       Gemini notice reader, quote check, and a basic parser used if the AI is unavailable
    policy.py        the evidence rules
    data.py          the six sample restaurants, their posts and bookings
    store.py         keeps the demo state in SQLite (or Postgres when DATABASE_URL is set)
    index.html       the single page front end
    test_policy.py   tests for every rule and a full sample run
    render.yaml      Render blueprint
    .github/workflows/
      tests.yml      runs the tests on every push
      nightly.yml    runs the check every night

## Running Locally

```bash
pip install -r requirements.txt
GEMINI_API_KEY=your_key uvicorn main:app --reload
```

Open http://localhost:8000. Without a key, a basic parser reads the sample notices and every result says so. Photos need the AI.

## Tests

```bash
pytest -q
```

The tests cover each rule (authorised closure, third party post, diner report, unclear outlet, other outlet, guessed dates, stale post, unverified quote, later cancellation, hours change, permanent closure, ended closure) and a full run over the sample restaurants, including the partner confirming a closure and booked diners being told.

## Deployment

The app runs on Render's free plan from `render.yaml`. Set `GEMINI_API_KEY` in Render. The nightly job in `.github/workflows/nightly.yml` needs two repository secrets: `APP_URL` (the Render link) and `CRON_TOKEN` (copied from Render's environment settings), so only the schedule can record a run as "nightly schedule".

If the configured Gemini model is retired or out of quota, the reader asks the API which Flash models the key can use and switches to one that works.

## Limits and Next Steps

- The demo reads sample posts. A real version would connect to sources the restaurant links during onboarding, such as their Instagram or Google business profile.
- On the free plan the server sleeps when idle, and the demo state resets when it restarts.
- What I would measure first: complaints about closed restaurants, and repeat bookings from diners who were warned before travelling.

Built by Rajat Murhe.
