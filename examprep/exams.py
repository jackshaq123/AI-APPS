"""Exam packs: one JSON file per exam in the content directory.

A pack holds the exam's settings (price, mock-test size, pass mark) and its
questions. Every question carries all acceptable answers; multiple-choice
wrong options are drawn from other questions in the same section unless the
pack lists its own "distractors".
"""
import json
import os
import random
import re

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
    for qid in pack.get("free_ids", []):
        if qid not in seen:
            raise PackError(f"{source}: free_ids lists unknown question {qid!r}")
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


_BRACKET = re.compile(r"\s*\[[^\]]*\]")


def clean_option(text):
    """Drop bracketed officer notes, e.g. "Liberty Island [Also acceptable ...]"."""
    return _BRACKET.sub("", text).strip()


def localize_question(q, lang):
    item = {
        "id": q["id"],
        "section": _text(q, "section", lang),
        "q": _text(q, "q", lang),
        "answers": _text(q, "answers", lang),
        "note": _text(q, "note", lang) if q.get("note") else None,
        "star": bool(q.get("star")),
        "changes": bool(q.get("changes")),
        "personal": bool(q.get("personal")),
        "lookup": q.get("lookup"),
        "pick": int(q.get("pick", 1)),
    }
    if lang != "en":
        # The interview is in English, so always show the English wording too.
        item["q_en"] = q["q"]
        item["answers_en"] = q["answers"]
    return item


def can_quiz(q):
    """Questions whose answer depends on where you live are flashcard-only."""
    return not q.get("personal")


def build_choice(q, pack, lang, rng):
    """One multiple-choice item: a correct answer plus 3 wrong options.

    "Name two/three/five" questions get N accepted answers joined together.
    Wrong options come from the pack's hand-written "distractors"; packs
    without them fall back to answers of other questions in the same section.
    """
    item = localize_question(q, lang)
    answers = [clean_option(a) for a in item["answers"]]
    pick = min(item["pick"], len(answers))
    if pick > 1:
        chosen = sorted(rng.sample(range(len(answers)), pick))
        correct = ", ".join(answers[i] for i in chosen)
    else:
        correct = rng.choice(answers)
    accepted = {a.lower() for a in answers}
    pool = [clean_option(d) for d in _text(q, "distractors", lang)] if q.get("distractors") else []
    if len(pool) < 3:
        same_section = [o for o in pack["questions"]
                        if o["section"] == q["section"] and o["id"] != q["id"] and can_quiz(o)]
        others = same_section if len(same_section) >= 3 else [
            o for o in pack["questions"] if o["id"] != q["id"] and can_quiz(o)]
        rng.shuffle(others)
        pool += [clean_option(localize_question(o, lang)["answers"][0]) for o in others]
    wrong = []
    for option in pool:
        if option.lower() not in accepted and option != correct and option not in wrong:
            wrong.append(option)
        if len(wrong) == 3:
            break
    options = wrong + [correct]
    rng.shuffle(options)
    item["options"] = options
    item["correct_index"] = options.index(correct)
    return item


def _quizzable(pack):
    return [q for q in pack["questions"] if can_quiz(q)]


def free_questions(pack, lang):
    rng = random.Random(f"{pack['slug']}-free")  # same free quiz for everyone
    if pack.get("free_ids"):
        by_id = {q["id"]: q for q in pack["questions"]}
        chosen = [by_id[i] for i in pack["free_ids"] if i in by_id]
    else:
        chosen = _quizzable(pack)[: pack["free_count"]]
    return [build_choice(q, pack, lang, rng) for q in chosen]


def all_questions(pack, lang, seed=None):
    rng = random.Random(seed)
    return [build_choice(q, pack, lang, rng) for q in _quizzable(pack)]


def study_cards(pack, lang):
    return [localize_question(q, lang) for q in pack["questions"]]


def mock_test(pack, lang, seed=None, star_only=False):
    rng = random.Random(seed)
    pool = [q for q in _quizzable(pack) if q.get("star") or not star_only]
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
