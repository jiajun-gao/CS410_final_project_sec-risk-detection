"""Project configuration: company/filing scope, paths, and heuristic defaults.

All thresholds here are PRELIMINARY and have NOT been validated against
human annotations. They exist so the halfway prototype is transparent and
tunable, not because they are known to be correct.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"              # original filing HTML, as downloaded
EXTRACTED_DIR = DATA_DIR / "extracted"  # extracted Item 1A text + paragraphs
MANUAL_DIR = DATA_DIR / "manual"        # manually supplied Risk Factors text
CACHE_DIR = DATA_DIR / "cache"          # embedding cache
MANIFEST_PATH = DATA_DIR / "manifest.json"
ANNOTATION_DIR = ROOT / "annotation"

# SEC asks automated clients to identify themselves. We send a generic client
# name by default; set SEC_USER_AGENT to include your own contact details
# (e.g. "Your Name your@email") if EDGAR rejects the default.
SEC_USER_AGENT = os.environ.get(
    "SEC_USER_AGENT", "sec-risk-prototype/0.1 (academic course project)"
)

EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

# --- Scope -----------------------------------------------------------------
# Three technology companies, two consecutive annual 10-K filings each.
# Accession numbers were read from the EDGAR submissions API on 2026-11-15;
# these are the two most recent 10-Ks available for each company on that date.
# Fiscal period end and filing date are recorded separately because the three
# companies use different fiscal calendars.
COMPANIES = {
    "AAPL": {"name": "Apple Inc.", "cik": "0000320193"},
    "NVDA": {"name": "NVIDIA Corporation", "cik": "0001045810"},
    "INTC": {"name": "Intel Corporation", "cik": "0000050863"},
}

FILINGS = [
    # ticker, company's own fiscal-year label, fiscal period end, filing date, accession, primary doc
    ("AAPL", "FY2025", "2025-09-27", "2025-10-31", "0000320193-25-000079", "aapl-20250927.htm"),
    ("AAPL", "FY2026", "2026-09-26", "2026-11-03", "0000320193-26-000026", "aapl-20260926.htm"),
    ("NVDA", "FY2025", "2025-01-26", "2025-02-26", "0001045810-25-000023", "nvda-20250126.htm"),
    ("NVDA", "FY2026", "2026-01-25", "2026-02-25", "0001045810-26-000021", "nvda-20260125.htm"),
    ("INTC", "FY2024", "2024-12-28", "2025-01-31", "0000050863-25-000009", "intc-20241228.htm"),
    ("INTC", "FY2025", "2025-12-27", "2026-01-23", "0000050863-26-000011", "intc-20251227.htm"),
]

# --- Extraction sanity bounds ------------------------------------------------
MIN_SECTION_CHARS = 15_000   # a large-cap Risk Factors section shorter than this is suspicious
MAX_SECTION_FRACTION = 0.6   # section covering more than this share of the filing is suspicious

# --- Alignment defaults (preliminary, unvalidated) ---------------------------
DEFAULT_THRESHOLDS = {"embeddings": 0.60, "tfidf": 0.30}
AMBIGUITY_MARGIN = 0.05      # runner-up candidate within this similarity => ambiguous
UNCERTAIN_BAND = 0.10        # match within this distance above the threshold => uncertain

# --- Change heuristics defaults (preliminary, unvalidated) -------------------
MINOR_CHANGE_MAX = 0.15      # lexical change ratio below this => "Minor rewording"

# --- Review-priority weights (transparent, hand-set, unvalidated) ------------
PRIORITY_BASE = {
    "Potential addition": 0.70,
    "Potential deletion": 0.70,
    "Potential substantive revision": 0.40,
    "Uncertain match / needs review": 0.50,
    "Minor rewording": 0.05,
    "Unchanged": 0.0,
}
PRIORITY_CHANGE_WEIGHT = 0.40   # x lexical change ratio (matched pairs)
PRIORITY_LENGTH_WEIGHT = 0.20   # x min(1, words/150) for unmatched passages
PRIORITY_CUE_BONUS = 0.10       # per cue type (numbers, negation)
PRIORITY_AMBIGUOUS_BONUS = 0.05
