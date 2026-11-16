"""Section extraction: locate Item 1A (Risk Factors) in a 10-K HTML document.

Strategy
--------
1. Flatten the HTML into an ordered list of text "blocks" (one per leaf
   block element or table row), recording whether each block is fully
   bold/italic/underlined (used later for heading detection).
2. Find every block that looks like an "Item 1A" heading and, for each, the
   next block that looks like the start of a later item (1B / 1C / 2).
   The table-of-contents entry yields a near-empty span, so the LONGEST
   candidate span is taken as the real section.
3. If no "Item 1A" heading exists (some filers use a custom layout), fall
   back to a standalone "Risk Factors" heading bounded by the next known
   10-K section title. This fallback is always reported as uncertain.
4. Sanity-check the result and emit warnings instead of failing silently.
"""
from __future__ import annotations

import re
import warnings
from collections import Counter
from dataclasses import asdict, dataclass, replace

from bs4 import BeautifulSoup, NavigableString, Tag, XMLParsedAsHTMLWarning

from . import config

BLOCK_TAGS = {"div", "p", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6",
              "table", "ul", "ol", "td", "th", "tbody", "thead", "blockquote",
              "section", "article", "body", "center"}

_WS = re.compile(r"\s+")
_WEIGHT = re.compile(r"font-weight\s*:\s*(\w+)", re.I)
_SIZE = re.compile(r"font-size\s*:\s*([\d.]+)\s*pt", re.I)
_BULLET = re.compile(r"^([•▪●◦■])(?=\S)")
_ITALIC = re.compile(r"font-style\s*:\s*italic", re.I)
_UNDERLINE = re.compile(r"text-decoration[^;]*:\s*[^;]*underline", re.I)
_HIDDEN = re.compile(r"display\s*:\s*none", re.I)

# "Item 1A", "ITEM 1A.", "Item 1A. Risk Factors", "Item 1A — Risk Factors"
ITEM_1A_RE = re.compile(r"^\W*item\s*1\s*a\b[\s.:\-–—|]*(risk\s+factors)?[\W\d]*$", re.I)
# first heading that can follow Item 1A
ITEM_END_RE = re.compile(r"^\W*item\s*(1\s*b|1\s*c|2)\b", re.I)
RISK_HEADING_RE = re.compile(r"^\W*risk\s+factors\W*$", re.I)

# Section titles that can follow Risk Factors in filings with a custom layout.
FALLBACK_END_TITLES = [
    "unresolved staff comments", "cybersecurity", "properties", "legal proceedings",
    "mine safety disclosures", "controls and procedures", "sales and marketing",
    "quantitative and qualitative disclosures about market risk",
    "management's discussion and analysis",
    "market for registrant's common equity", "market for our common stock",
    "issuer purchases of equity securities", "financial statements and supplemental details",
    "financial statements and supplementary data", "exhibits",
    "form 10-k cross-reference index", "supplemental details", "other key information",
    "information about our executive officers", "availability of company information",
    "non-gaap financial measures", "liquidity and capital resources",
]

PAGE_ARTIFACT_RES = [
    re.compile(r"^\d{1,4}$"),                                   # bare page number
    re.compile(r"^page\s+\d+(\s+of\s+\d+)?$", re.I),
    re.compile(r"^table\s+of\s+contents$", re.I),
    re.compile(r"^.{0,60}\|\s*\d{4}\s+form\s+10-k\s*\|\s*\d+$", re.I),  # "Apple Inc. | 2025 Form 10-K | 5"
    re.compile(r"^.{0,60}\d{4}\s+form\s+10-k\s+\d{1,4}$", re.I),
    re.compile(r"^\d{1,4}\s+.{0,60}form\s+10-k$", re.I),
]


@dataclass
class Block:
    text: str
    bold: bool = False      # (nearly) all text is bold
    emph: bool = False      # (nearly) all text is italic or underlined
    size: float = 0.0       # dominant font size in pt (0 = unknown)
    large: bool = False     # font clearly larger than the document's body text
    styled: bool = True     # False when no style information exists (plain text)


def _clean(text: str) -> str:
    return _WS.sub(" ", text.replace("\xa0", " ")).strip()


def _style_of(el: Tag | None, memo: dict) -> tuple[bool, bool, float]:
    """Inherited (bold, emphasised, font-size-pt) of an element, from inline
    styles and b/strong/i/em/u tags. An explicit value overrides the parent's."""
    if el is None or not isinstance(el, Tag):
        return False, False, 0.0
    key = id(el)
    if key in memo:
        return memo[key]
    bold, emph, size = _style_of(el.parent, memo)
    style = el.get("style", "") or ""
    if el.name in ("b", "strong"):
        bold = True
    m = _WEIGHT.search(style)
    if m:
        bold = m.group(1).lower() in ("bold", "bolder", "600", "700", "800", "900")
    if el.name in ("i", "em", "u") or _ITALIC.search(style) or _UNDERLINE.search(style):
        emph = True
    m = _SIZE.search(style)
    if m:
        size = float(m.group(1))
    memo[key] = (bold, emph, size)
    return memo[key]


def _emit(el, blocks: list[Block], memo: dict) -> None:
    if isinstance(el, NavigableString):
        text = _clean(str(el))
        if text:
            blocks.append(Block(text))
        return
    if el.name == "tr":
        cells = [_clean(c.get_text("")) for c in el.find_all(["td", "th"])]
        text = _clean(" ".join(c for c in cells if c))
    else:
        text = _clean(el.get_text(""))
    text = _BULLET.sub(r"\1 ", text)
    if not text:
        return
    total = bold_chars = emph_chars = 0
    sizes: Counter = Counter()
    for s in el.find_all(string=True):
        n = len(s.strip())
        if not n:
            continue
        b, e, size = _style_of(s.parent, memo)
        total += n
        bold_chars += n if b else 0
        emph_chars += n if e else 0
        sizes[size] += n
    blocks.append(Block(text,
                        bold=total > 0 and bold_chars / total >= 0.9,
                        emph=total > 0 and emph_chars / total >= 0.9,
                        size=sizes.most_common(1)[0][0] if sizes else 0.0))


def _walk(el: Tag, blocks: list[Block], memo: dict) -> None:
    if el.name == "tr":
        _emit(el, blocks, memo)
        return
    has_block_child = el.find(lambda t: isinstance(t, Tag) and t.name in BLOCK_TAGS) is not None
    if not has_block_child:
        _emit(el, blocks, memo)
        return
    for child in el.children:
        if isinstance(child, Tag):
            _walk(child, blocks, memo)
        elif isinstance(child, NavigableString) and type(child) is NavigableString:
            _emit(child, blocks, memo)


def html_to_blocks(html: str | bytes) -> list[Block]:
    """Flatten filing HTML into ordered text blocks."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", XMLParsedAsHTMLWarning)  # iXBRL is XHTML; fine as HTML
        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception:
            soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "head", "title", "ix:header"]):
        tag.decompose()
    for tag in soup.find_all(style=_HIDDEN):
        tag.decompose()
    for br in soup.find_all("br"):
        br.replace_with(" ")
    blocks: list[Block] = []
    _walk(soup.body or soup, blocks, {})
    # Body font size = the size carrying the most text. Some filers (e.g. Intel)
    # mark headings only with a larger font, not with bold.
    by_size: Counter = Counter()
    for b in blocks:
        if b.size:
            by_size[b.size] += len(b.text)
    if by_size:
        body = by_size.most_common(1)[0][0]
        for b in blocks:
            b.large = b.size >= body + 1.5
    return blocks


def text_to_blocks(text: str) -> list[Block]:
    """Blocks from manually supplied plain text (no style information)."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    parts = re.split(r"\n\s*\n", text) if re.search(r"\n\s*\n", text) else text.split("\n")
    return [Block(_clean(p), styled=False) for p in parts if _clean(p)]


def is_page_artifact(text: str) -> bool:
    return any(rx.match(text) for rx in PAGE_ARTIFACT_RES)


def is_heading(block: Block) -> bool:
    """Heading heuristic: short block that is fully bold/italic/underlined or
    set in a larger font than body text; or, for
    unstyled text, a short line without sentence-ending punctuation."""
    words = len(block.text.split())
    if block.styled:
        return (block.bold or block.emph or block.large) and words <= 70
    return words <= 14 and not block.text.rstrip().endswith((".", ";", ",", ":"))


def _is_fallback_end(block: Block) -> bool:
    t = block.text.lower().replace("’", "'").strip(" .:")
    if len(t) > 90:
        return False
    return any(t == title or t.startswith(title) for title in FALLBACK_END_TITLES)


def _best_span(blocks, starts, is_end):
    """For each start, span to the next end marker; return the longest span."""
    best = None
    for s in starts:
        end, found = len(blocks), False
        for j in range(s + 1, len(blocks)):
            if is_end(blocks[j]):
                end, found = j, True
                break
        chars = sum(len(b.text) for b in blocks[s + 1:end])
        if best is None or chars > best["chars"]:
            best = {"start": s, "end": end, "end_found": found, "chars": chars}
    return best


def extract_risk_factors(blocks: list[Block]) -> dict:
    """Locate the Risk Factors section in a flattened document.

    Returns a dict with: status ('ok' | 'uncertain' | 'failed'), method,
    warnings, notes, blocks (section blocks, artifacts removed), and
    boundary diagnostics for human verification.
    """
    warnings: list[str] = []
    notes: list[str] = []
    doc_chars = sum(len(b.text) for b in blocks) or 1

    starts = [i for i, b in enumerate(blocks) if len(b.text) < 120 and ITEM_1A_RE.match(b.text)]
    method = "item_1a_heading"
    span = _best_span(blocks, starts, lambda b: len(b.text) < 200 and bool(ITEM_END_RE.match(b.text))) if starts else None

    if span is None or span["chars"] < 2000:
        fb_starts = [i for i, b in enumerate(blocks) if RISK_HEADING_RE.match(b.text)]
        fb = _best_span(blocks, fb_starts, _is_fallback_end) if fb_starts else None
        if fb and (span is None or fb["chars"] > span["chars"]):
            span, starts, method = fb, fb_starts, "risk_factors_heading_fallback"
            warnings.append(
                "No usable 'Item 1A' heading was found. The section was located from a "
                "standalone 'Risk Factors' heading and the next recognised section title; "
                "verify the start and end previews before relying on this comparison.")

    if span is None:
        return {"status": "failed", "method": "none", "notes": notes, "blocks": [],
                "warnings": ["Could not find an 'Item 1A' or 'Risk Factors' heading. "
                             "Supply the Risk Factors text manually."],
                "section_chars": 0, "doc_chars": doc_chars, "n_start_candidates": 0,
                "start_marker": "", "end_marker": ""}

    if len(starts) > 1:
        notes.append(f"{len(starts)} candidate section headings found (e.g. a table-of-contents "
                     f"entry); the one followed by the longest body was selected.")
    if not span["end_found"]:
        warnings.append("No end-of-section heading (Item 1B / 1C / 2) was found after the "
                        "start; the section may run past the true end of Risk Factors.")

    raw_section = blocks[span["start"] + 1:span["end"]]

    # Page artifacts: pattern-based, plus short lines repeated across the whole
    # document (running headers/footers). Conservative: only short blocks.
    def stem(text: str) -> str:   # "Risk Factors 51" -> "Risk Factors"
        return re.sub(r"^\d{1,4}\s+|\s+\d{1,4}$", "", text)

    doc_counts = Counter(stem(b.text) for b in blocks if len(b.text) <= 80)
    section, removed, merged = [], 0, 0
    for b in raw_section:
        repeated = (len(b.text) <= 80 and doc_counts[stem(b.text)] >= 5
                    and not re.search(r"[.;:,]$", b.text))
        if is_page_artifact(b.text) or repeated:
            removed += 1
            continue
        prev = section[-1] if section else None
        # Page-break repair: a block starting in lower case right after a block
        # with no closing punctuation is the continuation of the same paragraph.
        if (prev is not None and b.text[:1].islower()
                and (prev.bold, prev.emph, prev.large) == (b.bold, b.emph, b.large) and not re.search(r"[.!?:;][\"')\u201d\u2019]*$", prev.text)):
            section[-1] = replace(prev, text=prev.text + " " + b.text)
            merged += 1
            continue
        section.append(b)
    if removed:
        notes.append(f"{removed} page artifacts (page numbers, running headers) removed.")
    if merged:
        notes.append(f"{merged} paragraphs that were split across a page break were rejoined.")

    chars = sum(len(b.text) for b in section)
    if chars < config.MIN_SECTION_CHARS:
        warnings.append(f"Extracted section is short ({chars:,} characters); it may be "
                        f"incomplete or a table-of-contents fragment.")
    if chars / doc_chars > config.MAX_SECTION_FRACTION:
        warnings.append(f"Extracted section covers {chars / doc_chars:.0%} of the filing; "
                        f"the end boundary is probably wrong.")
    n_head = sum(is_heading(b) for b in section)
    if section and n_head < 3:
        warnings.append("Very few risk headings were detected; heading context may be missing.")

    return {
        "status": "uncertain" if warnings else "ok",
        "method": method,
        "warnings": warnings,
        "notes": notes,
        "blocks": section,
        "section_chars": chars,
        "doc_chars": doc_chars,
        "n_start_candidates": len(starts),
        "start_marker": blocks[span["start"]].text,
        "end_marker": blocks[span["end"]].text[:200] if span["end"] < len(blocks) else "(end of document)",
    }


def blocks_to_text(blocks: list[Block]) -> str:
    return "\n\n".join(b.text for b in blocks)


def block_dicts(blocks: list[Block]) -> list[dict]:
    return [asdict(b) for b in blocks]
