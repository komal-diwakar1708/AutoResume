# AutomateResume — Automated Job Application System

Automatically searches job boards, applies for roles, and emails recruiters — all configured for Product Manager roles in Germany, Singapore, Japan, Australia, New Zealand, and Canada.

---

## Quick Start

### 1. Install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

### 2. Configure secrets

```bash
cp .env.example .env
```

Open `.env` and fill in:

| Key | Where to get it |
|---|---|
| `RAPIDAPI_KEY` | [rapidapi.com](https://rapidapi.com) — subscribe to **JSearch** (free tier) |
| `OPENAI_API_KEY` | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) |
| `HUNTER_API_KEY` | [hunter.io/api-keys](https://hunter.io/api-keys) (free: 25/month) |
| `EMAIL_ADDRESS` | Your Gmail address |
| `EMAIL_APP_PASSWORD` | [Google App Password](https://myaccount.google.com/apppasswords) (not your Gmail password) |
| `LINKEDIN_EMAIL` | Your LinkedIn login email |
| `LINKEDIN_PASSWORD` | Your LinkedIn login password |

### 3. Add your resume

Place your resume PDF at:
```
resume/resume.pdf
```

### 4. Edit your preferences

Open `config/settings.yaml` and update:
- `job_title` and `alt_titles`
- `skills` — your key product management skills
- `locations` — target countries
- `personal` — your name, phone, LinkedIn URL, etc.

### 5. Check your setup

```bash
python main.py --check
```

### 6. Run it

```bash
# Run once
python main.py

# Run every 12 hours automatically (set interval in settings.yaml)
python main.py --schedule
```

---

## Commands

```bash
python main.py               # Run the full pipeline once
python main.py --schedule    # Run now + repeat every N hours
python main.py --stats       # Show application statistics
python main.py --list-jobs   # List all tracked jobs
python main.py --manual      # List jobs that need manual apply
python main.py --check       # Verify setup is complete
```

---

## How It Works

```
Search (JSearch + LinkedIn + Indeed + Seek + StepStone)
    ↓
Filter & Score (title match + skill keywords + location)
    ↓
Save to SQLite database (dedup — skip already-seen jobs)
    ↓
For each matched job:
  1. Generate personalised cover letter (OpenAI GPT-4o)
  2. Auto-apply: LinkedIn Easy Apply → Indeed Quick Apply
  3. Find recruiter email (Hunter.io / description scraping)
  4. Send personalised email with cover letter + resume attached
  5. Log everything to database
```

---

## Job Status Lifecycle

| Status | Meaning |
|---|---|
| `found` | Job discovered from a source |
| `matched` | Passed filter — cover letter generated |
| `applied` | Application submitted automatically |
| `emailed` | Recruiter email sent |
| `manual_required` | Auto-apply failed — apply manually |
| `interview` | Update manually when you get a response |
| `rejected` | Update manually |

---

## Important Notes

### Visa & Relocation
Set `visa_sponsorship_required: true` in settings.yaml to only apply to jobs that mention visa/relocation support.

### Apply Limit
`apply_limit_per_run: 10` caps how many applications per run. Increase carefully.

### Anti-Detection
The browser automation uses realistic delays and stealth mode. However, LinkedIn and Indeed may still flag automated behaviour. If blocked, affected jobs are logged as `manual_required` and you can apply to them manually via `python main.py --manual`.

### Terms of Service
Automated applying may violate some platforms' ToS. Use responsibly.

---

## File Structure

```
AutomateResume/
├── config/settings.yaml    ← Edit your preferences here
├── resume/resume.pdf       ← Place your resume here
├── .env                    ← Your API keys (never commit this)
├── main.py                 ← Entry point
├── src/
│   ├── search/             ← Job board searchers
│   ├── apply/              ← Auto-apply automation (Playwright)
│   ├── email/              ← Recruiter email finder + sender
│   ├── ai/                 ← Cover letter generator (OpenAI)
│   ├── db/                 ← SQLite tracker
│   └── orchestrator.py     ← Main pipeline
└── data/jobs.db            ← Auto-created SQLite database
```
