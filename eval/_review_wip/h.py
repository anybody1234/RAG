"""Helper for golden v2 review: page access, search, article text."""
import json
import re
import sys
from functools import cache
from pathlib import Path

ROOT = Path(r"C:\Users\asus\New folder\RAG\.claude\worktrees\golden-v2-review")
sys.path.insert(0, str(ROOT / "backend"))
sys.stdout.reconfigure(encoding="utf-8")

from app.evaluation.golden import normalize_for_match, article_at  # noqa: E402
from app.ingestion.manifest import load_manifest, read_pdf_pages  # noqa: E402

M = load_manifest()

ALIAS = {
    "lab": "vi-bo-luat-lao-dong-2019",
}


@cache
def pages(doc_id: str) -> list[str]:
    return read_pdf_pages(M.get(doc_id))


def docs():
    return [d.doc_id for d in M.documents]


def load(path):
    return [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]


def search(pattern, doc_ids=None, flags=re.I, ctx=80, maxhits=30):
    """regex search on normalized page text; prints doc, page, context."""
    rx = re.compile(pattern, flags)
    n = 0
    for d in doc_ids or docs():
        for i, p in enumerate(pages(d), start=1):
            t = normalize_for_match(p)
            for m in rx.finditer(t):
                s = max(0, m.start() - ctx)
                e = min(len(t), m.end() + ctx)
                print(f"[{d} p{i}] ...{t[s:e]}...")
                n += 1
                if n >= maxhits:
                    print("(max hits)")
                    return
    if n == 0:
        print(f"(no hits for {pattern!r})")


_HEAD = re.compile(r"^\s*(?:Điều|Article) (\d+)\.")


def article_text(doc_id, num):
    """Full text of article num (from its heading to next article heading), with page markers."""
    out = []
    capturing = False
    for i, p in enumerate(pages(doc_id), start=1):
        for line in p.splitlines():
            m = _HEAD.match(line)
            if m:
                n = int(m.group(1))
                if capturing and n != num:
                    return "\n".join(out)
                if n == num and not capturing:
                    capturing = True
                    out.append(f"<<p{i}>>")
            if capturing:
                if out and out[-1].startswith("<<p") is False and getattr(article_text, "_lastpage", None) != i:
                    pass
                out.append(line)
        if capturing:
            out.append(f"<<end p{i}>>")
    return "\n".join(out)


def gdpr_article(num):
    """GDPR article text: headings are 'Article N' on its own line."""
    d = "en-gdpr-2016"
    rx = re.compile(r"^\s*Article\s+(\d+)\s*$")
    out = []
    capturing = False
    for i, p in enumerate(pages(d), start=1):
        for line in p.splitlines():
            m = rx.match(line)
            if m:
                n = int(m.group(1))
                if capturing and n != num:
                    return "\n".join(out)
                if n == num:
                    capturing = True
                    out.append(f"<<p{i}>>")
            if capturing:
                out.append(line)
        if capturing:
            out.append(f"<<end p{i}>>")
    return "\n".join(out)


def where(doc_id, quote):
    q = normalize_for_match(quote)
    return [i for i, p in enumerate(pages(doc_id), start=1) if q in normalize_for_match(p)]
