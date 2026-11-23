"""Turn the official USCIS civics test PDF into an exam pack.

Usage:
    python scripts/import_uscis_pdf.py questions-en.pdf [--es questions-es.pdf] \
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


def parse_lines(lines):
    """Return a list of {n, section, q, answers, star, changes}."""
    out, section, current = [], "", None
    pending_heading = []
    for line in lines:
        qm = QUESTION.match(line)
        if qm:
            if current:
                out.append(current)
            if pending_heading:
                section = " ".join(pending_heading).strip(" :")
                pending_heading = []
            text = qm.group(2).strip()
            star = text.startswith("*") or text.endswith("*") or line.lstrip().startswith("*")
            current = {"n": int(qm.group(1)), "section": section, "q": text.strip("* ").strip(),
                       "answers": [], "star": star, "changes": False}
            continue
        if BULLET.match(line):
            if current is not None:
                current["answers"].append(BULLET.sub("", line).strip())
            continue
        if current is not None and not current["answers"] and not current["q"].endswith("?"):
            current["q"] += " " + line  # question wrapped onto the next line
            continue
        if current is not None and current["answers"] and line[:1].islower():
            current["answers"][-1] += " " + line  # answer wrapped onto the next line
            continue
        pending_heading.append(line)  # anything else between questions is a heading
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


def build_pack(base, en, es=None):
    pack = {k: v for k, v in base.items() if k not in {"questions", "demo", "source_note"}}
    es_by_n = {q["n"]: q for q in (es or [])}
    questions = []
    for q in en:
        item = {"id": f"q{q['n']}", "section": q["section"], "q": q["q"], "answers": q["answers"],
                "star": q["star"], "changes": q["changes"]}
        other = es_by_n.get(q["n"])
        if other:
            item.update(section_es=other["section"], q_es=other["q"], answers_es=other["answers"])
        questions.append(item)
    pack["questions"] = questions
    pack["languages"] = ["en", "es"] if es else ["en"]
    return pack


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf")
    ap.add_argument("--es", help="Spanish edition of the same list")
    ap.add_argument("--base", default="content/us-citizenship-2025.json")
    ap.add_argument("--out", default="content/us-citizenship-2025.json")
    args = ap.parse_args(argv)

    en = parse_lines(pdf_lines(args.pdf))
    es = parse_lines(pdf_lines(args.es)) if args.es else None
    problems = check(en, "English")
    if es is not None:
        problems += check(es, "Spanish")
        if len(es) != len(en):
            problems.append(f"English has {len(en)} questions, Spanish has {len(es)}")
    with open(args.base, encoding="utf-8") as fh:
        base = json.load(fh)
    pack = build_pack(base, en, es)

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
