"""Policies for answer planning."""

from __future__ import annotations

from atenex_nova.application.policies.context_packing_policy import EvidencePack


class AnswerPlanningPolicy:
    """Select a synthesis plan from an evidence pack."""

    def choose_plan(self, evidence_pack: EvidencePack) -> str:
        if evidence_pack.route_mode == "visual":
            return "visual_grounded_synthesis"
        if evidence_pack.contradictions:
            return "argument_synthesis"
        if len(evidence_pack.items) > 8:
            return "hierarchical_synthesis"
        if evidence_pack.summaries:
            return "global_synthesis"
        return "direct_answer"