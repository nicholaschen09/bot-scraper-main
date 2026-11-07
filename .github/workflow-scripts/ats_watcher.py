"""Poll company ATS boards (Greenhouse / Lever / Ashby / Workday /
SmartRecruiters / iCIMS) for US and Canadian software
engineering intern roles (general SWE, full-stack, frontend, backend,
infra/platform, product engineering) and emit an email via GITHUB_OUTPUT,
mirroring parse_boards.py.

Postings hit the ATS before LinkedIn or the SimplifyJobs boards pick them
up, so this is the fastest signal. Companies live in ats_companies.json;
the title/location filters live in job_filters.py.

Platform-specific configuration (there are intentionally no unverified sample
boards in the JSON) is: Workday ``tenant``, ``site`` and optional ``base_url``;
SmartRecruiters ``company``; and iCIMS ``base_url`` with optional
``search_url``.  iCIMS ``base_url`` is the public careers host and
``search_url`` can be used when the employer's search route differs from the
usual ``/jobs/search?ss=1``.
"""

import html
from html.parser import HTMLParser
import json
import math
import os
import re
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from job_filters import is_us, wanted_title

SCRIPT_DIR = Path(__file__).resolve().parent
COMPANIES_PATH = SCRIPT_DIR / "ats_companies.json"
SEEN_PATH = Path("snapshots/ats-seen.json")
SIMPLIFY_SEEN_PATH = Path("snapshots/seen.json")

WHITESPACE_RE = re.compile(r"\s+")


def fetch_json(url: str):
    last_err = None
    for _ in range(2):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=25) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001 - retry once, then report
            last_err = e
    raise last_err


def fetch_json_request(url: str, method="GET", payload=None):
    """Fetch JSON using the stdlib, including Workday's public POST endpoint."""
    data = None
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    last_err = None
    for _ in range(2):
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001 - retry once, then report
            last_err = e
    raise last_err


def require_config(company: dict, *fields: str) -> None:
    missing = [field for field in fields if not company.get(field)]
    if missing:
        raise ValueError(
            f"{company.get('ats', 'ATS')} board {company.get('name', '')!r} "
            f"requires config field(s): {', '.join(missing)}"
        )


def _workday_jobs(company: dict) -> list:
    # Workday identifiers are tenant + career site, not a portable company slug.
    require_config(company, "tenant", "site")
    tenant, site = company["tenant"], company["site"]
    base = company.get("base_url", f"https://{tenant}.wd5.myworkdayjobs.com")
    endpoint = f"{base.rstrip('/')}/wday/cxs/{tenant}/{site}/jobs"
    data = fetch_json_request(
        endpoint,
        method="POST",
        payload={"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": ""},
    )
    jobs = []
    for job in data.get("jobPostings", []):
        path = job.get("externalPath") or job.get("url") or ""
        locations = job.get("locationsText") or job.get("location") or ""
        if isinstance(locations, list):
            locations = " / ".join(str(value) for value in locations)
        jobs.append(
            {
                "id": f"w:{tenant}:{site}:{job.get('id') or path}",
                "title": job.get("title", ""),
                "location": locations,
                "url": urllib.parse.urljoin(base.rstrip("/") + "/", path),
            }
        )
    return jobs


def _smartrecruiters_jobs(company: dict) -> list:
    require_config(company, "company")
    account = company["company"]
    data = fetch_json(
        f"https://api.smartrecruiters.com/v1/companies/"
        f"{urllib.parse.quote(account, safe='')}/postings?limit=100"
    )
    jobs = []
    for job in data.get("content", []):
        location = job.get("location") or {}
        location_text = location.get("fullLocation") or " / ".join(
            str(value) for value in (
                location.get("city"), location.get("region"), location.get("country")
            ) if value
        )
        job_id = job.get("id", job.get("ref", ""))
        jobs.append(
            {
                "id": f"s:{account}:{job_id}",
                "title": job.get("name", ""),
                "location": location_text,
                "url": job.get("ref")
                or f"https://jobs.smartrecruiters.com/{account}/{job_id}",
            }
        )
    return jobs


class _ICIMSJobLinks(HTMLParser):
    """Small dependency-free parser for the public iCIMS search page."""

    def __init__(self):
        super().__init__()
        self.links = []
        self._href = None
        self._text = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and "/jobs/" in attrs.get("href", "").lower():
            self._href, self._text = attrs["href"], []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            title = WHITESPACE_RE.sub(" ", " ".join(self._text)).strip()
            if title:
                self.links.append((self._href, title))
            self._href, self._text = None, []


def _icims_jobs(company: dict) -> list:
    require_config(company, "base_url")
    search_url = company.get("search_url") or (
        company["base_url"].rstrip("/") + "/jobs/search?ss=1"
    )
    req = urllib.request.Request(search_url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=25) as resp:
        parser = _ICIMSJobLinks()
        parser.feed(resp.read().decode("utf-8", errors="replace"))
    jobs, seen = [], set()
    for path, title in parser.links:
        url = urllib.parse.urljoin(search_url, path)
        if url in seen:
            continue
        seen.add(url)
        jobs.append({"id": f"i:{url}", "title": title, "location": "", "url": url})
    return jobs


def board_jobs(company: dict) -> list:
    """Return [{id, title, location, url}] for one company's board."""
    ats, slug = company["ats"], company.get("slug", "")
    if ats == "greenhouse":
        data = fetch_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs")
        return [
            {
                "id": f"g:{slug}:{j['id']}",
                "title": j["title"],
                "location": (j.get("location") or {}).get("name", ""),
                "url": j.get("absolute_url", ""),
            }
            for j in data.get("jobs", [])
        ]
    if ats == "lever":
        data = fetch_json(f"https://api.lever.co/v0/postings/{slug}?mode=json")
        return [
            {
                "id": f"l:{slug}:{j.get('id', j.get('hostedUrl', ''))}",
                "title": j.get("text", ""),
                "location": (j.get("categories") or {}).get("location") or "",
                "url": j.get("hostedUrl", ""),
            }
            for j in data
        ]
    if ats == "ashby":
        data = fetch_json(
            "https://api.ashbyhq.com/posting-api/job-board/"
            + urllib.parse.quote(slug)
        )
        jobs = []
        for j in data.get("jobs", []):
            locs = [j.get("location", "")] + [
                s.get("location", "") for s in j.get("secondaryLocations", [])
            ]
            jobs.append(
                {
                    "id": f"a:{slug}:{j.get('id', j.get('jobUrl', ''))}",
                    "title": j.get("title", ""),
                    "location": " / ".join(x for x in locs if x),
                    "url": j.get("jobUrl") or j.get("applyUrl", ""),
                }
            )
        return jobs
    if ats == "workday":
        return _workday_jobs(company)
    if ats == "smartrecruiters":
        return _smartrecruiters_jobs(company)
    if ats == "icims":
        return _icims_jobs(company)
    raise ValueError(f"unknown ats {ats!r}")


def display_id(company_name: str, it: dict) -> str:
    title = it["title"]
    for marker in ("🎓", "🛂", "🇺🇸", "🔥", "🔒"):
        title = title.replace(marker, "")
    key = f"{company_name}|{title}|{it['location']}".lower()
    return "d:" + WHITESPACE_RE.sub(" ", key).strip()


def collect_matches() -> tuple:
    """Fetch every board; return (matches, failed_names). A failed board is
    skipped for this run — its ids stay in seen, so nothing re-alerts."""
    companies = json.loads(COMPANIES_PATH.read_text(encoding="utf-8"))
    matches, failed = [], []
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = {pool.submit(board_jobs, c): c for c in companies}
        for fut in as_completed(futures):
            c = futures[fut]
            try:
                jobs = fut.result()
            except Exception as e:  # noqa: BLE001 - one bad board can't kill the run
                failed.append(c["name"])
                board_ref = c.get("slug") or c.get("company") or c.get("name", "")
                print(f"WARN: {c['ats']}:{board_ref} failed: {e}", file=sys.stderr)
                continue
            for j in jobs:
                if wanted_title(j["title"]) and is_us(j["location"]):
                    j["company"] = c["name"]
                    matches.append(j)
    matches.sort(key=lambda j: (j["company"].lower(), j["title"].lower()))
    return matches, failed


def render_html(items: list) -> str:
    rows = []
    for it in items:
        rows.append(
            '<tr>'
            '<td style="padding:10px 0;border-bottom:1px solid #eee;vertical-align:top;">'
            f'<div style="font-weight:600;font-size:14px;color:#111;">'
            f'{html.escape(it["company"])}</div>'
            f'<div style="font-size:14px;color:#333;margin-top:2px;">'
            f'{html.escape(it["title"])}</div>'
            f'<div style="font-size:12px;color:#666;margin-top:2px;">'
            f'{html.escape(it["location"] or "Location not listed")}</div>'
            '</td>'
            '<td style="padding:10px 0;border-bottom:1px solid #eee;'
            'vertical-align:middle;text-align:right;white-space:nowrap;">'
            f'<a href="{html.escape(it["url"])}" '
            f'style="display:inline-block;padding:6px 14px;background:#059669;'
            f'color:#fff;text-decoration:none;border-radius:4px;font-size:13px;'
            f'font-weight:600;">Apply</a>'
            '</td>'
            '</tr>'
        )
    return (
        '<html><body style="font-family:-apple-system,BlinkMacSystemFont,'
        '\'Segoe UI\',Roboto,sans-serif;background:#f7f7f7;margin:0;padding:20px;">'
        '<div style="max-width:640px;margin:0 auto;background:#fff;padding:24px;'
        'border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,0.08);">'
        f'<h1 style="font-size:18px;margin:0 0 4px;color:#111;">'
        f'{len(items)} new SWE intern role{"s" if len(items) != 1 else ""}</h1>'
        '<p style="font-size:12px;color:#888;margin:0 0 8px;">'
        'US and Canadian software engineering internships — straight from company ATS '
        'boards (Greenhouse / Lever / Ashby), usually before LinkedIn.</p>'
        '<table cellpadding="0" cellspacing="0" border="0" '
        'style="width:100%;border-collapse:collapse;">'
        + "\n".join(rows) +
        '</table>'
        '<hr style="border:0;border-top:1px solid #eee;margin:20px 0 8px;">'
        '<p style="color:#aaa;font-size:11px;margin:0;">'
        'Sent by internship-watcher (ATS) · '
        '<a href="https://github.com/nicholaschen09/bot-scraper-main/actions" '
        'style="color:#aaa;">workflow logs</a></p>'
        '</div></body></html>'
    )


def render_plain(items: list) -> str:
    lines = [f"{len(items)} new SWE intern role(s)", ""]
    for it in items:
        lines.append(f"  {it['company']} - {it['title']}")
        lines.append(f"    Location: {it['location'] or '(not listed)'}")
        lines.append(f"    Apply: {it['url']}")
    return "\n".join(lines)


def build_subject(items: list) -> str:
    if not items:
        return "No new ATS intern roles"
    unique = list(dict.fromkeys(it["company"] for it in items))
    preview = ", ".join(unique[:3])
    suffix = f" +{len(unique) - 3} more" if len(unique) > 3 else ""
    plural = "s" if len(items) != 1 else ""
    return f"{len(items)} new SWE intern role{plural} (ATS): {preview}{suffix}"


def main():
    matches, failed = collect_matches()
    companies = json.loads(COMPANIES_PATH.read_text(encoding="utf-8"))
    failure_limit = max(10, math.ceil(len(companies) * 0.20))
    if len(failed) >= failure_limit:
        raise SystemExit(
            f"ATS health check failed: {len(failed)}/{len(companies)} boards "
            f"failed (threshold {failure_limit})"
        )

    first_run = not SEEN_PATH.exists()
    seen = set()
    if not first_run:
        try:
            seen = set(json.loads(SEEN_PATH.read_text(encoding="utf-8")))
        except (ValueError, OSError):
            first_run = True
    simplify_seen = set()
    if SIMPLIFY_SEEN_PATH.exists():
        try:
            simplify_seen = set(
                json.loads(SIMPLIFY_SEEN_PATH.read_text(encoding="utf-8"))
            )
        except (ValueError, OSError):
            print("WARN: could not read Simplify seen state; "
                  "cross-source deduplication is unavailable", file=sys.stderr)

    new, shown = [], set()
    for it in matches:
        did = display_id(it["company"], it)
        if it["id"] in seen or did in seen or did in simplify_seen:
            continue
        dkey = did
        if dkey in shown:
            continue
        shown.add(dkey)
        new.append(it)

    for it in matches:
        seen.add(it["id"])
        seen.add(display_id(it["company"], it))
    SEEN_PATH.parent.mkdir(exist_ok=True)
    SEEN_PATH.write_text(
        json.dumps(sorted(seen), indent=0) + "\n", encoding="utf-8"
    )

    if first_run:
        # No history: record current state without emailing.
        new = []

    print(f"Matches: {len(matches)} across boards, failed_boards={len(failed)} "
          f"{failed if failed else ''}")
    print(f"New: {len(new)} first_run={'yes' if first_run else 'no'}")

    total = len(new)
    subject = build_subject(new)
    html_body = render_html(new)
    plain_body = render_plain(new)

    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        print("---SUBJECT---")
        print(subject)
        print("---PLAIN---")
        print(plain_body)
        return

    with open(output_path, "a", encoding="utf-8") as f:
        f.write(f"total={total}\n")
        f.write(f"subject={subject}\n")
        f.write("html_body<<HTMLEOF\n")
        f.write(html_body)
        f.write("\nHTMLEOF\n")
        f.write("plain_body<<PLAINEOF\n")
        f.write(plain_body)
        f.write("\nPLAINEOF\n")


if __name__ == "__main__":
    main()
