"""Policies for building evidence packs."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from atenex_nova.domain.entities.evidence_item import EvidenceItem


@dataclass
class EvidencePack:
    query_id: str
    route_mode: str
    items: list[EvidenceItem] = field(default_factory=list)
    contradictions: list[EvidenceItem] = field(default_factory=list)
    summaries: list[EvidenceItem] = field(default_factory=list)
    token_budget: int = 2048
    estimated_tokens: int = 0
    selected_count: int = 0
    budget_utilization: float = 0.0
    excluded_count: int = 0
    evidence_groups: dict[str, list[str]] = field(default_factory=dict)


class ContextPackingPolicy:
    """Build a relevance-first, document-diverse evidence pack.

    Retrieval scores are already fused across engines.  Packing must therefore not
    replace relevance with a hard source-type ordering: doing so allowed weak graph
    edges and propositions to evict stronger documentary chunks.  The policy first
    reserves high-signal evidence across distinct documents and then fills the
    remaining budget by utility.
    """

    def build(
        self,
        query_id: str,
        route_mode: str,
        items: list[EvidenceItem],
        token_budget: int | None = None,
    ) -> EvidencePack:
        ordered = self._order_items(route_mode, items)
        deduplicated = self._deduplicate(ordered)

        selected: list[EvidenceItem] = []
        estimated_tokens = 0
        budget = max(int(token_budget or self._token_budget(route_mode)), 1)
        document_counts: Counter[str] = Counter()
        type_counts: Counter[str] = Counter()
        max_items = self._max_items(route_mode)
        max_per_document = self._max_per_document(route_mode)

        def try_select(item: EvidenceItem) -> bool:
            nonlocal estimated_tokens
            if len(selected) >= max_items or self._is_low_signal(item):
                return False
            document_key = item.document_id or item.source_type
            if document_counts[document_key] >= max_per_document:
                return False
            if type_counts[item.source_type] >= self._max_per_source_type(route_mode, item.source_type):
                return False
            item_tokens = self._estimate_tokens(item)
            if item_tokens > budget or estimated_tokens + item_tokens > budget:
                return False
            selected.append(item)
            estimated_tokens += item_tokens
            document_counts[document_key] += 1
            type_counts[item.source_type] += 1
            return True

        # Coverage pass: take at most one citable item per document before allowing
        # any document (or synthetic source type) to dominate the prompt.
        seen_documents: set[str] = set()
        for item in deduplicated:
            document_key = item.document_id or ""
            if not document_key or document_key in seen_documents:
                continue
            if not item.citation_candidate or item.source_type == "graph_edge":
                continue
            if try_select(item):
                seen_documents.add(document_key)

        # A real text span is more useful to the generator than a pack made only of
        # propositions/summaries. Reserve the strongest chunk when retrieval found
        # one and the coverage pass did not already retain it.
        if not any(item.source_type == "chunk" for item in selected):
            first_chunk = next((item for item in deduplicated if item.source_type == "chunk"), None)
            if first_chunk is not None:
                try_select(first_chunk)

        for item in deduplicated:
            if item in selected:
                continue
            try_select(item)
            if len(selected) >= max_items:
                break

        contradictions = [item for item in selected if self._is_contradictory(item)]
        summaries = [item for item in selected if item.source_type == "summary"]
        groups = self._group_items(selected)

        return EvidencePack(
            query_id=query_id,
            route_mode=route_mode,
            items=selected,
            contradictions=contradictions,
            summaries=summaries,
            token_budget=budget,
            estimated_tokens=estimated_tokens,
            selected_count=len(selected),
            budget_utilization=min(1.0, round(estimated_tokens / budget, 3)),
            excluded_count=max(0, len(items) - len(selected)),
            evidence_groups=groups,
        )

    def _order_items(self, route_mode: str, items: list[EvidenceItem]) -> list[EvidenceItem]:
        quality_weights = {
            "chunk": 1.0,
            "visual_page": 1.0,
            "proposition": 0.94,
            "summary": 0.9,
            "graph_edge": 0.72,
        }
        route_bonus = {
            "global": {"summary": 0.08, "chunk": 0.05},
            "argumentative": {"proposition": 0.06, "chunk": 0.05},
            "multi_hop": {"proposition": 0.05, "chunk": 0.05},
            "visual": {"visual_page": 0.12},
        }.get(route_mode, {})

        def utility(item: EvidenceItem) -> tuple[float, float, int]:
            weighted_score = item.score * quality_weights.get(item.source_type, 0.85)
            weighted_score += route_bonus.get(item.source_type, 0.0)
            if item.citation_candidate and item.document_id:
                weighted_score += 0.04
            return weighted_score, item.score, 1 if item.document_id else 0

        return sorted(
            items,
            key=utility,
            reverse=True,
        )

    def _deduplicate(self, items: list[EvidenceItem]) -> list[EvidenceItem]:
        deduplicated: list[EvidenceItem] = []
        seen_signatures: set[str] = set()
        for item in items:
            normalized_snippet = " ".join(item.snippet[:160].strip().lower().split())
            signature = f"{item.source_type}:{item.document_id}:{normalized_snippet}"
            if signature in seen_signatures:
                continue
            seen_signatures.add(signature)
            deduplicated.append(item)
        return deduplicated

    @staticmethod
    def _estimate_tokens(item: EvidenceItem) -> int:
        snippet_tokens = len(item.snippet.split())
        title_tokens = len(item.title.split()) if item.title else 0
        # Prompt formatting includes the compact snippet and location, but not
        # metadata.source_text (which may contain an entire transcript).
        return max(1, snippet_tokens + title_tokens + 12)

    @staticmethod
    def _is_contradictory(item: EvidenceItem) -> bool:
        lower = item.snippet.lower()
        if any(marker in lower for marker in ("however", "but", "sin embargo", "contradict", "no obstante")):
            return True
        relation = str(item.metadata.get("relation") or "").lower()
        return relation in {"contradicts", "conflicts", "supports_and_refutes"}

    @staticmethod
    def _is_low_signal(item: EvidenceItem) -> bool:
        snippet = item.snippet.strip()
        if len(snippet) < 24 and item.source_type != "graph_edge":
            return True
        return item.source_type == "summary" and len(snippet.split()) < 6

    @staticmethod
    def _group_items(items: list[EvidenceItem]) -> dict[str, list[str]]:
        groups: dict[str, list[str]] = {}
        for item in items:
            heading_path = item.metadata.get("heading_path")
            if isinstance(heading_path, list) and heading_path:
                label = " / ".join(str(part) for part in heading_path[:3])
            else:
                label = item.title or item.document_id or item.source_type
            key = f"{item.source_type}:{label}"
            groups.setdefault(key, []).append(item.id)
        return groups

    @staticmethod
    def _max_items(route_mode: str) -> int:
        return {
            "exact": 10,
            "factual_local": 12,
            "multi_hop": 24,
            "global": 24,
            "argumentative": 24,
            "visual": 10,
        }.get(route_mode, 12)

    @staticmethod
    def _max_per_document(route_mode: str) -> int:
        return {
            "exact": 4,
            "factual_local": 4,
            "multi_hop": 4,
            "global": 4,
            "argumentative": 4,
            "visual": 3,
        }.get(route_mode, 4)

    @staticmethod
    def _max_per_source_type(route_mode: str, source_type: str) -> int:
        if source_type == "graph_edge":
            return 2
        if source_type == "summary":
            return 8 if route_mode == "global" else 4
        return ContextPackingPolicy._max_items(route_mode)

    @staticmethod
    def _token_budget(route_mode: str) -> int:
        return {
            "exact": 2400,
            "factual_local": 3200,
            "multi_hop": 6000,
            "global": 6000,
            "argumentative": 6000,
            "visual": 3600,
        }.get(route_mode, 3200)
