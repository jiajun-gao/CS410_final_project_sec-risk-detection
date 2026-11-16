# Detecting Emerging Risks in Corporate SEC Filings Using Text Mining

**Halfway prototype.** Compares the *Risk Factors* (Item 1A) sections of two consecutive
annual Form 10-K filings of the same company and helps a reader inspect potentially
added, deleted, and revised disclosures next to the original text.

This is **disclosure analysis**. The tool does not predict stock prices, and a change in
disclosure wording does not prove a change in actual business risk. All labels are
preliminary heuristic flags for human review; **no threshold has been validated and no
accuracy figures exist yet.**

Team: Jiajun Gao (coordination, semantic matching, change detection, integration) ·
Yingcheng Deng (data collection, preprocessing) · Sihan Wang (risk categorisation,
evaluation) · Zhenhan Zhao (interface, application testing).

## Install and run

Python 3.10+ (developed on 3.11, Windows). CPU only; no paid APIs.

```powershell
python -m venv .venv            # if the project lives in OneDrive, create the venv outside it
.venv\Scripts\Activate.ps1
pip install torch --index-url https://download.pytorch.org/whl/cpu   # CPU build, smaller download
pip install -r requirements.txt

# 1. Download the six filings and extract Item 1A (one-time)
$env:SEC_USER_AGENT = "Your Name your@email"   # SEC requires automated tools to declare a contact
python scripts/fetch_filings.py

# 2. Launch the interface
streamlit run app.py

# Optional
python -m pytest -q                         # focused checks on synthetic fixtures
python scripts/smoke_test_app.py            # headless app check on the real filings
python scripts/build_annotation_sample.py   # regenerate the 20 annotation candidates
```

The first embedding comparison downloads `all-MiniLM-L6-v2` (about 90 MB) from Hugging
Face; afterwards it runs offline. TF-IDF needs no model.

SEC.gov rejects requests that do not declare a contact in the User-Agent. The contact is
read from the `SEC_USER_AGENT` environment variable and is never written to the
repository or the manifest. Alternatively, save each filing page from a browser to the
`raw_path` listed in `data/manifest.json`.

## Data-source manifest

Source: SEC EDGAR (public). Machine-readable copy with URLs, retrieval times, sizes, and
SHA-256 hashes: [data/manifest.json](data/manifest.json). These were the two most recent
10-Ks for each company on 2026-11-15. Fiscal period and filing date are recorded
separately because the three fiscal calendars differ, so "FY2025" does not mean the same
months for each company.

| Filing ID | Company | Fiscal period ended | Filed | Accession no. |
| --- | --- | --- | --- | --- |
| AAPL_FY2025 | Apple Inc. | 2025-09-27 | 2025-10-31 | 0000320193-25-000079 |
| AAPL_FY2026 | Apple Inc. | 2026-09-26 | 2026-11-03 | 0000320193-26-000026 |
| NVDA_FY2025 | NVIDIA Corporation | 2025-01-26 | 2025-02-26 | 0001045810-25-000023 |
| NVDA_FY2026 | NVIDIA Corporation | 2026-01-25 | 2026-02-25 | 0001045810-26-000021 |
| INTC_FY2024 | Intel Corporation | 2024-12-28 | 2025-01-31 | 0000050863-25-000009 |
| INTC_FY2025 | Intel Corporation | 2025-12-27 | 2026-01-23 | 0000050863-26-000011 |

Each company is compared only with its own previous annual report. There is no
cross-company matching.

Extraction results on these filings (after artifact removal):

| Filing | Method | Section length | Paragraphs (headings) |
| --- | --- | --- | --- |
| AAPL_FY2025 | Item 1A heading | 67,524 chars | 106 (32) |
| AAPL_FY2026 | Item 1A heading | 85,920 chars | 121 (33) |
| NVDA_FY2025 | Item 1A heading | 110,212 chars | 212 (33) |
| NVDA_FY2026 | Item 1A heading | 114,248 chars | 227 (34) |
| INTC_FY2024 | "Risk Factors" heading fallback | 101,482 chars | 162 (24) |
| INTC_FY2025 | "Risk Factors" heading fallback | 95,874 chars | 156 (22) |

Intel's 10-K has no "Item 1A" heading in the body (it uses its own layout plus a
cross-reference index), so the fallback is used and the app always shows a warning and
asks for confirmation. We checked the Intel start and end boundaries by hand for both
years; they were correct.

## Project layout

```
app.py                      Streamlit interface
riskdiff/
  config.py                 scope (companies, filings), paths, all heuristic defaults
  ingest.py                 EDGAR download, manifest
  extract.py                HTML -> text blocks, Item 1A location, warnings
  preprocess.py             paragraph segmentation, IDs, normalisation, heading context
  align.py                  embeddings (cached), TF-IDF, one-to-one matching
  changes.py                change labels, review cues, review priority, word diff
  export.py                 CSV/JSON export, annotation template, candidate sampling
  pipeline.py               glue between the stages
scripts/                    fetch_filings, build_annotation_sample, smoke_test_app
tests/test_pipeline.py      focused checks (synthetic fixtures only)
data/raw/                   original filing HTML        data/extracted/  extracted text, paragraphs, diagnostics
data/manual/                manually supplied text      data/cache/      embedding cache
annotation/                 guidelines, blank template, 20 candidate examples
docs/evaluation_plan.md     plan for the ~200-example evaluation (not run)
```

## Pipeline

1. **Ingestion.** Download the primary 10-K document for each filing; store it unchanged
   in `data/raw/` and record metadata in the manifest.
2. **Section extraction.** Flatten the HTML into ordered text blocks (one per leaf block
   element or table row). Find every block that looks like an "Item 1A" heading and span
   to the next "Item 1B / 1C / 2" heading; the table-of-contents entry gives a near-empty
   span, so the longest span is taken. If there is no Item 1A heading, fall back to a
   standalone "Risk Factors" heading bounded by the next recognised section title. Page
   numbers, "Table of Contents" links, and running headers/footers are removed, and
   paragraphs cut by a page break are rejoined. Warnings are raised when the section is
   missing, short, implausibly large, lacks an end marker, or came from the fallback.
   The app shows the start/end markers, first and last passages, and section length, and
   accepts manually pasted text (stored in `data/manual/`), which then takes precedence.
   A comparison is blocked when extraction failed and needs explicit confirmation when
   it is uncertain.
3. **Paragraph preprocessing.** Each block becomes a paragraph with a stable ID
   (`<filing>_p<position>`), original text, normalised text, a content hash, and heading
   context. Headings (bold, italic/underlined, or larger-font short blocks) are kept as
   their own units because risk headings are often full sentences whose wording matters.
   Normalisation only unifies Unicode forms, quotes, dashes, and whitespace; case,
   numbers, dates, punctuation, and negation are untouched. Only blocks with no letters
   or digits are filtered; short passages are kept.
4. **Alignment.** Identical normalised paragraphs are paired first, in order. For the
   rest, cosine similarity is computed either from `all-MiniLM-L6-v2` sentence embeddings
   (cached per filing in `data/cache/`) or from TF-IDF vectors (unigrams and bigrams,
   stop words kept). Pairs at or above the threshold are accepted greedily from the
   highest similarity down, and only if both paragraphs are still free, so the matching
   is deterministic and one-to-one. A match is flagged *ambiguous* when a competing
   candidate scores within 0.05 of it. Unmatched paragraphs are kept.
5. **Change flags** (separate from alignment; see below).
6. **Ranking and export.** Review-priority ordering, CSV/JSON download, annotation files.

## Heuristic labels

Defaults live in `riskdiff/config.py`. **They are preliminary and have not been
validated.** High embedding similarity is never treated as evidence that meaning is
unchanged.

| Label | Rule |
| --- | --- |
| Unchanged | Matched pair whose normalised text is identical. |
| Uncertain match / needs review | Matched, but similarity is within 0.10 above the threshold, or the match is ambiguous and the texts differ by at least the minor-edit cutoff. |
| Minor rewording | Matched; lexical change below the minor-edit cutoff (default 0.15) and no review cue. |
| Potential substantive revision | Matched; lexical change at or above the cutoff, **or** a small edit that changes a number or negation term (this escalation can be switched off in the app). |
| Potential addition | New paragraph with no match. |
| Potential deletion | Old paragraph with no match. |

- *Lexical change* = 1 − `difflib.SequenceMatcher` ratio over lower-cased word tokens.
- *Matching threshold defaults*: 0.60 for embeddings, 0.30 for TF-IDF.
- *Review cues*: numbers present on one side only (amounts, percentages, years) and
  negation terms whose counts differ ("not", "no longer", "cannot", ...). They are shown
  as cues; they do not reliably indicate significance. A fiscal year rolling forward
  triggers the number cue, for example.

### Review priority

A transparent ordering score in [0, 1] - **not** financial severity, probability, or
business importance. No learning is involved.

```
priority = base(label)
         + 0.40 x lexical change            (matched pairs)
         + 0.20 x min(1, words / 150)       (unmatched passages)
         + 0.10 per cue type present        (numbers, negation; matched pairs)
         + 0.05 if the match is ambiguous
base: addition 0.70, deletion 0.70, uncertain 0.50, substantive 0.40, minor 0.05, unchanged 0
```

Every result shows the reason it was flagged.

## Demonstration walkthrough

1. `streamlit run app.py`. Company **NVIDIA**, old FY2025, new FY2026, embeddings, default
   threshold. Read out the fiscal period end and filing date of each filing.
2. Open **Extraction check**: start marker "Item 1A. Risk Factors", end marker "Item 1B",
   section length, first and last passages. Point out the note that the table-of-contents
   entry was skipped.
3. Press **Compare filings**. Show the counts by label, then the ranked list. Open a
   top-ranked item and show the side-by-side text, word-level highlighting, similarity,
   and the "Why flagged" line. Follow the SEC.gov link to the source.
4. Filter to **Potential addition** to show the empty-state explanation on the old side,
   then to **Minor rewording** to show small edits.
5. Switch the alignment method to **TF-IDF**, compare again, and note how the counts move.
   Lower or raise the threshold to show how additions/deletions trade off against matches.
6. Select **Intel** to show the extraction warning, the confirmation checkbox, and the
   manual-text override.
7. Download the CSV, and open `annotation/annotation_candidates.csv`.

Topics the team intends to examine in the results - AI-related competition and demand,
semiconductor supply and manufacturing, export restrictions, cybersecurity, regulation,
supplier and customer dependence - are things to look for, not findings. Report a change
only when the filing text shown in the tool supports it.

## Verification performed

- `python -m pytest -q`: 17 checks pass on **synthetic** fixtures - Item 1A chosen over
  its table-of-contents entry; page artifacts removed and headings kept; missing/short
  section warnings; normalisation keeps numbers, punctuation, negation; unchanged
  passages; minor rewording; substantially reworded but related passages (TF-IDF, and
  the real embedding model); numeric change and negation change surfaced in otherwise
  near-identical passages; potential additions and deletions; no duplicate one-to-one
  assignments (including a contested case and a random matrix); weak matches labelled
  uncertain; exports with blank human labels; diff rendering.
- All six real filings downloaded and extracted; boundaries inspected.
- All three real filing pairs compared with both alignment methods.
- `scripts/smoke_test_app.py`: the app starts and completes a real Apple comparison with
  both methods. The Streamlit server was also started and answered HTTP requests.
- Not done: clicking through the interface in a browser by a person, and any measurement
  of label quality.

## Known limitations

- **Splits and merges are not properly supported.** Matching is strictly one-to-one. If a
  paragraph is split in two, one half matches and the other appears as a "Potential
  addition" (the reason text says when a close passage was already taken). Reordered and
  restructured sections inflate additions and deletions the same way.
- Thresholds, cutoffs, and priority weights are hand-set and unvalidated.
- The labels measure wording change. A one-word edit can matter and a full rewrite may
  not; the number and negation cues are crude and noisy.
- MiniLM truncates input at 256 word pieces, so long paragraphs are embedded from their
  opening only. TF-IDF sees the whole paragraph but not paraphrase.
- Greedy matching is not globally optimal.
- Extraction is rule-based and tuned on three filers. Intel needs the fallback path.
  Paragraphs split by a page break at a sentence boundary cannot be detected and stay
  split. Heading detection depends on inline styling. Tables inside the section are
  flattened to one line per row.
- Paragraph IDs are positional: stable for a given extraction, but they change if the
  extraction rules change.
- Six filings from three large technology companies; nothing here generalises yet.

## Milestone checklist

**Implemented (halfway milestone)**

- [x] Six real 10-K filings for Apple, NVIDIA, Intel with a data-source manifest
- [x] Item 1A extraction with table-of-contents handling, artifact removal, warnings,
      previews, and a manual-text override
- [x] Paragraph segmentation with IDs, original and normalised text, heading context
- [x] Cached embedding alignment and TF-IDF baseline; deterministic one-to-one matching
      with a configurable threshold, unmatched passages kept, ambiguous matches flagged
- [x] Preliminary change labels, number/negation review cues, documented defaults
- [x] Transparent review-priority ranking with a reason per passage
- [x] Streamlit interface with selectors, counts, filters, side-by-side word-level diff,
      source links, extraction preview, CSV/JSON export
- [x] Annotation template, guidance, 20 candidate examples with blank human labels
- [x] Evaluation plan; focused tests

**Remaining (second half) - not implemented, no interface controls**

- [ ] Expansion to about 10 companies
- [ ] Form 10-Q support
- [ ] Management's Discussion and Analysis extraction
- [ ] Robust split/merge and many-to-many alignment
- [ ] Full automated risk categorisation
- [ ] Generative summaries
- [ ] Model fine-tuning
- [ ] Completed ~200-example annotation
- [ ] Formal evaluation and performance claims (plan: `docs/evaluation_plan.md`)
- [ ] Production deployment, accounts, database infrastructure
