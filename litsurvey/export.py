"""Export result lists: BibTeX, RIS, CSV, JSON, Markdown."""
import csv
import io
import json
import re

from . import papers as P


def _bib_escape(s):
    return (s or "").replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}") \
        .replace("&", "\\&").replace("%", "\\%")


def _lastname(name):
    parts = (name or "").replace(",", " ").split()
    return parts[-1] if parts else "anon"


def _bibkey(p, used):
    first = _lastname(p["authors"][0]) if p["authors"] else "anon"
    first = re.sub(r"[^A-Za-z]", "", first).lower() or "anon"
    words = [w for w in re.findall(r"[A-Za-z]{3,}", p["title"] or "")
             if w.lower() not in ("the", "and", "for", "with", "from", "using", "via",
                                  "towards", "toward", "based", "into")]
    word = words[0].lower() if words else "paper"
    base = f"{first}{p['year'] or 'nd'}{word}"
    key, n = base, 1
    while key in used:
        n += 1
        key = f"{base}{n}"
    used.add(key)
    return key


def _bib_author(name):
    """'Given Family' -> 'Family, Given' so BibTeX parses multi-part names."""
    parts = name.split()
    if len(parts) < 2:
        return name
    return f"{parts[-1]}, {' '.join(parts[:-1])}"


def to_bibtex(plist):
    used, out = set(), []
    for p in plist:
        key = _bibkey(p, used)
        authors = " and ".join(_bib_author(a) for a in p["authors"]) or "unknown"
        fields = [("title", "{" + _bib_escape(p["title"]) + "}"),
                  ("author", "{" + _bib_escape(authors) + "}")]
        if p["year"]:
            fields.append(("year", "{" + str(p["year"]) + "}"))
        is_arxiv_only = p["arxiv"] and (not p["venue"] or p["venue"].lower().startswith("arxiv"))
        if is_arxiv_only:
            kind = "misc"
            fields += [("eprint", "{" + p["arxiv"] + "}"),
                       ("archivePrefix", "{arXiv}")]
        else:
            kind = "article" if p["venue"] else "misc"
            if p["venue"]:
                fields.append(("journal", "{" + _bib_escape(p["venue"]) + "}"))
        if p["doi"]:
            fields.append(("doi", "{" + p["doi"] + "}"))
        if p["url"]:
            fields.append(("url", "{" + p["url"] + "}"))
        if p["abstract"]:
            fields.append(("abstract", "{" + _bib_escape(p["abstract"]) + "}"))
        body = ",\n".join(f"  {k} = {v}" for k, v in fields)
        out.append(f"@{kind}{{{key},\n{body}\n}}")
    return "\n\n".join(out) + "\n"


def to_ris(plist):
    out = []
    for p in plist:
        lines = ["TY  - " + ("JOUR" if p["venue"] and not p["venue"].lower().startswith("arxiv") else "GEN"),
                 "TI  - " + (p["title"] or "")]
        lines += ["AU  - " + _bib_author(a) for a in p["authors"]]
        if p["year"]:
            lines.append(f"PY  - {p['year']}")
        if p["venue"]:
            lines.append("JO  - " + p["venue"])
        if p["doi"]:
            lines.append("DO  - " + p["doi"])
        if p["url"]:
            lines.append("UR  - " + p["url"])
        if p["abstract"]:
            lines.append("AB  - " + p["abstract"])
        lines.append("ER  - ")
        out.append("\n".join(lines))
    return "\n\n".join(out) + "\n"


def to_csv(plist):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["title", "year", "authors", "venue", "doi", "arxiv", "citations",
                "url", "sources", "id"])
    for p in plist:
        w.writerow([p["title"], p["year"] or "", "; ".join(p["authors"]), p["venue"],
                    p["doi"], p["arxiv"], p["citations"], p["url"],
                    "+".join(p["sources"]), P.best_id(p)])
    return buf.getvalue()


def to_json(plist):
    return json.dumps(plist, indent=2, ensure_ascii=False) + "\n"


def to_markdown(plist, snippet=0):
    return "\n\n".join(P.format_paper(p, i, snippet=snippet)
                       for i, p in enumerate(plist, 1)) + "\n"


FORMATS = {"bib": to_bibtex, "bibtex": to_bibtex, "ris": to_ris, "csv": to_csv,
           "json": to_json, "md": to_markdown, "markdown": to_markdown}


def render(plist, fmt):
    fn = FORMATS.get(fmt.lower().lstrip("."))
    if not fn:
        raise ValueError(f"unknown export format {fmt!r}; use one of {sorted(FORMATS)}")
    return fn(plist)


def write(plist, path):
    """Write in the format implied by the file extension."""
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else "md"
    text = render(plist, ext)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path
