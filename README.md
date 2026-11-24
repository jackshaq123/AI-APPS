# PassPrep: exam prep sites

One app that sells prep for many exams. Each exam is a JSON file in `content/`.
Every exam follows the same funnel, built for cold Facebook and Instagram (Zeely) traffic:

1. **Ad → landing page** (`/` or `/exam/<slug>`), in English or Spanish.
2. **Free 10-question practice test**, no account needed.
3. **Score and missed answers → email capture.** This fires the Meta `Lead` event.
4. **One payment** through Stripe Checkout ($29 by default, set per exam). This fires `InitiateCheckout`, then `Purchase`.
5. **Paid area:**
   - flashcards
   - practice with instant feedback
   - mock tests in the real format, with no feedback until the end
   - a 65/20 mock
   - a "questions I miss" review list
6. **Login later** with an emailed link. There are no passwords.

The first exam is the **U.S. citizenship civics test** (`content/us-citizenship-2025.json`). It contains:

- **All 128 official questions and answers** from the USCIS 2025 list (M-1778, 09/25). A test checks every question and answer word for word against that PDF.
- **Three hand-written wrong options per question** for multiple choice, in English and Spanish.
- **A Spanish translation** (our own; USCIS publishes no Spanish 2025 list). In Spanish mode the English wording also shows, because the interview is in English.
- **Current officials** (questions 30, 38, 39, 57) from uscis.gov/citizenship/testupdates, checked 2026-11-24.
- **Four state-specific questions** (23, 29, 61, 62): flashcards only, with a link to look up your own answer.
- **The official rules:** a 20-question mock with 12 to pass, and a 65/20 mock of 10 starred questions with 6 to pass.

## Keeping the questions current

- **When an official changes** (election, new Speaker or Chief Justice):
  1. Check uscis.gov/citizenship/testupdates.
  2. Edit `current` / `current_es` and `current_checked` in `content/sources/us-citizenship-2025.extra.json`.
  3. Re-run the importer.
- **When USCIS publishes a new edition of the list:** download the new PDF to `content/sources/`, then run:
  ```
  python scripts/import_uscis_pdf.py content/sources/2025-Civics-Test-128-Questions-and-Answers.pdf
  ```
  The importer refuses to write if numbering has gaps, or if any question is missing Spanish or its 3 wrong options.
- **uscis.gov blocks plain downloads from cloud servers.** Use a browser to download.

## Run locally

```
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
ALLOW_FAKE_CHECKOUT=1 flask --app examprep.wsgi run
python -m pytest -q tests
```

`ALLOW_FAKE_CHECKOUT` gives you a buy button that skips Stripe, for local testing only. It is ignored once a Stripe key is set.

## Deploy (Railway)

1. Create a new service from this repo and add a Postgres database.
   - Railway sets `DATABASE_URL`.
   - The `Procfile` starts gunicorn.
2. Set the variables from `.env.example`:
   - `SECRET_KEY`
   - `BASE_URL`
   - `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`
   - SMTP settings (Google Workspace works: use an app password)
   - `META_PIXEL_ID`
   - `SUPPORT_EMAIL`, `BUSINESS_ADDRESS`
3. In Stripe, add a webhook to `https://<your domain>/stripe/webhook` for:
   - `checkout.session.completed`
   - `charge.refunded`

## Zeely campaign

- Point the ad at `https://<domain>/?utm_source=zeely&utm_campaign=<name>`. The source is saved on each sign-up.
- Use the Spanish page for Spanish ads: `?lang=es`.
- Optimize for **Purchase** once the pixel has about 50 purchases. Until then, optimize for **Lead**.
- Test with $150–200 first. Cost per purchase must stay under $29.

## Add another exam

Copy the pack format into a new `content/<slug>.json`:

- settings: `slug`, `title`, `price_cents`, `currency`, `mock`, `landing` copy
- `questions`: each with `id`, `section`, `q`, `answers` and, if you have them, `_es` fields
- optionally, `distractors` for each question

It goes live at `/exam/<slug>`. Good next exams:

- Florida real estate sales associate exam
- DMV permit test (by state)
- CDL
- CNA

For those exams you write the questions yourself, so have someone who knows the exam check them.

## Rules the copy follows

- The site never claims to be official. Every page says it is a private service and that official material is free.
- Price, one-time payment and the refund policy are stated next to every buy button.
- There is no pass guarantee.
- Answers that change with elections are flagged and point to uscis.gov.
