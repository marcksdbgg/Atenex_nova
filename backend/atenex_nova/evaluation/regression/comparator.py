"""Run-to-run regression comparison."""

from __future__ import annotations


class RegressionComparator:
    def compare(self, previous: dict[str, float], current: dict[str, float]) -> dict[str, float]:
        keys = sorted(set(previous) | set(current))
        return {key: round(current.get(key, 0.0) - previous.get(key, 0.0), 3) for key in keys}