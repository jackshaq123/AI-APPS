"""Exam prep web app: free practice quiz -> email -> one-time Stripe payment -> full prep."""
import hashlib
import hmac
import logging
import random
import secrets
from datetime import timedelta
from functools import wraps
from urllib.parse import urlencode

from flask import (
    Flask, abort, g, jsonify, redirect, render_template, request, session, url_for,
)
from sqlalchemy import and_, insert, select, update

from . import db, exams
from .config import Config
from .i18n import SUPPORTED, translator
from .mail import send_email

log = logging.getLogger(__name__)
EMAIL_MAX = 320


def _normalize_email(raw):
    email = (raw or "").strip().lower()
    if len(email) > EMAIL_MAX or "@" not in email or email.startswith("@") or email.endswith("@"):
        return None
    local, _, domain = email.rpartition("@")
    if not local or "." not in domain or " " in email:
        return None
    return email


def _hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


def format_price(cents, currency):
    symbol = {"usd": "$"}.get(currency.lower(), currency.upper() + " ")
    whole, rest = divmod(cents, 100)
    return f"{symbol}{whole}" if rest == 0 else f"{symbol}{whole}.{rest:02d}"


def create_app(overrides=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if overrides:
        app.config.update(overrides)
    app.permanent_session_lifetime = timedelta(seconds=app.config["PERMANENT_SESSION_LIFETIME"])

    engine = db.make_engine(app.config["DATABASE_URL"])
    packs = exams.load_packs(app.config["CONTENT_DIR"], include_demo=app.config["SHOW_DEMO_PACKS"])
    app.extensions["engine"] = engine
    app.extensions["packs"] = packs

    stripe = None
    if app.config["STRIPE_SECRET_KEY"]:
        import stripe as stripe_lib
        stripe_lib.api_key = app.config["STRIPE_SECRET_KEY"]
        stripe = stripe_lib
    app.extensions["stripe"] = stripe

    # ---------- request helpers ----------

    def get_pack(slug):
        pack = packs.get(slug)
        if not pack:
            abort(404)
        return pack

    def current_user():
        uid = session.get("uid")
        if not uid:
            return None
        with engine.connect() as conn:
            return conn.execute(select(db.users).where(db.users.c.id == uid)).mappings().first()

    def has_access(user, slug):
        if not user:
            return False
        with engine.connect() as conn:
            row = conn.execute(
                select(db.purchases.c.id).where(and_(
                    db.purchases.c.user_id == user["id"],
                    db.purchases.c.exam_slug == slug,
                    db.purchases.c.status == "paid",
                ))
            ).first()
        return row is not None

    def get_or_create_user(conn, email, lang="en", source=None):
        row = conn.execute(select(db.users).where(db.users.c.email == email)).mappings().first()
        if row:
            return row["id"]
        result = conn.execute(insert(db.users).values(
            email=email, lang=lang, source=(source or "")[:200], created_at=db.now(),
        ))
        return result.inserted_primary_key[0]

    def record_purchase(email, slug, stripe_session_id, amount_cents, currency):
        """Idempotent: the success page and the webhook may both call this."""
        with engine.begin() as conn:
            existing = conn.execute(
                select(db.purchases).where(db.purchases.c.stripe_session_id == stripe_session_id)
            ).mappings().first()
            if existing:
                return existing["user_id"]
            uid = get_or_create_user(conn, email)
            conn.execute(insert(db.purchases).values(
                user_id=uid, exam_slug=slug, stripe_session_id=stripe_session_id,
                amount_cents=amount_cents, currency=currency, status="paid", created_at=db.now(),
            ))
            return uid

    def login_user(uid):
        session.clear()
        session.permanent = True
        session["uid"] = uid
        session["csrf"] = secrets.token_urlsafe(32)

    def require_access(view):
        @wraps(view)
        def wrapped(slug, *args, **kwargs):
            pack = get_pack(slug)
            if not has_access(g.user, slug):
                return redirect(url_for("landing", slug=slug, _anchor="pricing"))
            return view(pack, *args, **kwargs)
        return wrapped

    @app.before_request
    def load_request_state():
        g.user = current_user()
        lang = request.args.get("lang") or session.get("lang") or (g.user["lang"] if g.user else None)
        if not lang:
            lang = request.accept_languages.best_match(SUPPORTED) or "en"
        g.lang = lang if lang in SUPPORTED else "en"
        session["lang"] = g.lang
        if "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(32)
        # Remember where an ad visitor came from, for attribution at sign-up.
        if request.args.get("utm_source") and "src" not in session:
            session["src"] = f"{request.args.get('utm_source')}/{request.args.get('utm_campaign', '')}"[:200]
        if request.method == "POST" and request.endpoint not in {"stripe_webhook"}:
            sent = request.headers.get("X-CSRF-Token") or request.form.get("csrf")
            if not sent or not hmac.compare_digest(sent, session["csrf"]):
                abort(400, "Invalid or missing CSRF token")

    @app.context_processor
    def inject():
        t = translator(g.lang)
        other = "es" if g.lang == "en" else "en"
        return {
            "t": t, "lang": g.lang, "other_lang": other, "user": g.user,
            "csrf_token": session.get("csrf"), "cfg": app.config,
            "format_price": format_price, "packs": packs,
        }

    # ---------- public pages ----------

    @app.get("/")
    def home():
        if app.config["DEFAULT_EXAM"] in packs:
            return landing(app.config["DEFAULT_EXAM"])
        return render_template("index.html")

    @app.get("/exam/<slug>")
    def landing(slug):
        pack = get_pack(slug)
        return render_template(
            "landing.html", pack=pack, owned=has_access(g.user, slug),
            price=format_price(pack["price_cents"], pack["currency"]),
        )

    @app.get("/exam/<slug>/free")
    def free_quiz(slug):
        pack = get_pack(slug)
        return render_template(
            "quiz.html", pack=pack, mode="free",
            questions=exams.free_questions(pack, g.lang),
            price=format_price(pack["price_cents"], pack["currency"]),
        )

    @app.post("/exam/<slug>/lead")
    def capture_lead(slug):
        get_pack(slug)
        data = request.get_json(silent=True) or request.form
        email = _normalize_email(data.get("email"))
        if not email:
            return jsonify(ok=False, error="email"), 400
        with engine.begin() as conn:
            get_or_create_user(conn, email, lang=g.lang, source=session.get("src"))
        session["lead_email"] = email
        return jsonify(ok=True)

    # ---------- payment ----------

    @app.post("/exam/<slug>/checkout")
    def checkout(slug):
        pack = get_pack(slug)
        email = g.user["email"] if g.user else session.get("lead_email")
        success = f"{app.config['BASE_URL']}{url_for('checkout_success', slug=slug)}?session_id={{CHECKOUT_SESSION_ID}}"
        cancel = f"{app.config['BASE_URL']}{url_for('landing', slug=slug)}#pricing"
        if stripe is None:
            if app.config.get("ALLOW_FAKE_CHECKOUT"):
                fake_id = "fake_" + secrets.token_hex(8)
                session["fake_checkout"] = {"id": fake_id, "email": email or "test@example.com", "slug": slug}
                return redirect(url_for("checkout_success", slug=slug, session_id=fake_id))
            abort(503, "Payments are not configured. Set STRIPE_SECRET_KEY.")
        params = dict(
            mode="payment",
            line_items=[{
                "quantity": 1,
                "price_data": {
                    "currency": pack["currency"],
                    "unit_amount": pack["price_cents"],
                    "product_data": {"name": f"{pack['title']} — full access"},
                },
            }],
            success_url=success,
            cancel_url=cancel,
            metadata={"exam_slug": slug},
            allow_promotion_codes=True,
        )
        if email:
            params["customer_email"] = email
        checkout_session = stripe.checkout.Session.create(**params)
        return redirect(checkout_session.url, code=303)

    @app.get("/exam/<slug>/success")
    def checkout_success(slug):
        pack = get_pack(slug)
        sid = request.args.get("session_id", "")
        fake = session.get("fake_checkout")
        if fake and fake["id"] == sid and app.config.get("ALLOW_FAKE_CHECKOUT"):
            email, amount, currency = fake["email"], pack["price_cents"], pack["currency"]
            session.pop("fake_checkout", None)
        elif stripe is not None and sid:
            cs = stripe.checkout.Session.retrieve(sid)
            if cs.payment_status != "paid" or cs.metadata.get("exam_slug") != slug:
                return redirect(url_for("landing", slug=slug))
            email = _normalize_email(cs.customer_details.email if cs.customer_details else cs.customer_email)
            amount, currency = cs.amount_total, cs.currency
            if not email:
                abort(400, "Checkout has no email")
        else:
            return redirect(url_for("landing", slug=slug))
        uid = record_purchase(email, slug, sid, amount, currency)
        login_user(uid)
        g.user = current_user()
        return render_template(
            "welcome.html", pack=pack, purchase_value=amount / 100,
            purchase_currency=currency.upper(), event_id=sid,
        )

    @app.post("/stripe/webhook")
    def stripe_webhook():
        if stripe is None or not app.config["STRIPE_WEBHOOK_SECRET"]:
            abort(404)
        try:
            event = stripe.Webhook.construct_event(
                request.get_data(), request.headers.get("Stripe-Signature", ""),
                app.config["STRIPE_WEBHOOK_SECRET"],
            )
        except Exception:  # bad payload or bad signature
            abort(400)
        obj = event["data"]["object"]
        if event["type"] == "checkout.session.completed" and obj.get("payment_status") == "paid":
            slug = (obj.get("metadata") or {}).get("exam_slug")
            details = obj.get("customer_details") or {}
            email = _normalize_email(details.get("email") or obj.get("customer_email"))
            if slug in packs and email:
                record_purchase(email, slug, obj["id"], obj["amount_total"], obj["currency"])
        elif event["type"] == "charge.refunded" and obj.get("refunded") and obj.get("payment_intent"):
            sessions = stripe.checkout.Session.list(payment_intent=obj["payment_intent"], limit=1)
            for cs in sessions.data:
                with engine.begin() as conn:
                    conn.execute(update(db.purchases)
                                 .where(db.purchases.c.stripe_session_id == cs.id)
                                 .values(status="refunded"))
        return jsonify(received=True)

    # ---------- paid area ----------

    @app.get("/exam/<slug>/study")
    @require_access
    def study(pack):
        return render_template("study.html", pack=pack,
                               questions=exams.all_questions(pack, g.lang))

    @app.get("/exam/<slug>/practice")
    @require_access
    def practice(pack):
        qs = exams.all_questions(pack, g.lang, seed=secrets.randbits(32))
        weak_only = request.args.get("weak") == "1"
        if weak_only:
            with engine.connect() as conn:
                rows = conn.execute(select(db.progress.c.question_id).where(and_(
                    db.progress.c.user_id == g.user["id"],
                    db.progress.c.exam_slug == pack["slug"],
                    db.progress.c.wrong > db.progress.c.correct,
                ))).all()
            weak = {r[0] for r in rows}
            qs = [q for q in qs if q["id"] in weak]
        random.shuffle(qs)
        return render_template("quiz.html", pack=pack, mode="weak" if weak_only else "practice",
                               questions=qs, price=None)

    @app.get("/exam/<slug>/mock")
    @require_access
    def mock(pack):
        star_only = request.args.get("mode") == "65"
        test = exams.mock_test(pack, g.lang, seed=secrets.randbits(32), star_only=star_only)
        return render_template("quiz.html", pack=pack, mode="mock65" if star_only else "mock",
                               questions=test["questions"], pass_mark=test["pass_mark"], price=None)

    @app.post("/api/<slug>/progress")
    def save_progress(slug):
        pack = get_pack(slug)
        if not has_access(g.user, slug):
            return jsonify(ok=False), 403
        data = request.get_json(silent=True) or {}
        qid = str(data.get("question_id", ""))
        if qid not in {q["id"] for q in pack["questions"]}:
            return jsonify(ok=False), 400
        field = "correct" if data.get("correct") else "wrong"
        with engine.begin() as conn:
            row = conn.execute(select(db.progress).where(and_(
                db.progress.c.user_id == g.user["id"],
                db.progress.c.exam_slug == slug,
                db.progress.c.question_id == qid,
            ))).mappings().first()
            if row:
                conn.execute(update(db.progress).where(db.progress.c.id == row["id"]).values(
                    **{field: row[field] + 1}, updated_at=db.now()))
            else:
                conn.execute(insert(db.progress).values(
                    user_id=g.user["id"], exam_slug=slug, question_id=qid,
                    correct=1 if field == "correct" else 0, wrong=1 if field == "wrong" else 0,
                    updated_at=db.now()))
        return jsonify(ok=True)

    @app.post("/api/<slug>/mock-result")
    def save_mock_result(slug):
        get_pack(slug)
        if not has_access(g.user, slug):
            return jsonify(ok=False), 403
        data = request.get_json(silent=True) or {}
        try:
            score, total, pass_mark = int(data["score"]), int(data["total"]), int(data["pass_mark"])
        except (KeyError, TypeError, ValueError):
            return jsonify(ok=False), 400
        if not (0 <= score <= total <= 200):
            return jsonify(ok=False), 400
        with engine.begin() as conn:
            conn.execute(insert(db.mock_results).values(
                user_id=g.user["id"], exam_slug=slug, score=score, total=total,
                passed=int(score >= pass_mark), created_at=db.now()))
        return jsonify(ok=True)

    # ---------- login by email link ----------

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "GET":
            return render_template("login.html", sent=False)
        email = _normalize_email(request.form.get("email"))
        if email:
            with engine.begin() as conn:
                row = conn.execute(select(db.users).where(db.users.c.email == email)).mappings().first()
                if row:
                    token = secrets.token_urlsafe(32)
                    conn.execute(insert(db.login_tokens).values(
                        user_id=row["id"], token_hash=_hash_token(token),
                        expires_at=db.now() + timedelta(minutes=30)))
                    link = f"{app.config['BASE_URL']}{url_for('login_with_token', token=token)}"
                    t = translator(row["lang"])
                    send_email(app.config, email, f"{app.config['BRAND_NAME']}: {t('login')}",
                               f"{link}\n\n{t('login_sent')}")
        # Same answer whether or not the email exists, so accounts can't be probed.
        return render_template("login.html", sent=True)

    @app.get("/login/<token>")
    def login_with_token(token):
        with engine.begin() as conn:
            row = conn.execute(select(db.login_tokens).where(
                db.login_tokens.c.token_hash == _hash_token(token))).mappings().first()
            if not row or row["used_at"] is not None:
                return redirect(url_for("login"))
            expires = row["expires_at"]
            if expires.tzinfo is None:  # SQLite drops the timezone
                expires = expires.replace(tzinfo=db.now().tzinfo)
            if expires < db.now():
                return redirect(url_for("login"))
            conn.execute(update(db.login_tokens).where(db.login_tokens.c.id == row["id"])
                         .values(used_at=db.now()))
        login_user(row["user_id"])
        return redirect(url_for("account"))

    @app.post("/logout")
    def logout():
        lang = g.lang
        session.clear()
        session["lang"] = lang
        return redirect(url_for("home"))

    @app.get("/account")
    def account():
        if not g.user:
            return redirect(url_for("login"))
        with engine.connect() as conn:
            owned = conn.execute(select(db.purchases).where(and_(
                db.purchases.c.user_id == g.user["id"], db.purchases.c.status == "paid",
            ))).mappings().all()
        return render_template("account.html", owned=[o for o in owned if o["exam_slug"] in packs])

    # ---------- legal ----------

    @app.get("/terms")
    def terms():
        return render_template("legal.html", page="terms")

    @app.get("/privacy")
    def privacy():
        return render_template("legal.html", page="privacy")

    @app.get("/refunds")
    def refunds():
        return render_template("legal.html", page="refunds")

    @app.get("/healthz")
    def healthz():
        return jsonify(ok=True, packs=sorted(packs))

    @app.template_filter("qs")
    def qs_filter(params):
        return urlencode(params)

    return app

