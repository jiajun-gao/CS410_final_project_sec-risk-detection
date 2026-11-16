"""Focused checks on SYNTHETIC fixtures (not real filing text).

Run:  python -m pytest -q
"""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from riskdiff import align, changes, export, extract, pipeline, preprocess  # noqa: E402

FILLER = " ".join(["Our business could be harmed by many factors outside our control."] * 60)

SYNTHETIC_10K = f"""
<html><body>
<div><span style="font-weight:700">TABLE OF CONTENTS</span></div>
<table>
 <tr><td>Item 1.</td><td>Business</td><td>1</td></tr>
 <tr><td>Item 1A.</td><td>Risk Factors</td><td>5</td></tr>
 <tr><td>Item 1B.</td><td>Unresolved Staff Comments</td><td>17</td></tr>
 <tr><td>Item 2.</td><td>Properties</td><td>18</td></tr>
</table>
<div><span style="font-weight:700">Item 1. Business</span></div>
<div>We make widgets. See "Item 1A. Risk Factors" below for a discussion of risks that affect us.</div>
<div><span style="font-weight:700">Item 1A.&#160;&#160;&#160;Risk Factors</span></div>
<div>The following risks could materially affect the business.</div>
<div><span style="font-weight:700;font-style:italic">Supply Chain Risks</span></div>
<div><span style="font-weight:700">We depend on a limited number of suppliers.</span></div>
<div>A disruption at <span>any single</span> supplier could delay shipments. {FILLER}</div>
<div>Synthetic Corp. | 2025 Form 10-K | 6</div>
<div><span style="font-weight:700">Cybersecurity incidents could harm us.</span></div>
<div>We have not experienced a material breach. {FILLER}</div>
<div>7</div>
<div>{FILLER} {FILLER} {FILLER}</div>
<div><span style="font-weight:700">Item 1B.&#160;&#160;&#160;Unresolved Staff Comments</span></div>
<div>None.</div>
<div><span style="font-weight:700">Item 2. Properties</span></div>
<div>We lease an office.</div>
<div>{FILLER} {FILLER} {FILLER}</div>
<div>{FILLER} {FILLER} {FILLER}</div>
</body></html>
"""


def paras(texts, fid):
    return preprocess.segment([extract.Block(t, styled=False) for t in texts], fid)


def compare(old_texts, new_texts, **kw):
    kw.setdefault("method", "tfidf")
    return pipeline.compare_paragraphs(paras(old_texts, "OLD"), paras(new_texts, "NEW"), **kw)


def by_label(result, label):
    return [r for r in result["rows"] if r["label"] == label]


# --- extraction -------------------------------------------------------------

def test_extraction_skips_table_of_contents_entry():
    res = extract.extract_risk_factors(extract.html_to_blocks(SYNTHETIC_10K))
    texts = [b.text for b in res["blocks"]]
    assert res["method"] == "item_1a_heading"
    assert res["n_start_candidates"] == 2           # TOC row + real heading
    assert texts[0] == "The following risks could materially affect the business."
    assert not any("Unresolved Staff Comments" in t for t in texts)   # not the TOC span
    assert not any("We lease an office" in t for t in texts)          # stops at Item 1B
    assert res["status"] == "ok", res["warnings"]


def test_extraction_removes_page_artifacts_and_keeps_headings():
    res = extract.extract_risk_factors(extract.html_to_blocks(SYNTHETIC_10K))
    texts = [b.text for b in res["blocks"]]
    assert "7" not in texts
    assert not any("Form 10-K | 6" in t for t in texts)
    ps = preprocess.segment(res["blocks"], "SYN")
    body = next(p for p in ps if p["text"].startswith("A disruption at any single supplier"))
    assert body["heading"] == "We depend on a limited number of suppliers."
    assert body["section"] == "Supply Chain Risks"


def test_extraction_warns_when_section_is_missing_or_short():
    missing = extract.extract_risk_factors(extract.html_to_blocks("<html><body><div>Hello</div></body></html>"))
    assert missing["status"] == "failed" and missing["warnings"]
    short = extract.extract_risk_factors(extract.html_to_blocks(
        "<html><body><div>Item 1A. Risk Factors</div><div>" + "Short section. " * 200 +
        "</div><div>Item 1B. Unresolved Staff Comments</div></body></html>"))
    assert short["status"] == "uncertain"
    assert any("short" in w for w in short["warnings"])


# --- preprocessing ----------------------------------------------------------

def test_normalization_keeps_numbers_punctuation_and_negation():
    norm = preprocess.normalize("We  do not expect\n a 25% decline — in “fiscal 2026”.")
    assert norm == 'We do not expect a 25% decline - in "fiscal 2026".'
    ps = paras(["Short.", "•", "No."], "X")
    assert [p["text"] for p in ps] == ["Short.", "No."]     # short text kept, bare bullet dropped
    assert [p["id"] for p in ps] == ["X_p0000", "X_p0001"]


# --- change flags -----------------------------------------------------------

A = ("We rely on a single foundry in Taiwan to manufacture substantially all of our advanced "
     "processors, and any disruption to its operations could delay our product shipments.")
B = ("Cyberattacks, ransomware, and other security incidents could compromise our confidential "
     "information, disrupt our internal systems, and damage our reputation with customers.")
C = ("Changes in tax law across the many jurisdictions in which we operate could increase our "
     "effective tax rate and reduce our reported earnings in future periods.")


def test_unchanged_passages():
    res = compare([A, B, C], [A, B, C])
    assert res["counts"][changes.UNCHANGED] == 3
    assert all(r["priority"] == 0 for r in res["rows"])


def test_whitespace_and_quote_variants_are_unchanged():
    res = compare([A.replace(" ", "  ")], [A])
    assert res["counts"][changes.UNCHANGED] == 1


def test_minor_rewording():
    res = compare([A, B, C], [A.replace("could delay", "may delay"), B, C])
    assert res["counts"][changes.MINOR] == 1 and res["counts"][changes.UNCHANGED] == 2


def test_substantially_reworded_but_related_passage():
    new_a = ("We rely on a single foundry in Taiwan to manufacture substantially all of our advanced "
             "processors. Geopolitical tension, natural disasters, or capacity constraints affecting "
             "that foundry could delay our product shipments, raise costs, and reduce revenue.")
    res = compare([A, B, C], [new_a, B, C])
    row = by_label(res, changes.SUBSTANTIVE)
    assert len(row) == 1 and row[0]["old"]["text"] == A
    assert row[0]["change_ratio"] >= 0.15 and "tokens differ" in row[0]["reason"]


def test_numeric_change_is_surfaced_as_review_cue():
    old = "Our largest customer accounted for 13% of total revenue in fiscal 2025, and losing it would hurt results."
    new = "Our largest customer accounted for 22% of total revenue in fiscal 2025, and losing it would hurt results."
    res = compare([old, B], [new, B])
    row = next(r for r in res["rows"] if r["label"] != changes.UNCHANGED)
    assert "13%" in row["number_cue"] and "22%" in row["number_cue"]
    assert row["label"] == changes.SUBSTANTIVE and "review cue" in row["reason"].lower()
    # with escalation off the same small edit stays a minor rewording, cue still shown
    row2 = next(r for r in compare([old, B], [new, B], escalate_cues=False)["rows"]
                if r["label"] != changes.UNCHANGED)
    assert row2["label"] == changes.MINOR and row2["number_cue"]


def test_negation_change_is_surfaced_despite_high_similarity():
    old = "We have experienced material cybersecurity incidents in the past, and we expect attacks to continue in the future."
    new = "We have not experienced material cybersecurity incidents in the past, and we expect attacks to continue in the future."
    res = compare([old, C], [new, C])
    row = next(r for r in res["rows"] if r["label"] != changes.UNCHANGED)
    assert row["similarity"] > 0.8                      # very similar...
    assert "'not'" in row["negation_cue"]               # ...but the negation is flagged
    assert row["label"] == changes.SUBSTANTIVE


def test_potential_additions_and_deletions():
    res = compare([A, B], [A, C])
    add, dele = by_label(res, changes.ADDITION), by_label(res, changes.DELETION)
    assert len(add) == 1 and add[0]["new"]["text"] == C and add[0]["old"] is None
    assert len(dele) == 1 and dele[0]["old"]["text"] == B and dele[0]["new"] is None
    assert res["rows"][0]["label"] in (changes.ADDITION, changes.DELETION)   # ranked above unchanged
    assert [r["rank"] for r in res["rows"]] == list(range(1, len(res["rows"]) + 1))


# --- alignment ---------------------------------------------------------------

def test_no_duplicate_one_to_one_assignments():
    # two old paragraphs both prefer new paragraph 0
    sim = np.array([[0.90, 0.20, 0.10],
                    [0.88, 0.30, 0.10],
                    [0.10, 0.10, 0.95]])
    old, new = paras(["o0 a", "o1 b", "o2 c"], "OLD"), paras(["n0 d", "n1 e", "n2 f"], "NEW")
    out = align.match_one_to_one(sim, old, new, threshold=0.5)
    pairs = {(m["old_idx"], m["new_idx"]) for m in out["matches"]}
    assert pairs == {(0, 0), (2, 2)}
    assert len({m["new_idx"] for m in out["matches"]}) == len(out["matches"])
    assert len({m["old_idx"] for m in out["matches"]}) == len(out["matches"])
    assert [u["old_idx"] for u in out["unmatched_old"]] == [1]
    assert [u["new_idx"] for u in out["unmatched_new"]] == [1]
    # the contested match is flagged ambiguous, the clean one is not
    flags = {m["old_idx"]: m["ambiguous"] for m in out["matches"]}
    assert flags == {0: True, 2: False}


def test_matching_is_one_to_one_and_deterministic_on_random_input():
    rng = np.random.default_rng(0)
    sim = rng.random((40, 35))
    old, new = paras([f"old {i} x" for i in range(40)], "OLD"), paras([f"new {i} y" for i in range(35)], "NEW")
    a = align.match_one_to_one(sim, old, new, threshold=0.6)
    b = align.match_one_to_one(sim, old, new, threshold=0.6)
    assert a == b
    news = [m["new_idx"] for m in a["matches"]]
    assert len(news) == len(set(news))
    assert len(a["matches"]) + len(a["unmatched_old"]) == 40
    assert len(a["matches"]) + len(a["unmatched_new"]) == 35


def test_weak_match_is_labelled_uncertain():
    sim = np.array([[0.62]])
    out = align.match_one_to_one(sim, paras([A], "OLD"), paras([B], "NEW"), threshold=0.60)
    rows = changes.build_results(paras([A], "OLD"), paras([B], "NEW"), out, threshold=0.60)
    assert rows[0]["label"] == changes.UNCERTAIN and "threshold" in rows[0]["reason"]


def test_embedding_alignment_of_reworded_passage():
    """Uses the real MiniLM model; skipped if it cannot be loaded."""
    reworded = ("Substantially all of our leading-edge chips are produced by one contract manufacturer "
                "located in Taiwan; an interruption there would postpone deliveries to our customers.")
    try:
        res = compare([A, B, C], [B, C, reworded], method="embeddings")
    except align.ModelUnavailable as exc:
        pytest.skip(str(exc))
    assert res["counts"][changes.UNCHANGED] == 2
    row = next(r for r in res["rows"] if r["label"] != changes.UNCHANGED)
    assert row["old"]["text"] == A and row["new"]["text"] == reworded
    assert row["label"] in (changes.SUBSTANTIVE, changes.UNCERTAIN)


# --- export -------------------------------------------------------------------

def test_exports_and_blank_annotation_labels():
    res = compare([A, B], [A.replace("could", "may"), C])
    meta = {"filing_id": "OLD", "ticker": "SYN", "source_url": "http://example.invalid/old"}
    res["old_filing"], res["new_filing"] = meta, {**meta, "filing_id": "NEW"}
    flat = export.flat_rows(res)
    assert export.results_csv(res).splitlines()[0].split(",")[:4] == export.RESULT_COLUMNS[:4]
    ann = export.annotation_rows(flat)
    assert all(r["annotator_1_label"] == r["annotator_2_label"] == r["reconciled_label"] == "" for r in ann)
    assert len(export.sample_candidates({"OLD__NEW": flat}, n=2)) == 2


def test_diff_html_marks_changes_and_escapes():
    old_html, new_html = changes.diff_html("Revenue fell <5% last year", "Revenue rose <5% last year")
    assert '<span class="rd-del">fell</span>' in old_html
    assert '<span class="rd-add">rose</span>' in new_html
    assert "&lt;5%" in old_html
