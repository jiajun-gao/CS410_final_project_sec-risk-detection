"""Paragraph preprocessing: segment section blocks into ordered paragraphs
with stable IDs, original text, normalized text, and heading context."""
from __future__ import annotations

import hashlib
import re
import unicodedata

from .extract import Block, is_heading

_WS = re.compile(r"\s+")
_TRANSLATE = str.maketrans({
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", "‑": "-", "\xa0": " ", "​": "",
})


def normalize(text: str) -> str:
    """Normalize for comparison only. Unicode/quote/dash/whitespace variants are
    unified; case, numbers, dates, punctuation, and negation are all retained."""
    text = unicodedata.normalize("NFKC", text).translate(_TRANSLATE)
    return _WS.sub(" ", text).strip()


def _is_formatting_artifact(text: str) -> bool:
    """Conservative: only drop blocks with no letters or digits at all
    (stray bullets, rules). Short passages are NOT dropped for being short."""
    return not any(ch.isalnum() for ch in text)


def segment(blocks: list[Block], filing_id: str) -> list[dict]:
    """Turn ordered section blocks into paragraph records.

    Headings are kept as their own units (kind='heading') because risk-factor
    headings are often full sentences whose wording changes matter. Each
    paragraph also records the nearest heading above it (`heading`) and the
    enclosing category heading (`section`) when two headings are stacked.
    """
    paragraphs: list[dict] = []
    section = heading = ""
    prev_was_heading = False
    for block in blocks:
        if _is_formatting_artifact(block.text):
            continue
        head = is_heading(block)
        if head:
            if prev_was_heading and heading:
                section = heading  # stacked headings: the earlier one is the category
            heading = block.text
        norm = normalize(block.text)
        paragraphs.append({
            "id": f"{filing_id}_p{len(paragraphs):04d}",
            "filing_id": filing_id,
            "order": len(paragraphs),
            "kind": "heading" if head else "body",
            "section": section if not head or section != block.text else "",
            "heading": "" if head else heading,
            "text": block.text,
            "norm": norm,
            "hash": hashlib.sha1(norm.encode("utf-8")).hexdigest()[:12],
            "n_words": len(norm.split()),
        })
        prev_was_heading = head
    return paragraphs
