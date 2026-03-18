# JobBot v2.0 — Harish K
## 100% Free Agentic Job Application Pipeline

Stack: **Playwright** (scraping) + **Groq API free tier** (LLaMA 3, resume tailoring) + **ReportLab** (PDF) + **Gmail SMTP** (email report)

---

## ⚡ Quick Setup (5 minutes)

### 1. Install Python dependencies
```bash
pip install -r requirements.txt
playwright install chromium   # Downloads ~130MB Chromium browser
```

### 2. Get your FREE API keys

**Groq API (FREE — no credit card)**
1. Go to https://console.groq.com
2. Sign Up → API Keys → Create API Key
3. Copy your key (starts with `gsk_...`)

**Gmail App Password (for email reports)**
1. Go to myaccount.google.com → Security
2. Enable 2-Step Verification
3. Search "App Passwords" → Generate → Select "Mail" + "Other"
4. Copy the 16-character password (e.g. `abcd efgh ijkl mnop`)

### 3. Set environment variables
```bash
export GROQ_API_KEY=gsk_your_key_here
export GMAIL_APP_PASSWORD="abcd efgh ijkl mnop"   # optional, for email reports
```

Or create a `.env` file:
```
GROQ_API_KEY=gsk_your_key_here
GMAIL_APP_PASSWORD=abcd efgh ijkl mnop
```

### 4. Run!

```bash
# Test run (scrape + tailor resumes, no actual applications)
python orchestrator.py --dry-run

# Full run (scrape + tailor + apply + email report)
python orchestrator.py

# Scheduled (every 12 hours)
python orchestrator.py --schedule 12

# Launch web dashboard
python dashboard/app.py
# Then open: dashboard/index.html in your browser
```

---

## 📁 Project Structure

```
jobbot2/
├── agents/
│   ├── scraper.py          # Playwright scraper: Naukri, LinkedIn, Indeed, Wellfound
│   ├── jd_extractor.py     # Visits job URLs, extracts full JD + salary info
│   ├── resume_tailor.py    # Groq (LLaMA 3) tailors resume per JD → PDF
│   ├── applicator.py       # Playwright auto-applies, fills forms, handles Q&A
│   └── email_reporter.py   # Gmail SMTP sends HTML report after each run
├── config/
│   ├── personal_kb.json    # Your personal info + Q&A answers
│   └── base_resume.json    # Your base resume content
├── data/
│   ├── resumes/            # Tailored PDFs: CompanyName_YYYYMMDD.pdf
│   ├── applications/       # applied_links.json (duplicate guard) + log
│   └── logs/               # Run summaries + HTML reports
├── dashboard/
│   ├── app.py              # Flask API (port 5050)
│   └── index.html          # Web dashboard UI
├── orchestrator.py         # Master pipeline controller
└── requirements.txt
```

---

## 🔑 Key Features

| Feature | Detail |
|---|---|
| **FREE stack** | Playwright (free) + Groq free tier + Gmail SMTP |
| **Fresher filter** | Skips roles requiring 3+ years experience |
| **Duplicate guard** | `applied_links.json` — never applies twice to same URL |
| **Smart reuse** | If ≥85% skill match with existing resume, reuses it |
| **Resume naming** | `CompanyName_YYYYMMDD.pdf` |
| **Email report** | HTML email: Company | Role | Package | Location |
| **Q&A engine** | KB lookup → Groq AI for unknown questions |
| **Resume rules** | Problem→Task→Solution narrative, ATS keywords, 1-page |
| **Dashboard** | Live stats, application log, resume downloads |

---

## 📧 Email Report Format

After each run, you'll receive an email at `harishknlpengineer25@gmail.com`:
- Total applications, scraped jobs, resumes made
- Table: Company | Role | Package | Location | Platform | Time

---

## ⚠️ Important Notes

1. **LinkedIn auto-apply** works only for "Easy Apply" jobs (no redirect)
2. **Naukri** requires you to be logged in — log into Naukri in the Chromium window first (run headless=False temporarily)
3. **Groq free tier**: 14,400 requests/day, ~30 requests/minute — the bot adds delays automatically
4. **Gmail App Password**: Use App Password, NOT your main Google password

---

## 🧠 Resume Tailoring Rules (baked in)

1. **Problem → Task → Solution** narrative (never "I did X")
2. Only JD-relevant skills and content
3. ATS keywords extracted from JD and embedded naturally
4. 1-page tight format with metrics preserved
