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
    """Deduplicate, diversify and trim ranked results into a compact evidence pack."""

    def build(self, query_id: str, route_mode: str, items: list[EvidenceItem], token_budget: int = 2048) -> EvidencePack:
        ordered = self._order_items(route_mode, items)
        deduplicated = self._deduplicate(ordered)

        selected: list[EvidenceItem] = []
        estimated_tokens = 0
        budget = max(int(token_budget), 1)
        document_counts: Counter[str] = Counter()
        type_counts: Counter[str] = Counter()
        max_items = self._max_items(route_mode)
        max_per_document = self._max_per_document(route_mode)

        for item in deduplicated:
            if len(selected) >= max_items:
                break

            document_key = item.document_id or item.source_type
            if document_counts[document_key] >= max_per_document and item.source_type not in {"summary", "graph_edge"}:
                continue

            if self._is_low_signal(item) and selected:
                continue

            item_tokens = self._estimate_tokens(item)
            if selected and estimated_tokens + item_tokens > budget:
                continue

            selected.append(item)
            estimated_tokens += item_tokens
            document_counts[document_key] += 1
            type_counts[item.source_type] += 1

        contradictions = [item for item in selected if self._is_contradictory(item)]
        summaries = [item for item in selected if item.source_type == "summary"]
        groups = self._group_items(selected)

        return EvidencePack(
            query_id=query_id,
            route_mode=route_mode,
            items=selected,
            contradictions=contradictions,
            summaries=summaries,
            token_budget=token_budget,
            estimated_tokens=estimated_tokens,
            selected_count=len(selected),
            budget_utilization=min(1.0, round(estimated_tokens / budget, 3)),
            excluded_count=max(0, len(items) - len(selected)),
            evidence_groups=groups,
        )

    def _order_items(self, route_mode: str, items: list[EvidenceItem]) -> list[EvidenceItem]:
        priorities = {
            "exact": {"chunk": 4, "proposition": 3, "summary": 1, "graph_edge": 1},
            "factual_local": {"chunk": 4, "proposition": 3, "summary": 2, "graph_edge": 1},
            "multi_hop": {"proposition": 4, "graph_edge": 4, "chunk": 3, "summary": 2},
            "global": {"summary": 4, "chunk": 3, "proposition": 2, "graph_edge": 1},
            "argumentative": {"proposition": 4, "chunk": 3, "graph_edge": 3, "summary": 2},
            "visual": {"visual_page": 5, "chunk": 3, "summary": 2, "proposition": 2},
        }.get(route_mode, {})
        return sorted(
            items,
            key=lambda item: (
                priorities.get(item.source_type, 1),
                round(item.score, 6),
                1 if item.document_id else 0,
            ),
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
        metadata_tokens = sum(len(str(value).split()) for value in item.metadata.values()) if item.metadata else 0
        return max(1, snippet_tokens + title_tokens + metadata_tokens + 8)

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
            "exact": 8,
            "factual_local": 8,
            "multi_hop": 10,
            "global": 8,
            "argumentative": 10,
            "visual": 8,
        }.get(route_mode, 8)

    @staticmethod
    def _max_per_document(route_mode: str) -> int:
        return {
            "exact": 3,
            "factual_local": 3,
            "multi_hop": 2,
            "global": 2,
            "argumentative": 2,
            "visual": 2,
        }.get(route_mode, 2)
