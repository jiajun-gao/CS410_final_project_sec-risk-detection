"""Pipeline glue: filing -> extracted section -> paragraphs -> comparison."""
from __future__ import annotations

import json

from . import align, changes, config, extract, ingest, preprocess


def _paths(fid: str) -> dict:
    return {
        "raw": config.RAW_DIR / f"{fid}.htm",
        "manual": config.MANUAL_DIR / f"{fid}.txt",
        "text": config.EXTRACTED_DIR / f"{fid}.txt",
        "paragraphs": config.EXTRACTED_DIR / f"{fid}.paragraphs.json",
        "meta": config.EXTRACTED_DIR / f"{fid}.extraction.json",
    }


def extract_and_store(fid: str) -> dict:
    """Extract Risk Factors for one filing and write text, paragraphs, and
    extraction diagnostics to data/extracted/. Manually supplied text in
    data/manual/<filing_id>.txt takes precedence over automatic extraction."""
    p = _paths(fid)
    config.EXTRACTED_DIR.mkdir(parents=True, exist_ok=True)
    if p["manual"].exists():
        blocks = extract.text_to_blocks(p["manual"].read_text(encoding="utf-8"))
        chars = sum(len(b.text) for b in blocks)
        result = {"status": "manual", "method": "manual", "warnings": [],
                  "notes": ["Risk Factors text was supplied manually; automatic extraction was bypassed."],
                  "blocks": blocks, "section_chars": chars, "doc_chars": None,
                  "n_start_candidates": 0, "start_marker": "(manual)", "end_marker": "(manual)"}
    elif p["raw"].exists():
        result = extract.extract_risk_factors(extract.html_to_blocks(p["raw"].read_bytes()))
    else:
        result = {"status": "missing", "method": "none", "notes": [], "blocks": [],
                  "warnings": [f"Source filing not found at data/raw/{fid}.htm. "
                               f"Run `python scripts/fetch_filings.py`."],
                  "section_chars": 0, "doc_chars": None, "n_start_candidates": 0,
                  "start_marker": "", "end_marker": ""}

    blocks = result.pop("blocks")
    paragraphs = preprocess.segment(blocks, fid)
    result["n_paragraphs"] = len(paragraphs)
    result["n_headings"] = sum(p_["kind"] == "heading" for p_ in paragraphs)
    result["start_preview"] = [b.text[:300] for b in blocks[:4]]
    result["end_preview"] = [b.text[:300] for b in blocks[-3:]]
    result["filing_id"] = fid

    p["text"].write_text(extract.blocks_to_text(blocks), encoding="utf-8")
    p["paragraphs"].write_text(json.dumps(paragraphs, ensure_ascii=False, indent=1), encoding="utf-8")
    p["meta"].write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def load_extraction(fid: str, refresh: bool = False) -> tuple[dict, list[dict]]:
    """Return (extraction diagnostics, paragraphs), extracting on first use."""
    p = _paths(fid)
    if refresh or not (p["meta"].exists() and p["paragraphs"].exists()):
        extract_and_store(fid)
    meta = json.loads(p["meta"].read_text(encoding="utf-8"))
    paragraphs = json.loads(p["paragraphs"].read_text(encoding="utf-8"))
    return meta, paragraphs


def save_manual_text(fid: str, text: str) -> dict:
    config.MANUAL_DIR.mkdir(parents=True, exist_ok=True)
    _paths(fid)["manual"].write_text(text, encoding="utf-8")
    return extract_and_store(fid)


def clear_manual_text(fid: str) -> dict:
    path = _paths(fid)["manual"]
    if path.exists():
        path.unlink()
    return extract_and_store(fid)


def filing_meta(fid: str) -> dict:
    for rec in ingest.filing_records():
        if rec["filing_id"] == fid:
            return rec
    raise KeyError(fid)


def compare_paragraphs(old: list[dict], new: list[dict], method: str = "embeddings",
                       threshold: float | None = None, minor_max: float = config.MINOR_CHANGE_MAX,
                       escalate_cues: bool = True, old_id: str | None = None,
                       new_id: str | None = None) -> dict:
    """Align two paragraph lists and flag changes. Raises align.ModelUnavailable
    if the embedding model cannot be loaded."""
    if threshold is None:
        threshold = config.DEFAULT_THRESHOLDS[method]
    if method == "embeddings":
        sim = align.embedding_similarity(old, new, old_id, new_id)
    elif method == "tfidf":
        sim = align.tfidf_similarity(old, new)
    else:
        raise ValueError(f"Unknown alignment method: {method}")
    alignment = align.match_one_to_one(sim, old, new, threshold)
    rows = changes.build_results(old, new, alignment, threshold,
                                 minor_max=minor_max, escalate_cues=escalate_cues)
    counts = {label: 0 for label in changes.LABELS}
    for r in rows:
        counts[r["label"]] += 1
    return {"rows": rows, "counts": counts,
            "params": {"method": method, "threshold": threshold, "minor_max": minor_max,
                       "escalate_cues": escalate_cues,
                       "ambiguity_margin": config.AMBIGUITY_MARGIN,
                       "uncertain_band": config.UNCERTAIN_BAND,
                       "embedding_model": config.EMBEDDING_MODEL if method == "embeddings" else None}}


def compare_filings(old_fid: str, new_fid: str, **kwargs) -> dict:
    _, old = load_extraction(old_fid)
    _, new = load_extraction(new_fid)
    result = compare_paragraphs(old, new, old_id=old_fid, new_id=new_fid, **kwargs)
    result["old_filing"], result["new_filing"] = filing_meta(old_fid), filing_meta(new_fid)
    return result
