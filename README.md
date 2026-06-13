# IIMJobs Auto Applier

A local automation tool to search jobs on IIMJobs, filter them by **Job Role**, **JD Keywords**, and optional **Location**, then apply using one configured resume.

This project has:

1. **React Frontend UI** - where you enter roles, keywords, locations, start/stop the bot, and see logs/history.
2. **Python Flask Backend** - exposes APIs to the frontend and controls the automation.
3. **Playwright Bot** - opens browser, logs in to IIMJobs, searches roles, opens jobs, validates filters, and applies.
4. **Local JSON Tracking** - stores applied/skipped job history.

---

# 1. Final Folder Structure

```text
iimjobs-auto-applier/
│
├── backend/
│   ├── app.py
│   ├── iimjobs_bot.py
│   ├── config.py
│   ├── requirements.txt
│   ├── .env
│   ├── .env.example
│   │
│   ├── data/
│   │   ├── applied_jobs.json
│   │   ├── search_keywords.json
│   │   └── search_config.json
│   │
│   └── logs/
│       └── bot.log
│
├── frontend/
│   ├── package.json
│   ├── package-lock.json
│   │
│   ├── public/
│   │   └── index.html
│   │
│   └── src/
│       ├── App.js
│       ├── index.js
│       └── styles.css
│
├── resumes/
│   └── your-resume.pdf
│
├── .gitignore
└── README.md
```

---

# 2. What This Project Does

This tool automates the IIMJobs application process.

Flow:

```text
Open UI
  ↓
Enter Job Roles
  ↓
Enter JD Keywords
  ↓
Enter Locations, optional
  ↓
Click Start Apply
  ↓
Backend starts Playwright browser
  ↓
Bot logs in to IIMJobs
  ↓
Bot searches each role
  ↓
Bot opens job detail pages
  ↓
Bot validates filters
  ↓
Bot applies only if filters match
  ↓
Bot tracks applied/skipped jobs
```

---

# 3. Matching Logic

The bot applies only when this condition passes:

```text
Job Role Match
AND
JD Keyword Match
AND
Location Match
```

Location is optional.

If no location is given:

```text
Location Match = TRUE
```

So if Locations list is empty, bot considers all locations.

---

## 3.1 Job Role Match

The role entered in UI must match the actual job title or main job description.

Example:

```text
Role entered:
Manager
```

Matching job titles:

```text
General Manager
Senior Manager
Product Manager
Strategy Manager
```

---

## 3.2 JD Keyword Match

At least one JD keyword must match the actual main JD content.

Example:

```text
JD Keywords:
pharmaceutical
life science
biotech
```

If job description contains:

```text
pharmaceutical
```

then keyword condition passes.

If job is Swiggy Storefront Manager and does not contain pharma/life science/biotech, it should be skipped.

---

## 3.3 Location Match

If you provide locations:

```text
Mumbai
Delhi
Bengaluru
```

then job must contain one of those locations.

If location list is empty, all locations are allowed.

---

# 4. Important Safety Fixes in Current Bot

The updated `iimjobs_bot.py` avoids earlier false matches.

Earlier issue:

```text
Bot matched keywords from full page body.
```

IIMJobs pages may contain:

```text
Recommended jobs
Similar jobs
Sidebar jobs
Filters
Trending jobs
```

These sections can contain unrelated words like:

```text
pharma
hyderabad
strategy
```

So the bot was sometimes applying incorrectly.

Current fix:

```text
Bot tries to match only main job content.
It avoids broad full-page/sidebar matching.
It logs MATCH DEBUG context.
It does not auto-expand pharmaceutical to pharma.
```

If you want `pharma` as a keyword, add it manually in the UI.

---

# 5. Main Files and Their Purpose

## 5.1 `backend/app.py`

This is the Flask backend.

It provides APIs used by the React UI.

Important APIs:

```text
GET  /api/status
GET  /api/config
POST /api/config
GET  /api/applied
POST /api/run
POST /api/stop
```

Responsibilities:

```text
Start bot
Stop bot
Save roles/keywords/locations
Return logs/status/history
Expose data to frontend
```

---

## 5.2 `backend/iimjobs_bot.py`

This is the main automation bot.

Responsibilities:

```text
Open browser using Playwright
Login to IIMJobs
Search each job role
Collect job links
Open job pages
Extract title, JD, location
Validate filters
Click Apply
Upload resume if file input appears
Track applied/skipped jobs
Write logs
```

---

## 5.3 `backend/config.py`

Reads environment variables from `.env`.

Example values:

```text
IIMJOBS_EMAIL
IIMJOBS_PASSWORD
RESUME_PATH
HEADLESS
MAX_JOBS_PER_KEYWORD
PORT
```

---

## 5.4 `backend/data/applied_jobs.json`

Stores all processed jobs.

Example:

```json
{
  "url": "https://www.iimjobs.com/j/example-job",
  "title": "Manager - Strategy",
  "role": "Manager",
  "status": "applied",
  "reason": "role matched; JD keyword matched; location allowed",
  "applied_at": "2026-06-13 13:26:35"
}
```

Possible statuses:

```text
applied
already_applied
skipped_filter_mismatch
skipped_extraction_failed
attempted_needs_verification
```

---

## 5.5 `backend/logs/bot.log`

Stores detailed bot logs.

Use this file to debug why a job was applied or skipped.

Useful command:

```bash
tail -100 logs/bot.log
```

To search for match details:

```bash
grep "MATCH DEBUG" logs/bot.log -A 2
```

---

## 5.6 `frontend/src/App.js`

React UI.

It shows:

```text
Backend Status
Job Roles
JD Keywords
Locations
Start Apply button
Stop button
Current Activity
Logs
Applied/Skipped History
```

---

# 6. Backend Setup

## Step 1: Open terminal

Go to project backend folder:

```bash
cd iimjobs-auto-applier/backend
```

---

## Step 2: Create virtual environment

Run this only once:

```bash
python3 -m venv venv
```

Activate it:

```bash
source venv/bin/activate
```

You should see:

```text
(venv)
```

Example:

```text
(venv) jagankumar@192 backend %
```

---

## Step 3: Install Python packages

```bash
pip install -r requirements.txt
```

If `pip` does not work:

```bash
python3 -m pip install -r requirements.txt
```

---

## Step 4: Install Playwright browser

```bash
playwright install chromium
```

This installs Chromium browser used by the bot.

---

## Step 5: Create `.env`

If `.env` does not exist:

```bash
cp .env.example .env
```

Open it:

```bash
open .env
```

Update values:

```text
IIMJOBS_EMAIL=your_iimjobs_email
IIMJOBS_PASSWORD=your_iimjobs_password
RESUME_PATH=/Users/jagankumar/Downloads/resume.pdf
HEADLESS=false
MAX_JOBS_PER_KEYWORD=50
PORT=7001
```

Important:

```text
Use absolute resume path.
Do not push .env to GitHub.
```

---

## Step 6: Start backend

```bash
python app.py
```

Expected:

```text
Backend running at http://127.0.0.1:7001
```

Keep this terminal open.

---

## Step 7: Test backend

Open browser:

```text
http://127.0.0.1:7001/api/status
```

Expected response:

```json
{
  "ok": true
}
```

If this works, backend is running correctly.

---

# 7. Frontend Setup

## Step 1: Open second terminal

Keep backend running in first terminal.

Open second terminal:

```bash
cd iimjobs-auto-applier/frontend
```

---

## Step 2: Install frontend packages

```bash
npm install
```

---

## Step 3: Start UI

```bash
npm start
```

Frontend opens at:

```text
http://localhost:3000
```

---

# 8. How to Access the UI

Backend:

```text
http://127.0.0.1:7001
```

Frontend UI:

```text
http://localhost:3000
```

Steps:

1. Start backend:
   ```bash
   cd iimjobs-auto-applier/backend
   source venv/bin/activate
   python app.py
   ```

2. Start frontend:
   ```bash
   cd iimjobs-auto-applier/frontend
   npm start
   ```

3. Open:
   ```text
   http://localhost:3000
   ```

4. UI should show:
   ```text
   Backend online
   ```

---

# 9. How to Use the UI

## Step 1: Add Job Roles

Examples:

```text
Manager
Strategy
Chief of Staff
Product Manager
Data Engineer
```

Role match is mandatory.

---

## Step 2: Add JD Keywords

Examples:

```text
pharmaceutical
life science
biotech
M&A
investor relations
corporate strategy
```

At least one JD keyword is mandatory.

The bot applies only if at least one JD keyword is found in the job description.

---

## Step 3: Add Locations, optional

Examples:

```text
Mumbai
Delhi
Bengaluru
Hyderabad
Pune
Remote
```

If you leave Locations empty:

```text
All locations are allowed.
```

---

## Step 4: Click Start Apply

The browser opens and bot starts.

If:

```text
HEADLESS=false
```

you can see browser activity.

If IIMJobs asks for:

```text
OTP
Captcha
Security check
```

complete manually in the opened browser.

---

## Step 5: Watch Logs

UI shows logs in real time.

Backend log file:

```bash
tail -100 backend/logs/bot.log
```

---

## Step 6: Review History

UI shows:

```text
Applied / Skipped History
```

Backend file:

```bash
python3 -m json.tool backend/data/applied_jobs.json
```

---

# 10. Example Filter Setups

## Example 1: Pharma Strategy Manager

```text
Job Roles:
Manager
Strategy

JD Keywords:
pharmaceutical
life science
biotech

Locations:
Mumbai
Delhi
```

Applies only if:

```text
Manager/Strategy role match
AND
pharma/life science/biotech keyword match
AND
Mumbai/Delhi location match
```

---

## Example 2: Investor Relations Strategy

```text
Job Roles:
Manager
Strategy

JD Keywords:
Investor Relations
M&A
Corporate Strategy

Locations:
empty
```

Applies if role and JD keyword match, any location allowed.

---

## Example 3: Data Engineer

```text
Job Roles:
Data Engineer

JD Keywords:
Spark
PySpark
Kafka
Hadoop
AWS

Locations:
Bengaluru
Hyderabad
Remote
```

Applies only if role matches and at least one skill keyword appears.

---

# 11. How to Check Why a Job Was Applied

Use:

```bash
cd iimjobs-auto-applier/backend
grep -A 10 "Job Title Here" data/applied_jobs.json
```

Example:

```bash
grep -A 10 "Swiggy - Manager - Storefront" data/applied_jobs.json
```

Look at:

```text
reason
```

Example:

```json
"reason": "role matched: \"manager\"; JD keyword matched: \"pharmaceutical\"; location filter empty, allowing all locations"
```

---

# 12. How to Check Where a Keyword Matched

The updated bot logs match context.

Run:

```bash
grep "MATCH DEBUG" logs/bot.log -A 2
```

Example output:

```text
MATCH DEBUG [JD keyword] title='Manager - Strategy' variant='pharmaceutical'
MATCH CONTEXT => ... pharmaceutical industry experience ...
```

This tells exactly where the match happened.

---

# 13. How to Clear Old History

If wrong jobs were applied/tracked earlier:

```bash
cd iimjobs-auto-applier/backend
echo "[]" > data/applied_jobs.json
```

Restart backend:

```bash
python app.py
```

---

# 14. Common Issues and Fixes

## Issue 1: Backend offline in UI

Check backend:

```text
http://127.0.0.1:7001/api/status
```

If not working, start backend:

```bash
cd backend
source venv/bin/activate
python app.py
```

---

## Issue 2: Port already in use

Check:

```bash
lsof -i :7001
```

Kill process:

```bash
kill -9 <PID>
```

Or change port in `.env`:

```text
PORT=7002
```

Then update frontend `App.js`:

```js
const API_BASE = "http://127.0.0.1:7002";
```

---

## Issue 3: Failed to fetch in UI

Possible causes:

```text
Backend not running
Wrong port in App.js
CORS issue
```

Verify:

```text
http://127.0.0.1:7001/api/status
```

Also verify in `frontend/src/App.js`:

```js
const API_BASE = "http://127.0.0.1:7001";
```

---

## Issue 4: Bot applies to unrelated jobs

Check reason:

```bash
grep -A 10 "Job Title" data/applied_jobs.json
```

Check match context:

```bash
grep "MATCH DEBUG" logs/bot.log -A 2
```

If keyword is too broad, remove it.

Example:

```text
pharma
```

is broader than:

```text
pharmaceutical
```

Use stricter keywords when possible.

---

## Issue 5: Bot skips expected job

Check:

```bash
grep -A 10 "Job Title" data/applied_jobs.json
```

Look for:

```text
skipped_filter_mismatch
```

Common reasons:

```text
Role did not match
JD keyword did not match
Location did not match
Job was not processed due to MAX_JOBS_PER_KEYWORD
```

Increase:

```text
MAX_JOBS_PER_KEYWORD=100
```

in `.env`.

Restart backend.

---

## Issue 6: Resume upload does not happen

Some jobs may not show resume upload field.

The bot applies with available portal flow.

If IIMJobs redirects to external company page, manual action may be needed.

---

## Issue 7: Login stuck

Possible reasons:

```text
Wrong credentials
Captcha
OTP
Security verification
```

Use:

```text
HEADLESS=false
```

Then complete manually in browser.

---

# 15. Daily Run Commands

## Terminal 1: Backend

```bash
cd iimjobs-auto-applier/backend
source venv/bin/activate
python app.py
```

## Terminal 2: Frontend

```bash
cd iimjobs-auto-applier/frontend
npm start
```

Open:

```text
http://localhost:3000
```

---

# 16. GitHub Notes

Do not push private files.

`.gitignore` should include:

```text
backend/.env
backend/venv/
frontend/node_modules/
backend/data/applied_jobs.json
backend/logs/
resumes/*.pdf
.DS_Store
```

Push source code only:

```bash
git add .
git commit -m "Update IIMJobs auto applier"
git push
```

---

# 17. Best Practices

Use specific filters.

Better:

```text
Role: Manager
JD Keywords: pharmaceutical, life science, biotech
```

Avoid very broad keywords:

```text
strategy
sales
marketing
manager
business
```

Broad keywords can match too many jobs.

For high accuracy:

```text
Role = functional title
JD Keywords = domain/industry/skills
Location = optional
```

---

# 18. Recommended Filter Strategy

For pharma/life-science strategy jobs:

```text
Roles:
Manager
Strategy
Chief of Staff

JD Keywords:
pharmaceutical
life science
biotech
healthcare
medical devices

Locations:
empty or preferred cities
```

For investor relations strategy jobs:

```text
Roles:
Manager
Strategy

JD Keywords:
Investor Relations
M&A
Corporate Strategy
Corporate Finance

Locations:
empty or preferred cities
```

For data engineering jobs:

```text
Roles:
Data Engineer
Big Data Engineer

JD Keywords:
Spark
PySpark
Kafka
Hadoop
AWS
Airflow

Locations:
Bengaluru
Hyderabad
Remote
```

---

# 19. Final Reminder

This automation depends on IIMJobs page structure.

If IIMJobs changes UI selectors, the bot may need updates.

Always test with:

```text
HEADLESS=false
```

before running many applications.

Review `applied_jobs.json` and `bot.log` regularly.
