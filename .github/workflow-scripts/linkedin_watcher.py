"""Poll LinkedIn's public guest jobs search for matching internships.

This uses the unauthenticated guest-search endpoint, not a logged-in account.
LinkedIn may rate-limit or change this endpoint; a failure is reported rather
than treated as an empty result.
"""

import html
from html.parser import HTMLParser
import json
import os
import re
import sys
import urllib.parse
import urllib.error
import urllib.request
from pathlib import Path

from job_filters import is_us, wanted_title

SCRIPT_DIR = Path(__file__).resolve().parent
SEARCHES_PATH = SCRIPT_DIR / "linkedin_searches.json"
SEEN_PATH = Path("snapshots/linkedin-seen.json")
ATS_SEEN_PATH = Path("snapshots/ats-seen.json")
SIMPLIFY_SEEN_PATH = Path("snapshots/seen.json")
WHITESPACE_RE = re.compile(r"\s+")


class _JobCardParser(HTMLParser):
    """Extract the stable fields from LinkedIn's public job-card HTML."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.cards = []
        self.card = None
        self.card_depth = 0
        self.field = None
        self.parts = []

    @staticmethod
    def _classes(attrs):
        return set(dict(attrs).get("class", "").split())

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        classes = self._classes(attrs)
        if tag == "div" and "base-card" in classes and self.card is None:
            self.card = {
                "id": attrs_dict.get("data-entity-urn", ""),
                "title": [],
                "company": [],
                "location": [],
                "url": "",
            }
            self.card_depth = 1
            return
        if self.card is None:
            return
        if tag == "div":
            self.card_depth += 1
        if tag == "a" and "base-card__full-link" in classes:
            self.card["url"] = attrs_dict.get("href", "")
        if "base-search-card__title" in classes:
            self.field = "title"
            self.parts = []
        elif "base-search-card__subtitle" in classes:
            self.field = "company"
            self.parts = []
        elif "job-search-card__location" in classes:
            self.field = "location"
            self.parts = []

    def handle_data(self, data):
        if self.card is not None and self.field:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if self.card is None:
            return
        if tag in {"h3", "h4", "span"} and self.field:
            self.card[self.field] = [WHITESPACE_RE.sub(" ", " ".join(self.parts)).strip()]
            self.field = None
            self.parts = []
        if tag == "div":
            self.card_depth -= 1
            if self.card_depth == 0:
                card = {
                    key: (value[0] if isinstance(value, list) and value else value)
                    for key, value in self.card.items()
                }
                if card["title"] and card["url"]:
                    self.cards.append(card)
                self.card = None


def fetch_page(search: dict, start: int) -> list:
    params = {
        "keywords": search["keywords"],
        "location": search["location"],
        "start": str(start),
    }
    url = (
        "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?"
        + urllib.parse.urlencode(params)
    )
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; InternshipWatcher/1.0)",
            "Accept": "text/html",
        },
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        parser = _JobCardParser()
        parser.feed(response.read().decode("utf-8", errors="replace"))
    return parser.cards


def collect_matches() -> list:
    searches = json.loads(SEARCHES_PATH.read_text(encoding="utf-8"))
    matches = {}
    successful_pages = 0
    for search in searches:
        max_pages = int(search.get("max_pages", 1))
        for page in range(max_pages):
            try:
                cards = fetch_page(search, page * 25)
            except urllib.error.HTTPError as error:
                print(
                    f"WARN: LinkedIn search for {search['location']!r} "
                    f"page {page + 1} failed with HTTP {error.code}; "
                    "continuing with other searches",
                    file=sys.stderr,
                )
                break
            except (OSError, ValueError) as error:
                print(
                    f"WARN: LinkedIn search for {search['location']!r} "
                    f"page {page + 1} failed: {error}; "
                    "continuing with other searches",
                    file=sys.stderr,
                )
                break
            successful_pages += 1
            if not cards:
                break
            for card in cards:
                title = html.unescape(card["title"])
                location = html.unescape(card.get("location", ""))
                if not wanted_title(title) or not is_us(location):
                    continue
                url = urllib.parse.urljoin("https://www.linkedin.com", card["url"])
                url = url.split("?", 1)[0]
                job_id = card.get("id") or url
                matches[job_id] = {
                    "id": f"li:{job_id}",
                    "title": title,
                    "company": html.unescape(card.get("company", "")),
                    "location": location,
                    "url": url,
                }
    if not successful_pages:
        raise RuntimeError("all configured LinkedIn searches failed")
    return sorted(matches.values(), key=lambda item: (
        item["company"].lower(), item["title"].lower()
    ))


def display_id(item: dict) -> str:
    key = "|".join(
        (item[field] or "").strip().lower()
        for field in ("company", "title", "location")
    )
    return "d:" + WHITESPACE_RE.sub(" ", key)


def load_seen(path: Path) -> set:
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return set(data if isinstance(data, list) else data)
    except (ValueError, OSError):
        print(f"WARN: could not read {path}; starting with empty state", file=sys.stderr)
        return set()


def render_html(items: list) -> str:
    rows = []
    for item in items:
        rows.append(
            "<tr><td style=\"padding:10px 0;border-bottom:1px solid #eee;\">"
            f"<div style=\"font-weight:600;font-size:14px;color:#111;\">"
            f"{html.escape(item['company'])}</div>"
            f"<div style=\"font-size:14px;color:#333;margin-top:2px;\">"
            f"{html.escape(item['title'])}</div>"
            f"<div style=\"font-size:12px;color:#666;margin-top:2px;\">"
            f"{html.escape(item['location'] or 'Location not listed')}</div></td>"
            "<td style=\"padding:10px 0;border-bottom:1px solid #eee;text-align:right;\">"
            f"<a href=\"{html.escape(item['url'])}\" style=\"display:inline-block;"
            "padding:6px 14px;background:#0a66c2;color:#fff;text-decoration:none;"
            "border-radius:4px;font-size:13px;font-weight:600;\">Apply</a></td></tr>"
        )
    return (
        '<html><body style="font-family:-apple-system,BlinkMacSystemFont,'
        "'Segoe UI',Roboto,sans-serif;background:#f7f7f7;margin:0;padding:20px;\">"
        '<div style="max-width:640px;margin:0 auto;background:#fff;padding:24px;'
        'border-radius:8px;"><h1 style="font-size:18px;margin:0 0 16px;">'
        f"{len(items)} new SWE intern role{'s' if len(items) != 1 else ''} (LinkedIn)"
        '</h1><table cellpadding="0" cellspacing="0" border="0" '
        'style="width:100%;border-collapse:collapse;">' + "".join(rows)
        + "</table></div></body></html>"
    )


def render_plain(items: list) -> str:
    lines = [f"{len(items)} new SWE intern role(s) (LinkedIn)", ""]
    for item in items:
        lines += [
            f"  {item['company']} - {item['title']}",
            f"    Location: {item['location'] or '(not listed)'}",
            f"    Apply: {item['url']}",
        ]
    return "\n".join(lines)


def main():
    matches = collect_matches()
    seen = load_seen(SEEN_PATH)
    cross_source_seen = load_seen(ATS_SEEN_PATH) | load_seen(SIMPLIFY_SEEN_PATH)
    first_run = not SEEN_PATH.exists()
    new, shown = [], set()
    for item in matches:
        did = display_id(item)
        if item["id"] in seen or did in seen or did in cross_source_seen or did in shown:
            continue
        shown.add(did)
        new.append(item)
    for item in matches:
        seen.add(item["id"])
        seen.add(display_id(item))
    SEEN_PATH.parent.mkdir(exist_ok=True)
    SEEN_PATH.write_text(json.dumps(sorted(seen), indent=0) + "\n", encoding="utf-8")
    if first_run:
        new = []

    print(f"Matches: {len(matches)}")
    print(f"New: {len(new)} first_run={'yes' if first_run else 'no'}")
    subject = (
        "No new LinkedIn intern roles"
        if not new else f"{len(new)} new SWE intern role"
        f"{'s' if len(new) != 1 else ''} (LinkedIn)"
    )
    html_body, plain_body = render_html(new), render_plain(new)
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        print("---SUBJECT---\n" + subject + "\n---PLAIN---\n" + plain_body)
        return
    with open(output_path, "a", encoding="utf-8") as output:
        output.write(f"total={len(new)}\nsubject={subject}\n")
        output.write(f"html_body<<HTMLEOF\n{html_body}\nHTMLEOF\n")
        output.write(f"plain_body<<PLAINEOF\n{plain_body}\nPLAINEOF\n")


if __name__ == "__main__":
    main()
