"""Ingestion and metadata: download 10-K primary documents from SEC EDGAR
and maintain the data-source manifest (data/manifest.json)."""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone

import requests

from . import config


def filing_id(ticker: str, fiscal_year: str) -> str:
    return f"{ticker}_{fiscal_year}"


def filing_records() -> list[dict]:
    """Static metadata for the six in-scope filings."""
    records = []
    for ticker, fy, period_end, filed, accession, doc in config.FILINGS:
        company = config.COMPANIES[ticker]
        cik_int = str(int(company["cik"]))
        acc_nodash = accession.replace("-", "")
        base = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_nodash}"
        records.append({
            "filing_id": filing_id(ticker, fy),
            "ticker": ticker,
            "company": company["name"],
            "cik": company["cik"],
            "form": "10-K",
            "fiscal_year": fy,
            "fiscal_period_end": period_end,
            "filing_date": filed,
            "accession_number": accession,
            "source_url": f"{base}/{doc}",
            "index_url": f"{base}/{accession}-index.htm",
            "raw_path": f"data/raw/{filing_id(ticker, fy)}.htm",
        })
    return records


def load_manifest() -> dict:
    if config.MANIFEST_PATH.exists():
        return json.loads(config.MANIFEST_PATH.read_text(encoding="utf-8"))
    return {"filings": []}


def save_manifest(manifest: dict) -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def update_manifest_entry(fid: str, **fields) -> None:
    manifest = load_manifest()
    for rec in manifest["filings"]:
        if rec["filing_id"] == fid:
            rec.update(fields)
    save_manifest(manifest)


def fetch_all(force: bool = False, log=print) -> dict:
    """Download every in-scope filing not already on disk. Returns the manifest."""
    config.RAW_DIR.mkdir(parents=True, exist_ok=True)
    previous = {r["filing_id"]: r for r in load_manifest().get("filings", [])}
    out = []
    for rec in filing_records():
        rec = {**previous.get(rec["filing_id"], {}), **rec}
        path = config.ROOT / rec["raw_path"]
        if force or not path.exists():
            log(f"Downloading {rec['filing_id']} from {rec['source_url']}")
            resp = requests.get(
                rec["source_url"],
                headers={"User-Agent": config.SEC_USER_AGENT},
                timeout=60,
            )
            resp.raise_for_status()
            if b"Undeclared Automated Tool" in resp.content[:5000] or len(resp.content) < 100_000:
                raise RuntimeError(
                    "SEC.gov did not return the filing (it asks automated tools to declare a "
                    "contact). Set the SEC_USER_AGENT environment variable to "
                    "'Your Name your@email' and retry, or save the page from a browser to "
                    f"{rec['raw_path']}.")
            path.write_bytes(resp.content)
            rec["retrieved_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            time.sleep(0.5)  # stay well under SEC's 10 requests/second limit
        else:
            log(f"Already present: {rec['filing_id']}")
        data = path.read_bytes()
        rec["raw_bytes"] = len(data)
        rec["raw_sha256"] = hashlib.sha256(data).hexdigest()
        out.append(rec)
    manifest = {
        "description": "Data-source manifest for the halfway prototype. "
                       "Source: SEC EDGAR (public). Fiscal period end and filing "
                       "date are recorded separately.",
        "filings": out,
    }
    save_manifest(manifest)
    return manifest
