# IIMJobs Auto Applier - Fresh Setup

Automates job search/apply flow for https://www.iimjobs.com/jobfeed using one resume.

## Project Structure

```text
iimjobs-auto-applier/
├── backend/
│   ├── app.py
│   ├── iimjobs_bot.py
│   ├── config.py
│   ├── requirements.txt
│   ├── .env.example
│   ├── data/
│   │   ├── applied_jobs.json
│   │   └── search_keywords.json
│   └── logs/
│       └── bot.log
├── frontend/
│   ├── package.json
│   ├── public/index.html
│   └── src/
│       ├── App.js
│       ├── index.js
│       └── styles.css
├── resumes/
│   └── put-your-resume-here.pdf
├── .gitignore
└── README.md
```

## 1. Backend Setup

```bash
cd iimjobs-auto-applier/backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

Create environment file:

```bash
cp .env.example .env
open .env
```

Update values:

```text
IIMJOBS_EMAIL=your_email_here
IIMJOBS_PASSWORD=your_password_here
RESUME_PATH=/absolute/path/to/your/resume.pdf
HEADLESS=false
MAX_JOBS_PER_KEYWORD=20
PORT=7000
```

Run backend:

```bash
python app.py
```

Test:

```text
http://127.0.0.1:7000/api/status
```

## 2. Frontend Setup

Open second terminal:

```bash
cd iimjobs-auto-applier/frontend
npm install
npm start
```

Open UI:

```text
http://localhost:3000
```

## 3. Usage

1. Keep backend running.
2. Keep frontend running.
3. Add/search roles from UI.
4. Click **Start Apply**.
5. First run browser will open visibly.
6. Complete OTP/Captcha manually if portal asks.
7. Bot skips jobs already tracked in `backend/data/applied_jobs.json`.

## 4. Important Notes

- Do not hardcode credentials in code.
- Put credentials only in `backend/.env`.
- Do not push `.env` or resume to GitHub.
- Some portals may show CAPTCHA/OTP/security checks. Those need manual completion.
- If IIMJobs UI changes, selectors inside `iimjobs_bot.py` may need updates.

## 5. Daily Commands

Backend:

```bash
cd iimjobs-auto-applier/backend
source venv/bin/activate
python app.py
```

Frontend:

```bash
cd iimjobs-auto-applier/frontend
npm start
```
