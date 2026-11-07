"""Poll company ATS boards (Greenhouse / Lever / Ashby) for new US software
engineering intern roles (general SWE, full-stack, frontend, backend,
infra/platform, product engineering) and emit an email via GITHUB_OUTPUT,
mirroring parse_boards.py.

Postings hit the ATS before LinkedIn or the SimplifyJobs boards pick them
up, so this is the fastest signal. Companies live in ats_companies.json;
the title/location filters live in job_filters.py.
"""

import html
import json
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


def board_jobs(company: dict) -> list:
    """Return [{id, title, location, url}] for one company's board."""
    ats, slug = company["ats"], company["slug"]
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
    raise ValueError(f"unknown ats {ats!r}")


def display_id(company_name: str, it: dict) -> str:
    key = f"{company_name}|{it['title']}|{it['location']}".lower()
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
                print(f"WARN: {c['ats']}:{c['slug']} failed: {e}", file=sys.stderr)
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
        'US software engineering internships — straight from company ATS '
        'boards (Greenhouse / Lever / Ashby), usually before LinkedIn.</p>'
        '<table cellpadding="0" cellspacing="0" border="0" '
        'style="width:100%;border-collapse:collapse;">'
        + "\n".join(rows) +
        '</table>'
        '<hr style="border:0;border-top:1px solid #eee;margin:20px 0 8px;">'
        '<p style="color:#aaa;font-size:11px;margin:0;">'
        'Sent by internship-watcher (ATS) · '
        '<a href="https://github.com/jkhatri23/internship-watcher-standalone/actions" '
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

    first_run = not SEEN_PATH.exists()
    seen = set()
    if not first_run:
        try:
            seen = set(json.loads(SEEN_PATH.read_text(encoding="utf-8")))
        except (ValueError, OSError):
            first_run = True

    new, shown = [], set()
    for it in matches:
        did = display_id(it["company"], it)
        if it["id"] in seen or did in seen:
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
