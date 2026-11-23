"""Exam packs: one JSON file per exam in the content directory.

A pack holds the exam's settings (price, mock-test size, pass mark) and its
questions. Every question carries all acceptable answers; multiple-choice
wrong options are drawn from other questions in the same section unless the
pack lists its own "distractors".
"""
import json
import os
import random

REQUIRED_PACK_KEYS = {"slug", "title", "price_cents", "currency", "mock", "questions"}
REQUIRED_QUESTION_KEYS = {"id", "section", "q", "answers"}


class PackError(ValueError):
    pass


def validate_pack(pack, source="pack"):
    missing = REQUIRED_PACK_KEYS - pack.keys()
    if missing:
        raise PackError(f"{source}: missing keys {sorted(missing)}")
    mock = pack["mock"]
    if not (0 < mock.get("pass_mark", 0) <= mock.get("size", 0)):
        raise PackError(f"{source}: mock.pass_mark must be between 1 and mock.size")
    seen = set()
    for i, q in enumerate(pack["questions"]):
        missing = REQUIRED_QUESTION_KEYS - q.keys()
        if missing:
            raise PackError(f"{source}: question #{i} missing {sorted(missing)}")
        if q["id"] in seen:
            raise PackError(f"{source}: duplicate question id {q['id']!r}")
        seen.add(q["id"])
        if not q["answers"]:
            raise PackError(f"{source}: question {q['id']!r} has no answers")
    if len(pack["questions"]) < pack.get("free_count", 10):
        raise PackError(f"{source}: fewer questions than free_count")
    return pack


def load_packs(content_dir, include_demo=True):
    packs = {}
    if not os.path.isdir(content_dir):
        return packs
    for name in sorted(os.listdir(content_dir)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(content_dir, name)
        with open(path, encoding="utf-8") as fh:
            pack = validate_pack(json.load(fh), source=name)
        pack.setdefault("free_count", 10)
        pack.setdefault("languages", ["en"])
        if pack.get("demo") and not include_demo:
            continue
        packs[pack["slug"]] = pack
    return packs


def _text(item, key, lang):
    """Return the Spanish (or other) field if the pack has it, else English."""
    if lang != "en":
        localized = item.get(f"{key}_{lang}")
        if localized:
            return localized
    return item[key]


def localize_question(q, lang):
    return {
        "id": q["id"],
        "section": _text(q, "section", lang),
        "q": _text(q, "q", lang),
        "answers": _text(q, "answers", lang),
        "note": _text(q, "note", lang) if q.get("note") else None,
        "star": bool(q.get("star")),
        "changes": bool(q.get("changes")),
    }


def build_choice(q, pack, lang, rng):
    """One multiple-choice item: the first acceptable answer plus 3 wrong options."""
    item = localize_question(q, lang)
    correct = item["answers"][0]
    accepted = {a.strip().lower() for a in item["answers"]}
    pool = list(_text(q, "distractors", lang)) if q.get("distractors") else []
    if len(pool) < 3:
        same_section = [o for o in pack["questions"] if o["section"] == q["section"] and o["id"] != q["id"]]
        others = same_section if len(same_section) >= 3 else [o for o in pack["questions"] if o["id"] != q["id"]]
        rng.shuffle(others)
        for other in others:
            pool.append(localize_question(other, lang)["answers"][0])
    wrong = []
    for option in pool:
        key = option.strip().lower()
        if key not in accepted and option not in wrong:
            wrong.append(option)
        if len(wrong) == 3:
            break
    options = wrong + [correct]
    rng.shuffle(options)
    item["options"] = options
    item["correct_index"] = options.index(correct)
    return item


def free_questions(pack, lang):
    rng = random.Random(f"{pack['slug']}-free")  # same free quiz for everyone
    return [build_choice(q, pack, lang, rng) for q in pack["questions"][: pack["free_count"]]]


def all_questions(pack, lang, seed=None):
    rng = random.Random(seed)
    return [build_choice(q, pack, lang, rng) for q in pack["questions"]]


def mock_test(pack, lang, seed=None, star_only=False):
    rng = random.Random(seed)
    pool = [q for q in pack["questions"] if q.get("star")] if star_only else list(pack["questions"])
    mock = pack["mock_65_20"] if star_only and pack.get("mock_65_20") else pack["mock"]
    size = min(mock["size"], len(pool))
    chosen = rng.sample(pool, size)
    # A pack smaller than the real test keeps the same pass ratio.
    pass_mark = -(-mock["pass_mark"] * size // mock["size"])
    return {
        "questions": [build_choice(q, pack, lang, rng) for q in chosen],
        "pass_mark": pass_mark,
        "size": size,
    }
