"""Download the six in-scope 10-K filings and extract their Risk Factors sections.

Usage:  python scripts/fetch_filings.py [--force]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from riskdiff import ingest, pipeline  # noqa: E402

if __name__ == "__main__":
    manifest = ingest.fetch_all(force="--force" in sys.argv)
    for rec in manifest["filings"]:
        result = pipeline.extract_and_store(rec["filing_id"])
        status = "OK" if not result["warnings"] else "WARN"
        print(f"[{status}] {rec['filing_id']}: {result['section_chars']:,} chars, "
              f"{result['n_paragraphs']} paragraphs, method={result['method']}")
        for w in result["warnings"]:
            print(f"       - {w}")
