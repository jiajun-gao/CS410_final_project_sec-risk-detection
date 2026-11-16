# Annotation guidance (draft for the second-half evaluation)

Each row of the annotation sheet is one **old passage / new passage** pair from the
Risk Factors sections of two consecutive 10-K filings of the same company. One side
is empty when the tool found no counterpart.

You are judging **what the disclosure says**, not whether the company's real-world
risk changed and not whether the change matters to investors.

## Columns you fill in

| Column | What to enter |
| --- | --- |
| `annotator_1_label` / `annotator_2_label` | Your label, chosen independently. Do not look at the other annotator's label. |
| `reconciled_label` | Agreed label after the two annotators discuss disagreements. |
| `risk_categories_optional` | Optional, `;`-separated. Draft list below. |
| `notes` | Anything that made the case hard, including alignment problems. |

`predicted_label` is the tool's preliminary output. Try to label **before** reading it;
it is there for later error analysis, not as a hint.

## Labels

Use the same six labels the tool shows.

- **Unchanged** - the same text apart from whitespace or typography.
- **Minor rewording** - an *editorial* change: the passage discloses the same risk, with
  the same scope, likelihood language, and facts.
- **Potential substantive revision** - a *substantive* change: a reader would learn
  something different about the disclosed risk.
- **Potential addition** - the new passage discloses something with no counterpart in
  the old filing's Risk Factors.
- **Potential deletion** - the old passage has no counterpart in the new filing.
- **Uncertain match / needs review** - the two passages are not really counterparts, or
  you cannot tell (for example one paragraph was split into two). Explain in `notes`.

## Substantive vs. editorial

Treat a change as **substantive** if it does any of the following:

- adds, removes, or replaces a specific risk, cause, event, product, technology,
  counterparty, country, or regulation (for example a new export-control rule, a newly
  named supplier dependency, AI-related demand or competition);
- changes a quantity that describes exposure (a customer-concentration percentage, a
  charge, a count of facilities) - but not a date that simply rolls forward a year;
- changes tense or modality in a way that changes the claim: "could experience" becoming
  "have experienced", "may" becoming "will", or the reverse;
- adds or removes a negation or qualifier that changes meaning ("have not experienced
  material incidents" becoming "have experienced");
- widens or narrows scope (one region to all regions, one product line to the business).

Treat a change as **editorial** (Minor rewording) if it only:

- fixes grammar, punctuation, capitalisation, or style ("the Company" / "we");
- substitutes synonyms or reorders clauses without changing the claim;
- rolls a fiscal-year reference forward with no other change;
- renames a defined term consistently, or updates a cross-reference.

When unsure between Minor rewording and Potential substantive revision, choose
**Potential substantive revision** and say why in `notes`. Do not use outside knowledge
about the company to decide; judge only the two passages.

## Draft risk categories (optional, not final)

`ai_competition_demand`, `supply_chain_manufacturing`, `export_trade_restrictions`,
`cybersecurity`, `regulation_legal`, `supplier_customer_dependence`,
`macroeconomic`, `financial_tax`, `other`.

These reflect topics the team wants to examine. They are not predetermined findings:
assign a category only when the passage text supports it.
