import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "logs"
DATA_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)

IIMJOBS_EMAIL = os.getenv("IIMJOBS_EMAIL", "").strip()
IIMJOBS_PASSWORD = os.getenv("IIMJOBS_PASSWORD", "").strip()
RESUME_PATH = os.getenv("RESUME_PATH", "").strip()
HEADLESS = os.getenv("HEADLESS", "false").lower() == "true"
MAX_JOBS_PER_KEYWORD = int(os.getenv("MAX_JOBS_PER_KEYWORD", "20"))
PORT = int(os.getenv("PORT", "7000"))

APPLIED_JOBS_FILE = DATA_DIR / "applied_jobs.json"
KEYWORDS_FILE = DATA_DIR / "search_keywords.json"
LOG_FILE = LOG_DIR / "bot.log"
