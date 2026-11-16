"""Alignment: pair old and new paragraphs. Alignment says only "these two
passages probably correspond"; it says nothing about whether they changed
(see changes.py)."""
from __future__ import annotations

import numpy as np

from . import config


class ModelUnavailable(RuntimeError):
    """The embedding model could not be loaded (not installed / no download)."""


_MODEL = None


def _get_model():
    global _MODEL
    if _MODEL is None:
        try:
            from sentence_transformers import SentenceTransformer
            _MODEL = SentenceTransformer(config.EMBEDDING_MODEL, device="cpu")
        except Exception as exc:  # missing package, no network, corrupt cache...
            raise ModelUnavailable(
                f"Could not load embedding model '{config.EMBEDDING_MODEL}': {exc}") from exc
    return _MODEL


def embed_paragraphs(paragraphs: list[dict], filing_id: str | None = None) -> np.ndarray:
    """L2-normalised embeddings, cached on disk per filing.

    The cache is keyed by the paragraphs' text hashes, so it is invalidated
    automatically if extraction or segmentation changes.
    """
    hashes = np.array([p["hash"] for p in paragraphs])
    cache_path = None
    if filing_id:
        slug = config.EMBEDDING_MODEL.split("/")[-1]
        cache_path = config.CACHE_DIR / f"{filing_id}__{slug}.npz"
        if cache_path.exists():
            try:
                cached = np.load(cache_path)
                if np.array_equal(cached["hashes"], hashes):
                    return cached["vectors"]
            except Exception:
                pass  # unreadable cache: recompute
    if not paragraphs:
        return np.zeros((0, 384), dtype=np.float32)
    model = _get_model()
    vectors = model.encode([p["norm"] for p in paragraphs], batch_size=32,
                           normalize_embeddings=True, show_progress_bar=False)
    vectors = np.asarray(vectors, dtype=np.float32)
    if cache_path:
        config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(cache_path, hashes=hashes, vectors=vectors)
    return vectors


def embedding_similarity(old: list[dict], new: list[dict],
                         old_id: str | None = None, new_id: str | None = None) -> np.ndarray:
    a, b = embed_paragraphs(old, old_id), embed_paragraphs(new, new_id)
    return np.clip(a @ b.T, -1.0, 1.0) if len(a) and len(b) else np.zeros((len(a), len(b)))


def tfidf_similarity(old: list[dict], new: list[dict]) -> np.ndarray:
    """TF-IDF cosine baseline. Stop words are kept so negation is retained."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    if not old or not new:
        return np.zeros((len(old), len(new)))
    vec = TfidfVectorizer(lowercase=True, ngram_range=(1, 2), sublinear_tf=True,
                          token_pattern=r"(?u)\b\w+\b")
    matrix = vec.fit_transform([p["norm"] for p in old] + [p["norm"] for p in new])
    return cosine_similarity(matrix[:len(old)], matrix[len(old):])


def match_one_to_one(sim: np.ndarray, old: list[dict], new: list[dict],
                     threshold: float, margin: float = config.AMBIGUITY_MARGIN) -> dict:
    """Deterministic one-to-one matching.

    1. Paragraphs whose normalized text is identical are paired first, in
       document order.
    2. Remaining pairs with similarity >= threshold are taken greedily from
       highest similarity down (ties broken by position); a pair is accepted
       only if both paragraphs are still free, so no paragraph is claimed twice.
    3. A match is flagged ambiguous when a competing candidate for either
       paragraph scores within `margin` of the accepted pair.

    Splits and merges (one-to-many) are NOT handled: the extra pieces are left
    unmatched and will surface as potential additions/deletions.
    """
    n_old, n_new = len(old), len(new)
    old_to_new: dict[int, int] = {}
    new_taken: set[int] = set()
    exact: set[int] = set()

    by_hash: dict[str, list[int]] = {}
    for j, p in enumerate(new):
        by_hash.setdefault(p["hash"], []).append(j)
    for i, p in enumerate(old):
        queue = by_hash.get(p["hash"])
        if queue:
            j = queue.pop(0)
            old_to_new[i] = j
            new_taken.add(j)
            exact.add(i)

    exact_new = set(new_taken)
    if n_old and n_new:
        ii, jj = np.where(sim >= threshold)
        order = sorted(zip(ii.tolist(), jj.tolist()), key=lambda ij: (-sim[ij], ij[0], ij[1]))
        for i, j in order:
            if i in old_to_new or j in new_taken:
                continue
            old_to_new[i] = j
            new_taken.add(j)

    matches = []
    for i in sorted(old_to_new):
        j = old_to_new[i]
        s = float(sim[i, j])
        runner = 0.0
        if i not in exact:
            # best competing candidate in this row/column, ignoring exact-matched ones
            row = [float(sim[i, k]) for k in range(n_new) if k != j and k not in exact_new]
            col = [float(sim[k, j]) for k in range(n_old) if k != i and k not in exact]
            runner = max(row + col, default=0.0)
        matches.append({
            "old_idx": i, "new_idx": j, "similarity": s, "exact": i in exact,
            "runner_up": runner,
            "ambiguous": i not in exact and runner >= threshold and runner >= s - margin,
        })

    def nearest(vec):
        return (int(np.argmax(vec)), float(np.max(vec))) if len(vec) else (None, 0.0)

    unmatched_old = [{"old_idx": i, "nearest_idx": nearest(sim[i])[0], "nearest_sim": nearest(sim[i])[1]}
                     for i in range(n_old) if i not in old_to_new]
    unmatched_new = [{"new_idx": j, "nearest_idx": nearest(sim[:, j])[0], "nearest_sim": nearest(sim[:, j])[1]}
                     for j in range(n_new) if j not in new_taken]
    return {"matches": matches, "unmatched_old": unmatched_old, "unmatched_new": unmatched_new}
