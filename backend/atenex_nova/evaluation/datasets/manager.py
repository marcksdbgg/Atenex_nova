"""Golden set loading and defaults."""

from __future__ import annotations

import json
from pathlib import Path

from atenex_nova.evaluation.models import GoldenCase, GoldenSet
from atenex_nova.domain.value_objects.identifiers import new_id


class GoldenSetManager:
    def __init__(self, base_path: Path | None = None) -> None:
        self._base_path = base_path or Path(__file__).resolve().parent

    def list_datasets(self) -> list[str]:
        datasets = {"baseline"}
        for path in self._base_path.glob("*.json"):
            datasets.add(path.stem)
        return sorted(datasets)

    def load(self, name: str = "baseline") -> GoldenSet:
        path = self._base_path / f"{name}.json"
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return GoldenSet(
                name=data["name"],
                description=data.get("description", ""),
                cases=[
                    GoldenCase(
                        id=item.get("id") or new_id(),
                        category=item["category"],
                        question=item["question"],
                        expected_answer=item.get("expected_answer", ""),
                        expected_keywords=list(item.get("expected_keywords", [])),
                        route_mode=item.get("route_mode", "auto"),
                        mode=item.get("mode", "auto"),
                    )
                    for item in data.get("cases", [])
                ],
            )
        return GoldenSet(
            name="baseline",
            description="Built-in baseline dataset for Atenex Nova evaluation",
            cases=[
                GoldenCase(
                    id=new_id(),
                    category="exact",
                    question="What does EmbeddingGemma support?",
                    expected_answer="384d embeddings",
                    expected_keywords=["EmbeddingGemma", "384d"],
                    route_mode="factual_local",
                ),
                GoldenCase(
                    id=new_id(),
                    category="global",
                    question="Summarize the corpus",
                    expected_answer="local retrieval and proposition graphs",
                    expected_keywords=["summary", "corpus"],
                    route_mode="global",
                ),
                GoldenCase(
                    id=new_id(),
                    category="visual",
                    question="What does the table on page 1 show?",
                    expected_answer="table",
                    expected_keywords=["table", "page 1"],
                    route_mode="visual",
                ),
                GoldenCase(
                    id=new_id(),
                    category="argumentative",
                    question="Does the document mention proposition graphs?",
                    expected_answer="proposition graphs",
                    expected_keywords=["proposition", "graph"],
                    route_mode="multi_hop",
                ),
            ],
        )
