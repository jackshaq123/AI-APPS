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

The first exam is the **U.S. citizenship civics test** (`content/us-citizenship-2025.json`).
**It currently holds 14 demo questions only.** A yellow banner says so on every page.

## Before launch (must do)

1. **Load the official questions.**
   - Download the USCIS 2025 civics test "128 Questions and Answers" PDF. If you want Spanish, download the Spanish edition too.
   - Run:
     ```
     pip install -r requirements.txt
     python scripts/import_uscis_pdf.py civics-en.pdf --es civics-es.pdf
     ```
   - The script prints the question count, the starred (65/20) count, and the questions whose answers change. It refuses to write if the numbering has gaps.
   - Spot-check several questions against the PDF.
2. **Check the test rules** in the pack against what USCIS publishes today:
   - `mock.size` / `mock.pass_mark` (now 20 / 12)
   - `mock_65_20` (now 10 / 6)
3. Set `SHOW_DEMO_PACKS=false` in production.

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
