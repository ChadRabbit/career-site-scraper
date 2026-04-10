# Job Scraper + AI Ranking System

A configurable, multi-company job scraper that extracts job listings from various career pages and ranks them using AI.

---

## 🚀 Features

* 🔍 Scrapes multiple company career pages (API + DOM based)
* ⚙️ Config-driven architecture (easy to onboard new companies)
* 📄 Stores results in Excel
* 🤖 AI-based job relevance scoring (Ollama models)
* ⚡ Parallel AI evaluation support
* 🧩 Handles pagination, search, lazy loading
* 🧠 Works across different site architectures (API, DOM, SPA)

---

## 🏗️ Project Structure

```
.
├── api_strategy.py        # API-based scraping logic
├── dom_strategy.py        # DOM-based scraping logic
├── strategy.py            # Unified strategy runner
├── companies.py           # Company configurations
├── utils.py               # Pagination, search helpers
├── job_scraper.py         # Main entry point
├── jobAIEvaluator.py      # AI scoring logic
├── logger.py              # Logging setup
├── save_session.py             # Browser session initializer (IMPORTANT)
├── requirements.txt
```

---

## ⚙️ Setup

```bash
git clone git@github.com:ChadRabbit/career-site-scraper.git
cd career-site-scraper
pip install -r requirements.txt
```

---

## ⚠️ IMPORTANT: Avoid Bot Detection

Before running the scraper, you MUST initialize a browser session.

### Step 1: Run session script

```bash
python save_session.py
```

### Step 2: Manually browse

* Open the browser that launches
* Visit a few career pages
* Scroll, click, behave like a real user for ~30–60 seconds

This helps:

* avoid bot detection
* reuse cookies/session
* prevent blocked requests

---

## ▶️ Run Scraper

```bash
python job_scraper.py
```

---

## 🧠 AI Setup (Ollama)

Install and run Ollama:

```bash
ollama run qwen2.5:3b
```

Recommended models:

* `qwen2.5:3b` (fast)
* `qwen2.5:7b` (better quality)
* `gemma4:e2b` (latest but heavy) RECOMMENDED  

---

## 📊 Output

The system generates multiple outputs:

* 📄 Raw jobs → Excel
* 🧹 Deduplicated and heuristic scored jobs → Excel
* 🤖 AI-ranked jobs → Excel (sorted by score)

---

## ➕ Adding a New Company

1. Add a new entry in `companies.py`
2. Choose strategy:

   * `"api"` → intercept JSON responses
   * `"dom"` → parse HTML using selectors
3. Configure:

   * selectors (DOM)
   * data paths (API)
   * pagination
   * search (optional)

---

## 🧠 Architecture Overview

```
Scrape → Normalize → Filter → Store → AI Score → Final Excel
```

---

## ⚡ Supported Patterns

* API interception (Uber, Databricks)
* JSON endpoints (Rippling, Cohesity)
* DOM scraping (Google, Stripe)
* Lazy loading / infinite scroll
* Pagination (click, numbered, incremental)

---

## 📝 Logging

Logs are stored in:

```
logs/run_YYYYMMDD_HHMMSS.log
```

Live logs are also shown in terminal.

---

## ⚠️ Disclaimer

This project is for **educational purposes only**.

Please:

* respect website terms of service
* avoid aggressive scraping
* use responsibly

---

## 👨‍💻 Author

Built by Saransh Mehra
