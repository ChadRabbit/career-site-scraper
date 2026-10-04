"""
Project-wide tunables. Edit these instead of hunting through the code.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CONFIG_DIR = ROOT / "configs"  # onboarded companies, one JSON file each (committed)
CAPTURE_DIR = ROOT / "captures"  # raw network traffic + screenshots (gitignored)
RUNS_DIR = ROOT / "runs"  # Excel outputs, one folder per run (gitignored)
LOG_DIR = ROOT / "logs"
STATE_DIR = ROOT / "state"  # per-company health between runs (gitignored)
USER_DATA_DIR = ROOT / "user_data"  # persistent browser profile (gitignored)

# ── Browser ──────────────────────────────────────────────────────────────
BROWSER_ENGINE = "playwright"  # "playwright" | "patchright" (pip install patchright)
BROWSER_CHANNEL = None  # e.g. "chrome" to drive your installed Google Chrome
HEADLESS = False
HEADLESS_VIEWPORT = {"width": 1440, "height": 900}

# ── Politeness: one company at a time, human-ish pacing ──────────────────
HUMAN_SPEED = 1.0  # multiplier for every human-like pause; 0 = no pauses (tests)
DELAY_BETWEEN_COMPANIES_S = (20, 45)
DELAY_BETWEEN_PAGES_S = (4, 10)
DEFAULT_MAX_PAGES = 5
NAVIGATION_TIMEOUT_MS = 45_000
POPUP_CHECK_INTERVAL_S = 5  # how often recorded popups (cookie banners, ...) are looked for and closed

# ── Network capture ──────────────────────────────────────────────────────
CAPTURE_MAX_BODY_BYTES = 15 * 1024 * 1024
CAPTURE_SKIP_BODY_TYPES = {"image", "media", "font"}  # metadata only for these

# ── Heuristic scoring (pipeline/scoring.py) ──────────────────────────────
# Whole-word, case-insensitive regexes → points.
TITLE_KEYWORDS = {
    r"software": 5,
    r"engineer(ing)?": 5,
    r"developer": 4,
    r"sde|swe": 4,
    r"back[- ]?end": 3,
    r"front[- ]?end": 3,
    r"full[- ]?stack": 3,
    r"intern(ship)?": 2,
    r"senior|sr\.?": -10,
    r"staff|principal|director|manager|head": -8,
}
LOCATION_KEYWORDS = {
    r"india|bengaluru|bangalore|hyderabad|pune|gurugram|gurgaon|noida|mumbai|chennai|delhi": 3,
    r"remote": 2,
}
MIN_HEURISTIC_SCORE = 5  # jobs below this are dropped from the ranked sheet

# ── Local LLM ranking (ai/evaluator.py) ──────────────────────────────────
OLLAMA_URL = "http://localhost:11434"
AI_MODEL = "qwen2.5:7b"
AI_CONCURRENCY = 2  # parallel requests to the same model (set OLLAMA_NUM_PARALLEL to match)
AI_TIMEOUT_S = 90

CANDIDATE_PROFILE = """\
- Software engineer looking for Software Engineering roles (Backend / Fullstack / AI)
- Prefers locations in India or remote
- GOOD roles: Software Engineer, SDE, Backend, Fullstack, AI/ML Engineer
- BAD roles: Manager, Sales, HR, Operations, non-technical roles
"""
