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
        assert len(q["options"]) == 4 and q["options"][q["correct_index"]] == q["answers"][0]


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
    r = client.post(f"/api/{SLUG}/progress", json={"question_id": "demo-1", "correct": False},
                    headers={"X-CSRF-Token": token})
    assert r.get_json() == {"ok": True}
    r = client.get(f"/exam/{SLUG}/practice?weak=1")
    assert '"demo-1"' in r.get_data(as_text=True)


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
    assert parsed[2]["changes"] and parsed[2]["section"] == "B: System of Government"
    assert not check(parsed, "en")
    base = {"slug": "s", "title": "t", "price_cents": 1, "currency": "usd", "mock": {"size": 2, "pass_mark": 1},
            "questions": [], "demo": True, "free_count": 3}
    pack = build_pack(base, parsed)
    assert "demo" not in pack and len(pack["questions"]) == 3
    exams.validate_pack(pack)
