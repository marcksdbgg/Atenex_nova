"""Unit tests for query routing policy."""

from atenex_nova.application.policies.query_routing_policy import QueryRoutingPolicy
from atenex_nova.domain.value_objects.identifiers import QueryIntent, QueryMode


class TestQueryRoutingPolicy:
    def setup_method(self) -> None:
        self.policy = QueryRoutingPolicy()

    def test_exact_query_routes_to_exact_mode(self) -> None:
        features = self.policy.extract_features("Find the document ID 1234-ABCD-5678")
        assert self.policy.choose_mode(features) == QueryMode.EXACT
        assert self.policy.classify_intent(features) == QueryIntent.EXACT

    def test_global_query_routes_to_global_mode(self) -> None:
        features = self.policy.extract_features("Give me an overall summary of the corpus")
        assert self.policy.choose_mode(features) == QueryMode.GLOBAL
        assert self.policy.classify_intent(features) == QueryIntent.GLOBAL

    def test_visual_query_routes_to_visual_mode(self) -> None:
        features = self.policy.extract_features("What does the table on page 3 show?")
        assert self.policy.choose_mode(features) == QueryMode.VISUAL
        assert self.policy.classify_intent(features) == QueryIntent.VISUAL

    def test_argumentative_query_routes_to_argumentative_mode(self) -> None:
        features = self.policy.extract_features("Why does this document contradict the earlier claim?")
        assert self.policy.choose_mode(features) == QueryMode.ARGUMENTATIVE
        assert self.policy.classify_intent(features) == QueryIntent.ARGUMENTATIVE

    def test_detect_language_spanish_question(self) -> None:
        features = self.policy.extract_features(
            "Explica la neotenia literaria en 3 ideas y agrega 3 citas con referencia."
        )
        assert features.language == "es"

    def test_detect_language_english_question(self) -> None:
        features = self.policy.extract_features(
            "Explain literary neoteny in three concise points and cite the source documents."
        )
        assert features.language == "en"