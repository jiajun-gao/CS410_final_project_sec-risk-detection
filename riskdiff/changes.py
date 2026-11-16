"""Preliminary change flags and review-priority ranking.

Everything here is a transparent heuristic over an existing alignment.
High similarity is never treated as proof that meaning is unchanged, and the
"review priority" score is NOT a measure of financial severity, probability,
or business importance. Thresholds are preliminary and unvalidated.
"""
from __future__ import annotations

import difflib
import html
import re
from collections import Counter

from . import config

UNCHANGED = "Unchanged"
MINOR = "Minor rewording"
SUBSTANTIVE = "Potential substantive revision"
ADDITION = "Potential addition"
DELETION = "Potential deletion"
UNCERTAIN = "Uncertain match / needs review"
LABELS = [UNCHANGED, MINOR, SUBSTANTIVE, ADDITION, DELETION, UNCERTAIN]

_TOKEN = re.compile(r"\w+(?:['.,\-/]\w+)*|[^\w\s]")
_NUMBER = re.compile(r"\$?\d[\d,]*(?:\.\d+)?%?")
NEGATIONS = {
    "no", "not", "never", "none", "neither", "nor", "cannot", "without", "unable",
    "can't", "won't", "don't", "doesn't", "didn't", "isn't", "aren't", "wasn't",
    "weren't", "hasn't", "haven't", "hadn't", "shouldn't", "wouldn't", "couldn't",
    "mustn't", "no longer",
}


def tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def change_ratio(old_norm: str, new_norm: str) -> float:
    """Lexical change in [0, 1]: 1 - difflib token-sequence similarity."""
    a, b = tokens(old_norm), tokens(new_norm)
    if not a and not b:
        return 0.0
    return 1.0 - difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def _counter_diff(old: Counter, new: Counter) -> tuple[list[str], list[str]]:
    removed = sorted((old - new).elements())
    added = sorted((new - old).elements())
    return removed, added


def number_cue(old_norm: str, new_norm: str) -> str:
    removed, added = _counter_diff(Counter(_NUMBER.findall(old_norm)), Counter(_NUMBER.findall(new_norm)))
    if not removed and not added:
        return ""
    parts = []
    if removed:
        parts.append("removed " + ", ".join(removed[:6]))
    if added:
        parts.append("added " + ", ".join(added[:6]))
    return "; ".join(parts)


def _negations(norm: str) -> Counter:
    low = norm.lower()
    found = Counter(t for t in tokens(norm) if t in NEGATIONS)
    found["no longer"] = len(re.findall(r"\bno longer\b", low))
    return +found


def negation_cue(old_norm: str, new_norm: str) -> str:
    removed, added = _counter_diff(_negations(old_norm), _negations(new_norm))
    if not removed and not added:
        return ""
    parts = []
    if removed:
        parts.append("removed " + ", ".join(f"'{t}'" for t in removed[:6]))
    if added:
        parts.append("added " + ", ".join(f"'{t}'" for t in added[:6]))
    return "; ".join(parts)


def classify_match(old: dict, new: dict, match: dict, threshold: float,
                   minor_max: float = config.MINOR_CHANGE_MAX,
                   uncertain_band: float = config.UNCERTAIN_BAND,
                   escalate_cues: bool = True) -> dict:
    """Assign a preliminary label to one aligned pair and explain why."""
    sim = match["similarity"]
    if old["norm"] == new["norm"]:
        return {"label": UNCHANGED, "change_ratio": 0.0, "number_cue": "", "negation_cue": "",
                "reason": "Normalized text is identical."}

    ratio = change_ratio(old["norm"], new["norm"])
    num, neg = number_cue(old["norm"], new["norm"]), negation_cue(old["norm"], new["norm"])
    cue_text = "; ".join(x for x in (f"numbers changed ({num})" if num else "",
                                     f"negation terms changed ({neg})" if neg else "") if x)

    weak = sim < threshold + uncertain_band
    if weak or (match["ambiguous"] and ratio >= minor_max):
        why = []
        if weak:
            why.append(f"similarity {sim:.2f} is close to the matching threshold {threshold:.2f}")
        if match["ambiguous"]:
            why.append(f"another candidate scored nearly as high ({match['runner_up']:.2f})")
        label, reason = UNCERTAIN, "Alignment is not reliable: " + " and ".join(why) + \
            ". The passages may not correspond, or a paragraph may have been split or merged."
    elif ratio < minor_max:
        if escalate_cues and cue_text:
            label = SUBSTANTIVE
            reason = (f"Only {ratio:.0%} of tokens differ, but {cue_text}. "
                      f"This is a review cue, not proof of a substantive change.")
        else:
            label = MINOR
            reason = f"Only {ratio:.0%} of tokens differ (below the {minor_max:.0%} minor-edit cutoff)."
    else:
        label = SUBSTANTIVE
        reason = f"{ratio:.0%} of tokens differ (at or above the {minor_max:.0%} minor-edit cutoff)."

    if cue_text and cue_text not in reason:
        reason += f" Review cue: {cue_text}."
    if match["ambiguous"] and label != UNCERTAIN:
        reason += f" Note: another candidate match scored nearly as high ({match['runner_up']:.2f})."
    return {"label": label, "change_ratio": ratio, "number_cue": num, "negation_cue": neg,
            "reason": reason}


def review_priority(label: str, ratio: float | None, n_words: int,
                    has_number_cue: bool, has_negation_cue: bool, ambiguous: bool) -> float:
    """Transparent review-priority score in [0, 1].

    priority = base(label)
             + 0.40 * lexical change ratio          (matched pairs)
             + 0.20 * min(1, words / 150)           (unmatched passages)
             + 0.10 per cue type (numbers, negation)
             + 0.05 if the match is ambiguous
    """
    if label == UNCHANGED:
        return 0.0
    score = config.PRIORITY_BASE[label]
    if label in (ADDITION, DELETION):
        score += config.PRIORITY_LENGTH_WEIGHT * min(1.0, n_words / 150)
    else:
        score += config.PRIORITY_CHANGE_WEIGHT * (ratio or 0.0)
        score += config.PRIORITY_CUE_BONUS * (int(has_number_cue) + int(has_negation_cue))
        score += config.PRIORITY_AMBIGUOUS_BONUS * int(ambiguous)
    return round(min(1.0, score), 4)


def build_results(old: list[dict], new: list[dict], alignment: dict, threshold: float,
                  minor_max: float = config.MINOR_CHANGE_MAX, escalate_cues: bool = True) -> list[dict]:
    """Combine alignment + change heuristics into ranked result rows."""
    rows = []
    for m in alignment["matches"]:
        o, n = old[m["old_idx"]], new[m["new_idx"]]
        c = classify_match(o, n, m, threshold, minor_max=minor_max, escalate_cues=escalate_cues)
        rows.append({
            **c,
            "similarity": round(m["similarity"], 4),
            "ambiguous": m["ambiguous"],
            "old": o, "new": n,
            "priority": review_priority(c["label"], c["change_ratio"], max(o["n_words"], n["n_words"]),
                                        bool(c["number_cue"]), bool(c["negation_cue"]), m["ambiguous"]),
        })
    for side, label, items, others in (("old", DELETION, alignment["unmatched_old"], new),
                                       ("new", ADDITION, alignment["unmatched_new"], old)):
        source = old if side == "old" else new
        for u in items:
            p = source[u[f"{side}_idx"]]
            where = "new" if side == "old" else "old"
            near = others[u["nearest_idx"]]["id"] if u["nearest_idx"] is not None and others else None
            closest = f"{u['nearest_sim']:.2f}" + (f", {near}" if near else "")
            if u["nearest_sim"] >= threshold:
                reason = (f"Left unmatched: the closest {where}-filing passage ({closest}) is above the "
                          f"threshold {threshold:.2f} but was matched one-to-one with a different, "
                          f"more similar paragraph. Possibly a split or merge, which is not yet supported.")
            else:
                reason = (f"No {where}-filing passage reached the matching threshold {threshold:.2f} "
                          f"(closest: {closest}).")
            rows.append({
                "label": label, "change_ratio": None, "number_cue": "", "negation_cue": "",
                "reason": reason, "similarity": None, "ambiguous": False,
                "nearest_similarity": round(u["nearest_sim"], 4), "nearest_id": near,
                "old": p if side == "old" else None, "new": p if side == "new" else None,
                "priority": review_priority(label, None, p["n_words"], False, False, False),
            })

    def order_key(r):
        anchor = r["new"] or r["old"]
        return (-r["priority"], anchor["order"], 0 if r["new"] else 1)

    rows.sort(key=order_key)
    for rank, r in enumerate(rows, 1):
        r["rank"] = rank
    return rows


# --- word-level diff rendering ------------------------------------------------

_SPLIT = re.compile(r"(\s+)")


def diff_html(old_text: str, new_text: str) -> tuple[str, str]:
    """Word-level diff of the ORIGINAL texts. Returns (old_html, new_html):
    deletions are marked on the old side, additions on the new side."""
    a = [t for t in _SPLIT.split(old_text) if t and not t.isspace()]
    b = [t for t in _SPLIT.split(new_text) if t and not t.isspace()]
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    old_out, new_out = [], []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        old_seg = html.escape(" ".join(a[i1:i2]))
        new_seg = html.escape(" ".join(b[j1:j2]))
        if op == "equal":
            old_out.append(old_seg)
            new_out.append(new_seg)
        else:
            if old_seg:
                old_out.append(f'<span class="rd-del">{old_seg}</span>')
            if new_seg:
                new_out.append(f'<span class="rd-add">{new_seg}</span>')
    return " ".join(old_out), " ".join(new_out)
