"""Semantic content-gap index: gap is a real distance, not a yes/no flag."""
import pytest

from semantic import SemanticIndex


def test_gap_is_one_when_no_pages_exist():
    idx = SemanticIndex([], fit_corpus=["some demand text about homes"])
    assert idx.gap("anything at all") == pytest.approx(1.0)


def test_gap_smaller_for_a_covered_topic():
    pages = ["split level homes sloping block design floor plans"]
    covered = "split level homes sloping block design"
    uncovered = "first home buyer grant deposit eligibility timeline"
    idx = SemanticIndex(pages, fit_corpus=pages + [covered, uncovered])
    assert idx.gap(covered) < idx.gap(uncovered)


def test_char_ngrams_match_morphology():
    """char n-grams match singular/plural (laptop vs laptops) that word TF-IDF misses."""
    pages = ["ultrabook laptops fourteen inch", "wireless noise cancelling headphones"]
    word = SemanticIndex(pages, fit_corpus=pages, char_ngrams=False)
    char = SemanticIndex(pages, fit_corpus=pages, char_ngrams=True)
    assert char.gap("laptop") < word.gap("laptop")     # char bridges the plural


def test_similarity_is_one_for_identical_text_and_symmetric():
    idx = SemanticIndex(["alpha beta gamma delta"],
                        fit_corpus=["alpha beta gamma delta",
                                    "alpha beta xray yankee",
                                    "echo foxtrot golf hotel"])
    a, b = "alpha beta gamma delta", "alpha beta xray yankee"
    assert idx.similarity(a, a) == pytest.approx(1.0, abs=1e-6)
    assert idx.similarity(a, b) == pytest.approx(idx.similarity(b, a))
