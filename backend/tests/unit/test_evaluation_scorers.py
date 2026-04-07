"""Unit tests for evaluation scorers and regression comparator."""

from atenex_nova.evaluation.regression.comparator import RegressionComparator
from atenex_nova.evaluation.scorers.answer_scorer import AnswerScorer
from atenex_nova.evaluation.scorers.retrieval_scorer import RetrievalScorer


def test_retrieval_scorer_detects_keyword_matches() -> None:
    scorer = RetrievalScorer()
    metrics = scorer.score(
        [
            {"title": "EmbeddingGemma notes", "snippet": "EmbeddingGemma supports 384d embeddings."},
            {"title": "Other", "snippet": "Unrelated text."},
        ],
        ["EmbeddingGemma", "384d"],
    )

    assert metrics["recall_at_k"] > 0
    assert metrics["mrr"] > 0
    assert metrics["ndcg"] > 0


def test_answer_scorer_reports_grounding_and_relevance() -> None:
    scorer = AnswerScorer()
    metrics = scorer.score("EmbeddingGemma supports 384d embeddings.", "384d embeddings", 2)

    assert metrics["relevance"] > 0
    assert metrics["grounding"] > 0
    assert metrics["overall"] > 0


def test_regression_comparator_computes_deltas() -> None:
    comparator = RegressionComparator()
    deltas = comparator.compare({"a": 1.0, "b": 2.0}, {"a": 1.5, "c": 4.0})

    assert deltas["a"] == 0.5
    assert deltas["b"] == -2.0
    assert deltas["c"] == 4.0