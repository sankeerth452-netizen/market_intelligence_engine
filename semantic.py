"""
semantic.py
-----------
Semantic content-gap analysis.

The original spec's gap check was binary: "does a page exist? yes/no."
That misses the common case where a page exists but answers none of the
questions people are actually asking.

Here we embed both the live demand ("hidden costs, site costs, delays...")
and the existing site pages into a shared TF-IDF vector space, then measure
the *cosine distance* from the demand to its nearest page. A high gap means
the topic is genuinely under-served, even if some loosely related page exists.

TF-IDF keeps this fully offline (no model downloads). The interface is
deliberately simple so it can later be swapped for transformer embeddings.
"""
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np


class SemanticIndex:
    def __init__(self, page_texts, fit_corpus=None):
        self.pages = list(page_texts)
        corpus = list(fit_corpus) if fit_corpus else list(self.pages)
        if not corpus:
            corpus = ["placeholder"]
        # Fit vocabulary over the union of site + demand text so both are comparable.
        self.vec = TfidfVectorizer(stop_words="english").fit(corpus)
        self.page_mat = self.vec.transform(self.pages) if self.pages else None

    def gap(self, demand_text: str) -> float:
        """1 - (best cosine similarity to any existing page). Range 0..1."""
        if self.page_mat is None or self.page_mat.shape[0] == 0:
            return 1.0
        q = self.vec.transform([demand_text])
        best = float(cosine_similarity(q, self.page_mat)[0].max())
        return float(np.clip(1.0 - best, 0.0, 1.0))

    def similarity(self, a: str, b: str) -> float:
        """Cosine similarity between two pieces of text (used for de-duplication)."""
        m = self.vec.transform([a, b])
        return float(cosine_similarity(m[0], m[1])[0, 0])
