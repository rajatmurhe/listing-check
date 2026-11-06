# Listing Check

Catches restaurant closures and changed opening hours before a diner makes a wasted trip.

A concept prototype for Dineout by Rajat Murhe. Six fictional restaurants, sample posts and sample bookings. It does not touch Swiggy's real systems.

## How it works

1. **The system starts the check.** A nightly job (GitHub Actions) reads each restaurant's own posts and any diner reports. You can also run it from the page.
2. **The AI only reads.** Gemini extracts each claim: which outlet, which dates, closed or new hours, and the exact words it relied on. A quote only counts if it really appears in the notice.
3. **Fixed rules decide.** `policy.py` decides by who said it and how clear the evidence is:

| Evidence | What happens |
|---|---|
| Restaurant's own authorised account, this outlet, written dates, recent, not cancelled later, quote verified | Temporary closure applied as "Detected from the restaurant's published notice". Partner notified and can undo. Booked diners told it is being confirmed. |
| Closure from anyone else, or a permanent closure | Urgent confirmation request. Listing unchanged. |
| Change to regular hours | Proposed, waits for the partner's one tap. |
| One diner report | Early check with the restaurant. Never treated as proof. |
| Unclear outlet, dates or conflicting posts | A question to the restaurant. Nothing changes. |
| Temporary closure ends | Back to regular hours, shown as not separately verified. |

4. **The partner confirms in one tap.** Only then does the listing say "Confirmed by the restaurant".

If the AI is unavailable, a basic parser runs and every result says so. A photo needs the AI.

## Run locally

```bash
pip install -r requirements.txt
GEMINI_API_KEY=your_key uvicorn main:app --reload
pytest -q
```

## Deploy

`render.yaml` creates the web service and a free Postgres database on Render. Set `GEMINI_API_KEY` in Render. For the nightly job, add `APP_URL` and `CRON_TOKEN` (copied from Render) as GitHub repository secrets.
