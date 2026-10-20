"""Central settings. Everything here is company-neutral and overridable by environment variables."""
from __future__ import annotations
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_dotenv(path: Path | str) -> int:
    """Tiny .env reader (no dependency). Existing environment variables win. Returns how many were set."""
    p = Path(path)
    if not p.exists():
        return 0
    n = 0
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.split(" #")[0].strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v
            n += 1
    return n


load_dotenv(ROOT / ".env")
CACHE_DIR = Path(os.getenv("RESCOPE_CACHE_DIR", ROOT / "cache"))
DB_PATH = Path(os.getenv("RESCOPE_DB_PATH", ROOT / "data" / "rescope.db"))
INBOX_DIR = ROOT / "data" / "inbox"
CONTACT = os.getenv("RESCOPE_CONTACT", "contact-not-set@example.com")
USER_AGENT = f"ReScopeResearchBot/0.1 (student hackathon project; contact: {CONTACT})"
MIN_INTERVAL_SEC = float(os.getenv("RESCOPE_MIN_INTERVAL_SEC", "1.5"))
HTTP_TIMEOUT = 30
MAX_RETRIES = 3
MAX_HOST_FAILURES = 3          # consecutive refusals/timeouts before a host is skipped for the rest of the run
RESPECT_ROBOTS = True
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
DATA_GOV_IN_API_KEY = os.getenv("DATA_GOV_IN_API_KEY", "")

# Reliability tiers (starting values from the plan; tune on the test set)
TIER_WEIGHTS = {1: 1.00, 2: 0.85, 3: 0.70, 4: 0.55, 5: 0.35}

# URLs below are STARTING POINTS. Verify each against the site's current terms and structure
# before relying on it. They are only used by the live collectors, never by the offline tests.
URLS = {
    "exchange_equity_list_csv": "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv",
    "index_constituents_csv_template": "https://nsearchives.nseindia.com/content/indices/{file}.csv",
    "gdelt_doc_api": "https://api.gdeltproject.org/api/v2/doc/doc",
    "wayback_available": "https://archive.org/wayback/available",
    "tavily_search": "https://api.tavily.com/search",
    "data_gov_in_resource": "https://api.data.gov.in/resource/{resource_id}",
    "world_bank_indicator": "https://api.worldbank.org/v2/country/{country}/indicator/{indicator}",
}

# hosts that ask for slower access (seconds between requests)
HOST_MIN_INTERVAL = {"api.gdeltproject.org": 6.0}

DAYS_IN_QUARTER = 91.25
DAYS_IN_YEAR = 365.0
MIN_QUARTERS_TARGET = 8
