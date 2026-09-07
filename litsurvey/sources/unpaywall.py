"""Unpaywall (https://unpaywall.org): legal open-access copies by DOI. Needs only an email."""
import urllib.parse

from .. import http
from ..config import CFG


def lookup(doi):
    doi = doi.replace("DOI:", "").replace("https://doi.org/", "").strip()
    email = CFG["openalex_mailto"] or "litsurvey@localhost.local"
    url = (f"https://api.unpaywall.org/v2/{urllib.parse.quote(doi, safe='/')}"
           f"?email={urllib.parse.quote(email)}")
    d = http.get_json(url)
    for loc in [d.get("best_oa_location")] + (d.get("oa_locations") or []):
        if loc and (loc.get("url_for_pdf") or loc.get("url")):
            return {"doi": doi, "is_oa": True, "title": d.get("title") or "",
                    "pdf": loc.get("url_for_pdf") or "", "page": loc.get("url") or "",
                    "version": loc.get("version") or ""}
    return {"doi": doi, "is_oa": bool(d.get("is_oa")), "title": d.get("title") or "",
            "pdf": "", "page": "", "version": ""}
