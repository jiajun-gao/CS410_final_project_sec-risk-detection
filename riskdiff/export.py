"""Export of comparison results and preparation of annotation material.

Nothing here creates ground truth: human-label columns are always left blank.
"""
from __future__ import annotations

import csv
import io
import json

from . import changes

RESULT_COLUMNS = [
    "rank", "company", "filing_pair", "label", "review_priority", "reason",
    "alignment_method", "threshold", "similarity", "lexical_change_ratio",
    "number_cue", "negation_cue", "ambiguous_match",
    "old_paragraph_id", "new_paragraph_id", "old_heading", "new_heading",
    "old_text", "new_text", "old_source_url", "new_source_url",
]

ANNOTATION_COLUMNS = [
    "example_id", "company", "filing_pair", "old_paragraph_id", "new_paragraph_id",
    "old_text", "new_text", "predicted_label",
    "annotator_1_label", "annotator_2_label", "reconciled_label",
    "risk_categories_optional", "notes",
]


def _heading(p: dict | None) -> str:
    if not p:
        return ""
    return p["heading"] or (p["text"] if p["kind"] == "heading" else "")


def flat_rows(result: dict) -> list[dict]:
    """Flatten a comparison result into export rows."""
    old_f, new_f = result["old_filing"], result["new_filing"]
    pair = f"{old_f['filing_id']}__{new_f['filing_id']}"
    out = []
    for r in result["rows"]:
        o, n = r["old"], r["new"]
        out.append({
            "rank": r["rank"],
            "company": new_f["ticker"],
            "filing_pair": pair,
            "label": r["label"],
            "review_priority": r["priority"],
            "reason": r["reason"],
            "alignment_method": result["params"]["method"],
            "threshold": result["params"]["threshold"],
            "similarity": r["similarity"] if r["similarity"] is not None else "",
            "lexical_change_ratio": round(r["change_ratio"], 4) if r["change_ratio"] is not None else "",
            "number_cue": r["number_cue"],
            "negation_cue": r["negation_cue"],
            "ambiguous_match": r["ambiguous"],
            "old_paragraph_id": o["id"] if o else "",
            "new_paragraph_id": n["id"] if n else "",
            "old_heading": _heading(o),
            "new_heading": _heading(n),
            "old_text": o["text"] if o else "",
            "new_text": n["text"] if n else "",
            "old_source_url": old_f["source_url"],
            "new_source_url": new_f["source_url"],
        })
    return out


def to_csv(rows: list[dict], columns: list[str]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def results_csv(result: dict) -> str:
    return to_csv(flat_rows(result), RESULT_COLUMNS)


def results_json(result: dict) -> str:
    return json.dumps({
        "old_filing": result["old_filing"], "new_filing": result["new_filing"],
        "params": result["params"], "counts": result["counts"],
        "disclaimer": "Preliminary heuristic flags for human review. Not validated; "
                      "not a measure of actual business risk.",
        "results": flat_rows(result),
    }, indent=2, ensure_ascii=False)


def annotation_rows(flat: list[dict]) -> list[dict]:
    """Annotation-template rows with every human-label column left blank."""
    return [{
        "example_id": f"{r['filing_pair']}#{r['old_paragraph_id'] or '-'}>{r['new_paragraph_id'] or '-'}",
        "company": r["company"], "filing_pair": r["filing_pair"],
        "old_paragraph_id": r["old_paragraph_id"], "new_paragraph_id": r["new_paragraph_id"],
        "old_text": r["old_text"], "new_text": r["new_text"],
        "predicted_label": r["label"],
        "annotator_1_label": "", "annotator_2_label": "", "reconciled_label": "",
        "risk_categories_optional": "", "notes": "",
    } for r in flat]


def sample_candidates(flat_by_pair: dict[str, list[dict]], n: int = 20) -> list[dict]:
    """Pick ~n diverse candidates for later human annotation.

    Deterministic round-robin over (label, filing pair): within each cell rows
    are taken alternately from the top and from the middle of the priority
    ranking so the sample is not only the 'easiest' high-priority cases.
    Passages under 8 words (mostly headings) are skipped.
    """
    cells: dict[tuple[str, str], list[dict]] = {}
    for pair, rows in flat_by_pair.items():
        for r in rows:
            words = len((r["new_text"] or r["old_text"]).split())
            if words >= 8:
                cells.setdefault((r["label"], pair), []).append(r)

    def interleave(rows):
        mid = len(rows) // 2
        order, lo, hi = [], 0, mid
        while lo < mid or hi < len(rows):
            if lo < mid:
                order.append(rows[lo]); lo += 1
            if hi < len(rows):
                order.append(rows[hi]); hi += 1
        return order

    queues = {k: interleave(v) for k, v in cells.items()}
    picked: list[dict] = []
    pairs = sorted(flat_by_pair)
    while len(picked) < n and any(queues.values()):
        for label in changes.LABELS:
            for offset in range(len(pairs)):
                # rotate the starting company per label so no company dominates
                pair = pairs[(offset + changes.LABELS.index(label) + len(picked)) % len(pairs)]
                q = queues.get((label, pair))
                if q:
                    picked.append(q.pop(0))
                    break
            if len(picked) >= n:
                break
    return picked
