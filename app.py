"""Streamlit interface for the halfway prototype.

Run:  streamlit run app.py
"""
from __future__ import annotations

import html

import streamlit as st

from riskdiff import align, changes, config, export, ingest, pipeline

st.set_page_config(page_title="10-K Risk Factor Changes", layout="wide")

st.markdown("""
<style>
.rd-box {border:1px solid rgba(128,128,128,.35); border-radius:6px; padding:.7rem .9rem;
         line-height:1.55; font-size:.93rem; min-height:3rem; overflow-wrap:anywhere;}
.rd-empty {color:rgba(128,128,128,.95); font-style:italic; background:rgba(128,128,128,.08);}
.rd-del {background:rgba(255,80,80,.28); text-decoration:line-through; border-radius:3px; padding:0 2px;}
.rd-add {background:rgba(60,190,90,.30); border-radius:3px; padding:0 2px;}
.rd-head {font-size:.8rem; color:rgba(128,128,128,1); margin-bottom:.25rem;}
</style>
""", unsafe_allow_html=True)

LABEL_ICON = {
    changes.UNCHANGED: "⚪", changes.MINOR: "🟡", changes.SUBSTANTIVE: "🟠",
    changes.ADDITION: "🟢", changes.DELETION: "🔴", changes.UNCERTAIN: "🟣",
}
METHODS = {"Sentence embeddings (all-MiniLM-L6-v2)": "embeddings", "TF-IDF cosine (baseline)": "tfidf"}

st.title("Risk Factor disclosure changes in consecutive 10-K filings")
st.caption(
    "Halfway prototype. Labels are preliminary heuristic flags intended to direct human review "
    "of disclosure text; thresholds have not been validated. A change in disclosure wording "
    "does not prove a change in actual business risk, and nothing here predicts stock prices."
)

# --- selectors ----------------------------------------------------------------

records = ingest.filing_records()
by_ticker: dict[str, list[dict]] = {}
for rec in records:
    by_ticker.setdefault(rec["ticker"], []).append(rec)
for recs in by_ticker.values():
    recs.sort(key=lambda r: r["fiscal_period_end"])


def period_label(rec: dict) -> str:
    return f"{rec['fiscal_year']} (period ended {rec['fiscal_period_end']})"


with st.sidebar:
    st.header("Comparison")
    ticker = st.selectbox("Company", list(by_ticker),
                          format_func=lambda t: f"{config.COMPANIES[t]['name']} ({t})")
    filings = by_ticker[ticker]
    old_rec = st.selectbox("Old filing period", filings, index=0, format_func=period_label)
    new_rec = st.selectbox("New filing period", filings, index=len(filings) - 1, format_func=period_label)
    method_name = st.selectbox("Alignment method", list(METHODS))
    method = METHODS[method_name]
    threshold = st.slider(
        "Minimum similarity to match", 0.05, 0.95, config.DEFAULT_THRESHOLDS[method], 0.01,
        key=f"threshold_{method}",
        help="Paragraph pairs below this similarity are never matched. Unmatched passages "
             "become potential additions/deletions. Default is preliminary and unvalidated.")
    with st.expander("Change heuristics"):
        minor_max = st.slider(
            "Minor-edit cutoff (share of tokens changed)", 0.02, 0.60, config.MINOR_CHANGE_MAX, 0.01,
            help="Matched pairs with a smaller lexical change are 'Minor rewording'; larger "
                 "ones are 'Potential substantive revision'. Preliminary and unvalidated.")
        escalate = st.checkbox(
            "Escalate small edits that change numbers or negations", value=True,
            help="If on, a small edit that changes a number or a negation term is flagged as "
                 "'Potential substantive revision'. These are review cues, not proof.")
    run = st.button("Compare filings", type="primary", use_container_width=True)

old_id, new_id = old_rec["filing_id"], new_rec["filing_id"]

# --- source metadata ----------------------------------------------------------

st.subheader("Source filings")
cols = st.columns(2)
for col, side, rec in ((cols[0], "Old", old_rec), (cols[1], "New", new_rec)):
    with col:
        st.markdown(
            f"**{side}: {rec['company']} - Form {rec['form']}, {rec['fiscal_year']}**  \n"
            f"Fiscal period ended: {rec['fiscal_period_end']}  \n"
            f"Filed with SEC: {rec['filing_date']}  \n"
            f"Accession no.: {rec['accession_number']}  \n"
            f"[Filing document on SEC.gov]({rec['source_url']}) · [Filing index]({rec['index_url']})"
        )

# --- extraction preview and warnings --------------------------------------------


def show_extraction(side: str, rec: dict) -> dict:
    fid = rec["filing_id"]
    meta, paragraphs = pipeline.load_extraction(fid)
    status = meta["status"]
    with st.expander(
        f"{side} filing - Item 1A extraction: {status.upper()} · "
        f"{meta['section_chars']:,} characters · {meta['n_paragraphs']} paragraphs",
        expanded=status not in ("ok", "manual"),
    ):
        for w in meta["warnings"]:
            st.warning(w)
        for n in meta["notes"]:
            st.info(n)
        if meta["section_chars"]:
            share = f" ({meta['section_chars'] / meta['doc_chars']:.0%} of the filing text)" if meta.get("doc_chars") else ""
            st.markdown(
                f"**Method:** `{meta['method']}` · **Section length:** {meta['section_chars']:,} characters{share} · "
                f"**Paragraphs:** {meta['n_paragraphs']} (of which headings: {meta['n_headings']})")
            st.markdown(f"**Start marker:** {html.escape(meta['start_marker'])}  \n"
                        f"**End marker (first text after the section):** {html.escape(meta['end_marker'])}")
            st.markdown("**First passages of the extracted section**")
            for t in meta["start_preview"]:
                st.text(t)
            st.markdown("**Last passages of the extracted section**")
            for t in meta["end_preview"]:
                st.text(t)
            st.caption(f"Full extracted text: data/extracted/{fid}.txt · original filing: data/raw/{fid}.htm")
        st.markdown("**Manual override** - paste the Risk Factors text if the extraction above is wrong.")
        manual = st.text_area("Risk Factors text (blank line between paragraphs)", key=f"manual_{fid}", height=140)
        c1, c2 = st.columns(2)
        if c1.button("Use this text", key=f"use_{fid}", disabled=not manual.strip()):
            pipeline.save_manual_text(fid, manual)
            st.session_state.pop("result", None)
            st.rerun()
        if status == "manual" and c2.button("Discard manual text and re-extract", key=f"clear_{fid}"):
            pipeline.clear_manual_text(fid)
            st.session_state.pop("result", None)
            st.rerun()
    return meta


st.subheader("Extraction check")
st.caption("Verify that each extracted section really is Item 1A before trusting a comparison.")
old_meta = show_extraction("Old", old_rec)
new_meta = show_extraction("New", new_rec)

# --- comparison -----------------------------------------------------------------

blocking = []
if old_id == new_id:
    blocking.append("Select two different filing periods.")
elif old_rec["fiscal_period_end"] > new_rec["fiscal_period_end"]:
    blocking.append("The old filing period must precede the new one.")
for side, meta in (("old", old_meta), ("new", new_meta)):
    if meta["status"] in ("missing", "failed") or meta["n_paragraphs"] == 0:
        blocking.append(f"No Risk Factors text is available for the {side} filing. "
                        + " ".join(meta["warnings"]))

uncertain = [s for s, m in (("old", old_meta), ("new", new_meta)) if m["status"] == "uncertain"]
accept_uncertain = True
if uncertain and not blocking:
    st.warning(f"Extraction of the {' and '.join(uncertain)} filing is uncertain (see warnings above). "
               f"Check the previews, or supply the text manually.")
    accept_uncertain = st.checkbox("I have checked the previews; compare anyway", key=f"accept_{old_id}_{new_id}")

st.subheader("Comparison")
for msg in blocking:
    st.error(msg)

if run and not blocking:
    if not accept_uncertain:
        st.error("Comparison not run: confirm the uncertain extraction above, or supply the text manually.")
    else:
        try:
            with st.spinner("Aligning paragraphs (the first embedding run downloads the model and can take a minute)..."):
                st.session_state["result"] = pipeline.compare_filings(
                    old_id, new_id, method=method, threshold=threshold,
                    minor_max=minor_max, escalate_cues=escalate)
        except align.ModelUnavailable as exc:
            st.session_state.pop("result", None)
            st.error(f"The embedding model is unavailable. {exc}")
            st.info("Install `sentence-transformers` and allow a one-time model download, "
                    "or choose the TF-IDF alignment method, which needs no model.")
        except Exception as exc:  # show the failure rather than a blank page
            st.session_state.pop("result", None)
            st.error(f"Comparison failed: {exc}")

result = st.session_state.get("result")
if result and (result["old_filing"]["filing_id"], result["new_filing"]["filing_id"]) != (old_id, new_id):
    result = None  # selection changed since the last run

if not result:
    if not blocking:
        st.info("Choose settings in the sidebar and press **Compare filings**.")
    st.stop()

params = result["params"]
st.caption(
    f"Showing: {result['old_filing']['filing_id']} → {result['new_filing']['filing_id']} · "
    f"alignment: {params['method']} · threshold: {params['threshold']:.2f} · "
    f"minor-edit cutoff: {params['minor_max']:.2f}. Press **Compare filings** again after changing settings.")

rows = result["rows"]
if not rows:
    st.warning("The comparison produced no results (both sections are empty).")
    st.stop()

st.markdown("**Counts by preliminary change label**")
count_cols = st.columns(len(changes.LABELS))
for col, label in zip(count_cols, changes.LABELS):
    col.metric(f"{LABEL_ICON[label]} {label}", result["counts"][label])

default_labels = [l for l in changes.LABELS if l != changes.UNCHANGED]
f1, f2, f3 = st.columns([3, 1, 1])
selected = f1.multiselect("Show labels", changes.LABELS, default=default_labels)
include_headings = f2.checkbox("Include headings", value=True)
page_size = f3.selectbox("Results per page", [10, 25, 50, 100], index=1)

visible = [r for r in rows if r["label"] in selected
           and (include_headings or (r["new"] or r["old"])["kind"] != "heading")]

d1, d2, _ = st.columns([1, 1, 3])
pair_name = f"{result['old_filing']['filing_id']}__{result['new_filing']['filing_id']}__{params['method']}"
d1.download_button("Download all results (CSV)", export.results_csv(result),
                   file_name=f"{pair_name}.csv", mime="text/csv")
d2.download_button("Download all results (JSON)", export.results_json(result),
                   file_name=f"{pair_name}.json", mime="application/json")

if not visible:
    st.info("No passages match the selected label filters.")
    st.stop()

n_pages = (len(visible) - 1) // page_size + 1
page = st.number_input(f"Page (1-{n_pages})", 1, n_pages, 1) if n_pages > 1 else 1
st.markdown(f"**{len(visible)} passages**, ranked by review priority "
            f"(a transparent ordering heuristic - not financial severity, probability, or importance).")


def passage_box(par: dict | None, body_html: str | None, missing_msg: str) -> None:
    if par is None:
        st.markdown(f'<div class="rd-box rd-empty">{missing_msg}</div>', unsafe_allow_html=True)
        return
    context = " › ".join(x for x in (par["section"], par["heading"]) if x)
    kind = "heading" if par["kind"] == "heading" else "paragraph"
    st.markdown(f'<div class="rd-head">{html.escape(par["id"])} · {kind}'
                + (f' · under: {html.escape(context[:160])}' if context else "") + "</div>"
                f'<div class="rd-box">{body_html}</div>', unsafe_allow_html=True)


for r in visible[(page - 1) * page_size: page * page_size]:
    o, n = r["old"], r["new"]
    with st.container(border=True):
        sim = f"{r['similarity']:.2f}" if r["similarity"] is not None else "n/a (unmatched)"
        chg = f"{r['change_ratio']:.0%}" if r["change_ratio"] is not None else "n/a"
        st.markdown(
            f"**#{r['rank']} · {LABEL_ICON[r['label']]} {r['label']}** · review priority {r['priority']:.2f} · "
            f"similarity {sim} · tokens changed {chg}")
        st.markdown(f"**Why flagged:** {html.escape(r['reason'])}")
        if o and n:
            old_html, new_html = changes.diff_html(o["text"], n["text"])
        else:
            old_html = html.escape(o["text"]) if o else None
            new_html = html.escape(n["text"]) if n else None
        left, right = st.columns(2)
        with left:
            st.markdown(f"**Old · {result['old_filing']['fiscal_year']}**")
            passage_box(o, old_html, "No corresponding passage was matched in the old filing. "
                                     "This passage may be new, or its counterpart fell below the matching threshold.")
        with right:
            st.markdown(f"**New · {result['new_filing']['fiscal_year']}**")
            passage_box(n, new_html, "No corresponding passage was matched in the new filing. "
                                     "This passage may have been removed, or its counterpart fell below the matching threshold.")

st.caption("Highlighting: struck-through red = words only in the old passage; green = words only in the "
           "new passage. The original filing text on SEC.gov is authoritative.")
