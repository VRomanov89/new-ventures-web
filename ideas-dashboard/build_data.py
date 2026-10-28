#!/usr/bin/env python3
"""Build the Ideas Dashboard data file from the Markdown files in 02. Ideas.

Usage (from the repo root):
    python3 "03. Web Build/ideas-dashboard/build_data.py"           # build + report
    python3 "03. Web Build/ideas-dashboard/build_data.py" --check   # report only, no write

Sources parsed:
  - 02. Ideas/01. Initial/IG-*.md          Idea Generation (WF-01) outputs
  - 02. Ideas/<idea folder>/README.md      Ideas promoted to their own folder

Output:
  - 03. Web Build/ideas-dashboard/data.js  (window.IDEAS_DATA = {...})

The sync report lists ideas that are new (not yet on the page), removed,
and ideas that are missing fields required by the workflow.
"""
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IDEAS_DIR = ROOT / "02. Ideas"
INITIAL_DIR = IDEAS_DIR / "01. Initial"
OUT_FILE = Path(__file__).resolve().parent / "data.js"

CRITERIA = ["C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8"]
WEIGHTS = [0.20, 0.15, 0.15, 0.15, 0.10, 0.10, 0.10, 0.05]
PROFILE_FIELDS = {
    "one-liner": "oneLiner",
    "category / model": "categoryModel",
    "target customer": "customer",
    "problem": "problem",
    "why now": "whyNow",
    "signals": "signals",
    "founder fit": "founderFit",
    "key risk": "keyRisk",
    "first step (≤2 weeks)": "firstStep",
    "first step": "firstStep",
}
REQUIRED = ["name", "oneLiner", "customer", "problem", "whyNow", "signals",
            "founderFit", "keyRisk", "firstStep", "score", "tier", "confidence"]
IDEA_ID = re.compile(r"IG-\d{8}-\d{2}-\d{2}")
RUN_ID = re.compile(r"IG-\d{8}-\d{2}")
DR_ID = re.compile(r"DR-\d{8}-\d{2}")
RUN_INFO = {}
RESEARCH_FILE = re.compile(r"^(\d{2})\. (.+)\.md$")
LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def num(s):
    try:
        return float(s.strip())
    except (ValueError, AttributeError):
        return None


def cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def section(text, heading_regex):
    m = re.search(r"^## +" + heading_regex + r".*$", text, re.M | re.I)
    if not m:
        return ""
    rest = text[m.end():]
    nxt = re.search(r"^## +", rest, re.M)
    return rest[: nxt.start()] if nxt else rest


def parse_meta(text):
    meta = {}
    for line in text.splitlines()[:20]:
        m = re.match(r"\|\s*\*\*(.+?)\*\*\s*\|\s*(.*?)\s*\|", line)
        if m:
            meta[m.group(1).strip().lower()] = m.group(2).strip()
    title = re.search(r"^# +(.+)$", text, re.M)
    meta["title"] = title.group(1).strip() if title else ""
    return meta


def parse_initial(path):
    text = path.read_text(encoding="utf-8")
    meta = parse_meta(text)
    run_id = meta.get("run id") or (RUN_ID.search(path.name) or [None])[0]
    if run_id is None or not RUN_ID.fullmatch(run_id):
        return []
    run = {
        "runId": run_id,
        "runDate": meta.get("date", ""),
        "focus": meta.get("focus", ""),
        "sourceFile": str(path.relative_to(ROOT)),
    }
    RUN_INFO[run_id] = {
        "brief": section(text, r"\d*\.? *Opportunity Brief").strip(),
        "summary": section(text, r"\d*\.? *Executive Summary").strip(),
        "top": section(text, r"\d*\.? *Top 5").strip(),
        "themes": section(text, r"\d*\.? *Special Mentions").strip(),
        "nextSteps": section(text, r"\d*\.? *Next Steps").strip(),
    }
    ideas = {}

    # Ranked summary table
    for line in section(text, r"\d*\.? *Ranked Summary").splitlines():
        if not line.startswith("|"):
            continue
        c = cells(line)
        if len(c) < 15 or not IDEA_ID.fullmatch(c[1]):
            continue
        scores = [num(x) for x in c[4:12]]
        ideas[c[1]] = {
            "id": c[1], "rank": num(c[0]), "name": c[2], "model": c[3],
            "scores": dict(zip(CRITERIA, scores)),
            "score": num(c[12]), "tier": c[13], "confidence": c[14],
        }

    # Idea profiles
    profiles = section(text, r"\d*\.? *Idea Profiles")
    blocks = re.split(r"^### +", profiles, flags=re.M)[1:]
    for block in blocks:
        head, _, body = block.partition("\n")
        idm = IDEA_ID.search(head)
        if not idm:
            continue
        idea = ideas.setdefault(idm.group(0), {"id": idm.group(0)})
        hm = re.match(r"#?(\d+)\s*·\s*\S+\s*·\s*(.+?)\s+[—-]+\s+([\d.]+)\s*"
                      r"\(Tier\s+(\w)\s*,\s*Confidence:\s*(\w+)\)", head.strip())
        if hm:
            idea.setdefault("rank", num(hm.group(1)))
            idea.setdefault("name", hm.group(2).strip())
            idea.setdefault("score", num(hm.group(3)))
            idea.setdefault("tier", hm.group(4))
            idea.setdefault("confidence", hm.group(5))
        for line in body.splitlines():
            fm = re.match(r"\s*[-*]\s+\*\*(.+?):?\*\*:?\s*(.*)$", line)
            if not fm:
                continue
            key = PROFILE_FIELDS.get(fm.group(1).strip().rstrip(":").lower())
            if not key:
                continue
            val = fm.group(2).strip()
            if key == "signals":
                idea["signalLinks"] = [{"label": a, "url": u} for a, u in LINK.findall(val)]
            if key == "categoryModel":
                cat, _, model = val.partition("/")
                idea["category"] = cat.strip()
                if model.strip():
                    idea.setdefault("model", model.strip())
            idea[key] = val

    out = []
    for idea in ideas.values():
        s = idea.get("scores") or {}
        if idea.get("score") is None and all(s.get(k) is not None for k in CRITERIA):
            idea["score"] = round(sum(s[k] * w for k, w in zip(CRITERIA, WEIGHTS)) * 20, 1)
        idea.update(run)
        idea["stage"] = "Initial"
        idea["status"] = "Exploring"
        out.append(idea)
    return out


def parse_idea_folder(folder):
    readme = folder / "README.md"
    if not readme.exists():
        return None
    text = readme.read_text(encoding="utf-8")
    title = re.search(r"^# +(.+)$", text, re.M)
    status = section(text, r"Status")
    sm = re.search(r"\b(Exploring|Validating|Building|Parked|Dropped)\b", status, re.I)
    idm = IDEA_ID.search(text) or DR_ID.search(text)
    summary = section(text, r"Summary").strip().split("\n\n")[0].strip()
    idea = {
        "id": idm.group(0) if idm else "DIR-" + folder.name,
        "name": title.group(1).strip() if title else folder.name,
        "stage": "Researched",
        "status": sm.group(1).title() if sm else "Exploring",
        "oneLiner": summary,
        "folder": str(folder.relative_to(ROOT)),
        "sourceFile": str(readme.relative_to(ROOT)),
    }
    # Full deep-research content for the detail view
    idea["readme"] = text
    idea["research"] = [
        {"title": m.group(2), "markdown": f.read_text(encoding="utf-8")}
        for f in sorted(folder.iterdir())
        for m in [RESEARCH_FILE.match(f.name)] if m
    ]
    rec = re.search(r"\|\s*\*\*Recommendation\*\*\s*\|\s*(.+?)\s*\|", text)
    if rec and "/" not in rec.group(1):
        idea["recommendation"] = rec.group(1)

    # WF-03 scorecard: "| C1 Demand | 20% | <WF-01> | <New> | ... |"
    scores = {}
    for line in section(text, r"Scorecard").splitlines():
        c = cells(line) if line.startswith("|") else []
        if len(c) >= 4 and re.match(r"C[1-8]\b", c[0]):
            scores[c[0][:2]] = num(c[3])
    if all(scores.get(k) is not None for k in CRITERIA):
        idea["scores"] = scores
        idea["score"] = round(sum(scores[k] * w for k, w in zip(CRITERIA, WEIGHTS)) * 20, 1)
        idea["tier"] = "A" if idea["score"] >= 75 else "B" if idea["score"] >= 60 else "C"
    conf = re.search(r"\*\*Confidence:\*\*\s*(High|Medium|Low)\b", section(text, r"Scorecard"))
    if conf:
        idea["confidence"] = conf.group(1)
    return idea


def load_previous():
    if not OUT_FILE.exists():
        return {}
    raw = OUT_FILE.read_text(encoding="utf-8")
    m = re.search(r"window\.IDEAS_DATA\s*=\s*(\{.*\});?\s*$", raw, re.S)
    if not m:
        return {}
    try:
        return {i["id"]: i for i in json.loads(m.group(1)).get("ideas", [])}
    except json.JSONDecodeError:
        return {}


def main():
    check_only = "--check" in sys.argv
    ideas, runs = {}, {}

    for path in sorted(INITIAL_DIR.glob("IG-*.md")):
        for idea in parse_initial(path):
            ideas[idea["id"]] = idea
            runs[idea["runId"]] = {**{k: idea[k] for k in ("runId", "runDate", "focus", "sourceFile")},
                                   **RUN_INFO.get(idea["runId"], {})}

    # Promoted idea folders override / extend the initial entries
    for folder in sorted(p for p in IDEAS_DIR.iterdir() if p.is_dir() and p != INITIAL_DIR):
        promoted = parse_idea_folder(folder)
        if not promoted:
            continue
        base = ideas.get(promoted["id"], {})
        if base.get("oneLiner") and promoted.get("oneLiner"):
            promoted["summary"] = promoted.pop("oneLiner")
        merged = {**base, **{k: v for k, v in promoted.items() if v}}
        ideas[promoted["id"]] = merged

    previous = load_previous()
    new_ids = sorted(set(ideas) - set(previous))
    removed_ids = sorted(set(previous) - set(ideas))
    incomplete = {}
    for i in ideas.values():
        if i.get("stage") != "Initial":
            continue
        missing = [f for f in REQUIRED if not i.get(f)]
        missing += [k for k in CRITERIA if (i.get("scores") or {}).get(k) is None]
        if missing:
            incomplete[i["id"]] = missing

    print("Ideas Dashboard sync report")
    print("  Sources: %d run file(s), %d idea(s) total" % (len(runs), len(ideas)))
    print("  New (not yet on page): %d %s" % (len(new_ids), ", ".join(new_ids)))
    print("  Removed (on page, no longer in sources): %d %s" % (len(removed_ids), ", ".join(removed_ids)))
    print("  Incomplete ideas: %d" % len(incomplete))
    for iid, fields in sorted(incomplete.items()):
        print("    %s missing: %s" % (iid, ", ".join(fields)))

    if check_only:
        return
    data = {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "criteria": [{"key": k, "weight": w} for k, w in zip(CRITERIA, WEIGHTS)],
        "runs": sorted(runs.values(), key=lambda r: r["runId"], reverse=True),
        "ideas": sorted(ideas.values(), key=lambda i: -(i.get("score") or 0)),
        "incomplete": incomplete,
    }
    OUT_FILE.write_text("window.IDEAS_DATA = " + json.dumps(data, indent=1, ensure_ascii=False) + ";\n",
                        encoding="utf-8")
    print("  Wrote %s" % OUT_FILE.relative_to(ROOT))


if __name__ == "__main__":
    main()
