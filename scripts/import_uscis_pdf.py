"""Turn the official USCIS civics test PDF into an exam pack.

Usage:
    python scripts/import_uscis_pdf.py 2025-Civics-Test-128-Questions-and-Answers.pdf \
        [--extra content/sources/us-citizenship-2025.extra.json] \
        [--base content/us-citizenship-2025.json] [--out content/us-citizenship-2025.json]

The USCIS lists are numbered questions ("12. What is ...?") each followed by
bulleted answers. Section headings are lines without a number or bullet.
Questions marked with an asterisk are the 65/20 questions. Questions whose
answers change (officials, representatives) are flagged when an answer
points to uscis.gov or says "Answers will vary".

Settings (price, mock sizes, landing copy) are kept from --base. The demo flag
is removed. Read the printed summary and spot-check the output against the
PDF before you publish: PDF layouts differ between editions.
"""
import argparse
import json
import re
import sys

BULLET = re.compile(r"^\s*[•▪●◦\-–■□◆]\s*")
QUESTION = re.compile(r"^\s*(\d{1,3})\s*[.)]\s+(.*)$")
CHANGES_HINT = re.compile(r"uscis\.gov|answers will vary|las respuestas variar", re.I)
NOISE = re.compile(r"^\s*(page \d+|página \d+|\d+\s*of\s*\d+|uscis\.gov/citizenship\s*$)", re.I)


def pdf_lines(path):
    import pdfplumber
    lines = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            for line in (page.extract_text() or "").splitlines():
                line = line.strip()
                if line and not NOISE.match(line):
                    lines.append(line)
    return lines


SUBSECTION = re.compile(r"^[A-Z]:\s+\S")


def _is_category(line):
    letters = [c for c in line if c.isalpha()]
    return len(letters) >= 4 and all(c.isupper() for c in letters)


def parse_lines(lines):
    """Return a list of {n, section, q, answers, star, changes, note}.

    Section names combine the ALL-CAPS category and the "A: ..." heading,
    e.g. "American Government: Principles of American Government". Text
    between the last answer of a question and the next heading is kept as
    that question's note. Anything before the first heading is ignored.
    """
    out, category, section, current = [], "", "", None
    for line in lines:
        qm = QUESTION.match(line)
        if qm:
            if current:
                out.append(current)
            text = qm.group(2).strip()
            star = text.endswith("*") or text.startswith("*")
            current = {"n": int(qm.group(1)), "section": section, "q": text.strip("* ").strip(),
                       "answers": [], "star": star, "changes": False, "note": ""}
            continue
        if _is_category(line):
            category = line.title().replace(" And ", " and ")
            continue
        if SUBSECTION.match(line):
            name = line[2:].strip()
            section = f"{category}: {name}" if category else name
            continue
        if current is None:
            continue  # introduction text
        if BULLET.match(line):
            current["answers"].append(BULLET.sub("", line).strip())
        elif not current["answers"]:
            if line.strip() == "*":
                current["star"] = True
            else:
                current["q"] = (current["q"] + " " + line).strip()  # question wrapped
                if current["q"].endswith("*"):
                    current["star"] = True
                    current["q"] = current["q"].rstrip("* ").strip()
        elif current["note"] or line[:1].isupper():
            current["note"] = (current["note"] + " " + line).strip()  # note under the answers
        else:
            current["answers"][-1] += " " + line  # answer wrapped onto the next line
    if current:
        out.append(current)
    for q in out:
        q["changes"] = any(CHANGES_HINT.search(a) for a in q["answers"]) or bool(CHANGES_HINT.search(q["q"]))
    return out


def check(parsed, label):
    problems = []
    numbers = [q["n"] for q in parsed]
    expected = list(range(1, len(parsed) + 1))
    if numbers != expected:
        problems.append(f"{label}: numbering is not 1..{len(parsed)} in order (got {numbers[:5]}...)")
    for q in parsed:
        if not q["answers"]:
            problems.append(f"{label}: question {q['n']} has no answers")
    return problems


FREE_QUIZ = ["q2", "q7", "q16", "q21", "q36", "q53", "q78", "q94", "q119", "q122"]


def check_extra(en, extra):
    """Every quizzable question needs a Spanish version and 3 wrong options per language."""
    problems = []
    qx = extra.get("questions", {})
    for q in en:
        x = qx.get(str(q["n"]))
        if not x:
            problems.append(f"extra: question {q['n']} missing")
            continue
        if not x.get("q_es"):
            problems.append(f"extra: question {q['n']} has no q_es")
        if not x.get("current") and len(x.get("a_es", [])) != len(q["answers"]):
            problems.append(f"extra: question {q['n']} has {len(x.get('a_es', []))} Spanish answers, "
                            f"USCIS lists {len(q['answers'])}")
        if not x.get("personal") and (len(x.get("d", [])) != 3 or len(x.get("d_es", [])) != 3):
            problems.append(f"extra: question {q['n']} needs 3 wrong options in English and Spanish")
        if x.get("current") and not q["changes"]:
            problems.append(f"extra: question {q['n']} has current answers but USCIS does not mark it as changing")
    return problems


def build_pack(base, en, extra=None):
    pack = {k: v for k, v in base.items() if k not in {"questions", "demo", "source_note"}}
    extra = extra or {}
    qx = extra.get("questions", {})
    sections_es = extra.get("sections_es", {})
    checked = extra.get("current_checked", "")
    questions = []
    for q in en:
        item = {"id": f"q{q['n']}", "number": q["n"], "section": q["section"], "q": q["q"],
                "answers": q["answers"], "star": q["star"], "changes": q["changes"]}
        if q.get("note"):
            item["note"] = q["note"]
        x = qx.get(str(q["n"]), {})
        if x.get("current"):
            item["answers"] = x["current"]
            item["answers_es"] = x.get("current_es", x["current"])
            item["note"] = f"USCIS: {q['answers'][0]} Current answer checked {checked}."
            item["note_es"] = f"USCIS: visite uscis.gov/citizenship/testupdates. Respuesta actual verificada el {checked}."
        elif x.get("a_es"):
            item["answers_es"] = x["a_es"]
        if q["section"] in sections_es:
            item["section_es"] = sections_es[q["section"]]
        for src, dst in (("q_es", "q_es"), ("note_es", "note_es"), ("d", "distractors"),
                         ("d_es", "distractors_es"), ("pick", "pick"), ("personal", "personal"),
                         ("lookup", "lookup")):
            if x.get(src) and dst not in item:
                item[dst] = x[src]
        questions.append(item)
    pack["questions"] = questions
    pack["languages"] = ["en", "es"] if qx else ["en"]
    pack["free_ids"] = [i for i in FREE_QUIZ if any(q["id"] == i for q in questions)]
    pack["source"] = {"list": "USCIS M-1778 (09/25), 128 Civics Questions and Answers (2025 version)",
                      "current_answers_checked": checked,
                      "spanish": "Unofficial translation. USCIS does not publish a Spanish 2025 list."}
    return pack


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf")
    ap.add_argument("--extra", default="content/sources/us-citizenship-2025.extra.json",
                    help="Spanish, wrong options and current answers, keyed by question number")
    ap.add_argument("--base", default="content/us-citizenship-2025.json")
    ap.add_argument("--out", default="content/us-citizenship-2025.json")
    args = ap.parse_args(argv)

    en = parse_lines(pdf_lines(args.pdf))
    problems = check(en, "English")
    extra = None
    if args.extra:
        with open(args.extra, encoding="utf-8") as fh:
            extra = json.load(fh)
        problems += check_extra(en, extra)
    with open(args.base, encoding="utf-8") as fh:
        base = json.load(fh)
    pack = build_pack(base, en, extra)

    print(f"Questions: {len(en)}  65/20 (starred): {sum(q['star'] for q in en)}  "
          f"answers that change: {[q['n'] for q in en if q['changes']]}")
    print(f"Sections: {sorted({q['section'] for q in en})}")
    if problems:
        print("\nNot written. Fix these first:\n  " + "\n  ".join(problems), file=sys.stderr)
        return 1
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(pack, fh, ensure_ascii=False, indent=1)
    print(f"Wrote {args.out}. Spot-check several questions against the PDF before publishing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
