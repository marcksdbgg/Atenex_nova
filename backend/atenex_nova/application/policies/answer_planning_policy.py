"""Policies for answer planning."""

from __future__ import annotations

from atenex_nova.application.policies.context_packing_policy import EvidencePack


class AnswerPlanningPolicy:
    """Select a synthesis plan from an evidence pack."""

    def choose_plan(self, evidence_pack: EvidencePack) -> str:
        route_mode = evidence_pack.route_mode
        if route_mode == "visual":
            return "visual_grounded_synthesis"
        if route_mode == "argumentative" or evidence_pack.contradictions:
            return "argument_synthesis"
        if route_mode == "global":
            return "global_synthesis"
        if route_mode in {"exact", "factual_local"}:
            return "direct_answer"

        document_ids = {
            item.document_id
            for item in evidence_pack.items
            if item.document_id is not None
        }
        if route_mode == "multi_hop" and len(document_ids) >= 2:
            return "hierarchical_synthesis"
        if len(evidence_pack.items) > 8 and len(document_ids) >= 2:
            return "hierarchical_synthesis"
        return "direct_answer"
