import json
import re

import pytest

from examprep import exams
from examprep.app import create_app
from scripts.import_uscis_pdf import build_pack, check, parse_lines


@pytest.fixture
def app(tmp_path):
    return create_app({
        "TESTING": True,
        "DATABASE_URL": f"sqlite:///{tmp_path/'t.db'}",
        "ALLOW_FAKE_CHECKOUT": True,
        "STRIPE_SECRET_KEY": "",
        "SHOW_DEMO_PACKS": True,
    })


@pytest.fixture
def client(app):
    return app.test_client()


def csrf(client, path="/"):
    html = client.get(path).get_data(as_text=True)
    return re.search(r'name="csrf-token" content="([^"]+)"', html).group(1)


SLUG = "us-citizenship-2025"


def test_landing_and_free_quiz(client):
    r = client.get("/")
    assert r.status_code == 200 and "free practice test" in r.get_data(as_text=True)
    r = client.get(f"/exam/{SLUG}/free")
    data = re.search(r'id="quiz-data">(.*?)</script>', r.get_data(as_text=True), re.S).group(1)
    qs = json.loads(data)
    assert len(qs) == 10
    for q in qs:
        assert len(q["options"]) == 4 and q["options"][q["correct_index"]] in [exams.clean_option(a) for a in q["answers"]]


def test_spanish(client):
    r = client.get(f"/exam/{SLUG}?lang=es")
    assert "Aprueba" in r.get_data(as_text=True)


def test_paid_pages_locked(client):
    r = client.get(f"/exam/{SLUG}/study")
    assert r.status_code == 302 and "#pricing" in r.headers["Location"]


def test_post_without_csrf_rejected(client):
    assert client.post(f"/exam/{SLUG}/lead", json={"email": "a@b.co"}).status_code == 400


def test_lead_then_fake_checkout_unlocks(client):
    token = csrf(client)
    r = client.post(f"/exam/{SLUG}/lead", json={"email": "Buyer@Example.com"}, headers={"X-CSRF-Token": token})
    assert r.get_json() == {"ok": True}
    r = client.post(f"/exam/{SLUG}/checkout", data={"csrf": token})
    assert r.status_code == 302
    r = client.get(r.headers["Location"])
    assert r.status_code == 200
    assert client.get(f"/exam/{SLUG}/study").status_code == 200
    assert client.get(f"/exam/{SLUG}/mock").status_code == 200
    token = csrf(client, f"/exam/{SLUG}/study")
    r = client.post(f"/api/{SLUG}/progress", json={"question_id": "q1", "correct": False},
                    headers={"X-CSRF-Token": token})
    assert r.get_json() == {"ok": True}
    r = client.get(f"/exam/{SLUG}/practice?weak=1")
    assert '"q1"' in r.get_data(as_text=True)


def test_bad_email_rejected(client):
    token = csrf(client)
    r = client.post(f"/exam/{SLUG}/lead", json={"email": "nope"}, headers={"X-CSRF-Token": token})
    assert r.status_code == 400


def test_login_does_not_reveal_accounts(client):
    token = csrf(client, "/login")
    a = client.post("/login", data={"csrf": token, "email": "nobody@example.com"}).get_data(as_text=True)
    assert "on its way" in a


def test_mock_keeps_pass_ratio():
    pack = {"slug": "x", "questions": [{"id": str(i), "section": "s", "q": "q", "answers": [f"a{i}"]} for i in range(14)],
            "mock": {"size": 20, "pass_mark": 12}}
    t = exams.mock_test(pack, "en", seed=1)
    assert t["size"] == 14 and t["pass_mark"] == 9  # 12/20 of 14, rounded up


def test_importer_parses_uscis_layout():
    lines = [
        "AMERICAN GOVERNMENT", "A: Principles of American Government",
        "1. What is the form of government of the", "United States?", "▪ Republic",
        "▪ Constitution-based federal republic",
        "2. What is the supreme law of the land?*", "▪ (U.S.) Constitution",
        "B: System of Government",
        "3. Who is one of your state's U.S. Senators now?", "▪ Answers will vary. Visit senate.gov",
        "▪ Check uscis.gov/citizenship/testupdates",
    ]
    parsed = parse_lines(lines)
    assert [q["n"] for q in parsed] == [1, 2, 3]
    assert parsed[0]["q"] == "What is the form of government of the United States?"
    assert parsed[0]["answers"] == ["Republic", "Constitution-based federal republic"]
    assert parsed[1]["star"] and not parsed[0]["star"]
    assert parsed[2]["changes"] and parsed[2]["section"] == "American Government: System of Government"
    assert not check(parsed, "en")
    base = {"slug": "s", "title": "t", "price_cents": 1, "currency": "usd", "mock": {"size": 2, "pass_mark": 1},
            "questions": [], "demo": True, "free_count": 3}
    pack = build_pack(base, parsed)
    assert "demo" not in pack and len(pack["questions"]) == 3
    exams.validate_pack(pack)


def _real_pack():
    import os
    return exams.load_packs(os.path.join(os.path.dirname(__file__), "..", "content"))[SLUG]


def test_real_pack_is_complete():
    pack = _real_pack()
    assert not pack.get("demo")
    assert len(pack["questions"]) == 128
    assert sum(q["star"] for q in pack["questions"]) == 20
    assert {q["id"] for q in pack["questions"] if q.get("personal")} == {"q23", "q29", "q61", "q62"}
    assert pack["mock"] == {"size": 20, "pass_mark": 12}
    assert pack["mock_65_20"] == {"size": 10, "pass_mark": 6}


@pytest.mark.parametrize("lang", ["en", "es"])
def test_every_choice_is_sound(lang):
    pack = _real_pack()
    for seed in range(5):
        for item in exams.all_questions(pack, lang, seed=seed):
            opts = item["options"]
            assert len(opts) == 4 and len(set(opts)) == 4, item["id"]
            correct = opts[item["correct_index"]]
            accepted = {exams.clean_option(a).lower() for a in item["answers"]}
            for i, o in enumerate(opts):
                if i != item["correct_index"]:
                    assert o.lower() not in accepted, (item["id"], o)
            if item["pick"] > 1:
                assert len(correct.split(", ")) >= item["pick"], item["id"]
            assert "[" not in correct, item["id"]
            if lang == "es":
                assert item["q_en"] and item["answers_en"]


def test_personal_questions_are_flashcards_only():
    pack = _real_pack()
    quiz_ids = {q["id"] for q in exams.all_questions(pack, "en", seed=1)}
    assert not quiz_ids & {"q23", "q29", "q61", "q62"}
    cards = {c["id"]: c for c in exams.study_cards(pack, "en")}
    assert cards["q23"]["lookup"].startswith("https://")
    mock = exams.mock_test(pack, "en", seed=3, star_only=True)
    assert mock["size"] == 10 and mock["pass_mark"] == 6
    assert all(q["star"] for q in mock["questions"])


def test_free_quiz_uses_chosen_questions():
    pack = _real_pack()
    ids = [q["id"] for q in exams.free_questions(pack, "en")]
    assert ids == pack["free_ids"] and len(ids) == 10


def test_pack_matches_official_pdf_word_for_word():
    import os
    pdfplumber = pytest.importorskip("pdfplumber")
    path = os.path.join(os.path.dirname(__file__), "..", "content", "sources",
                        "2025-Civics-Test-128-Questions-and-Answers.pdf")
    with pdfplumber.open(path) as pdf:
        text = " ".join((p.extract_text() or "") for p in pdf.pages)
    norm = lambda s: re.sub(r"\s+", " ", s).strip()  # noqa: E731
    official = norm(text)
    pack = _real_pack()
    current = {"q30", "q38", "q39", "q57"}  # answers come from the USCIS test-updates page
    for q in pack["questions"]:
        assert norm(q["q"]) in official, q["id"]
        if q["id"] not in current:
            for a in q["answers"]:
                assert norm(a) in official, (q["id"], a)


def test_checkout_sends_statement_suffix(tmp_path, monkeypatch):
    sent = {}

    class FakeSession:
        @staticmethod
        def create(**params):
            sent.update(params)
            return type("S", (), {"url": "https://checkout.stripe.test/x"})()

    import stripe
    monkeypatch.setattr(stripe.checkout, "Session", FakeSession)
    app = create_app({"TESTING": True, "DATABASE_URL": f"sqlite:///{tmp_path/'s.db'}",
                      "STRIPE_SECRET_KEY": "sk_test_dummy", "STATEMENT_DESCRIPTOR_SUFFIX": "PASSPREP"})
    client = app.test_client()
    r = client.post(f"/exam/{SLUG}/checkout", data={"csrf": csrf(client)})
    assert r.status_code == 303 and r.headers["Location"] == "https://checkout.stripe.test/x"
    assert sent["payment_intent_data"] == {"statement_descriptor_suffix": "PASSPREP"}
    assert sent["line_items"][0]["price_data"]["unit_amount"] == 2900
