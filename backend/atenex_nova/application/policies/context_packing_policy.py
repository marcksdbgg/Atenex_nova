"""Policies for building evidence packs."""

from __future__ import annotations

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


class ContextPackingPolicy:
    """Deduplicate and trim ranked results into a compact evidence pack."""

    def build(self, query_id: str, route_mode: str, items: list[EvidenceItem], token_budget: int = 2048) -> EvidencePack:
        deduplicated: list[EvidenceItem] = []
        seen_signatures: set[str] = set()
        for item in sorted(items, key=lambda item: item.score, reverse=True):
            signature = f"{item.source_type}:{item.source_id}:{item.snippet[:120].strip().lower()}"
            if signature in seen_signatures:
                continue
            seen_signatures.add(signature)
            deduplicated.append(item)

        selected = deduplicated[: min(len(deduplicated), 12)]
        contradictions = [item for item in selected if self._is_contradictory(item.snippet)]
        summaries = [item for item in selected if item.source_type == "summary"]
        return EvidencePack(
            query_id=query_id,
            route_mode=route_mode,
            items=selected,
            contradictions=contradictions,
            summaries=summaries,
            token_budget=token_budget,
        )

    @staticmethod
    def _is_contradictory(text: str) -> bool:
        lower = text.lower()
        markers = ("however", "but", "sin embargo", "contradict", "although", "no obstante")
        return any(marker in lower for marker in markers)