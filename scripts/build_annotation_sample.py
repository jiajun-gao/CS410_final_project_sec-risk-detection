"""Export ~20 diverse candidate examples from the real filing comparisons for
later human annotation. Human-label columns are left blank.

Usage:  python scripts/build_annotation_sample.py [--method tfidf] [--n 20]
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from riskdiff import config, export, ingest, pipeline  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--method", default="embeddings", choices=["embeddings", "tfidf"])
    ap.add_argument("--n", type=int, default=20)
    args = ap.parse_args()

    by_ticker = {}
    for rec in ingest.filing_records():
        by_ticker.setdefault(rec["ticker"], []).append(rec)

    flat_by_pair = {}
    for ticker, recs in by_ticker.items():
        recs.sort(key=lambda r: r["fiscal_period_end"])
        old, new = recs[-2]["filing_id"], recs[-1]["filing_id"]
        result = pipeline.compare_filings(old, new, method=args.method)
        flat_by_pair[f"{old}__{new}"] = export.flat_rows(result)
        print(f"{old} -> {new}: {result['counts']}")

    picked = export.sample_candidates(flat_by_pair, n=args.n)
    config.ANNOTATION_DIR.mkdir(exist_ok=True)
    out = config.ANNOTATION_DIR / "annotation_candidates.csv"
    out.write_text(export.to_csv(export.annotation_rows(picked), export.ANNOTATION_COLUMNS),
                   encoding="utf-8-sig")
    print(f"Wrote {len(picked)} candidates to {out} (human labels left blank).")
