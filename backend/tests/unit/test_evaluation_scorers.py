"""Unit tests for evaluation datasets, scorers and regression comparator."""

from atenex_nova.evaluation.datasets.manager import GoldenSetManager
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
    assert metrics["source_recall"] == 1.0


def test_answer_scorer_reports_grounding_and_relevance() -> None:
    scorer = AnswerScorer()
    metrics = scorer.score(
        "EmbeddingGemma supports 384d embeddings [1].",
        "384d embeddings",
        1,
        evidence_texts=["EmbeddingGemma supports 384d embeddings."],
    )

    assert metrics["relevance"] > 0
    assert metrics["support_coverage"] > 0
    assert metrics["citation_coverage"] > 0
    assert metrics["grounding"] > 0
    assert metrics["overall"] > 0


def test_answer_scorer_penalizes_uncited_and_forbidden_claims() -> None:
    scorer = AnswerScorer()
    metrics = scorer.score(
        "La libertad exige vida [1]. No hay evidencia sobre eutanasia.",
        "La muerte anula la libertad",
        1,
        evidence_texts=["La libertad solo puede ejercerse mientras existe vida."],
        required_claims=[["libertad", "vida"], ["muerte", "anula"]],
        forbidden_phrases=["no hay evidencia"],
        min_citations=2,
    )

    assert metrics["claim_coverage"] < 1.0
    assert metrics["citation_coverage"] == 0.0
    assert metrics["forbidden_phrase_rate"] == 1.0
    assert metrics["overall"] < 0.7


def test_retrieval_scorer_measures_source_and_document_coverage() -> None:
    metrics = RetrievalScorer().score(
        [
            {
                "title": "Don Quixote versus euthanasia",
                "snippet": "libertad vida muerte",
                "document_id": "doc-1",
            },
            {
                "title": "Literature defends life",
                "snippet": "literatura y vida",
                "document_id": "doc-2",
            },
        ],
        ["libertad", "literatura"],
        expected_source_patterns=["euthanasia", "defends life"],
        min_distinct_documents=2,
    )

    assert metrics["source_recall"] == 1.0
    assert metrics["document_diversity"] == 1.0


def test_regression_comparator_computes_deltas() -> None:
    comparator = RegressionComparator()
    deltas = comparator.compare({"a": 1.0, "b": 2.0}, {"a": 1.5, "c": 4.0})

    assert deltas["a"] == 0.5
    assert deltas["b"] == -2.0
    assert deltas["c"] == 4.0


def test_jesus_g_argumentation_dataset_has_stable_reviewable_cases() -> None:
    dataset = GoldenSetManager().load("jesus_g_argumentation")

    assert dataset.name == "jesus_g_argumentation"
    assert len(dataset.cases) >= 8
    assert len({case.id for case in dataset.cases}) == len(dataset.cases)
    assert {case.category for case in dataset.cases} >= {
        "argumentative",
        "multi_hop",
        "global",
    }
    assert all(case.expected_keywords for case in dataset.cases)
