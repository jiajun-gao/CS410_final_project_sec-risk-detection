# Evaluation plan (second half - not yet run)

No evaluation has been performed. The prototype's thresholds are hand-set defaults, and
no accuracy figures exist. This is the plan for the roughly 200-example evaluation.

## Data

- About 200 passage pairs sampled from the comparison output, stratified by predicted
  label, company, and alignment method so that rare labels are represented.
- Each pair labelled independently by two annotators using
  `annotation/annotation_guidelines.md`, then reconciled. Report inter-annotator
  agreement (Cohen's kappa) before reconciliation.
- The 20 rows in `annotation/annotation_candidates.csv` are a pilot to test the
  guidelines; they are not part of the test set unless re-drawn under this plan.

## Tuning / test separation

Split at the **filing-pair level**, not the passage level, because passages from the same
filing pair share boilerplate and style. Thresholds (matching threshold, minor-edit
cutoff, uncertainty band) are tuned only on tuning pairs; test pairs are scored once.
With three companies today, this requires the planned expansion to about 10 companies
so that several filing pairs can be held out.

## Measures

1. **Substantive-change detection.** Treat reconciled labels {Potential substantive
   revision, Potential addition, Potential deletion} as positive. Report precision,
   recall, and F1, for embeddings and for the TF-IDF baseline.
2. **Label-level confusion matrix** over the six labels, with attention to the
   Uncertain label (how often it was a real alignment error).
3. **Risk categorisation** (once implemented): per-category precision/recall/F1 and
   macro-F1 against the optional category annotations.
4. **Ranking.** Precision@k (k = 5, 10, 20) of the review-priority ordering per filing
   pair, where a hit is a reconciled substantive change.
5. **Alignment errors.** Count split/merge cases recorded in annotator notes, to size
   the need for many-to-many alignment.

## Reporting

Report results per company and overall, state the sample size behind every number, and
keep the framing as disclosure-change detection: no claims about actual business risk
or market outcomes.
