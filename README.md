# Internship Watcher

GitHub Actions-based job watcher that emails newly discovered US and Canadian
software engineering internships and co-ops.

The watcher monitors public job boards, filters out non-engineering roles, and
stores its state in the `snapshots/` directory so the same posting is not
emailed repeatedly.

## What it monitors

### SimplifyJobs boards

The workflow fetches and parses:

- Summer internship listings
- Off-season internship listings

The board snapshots are saved as:

- `snapshots/previous-main.md`
- `snapshots/previous-offseason.md`

### Company ATS boards

The ATS watcher supports these public board types:

- Greenhouse
- Lever
- Ashby
- Workday
- SmartRecruiters
- iCIMS

Company configurations are stored in
`.github/workflow-scripts/ats_companies.json`.

Greenhouse, Lever, and Ashby entries are already configured. Workday,
SmartRecruiters, and iCIMS require company-specific identifiers, so only
verified entries should be added to the JSON file. Do not invent a tenant,
site, slug, or URL: an invalid board is reported as failed and skipped.

## What roles are included

The title filter is in `.github/workflow-scripts/job_filters.py`.

Included examples:

- Software Engineer Intern
- Software Engineering Intern
- SWE Intern
- Backend Engineer Intern
- Frontend Engineer Intern
- Full-Stack Engineer Intern
- Web Developer Intern
- Product Engineer Intern
- Application Engineer Intern
- Member of Technical Staff Intern
- Infrastructure, platform, DevOps, cloud, and SRE internships
- Equivalent co-op roles

The filter requires the title to identify an internship, internship program, or
co-op. It excludes product management, technical program management, data
science, data engineering, machine learning-only, hardware, embedded,
security, QA/testing, marketing, sales, recruiting, and other non-engineering
roles.

The phrase "product engineer" is included. "Product manager" is excluded.

## Location filtering

The watcher includes US and Canadian locations, including remote roles that
identify the US or Canada.

Examples of included locations:

- New York, NY
- Seattle, WA
- Remote, US
- Toronto, ON
- Vancouver, BC
- Montreal, QC
- Calgary, AB
- Ottawa, ON
- Waterloo, ON

Clearly foreign locations are excluded. Rows with no location are retained
because some ATS APIs do not expose location data; review those results before
applying.

## Requirements

For local development:

- Python 3.9 or newer
- Internet access for API and board requests

For GitHub Actions:

- A GitHub repository
- Actions enabled
- Workflow write permissions enabled
- A Gmail account with a Gmail App Password, or compatible SMTP credentials

The project uses only Python's standard library. No `pip install` step is
required.

## Create and push the repository

Create an empty repository on GitHub. Do not initialize it with another
README, `.gitignore`, or license because this project already contains those
files.

Then run:

```bash
cd /Users/nicholas/Downloads/bot-scraper-main
git init
git branch -M main
git add .
git commit -m "Initial internship watcher"
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPOSITORY.git
git push -u origin main
```

Replace `YOUR_USERNAME` and `YOUR_REPOSITORY` with your GitHub repository
details.

The workflow assumes the default branch is named `main`.

## Configure email secrets

In the repository, open:

**Settings -> Secrets and variables -> Actions -> New repository secret**

Create these repository secrets:

| Secret | Value |
|---|---|
| `MAIL_USERNAME` | Gmail address that sends the messages |
| `MAIL_PASSWORD` | Gmail App Password |
| `MAIL_TO` | Address that receives the messages |

For Gmail:

1. Enable two-step verification on the sending Google account.
2. Create an App Password in the Google account security settings.
3. Store the generated App Password as `MAIL_PASSWORD`.
4. Do not commit the password or put it in a Python file.

The workflow uses GitHub's automatically provided `GITHUB_TOKEN` to read the
public Simplify board through the authenticated GitHub API and to commit state
updates. Do not hardcode a personal GitHub token in the workflow.

## Configure GitHub Actions permissions

Open:

**Settings -> Actions -> General -> Workflow permissions**

Select:

**Read and write permissions**

The workflow commits changes to:

- `snapshots/previous-main.md`
- `snapshots/previous-offseason.md`
- `snapshots/seen.json`
- `snapshots/ats-seen.json`

Without write permission, the watcher may find jobs but fail when saving state.

## Test the email path first

After pushing the repository:

1. Open the repository's **Actions** tab.
2. Select **Internship Watcher**.
3. Select **Run workflow**.
4. Enable `test_email`.
5. Click **Run workflow**.
6. Open the run and inspect each step.
7. Confirm that the test email arrived.

The test-email run does not fetch boards, send job alerts, or commit state.

If it fails, check:

- `MAIL_USERNAME` is present and spelled exactly.
- `MAIL_PASSWORD` is a Gmail App Password, not the normal account password.
- `MAIL_TO` is present and is a valid email address.
- The sending account allows SMTP access.

## Test locally before relying on Actions

From the project directory:

```bash
cd /Users/nicholas/Downloads/bot-scraper-main
python3 -m py_compile .github/workflow-scripts/*.py
python3 -m json.tool .github/workflow-scripts/ats_companies.json >/dev/null
```

Test the title and location filters:

```bash
python3 - <<'PY'
import sys
sys.path.insert(0, ".github/workflow-scripts")
from job_filters import is_us, wanted_title

titles = {
    "Software Engineer Intern": True,
    "Backend Engineer Intern": True,
    "Full Stack Engineer Intern": True,
    "Product Engineer Intern": True,
    "Member of Technical Staff Intern": True,
    "Product Manager Intern": False,
    "Technical Program Manager Intern": False,
    "Machine Learning Intern": False,
}

locations = {
    "New York, NY": True,
    "Toronto, ON": True,
    "Vancouver, BC": True,
    "Remote, Canada": True,
    "London, UK": False,
    "Berlin, Germany": False,
}

for title, expected in titles.items():
    assert wanted_title(title) == expected, title
for location, expected in locations.items():
    assert is_us(location) == expected, location

print("title and location checks passed")
PY
```

The function is still named `is_us` for compatibility with the existing
code, but it now means "US or Canada accepted."

## Run the email builder without sending email

The email script supports a dry-run mode:

```bash
MAIL_DRYRUN=1 \
MAIL_SUBJECT="Local test" \
MAIL_PLAIN="This is a local test" \
MAIL_TO="test@example.com" \
python3 .github/workflow-scripts/send_email.py
```

This validates email construction without connecting to Gmail. It does not
send a message.

## Run the ATS watcher locally

The ATS watcher makes live requests to every configured company board and may
take a while:

```bash
cd /Users/nicholas/Downloads/bot-scraper-main
python3 .github/workflow-scripts/ats_watcher.py
```

It prints the number of matching roles and failed boards. Without
`GITHUB_OUTPUT`, it prints the generated subject and plain-text message rather
than exporting GitHub step outputs.

Important: the first successful ATS run records current postings and does not
email them. This prevents a large alert on initial setup. Later runs alert
only on postings not already present in `snapshots/ats-seen.json`.

The first local run can modify `snapshots/ats-seen.json`. Inspect the result
before committing it.

## Run the Simplify parser locally

The parser expects these two files in the project root:

- `current-main.md`
- `current-offseason.md`

They are downloaded by the GitHub workflow and are ignored by `.gitignore`.
To test manually:

```bash
curl -fsSL \
  -H "Accept: application/vnd.github.raw" \
  "https://api.github.com/repos/SimplifyJobs/Summer2027-Internships/contents/README.md?ref=dev" \
  -o current-main.md

curl -fsSL \
  -H "Accept: application/vnd.github.raw" \
  "https://api.github.com/repos/SimplifyJobs/Summer2027-Internships/contents/README-Off-Season.md?ref=dev" \
  -o current-offseason.md

python3 .github/workflow-scripts/parse_boards.py
```

The parser prints the number of parsed and new rows. It does not send email
when run locally.

## Workflow schedule and external pinger

The workflow has two triggers:

- Manual `workflow_dispatch`
- A 15-minute scheduled backstop

The comments in `.github/workflows/watch.yml` describe an optional external
pinger. A pinger can dispatch the workflow more frequently, but it is not
required for basic operation.

To dispatch it manually from the GitHub UI, use:

**Actions -> Internship Watcher -> Run workflow**

If using an external pinger, it must call:

```text
POST https://api.github.com/repos/YOUR_USERNAME/YOUR_REPOSITORY/actions/workflows/watch.yml/dispatches
```

with:

```json
{
  "ref": "main"
}
```

The external service needs its own GitHub credential with permission to
dispatch workflows. Never put that credential in this repository.

## How state and duplicate prevention work

The watcher stores stable posting identifiers in:

- `snapshots/seen.json` for Simplify listings
- `snapshots/ats-seen.json` for ATS listings

The workflow commits state after a run. Do not delete these files during normal
operation or the next run may treat existing postings as new.

The initial repository snapshot also contains board history used to seed
duplicate detection:

- `snapshots/previous-main.md`
- `snapshots/previous-offseason.md`

## Troubleshooting

### The workflow cannot fetch Simplify boards

Check that:

- The workflow is running on the `main` branch.
- Actions are enabled.
- The `GITHUB_TOKEN` is available.
- The API response-size checks in the fetch step are passing.

### The workflow finds jobs but cannot commit state

Enable **Read and write permissions** under the Actions settings and confirm
the workflow is allowed to create and push commits.

### No email is sent

No email is expected when there are no new postings. Also check:

- The relevant `seen` file already contains the posting.
- The title is outside the SWE filter.
- The location is outside the US/Canada filter.
- The ATS board failed and is listed in the workflow log.
- Gmail rejected the credentials.

### An ATS board fails

One failed board does not stop all other boards. The workflow logs the failed
company and continues. Verify the company's board identifier and test its
public URL/API independently before adding or changing configuration.

### Too many or too few roles are matched

Review `.github/workflow-scripts/job_filters.py`. The title filter is
intentionally conservative about non-engineering roles, while location strings
with no country information are retained rather than silently discarded.

## Security checklist before making the repository public

- Confirm no passwords, App Passwords, or personal tokens are committed.
- Keep email credentials only in GitHub Actions secrets.
- Review workflow changes before merging them.
- Do not log secret environment variables.
- Consider keeping the repository private if you do not want the company list,
  alert configuration, and snapshots publicly visible.

