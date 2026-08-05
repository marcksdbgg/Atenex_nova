"""Answer orchestration, verification and citation binding."""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypedDict

from atenex_nova.application.orchestrators.retrieval_orchestrator import SearchResult
from atenex_nova.application.policies.answer_planning_policy import AnswerPlanningPolicy
from atenex_nova.application.policies.query_routing_policy import QueryRoutingPolicy
from atenex_nova.domain.entities.answer import Answer
from atenex_nova.domain.entities.citation import Citation
from atenex_nova.domain.entities.evidence_item import EvidenceItem
from atenex_nova.domain.value_objects.identifiers import AnswerVerdict, new_id
from atenex_nova.infrastructure.llm.llm_gateway import (
    LlamaCppAdapter,
    LLMGateway,
    LLMGenerationResult,
    OllamaAdapter,
)
from atenex_nova.shared.config.settings import get_settings
from atenex_nova.shared.exceptions.base import ServiceUnavailableError, StrictModeViolationError
from atenex_nova.shared.logging.logger import get_logger

logger = get_logger(__name__)

TOKEN_RE = re.compile(r"[\w\-]+", re.UNICODE)
CITATION_MARKER_RE = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
CLAIM_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=(?:[A-ZÁÉÍÓÚÑ¿¡]|\d))")
SUPPORT_STOPWORDS = {
    "a",
    "al",
    "an",
    "and",
    "are",
    "as",
    "con",
    "como",
    "de",
    "del",
    "el",
    "en",
    "es",
    "esta",
    "este",
    "for",
    "from",
    "in",
    "is",
    "la",
    "las",
    "lo",
    "los",
    "of",
    "on",
    "or",
    "para",
    "por",
    "que",
    "se",
    "sin",
    "su",
    "sus",
    "the",
    "to",
    "un",
    "una",
    "with",
    "y",
}


class ClaimSupportRecord(TypedDict):
    claim: int
    text: str
    referenced_evidence_indices: list[int]
    valid_evidence_indices: list[int]
    citable_evidence_indices: list[int]
    support_by_evidence: dict[str, float]
    support_score: float
    supported: bool


class ClaimSupportAudit(TypedDict):
    claim_count: int
    cited_claims: int
    supported_claims: int
    citation_coverage: float
    support_coverage: float
    mean_lexical_support: float
    claims: list[ClaimSupportRecord]


PROMPT_FILES = {
    "direct_answer": "DIRECT_ANSWER_PROMPT.md",
    "hierarchical_synthesis": "HIERARCHICAL_MAP_PROMPT.md",
    "hierarchical_reduce": "HIERARCHICAL_REDUCE_PROMPT.md",
    "global_synthesis": "GLOBAL_SYNTHESIS_PROMPT.md",
    "argument_synthesis": "ARGUMENT_SYNTHESIS_PROMPT.md",
    "visual_grounded_synthesis": "VISUAL_GROUNDED_PROMPT.md",
    "verification": "VERIFICATION_PROMPT.md",
}


@dataclass(slots=True)
class VerificationResult:
    verdict: AnswerVerdict
    grounding_score: float
    issues: list[str]


@dataclass(slots=True)
class AnswerBundle:
    query_id: str
    collection_id: str
    query_text: str
    normalized_query: str
    query_language: str
    query_intent: str
    route_mode: str
    route_reason: str
    plan_type: str
    answer: Answer
    citations: list[Citation]
    evidence_items: list[EvidenceItem]
    prompt: str
    draft_text: str
    verification: VerificationResult


@dataclass(slots=True)
class StagedGeneration:
    """Final generation plus bounded metadata for a real map/reduce run."""

    result: LLMGenerationResult
    prompt: str
    stages: list[dict[str, object]]


class AnswerOrchestrator:
    """Create grounded answers from an evidence pack."""

    def __init__(self, generator: LLMGateway | None = None) -> None:
        settings = get_settings()
        self._settings = settings
        self._planner = AnswerPlanningPolicy()
        self._generator = generator or self._build_generator(settings.llm_backend)

    async def compose(
        self,
        search_result: SearchResult,
        generation_profile: str = "standard",
        chat_history: list[Any] | None = None,
    ) -> AnswerBundle:
        plan_type = self._planner.choose_plan(search_result.evidence_pack)
        logger.info(
            f"Composing answer for query: '{search_result.query.text}' | "
            f"Routed Mode: {search_result.evidence_pack.route_mode} | "
            f"Plan Type: {plan_type} | Evidence Pack size: {len(search_result.evidence_pack.items)} hits"
        )

        # Ensure chat history fits in token budget (e.g. max prompt size of 8000 tokens)
        max_prompt_tokens = 8000
        while chat_history and (len(self._build_prompt(search_result, plan_type, generation_profile, chat_history)) // 4) > max_prompt_tokens:
            chat_history = chat_history[1:]

        prompt = self._build_prompt(search_result, plan_type, generation_profile, chat_history)
        staged_generation = await self._generate_for_plan(
            search_result=search_result,
            plan_type=plan_type,
            generation_profile=generation_profile,
            chat_history=chat_history,
            fallback_prompt=prompt,
        )
        prompt = staged_generation.prompt
        gen_res = staged_generation.result
        draft_text = gen_res.text
        input_token_count = int(gen_res.prompt_tokens or 0)
        output_token_count = int(gen_res.completion_tokens or 0)
        citations = self._bind_citations(search_result.evidence_pack.items, draft_text)
        answer_text = self._finalize_text(
            draft_text,
            citations,
            search_result.evidence_pack.route_mode,
            plan_type,
            search_result.query.language,
        )
        verification = await self._verify(search_result, answer_text, plan_type, citations)
        attempts = 1

        if self._should_retry_generation(verification, citations):
            repair_prompt = self._build_repair_prompt(
                prompt,
                verification.issues,
                search_result.query.language,
            )
            try:
                repaired_gen = await self._generate(repair_prompt, plan_type)
                repaired_draft = repaired_gen.text
                repaired_citations = self._bind_citations(search_result.evidence_pack.items, repaired_draft)
                repaired_answer = self._finalize_text(
                    repaired_draft,
                    repaired_citations,
                    search_result.evidence_pack.route_mode,
                    plan_type,
                    search_result.query.language,
                )
                repaired_verification = await self._verify(
                    search_result,
                    repaired_answer,
                    plan_type,
                    repaired_citations,
                )
                attempts = 2
                input_token_count += int(repaired_gen.prompt_tokens or 0)
                output_token_count += int(repaired_gen.completion_tokens or 0)
                repair_selected = self._is_better_attempt(
                    verification,
                    citations,
                    repaired_verification,
                    repaired_citations,
                )
                staged_generation.stages.append(
                    {
                        "stage": "verification_repair",
                        "selected": repair_selected,
                        "prompt_tokens": int(repaired_gen.prompt_tokens or 0),
                        "completion_tokens": int(repaired_gen.completion_tokens or 0),
                    }
                )
                if repair_selected:
                    prompt = repair_prompt
                    draft_text = repaired_draft
                    citations = repaired_citations
                    answer_text = repaired_answer
                    verification = repaired_verification
                    verification.issues = sorted(
                        set([*verification.issues, "regenerated_after_failed_verification"]),
                    )
            except ServiceUnavailableError:
                pass

        if "wrong_output_language" in verification.issues and search_result.query.language.startswith("es"):
            answer_text = (
                "No pude producir una respuesta en español suficientemente fundamentada "
                "con la evidencia recuperada. Reformula la pregunta o revisa los fragmentos disponibles."
            )
            citations = []
            verification = VerificationResult(
                verdict=AnswerVerdict.UNVERIFIED,
                grounding_score=0.0,
                issues=sorted(set([*verification.issues, "spanish_fallback_after_language_failure"])),
            )

        logger.info(
            f"Answer composition finished (attempts={attempts}) | Verdict: {verification.verdict} | "
            f"Grounding Score: {verification.grounding_score:.3f} | Citations: {len(citations)} | Issues: {verification.issues}"
        )

        self._enforce_strict_answer(answer_text, citations, verification, search_result.query.route_mode)

        serialized_history = []
        if chat_history:
            for msg in chat_history:
                if isinstance(msg, dict):
                    serialized_history.append(msg)
                else:
                    serialized_history.append({
                        "role": getattr(msg, "role", "user"),
                        "content": getattr(msg, "content", "")
                    })

        answer = Answer(
            id=new_id(),
            query_id=search_result.query.id,
            plan_type=plan_type,
            text=answer_text,
            grounding_score=verification.grounding_score,
            verdict=verification.verdict.value,
            prompt_version="v2",
            draft_text=draft_text,
            verification_issues=verification.issues,
            evidence_trace={
                "route_reason": search_result.route_reason,
                "evidence_groups": search_result.evidence_pack.evidence_groups,
                "excluded_evidence_count": search_result.evidence_pack.excluded_count,
                "selected_count": search_result.evidence_pack.selected_count,
                "selected_evidence": [
                    self._serialize_evidence_item(item) for item in search_result.evidence_pack.items
                ],
                "generation_attempts": attempts,
                "synthesis_stages": staged_generation.stages,
                "citation_audit": self._build_citation_audit(
                    search_result.evidence_pack.items,
                    answer_text,
                    citations,
                ),
                "claim_audit": self._build_claim_support_audit(
                    search_result.evidence_pack.items,
                    answer_text,
                ),
                "prompt_trace": self._build_prompt_trace(
                    search_result=search_result,
                    plan_type=plan_type,
                    generation_profile=generation_profile,
                    prompt=prompt,
                ),
            },
            full_prompt=prompt if self._settings.store_prompts else None,
            input_token_count=input_token_count,
            output_token_count=output_token_count,
            chat_history_used=bool(chat_history),
            chat_history_json=json.dumps(serialized_history) if chat_history else None,
        )
        return AnswerBundle(
            query_id=search_result.query.id,
            collection_id=search_result.query.collection_id,
            query_text=search_result.query.text,
            normalized_query=search_result.query.normalized_text,
            query_language=search_result.query.language,
            query_intent=search_result.query.intent,
            route_mode=search_result.query.route_mode,
            route_reason=search_result.route_reason,
            plan_type=plan_type,
            answer=answer,
            citations=citations,
            evidence_items=search_result.evidence_pack.items,
            prompt=prompt,
            draft_text=draft_text,
            verification=verification,
        )

    @staticmethod
    def _should_retry_generation(verification: VerificationResult, citations: list[Citation]) -> bool:
        if verification.verdict in {AnswerVerdict.UNVERIFIED, AnswerVerdict.CONFLICTING}:
            return True
        if verification.grounding_score < 0.55:
            return True
        return not citations

    @staticmethod
    def _is_better_attempt(
        previous: VerificationResult,
        previous_citations: list[Citation],
        current: VerificationResult,
        current_citations: list[Citation],
    ) -> bool:
        verdict_rank = {
            AnswerVerdict.UNVERIFIED: 0,
            AnswerVerdict.CONFLICTING: 1,
            AnswerVerdict.PARTIALLY_VERIFIED: 2,
            AnswerVerdict.VERIFIED: 3,
        }
        previous_tuple = (
            verdict_rank[previous.verdict],
            previous.grounding_score,
            len(previous_citations),
            -len(previous.issues),
        )
        current_tuple = (
            verdict_rank[current.verdict],
            current.grounding_score,
            len(current_citations),
            -len(current.issues),
        )
        return current_tuple > previous_tuple

    @staticmethod
    def _build_repair_prompt(prompt: str, issues: list[str], query_language: str) -> str:
        issue_text = ", ".join(issues) if issues else "low grounding"
        if query_language.startswith("es"):
            return (
                f"{prompt}\n\n"
                "### Corrección posterior a la verificación\n"
                f"El borrador anterior tuvo estos problemas: {issue_text}.\n"
                "Reescribe la respuesta exclusivamente en español y usa solo afirmaciones sostenidas "
                "por la evidencia. Coloca cada cita [1], [2] junto a la afirmación que respalda.\n"
                "No cites resúmenes sin documento ni relaciones del grafo como si fueran citas textuales. "
                "Si la evidencia no basta, dilo de forma explícita y breve.\n"
            )
        return (
            f"{prompt}\n\n"
            "### Verification Repair\n"
            f"The previous draft had these problems: {issue_text}.\n"
            "Regenerate the answer with only grounded claims, explicit inline citations like [1], [2], and clear uncertainty if evidence is insufficient.\n"
            "Do not add claims without support in the evidence block.\n"
        )

    async def _generate_for_plan(
        self,
        search_result: SearchResult,
        plan_type: str,
        generation_profile: str,
        chat_history: list[Any] | None,
        fallback_prompt: str,
    ) -> StagedGeneration:
        staged_plans = {
            "hierarchical_synthesis",
            "global_synthesis",
            "argument_synthesis",
        }
        groups = self._build_synthesis_groups(search_result.evidence_pack.items)
        if plan_type not in staged_plans or len(groups) < 2:
            result = await self._generate(fallback_prompt, plan_type)
            return StagedGeneration(result=result, prompt=fallback_prompt, stages=[])

        map_outputs: list[tuple[str, str]] = []
        stages: list[dict[str, object]] = []
        prompt_tokens = 0
        completion_tokens = 0
        preview_limit = max(0, int(self._settings.synthesis_trace_preview_chars))

        for group_number, (label, indexed_items) in enumerate(groups, start=1):
            map_prompt = self._build_map_prompt(
                search_result=search_result,
                plan_type=plan_type,
                generation_profile=generation_profile,
                group_label=label,
                indexed_items=indexed_items,
            )
            map_result = await self._generate_with_limits(
                map_prompt,
                max_tokens=max(128, int(self._settings.synthesis_map_max_tokens)),
                temperature=0.1,
            )
            memo = map_result.text.strip()
            map_outputs.append((label, memo))
            prompt_tokens += int(map_result.prompt_tokens or 0)
            completion_tokens += int(map_result.completion_tokens or 0)
            stages.append(
                {
                    "stage": "map",
                    "group": group_number,
                    "label": label,
                    "evidence_indices": [index for index, _item in indexed_items],
                    "document_ids": sorted(
                        {
                            item.document_id
                            for _index, item in indexed_items
                            if item.document_id is not None
                        }
                    ),
                    "prompt_tokens": int(map_result.prompt_tokens or 0),
                    "completion_tokens": int(map_result.completion_tokens or 0),
                    "memo_preview": memo[:preview_limit] if preview_limit else "",
                }
            )

        reduce_prompt = self._build_reduce_prompt(
            search_result=search_result,
            plan_type=plan_type,
            generation_profile=generation_profile,
            chat_history=chat_history,
            map_outputs=map_outputs,
        )
        reduce_result = await self._generate_with_limits(
            reduce_prompt,
            max_tokens=max(256, int(self._settings.synthesis_reduce_max_tokens)),
            temperature=0.2,
        )
        prompt_tokens += int(reduce_result.prompt_tokens or 0)
        completion_tokens += int(reduce_result.completion_tokens or 0)
        stages.append(
            {
                "stage": "reduce",
                "groups": len(map_outputs),
                "prompt_tokens": int(reduce_result.prompt_tokens or 0),
                "completion_tokens": int(reduce_result.completion_tokens or 0),
            }
        )
        return StagedGeneration(
            result=LLMGenerationResult(
                text=reduce_result.text,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            ),
            prompt=reduce_prompt,
            stages=stages,
        )

    def _build_synthesis_groups(
        self,
        items: list[EvidenceItem],
    ) -> list[tuple[str, list[tuple[int, EvidenceItem]]]]:
        raw_groups: dict[str, list[tuple[int, EvidenceItem]]] = {}
        labels: dict[str, str] = {}
        for index, item in enumerate(items, start=1):
            key = item.document_id or f"{item.source_type}:{item.title or item.source_id}"
            label = item.title or item.document_id or item.source_type
            raw_groups.setdefault(key, []).append((index, item))
            labels.setdefault(key, label)

        grouped = [(labels[key], value) for key, value in raw_groups.items()]
        max_calls = max(1, int(self._settings.synthesis_max_map_calls))
        if len(grouped) <= max_calls:
            return grouped

        # Preserve every selected evidence item while bounding local LLM calls.
        # Groups are distributed deterministically, keeping each document intact.
        buckets: list[list[tuple[str, list[tuple[int, EvidenceItem]]]]] = [
            [] for _ in range(max_calls)
        ]
        bucket_sizes = [0] * max_calls
        for group in grouped:
            target = min(range(max_calls), key=lambda index: bucket_sizes[index])
            buckets[target].append(group)
            bucket_sizes[target] += len(group[1])

        merged: list[tuple[str, list[tuple[int, EvidenceItem]]]] = []
        for bucket in buckets:
            if not bucket:
                continue
            bucket_labels = [label for label, _indexed in bucket]
            label = " | ".join(bucket_labels[:3])
            if len(bucket_labels) > 3:
                label += f" | +{len(bucket_labels) - 3} documentos"
            indexed_items = [pair for _label, pairs in bucket for pair in pairs]
            indexed_items.sort(key=lambda pair: pair[0])
            merged.append((label, indexed_items))
        return merged

    def _build_map_prompt(
        self,
        search_result: SearchResult,
        plan_type: str,
        generation_profile: str,
        group_label: str,
        indexed_items: list[tuple[int, EvidenceItem]],
    ) -> str:
        template = self._load_prompt("hierarchical_synthesis")
        replacements = {
            "{{QUERY}}": search_result.query.text,
            "{{PLAN}}": plan_type,
            "{{GENERATION_PROFILE}}": generation_profile,
            "{{ROUTE_REASON}}": search_result.route_reason,
            "{{LANGUAGE}}": "español" if search_result.query.language.startswith("es") else "English",
            "{{GROUP_LABEL}}": group_label,
            "{{EVIDENCE}}": self._format_indexed_evidence(indexed_items),
            "{{UNCERTAINTY_POLICY}}": (
                "Distingue evidencia explícita, inferencia razonable y ausencia de soporte."
                if search_result.query.language.startswith("es")
                else "Separate explicit evidence, reasonable inference, and missing support."
            ),
            "{{REDUCE_INSTRUCTIONS}}": "",
        }
        for key, value in replacements.items():
            template = template.replace(key, value)
        return template

    def _build_reduce_prompt(
        self,
        search_result: SearchResult,
        plan_type: str,
        generation_profile: str,
        chat_history: list[Any] | None,
        map_outputs: list[tuple[str, str]],
    ) -> str:
        template = self._load_prompt("hierarchical_reduce")
        memo_limit = max(400, int(self._settings.synthesis_trace_preview_chars))
        mapped = "\n\n".join(
            f"### Grupo {index}: {label}\n{memo[:memo_limit]}"
            for index, (label, memo) in enumerate(map_outputs, start=1)
        )
        replacements = {
            "{{QUERY}}": search_result.query.text,
            "{{PLAN}}": plan_type,
            "{{GENERATION_PROFILE}}": generation_profile,
            "{{ROUTE_REASON}}": search_result.route_reason,
            "{{LANGUAGE}}": "español" if search_result.query.language.startswith("es") else "English",
            "{{MAP_OUTPUTS}}": mapped,
            "{{EVIDENCE}}": self._format_evidence(search_result.evidence_pack.items),
        }
        for key, value in replacements.items():
            template = template.replace(key, value)

        if chat_history:
            turns: list[str] = []
            for message in chat_history:
                if isinstance(message, dict):
                    role = str(message.get("role", "user"))
                    content = str(message.get("content", ""))
                else:
                    role = str(getattr(message, "role", "user"))
                    content = str(getattr(message, "content", ""))
                turns.append(f"[{role}]: {content}")
            template = "Conversation history:\n" + "\n".join(turns) + "\n\n" + template
        return template

    @staticmethod
    def _format_indexed_evidence(indexed_items: list[tuple[int, EvidenceItem]]) -> str:
        lines: list[str] = []
        for index, item in indexed_items:
            location = f"doc={item.document_id or 'n/a'}"
            if item.page_number is not None:
                location += f" page={item.page_number}"
            lines.append(
                f"[{index}] {item.source_type} score={item.score:.3f} {location} "
                f"title={item.title or 'n/a'} :: {item.snippet}"
            )
        return "\n".join(lines)

    async def _generate_with_limits(
        self,
        prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> LLMGenerationResult:
        result = await self._generator.generate(
            prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            stop=["\n[User]", "\n[Assistant]", "\n<END>"],
        )
        if isinstance(result, str):
            result = LLMGenerationResult(
                text=result,
                prompt_tokens=max(1, len(prompt) // 4),
                completion_tokens=max(1, len(result) // 4),
            )
        if result.text.strip():
            return result
        raise ServiceUnavailableError(
            service="llm",
            message="LLM returned empty draft text; non-LLM fallback answers are disabled",
        )

    async def _generate(self, prompt: str, plan_type: str) -> LLMGenerationResult:
        max_tokens = 1024 if plan_type in {"direct_answer", "visual_grounded_synthesis"} else 1536
        temperature = 0.15 if plan_type == "direct_answer" else 0.25
        return await self._generate_with_limits(prompt, max_tokens=max_tokens, temperature=temperature)

    def _build_prompt(
        self,
        search_result: SearchResult,
        plan_type: str,
        generation_profile: str,
        chat_history: list[Any] | None = None,
    ) -> str:
        template = self._load_prompt(plan_type)
        evidence_block = self._format_evidence(search_result.evidence_pack.items)
        reduce_instructions = ""
        uncertainty_policy = (
            "If evidence is weak or contradictory, say so explicitly and prefer uncertainty over invention."
        )
        language_name = "español" if search_result.query.language.startswith("es") else "English"
        if search_result.query.language.startswith("es"):
            uncertainty_policy = (
                "Si la evidencia es débil, indirecta o contradictoria, indícalo expresamente; "
                "prefiere reconocer la incertidumbre antes que completar o traducir ideas."
            )
        replacements = {
            "{{QUERY}}": search_result.query.text,
            "{{NORMALIZED_QUERY}}": search_result.query.normalized_text,
            "{{PLAN}}": plan_type,
            "{{ROUTE_MODE}}": search_result.query.route_mode,
            "{{ROUTE_REASON}}": search_result.route_reason,
            "{{LANGUAGE}}": language_name,
            "{{GENERATION_PROFILE}}": generation_profile,
            "{{EVIDENCE}}": evidence_block,
            "{{GROUP_LABEL}}": "all selected evidence",
            "{{UNCERTAINTY_POLICY}}": uncertainty_policy,
            "{{REDUCE_INSTRUCTIONS}}": reduce_instructions,
        }
        for key, value in replacements.items():
            template = template.replace(key, value)

        if chat_history:
            turns = []
            for msg in chat_history:
                if isinstance(msg, dict):
                    role = msg.get("role", "user")
                    content = msg.get("content", "")
                else:
                    role = getattr(msg, "role", "user")
                    content = getattr(msg, "content", "")
                prefix = "[User]" if role == "user" else "[Assistant]"
                turns.append(f"{prefix}: {content}")
            history_str = "Conversation history:\n" + "\n".join(turns) + "\n\n"
            template = history_str + template

        if search_result.query.language.startswith("es"):
            template += (
                "\n\n### Restricción final de idioma\n"
                "- Escribe toda la respuesta exclusivamente en español.\n"
                "- La evidencia del corpus ya está en español: razona directamente sobre ella; "
                "no redactes primero en inglés ni entregues traducciones.\n"
                "- Conserva literalmente los marcadores de evidencia [n] y no cites una evidencia "
                "que no respalde la afirmación adyacente.\n"
            )

        return template

    def _build_prompt_trace(
        self,
        search_result: SearchResult,
        plan_type: str,
        generation_profile: str,
        prompt: str,
    ) -> dict[str, object]:
        trace: dict[str, object] = {
            "template": PROMPT_FILES.get(plan_type, PROMPT_FILES["direct_answer"]),
            "placeholders": {
                "query": search_result.query.text,
                "normalized_query": search_result.query.normalized_text,
                "route_mode": search_result.query.route_mode,
                "route_reason": search_result.route_reason,
                "plan": plan_type,
                "language": search_result.query.language,
                "generation_profile": generation_profile,
            },
            "evidence_ids": [item.id for item in search_result.evidence_pack.items],
            "llm_backend": self._settings.llm_backend,
            "llm_model": self._settings.llm_model,
            "embedding_contract": self._settings.embedding_contract_fingerprint,
        }
        if self._settings.store_prompts:
            trace["prompt"] = prompt
        return trace

    @staticmethod
    def _serialize_evidence_item(item: EvidenceItem) -> dict[str, object]:
        metadata = {
            key: value
            for key, value in item.metadata.items()
            if key not in {"source_text", "raw_text", "full_text"}
        }
        source_text = item.metadata.get("source_text")
        if isinstance(source_text, str):
            metadata["source_text_chars"] = len(source_text)
        return {
            "id": item.id,
            "query_id": item.query_id,
            "source_type": item.source_type,
            "source_id": item.source_id,
            "score": item.score,
            "rank": item.rank,
            "document_id": item.document_id,
            "page_number": item.page_number,
            "title": item.title,
            "snippet": item.snippet,
            "citation_candidate": item.citation_candidate,
            "metadata": metadata,
        }

    def _load_prompt(self, plan_type: str) -> str:
        prompts_dir = Path(__file__).resolve().parents[4] / "prompts"
        file_name = PROMPT_FILES.get(plan_type, PROMPT_FILES["direct_answer"])
        path = prompts_dir / file_name
        if path.exists():
            return path.read_text(encoding="utf-8")
        return (
            "# Answer Prompt\n\n"
            "Query: {{QUERY}}\n"
            "Plan: {{PLAN}}\n"
            "Evidence:\n{{EVIDENCE}}\n"
            "{{REDUCE_INSTRUCTIONS}}\n"
            "{{UNCERTAINTY_POLICY}}\n"
        )

    def _format_evidence(self, items: list[EvidenceItem]) -> str:
        lines: list[str] = []
        for index, item in enumerate(items, start=1):
            location = f"doc={item.document_id or 'n/a'}"
            if item.page_number is not None:
                location += f" page={item.page_number}"
            lines.append(
                f"[{index}] {item.source_type} rank={item.rank} score={item.score:.3f} {location} :: {item.snippet}"
            )
        return "\n".join(lines) if lines else "[No evidence items available]"

    @staticmethod
    def _compact_snippet(snippet: str, max_chars: int = 220) -> str:
        clean = " ".join(snippet.split())
        clean = re.sub(
            r"(?:^|[;|])\s*(?:title|video\s*id|video\s*url|channel|kind|language)\s*:\s*[^;|]+",
            " ",
            clean,
            flags=re.IGNORECASE,
        )
        clean = re.sub(r"\s+", " ", clean).strip(" .;-")
        if not clean:
            return ""
        if len(clean) <= max_chars:
            return clean
        shortened = clean[:max_chars].rsplit(" ", 1)[0].strip()
        return f"{shortened}..."

    def _bind_citations(self, items: list[EvidenceItem], draft_text: str) -> list[Citation]:
        citations: list[Citation] = []
        referenced_indices = self._extract_citation_indices(draft_text)
        for index in referenced_indices:
            if index < 1 or index > len(items):
                continue
            item = items[index - 1]
            if not self._evidence_is_citable(item):
                continue
            document_id = item.document_id
            if document_id is None:
                continue
            source_text = str(item.metadata.get("source_text") or item.snippet)
            start, end = self._locate_source_span(source_text, item.snippet)
            citation = Citation(
                id=new_id(),
                answer_id="",
                document_id=document_id,
                page_number=item.page_number,
                node_id=self._extract_node_id(item),
                char_start=start,
                char_end=end,
                snippet=item.snippet[:240],
                bbox=self._extract_bbox(item),
                heading_path=self._extract_heading_path(item),
                page_asset_path=self._extract_page_asset_path(item),
            )
            if self._citation_is_resolved(citation):
                citations.append(citation)
        return citations

    def _build_citation_audit(
        self,
        items: list[EvidenceItem],
        answer_text: str,
        citations: list[Citation],
    ) -> dict[str, object]:
        referenced_indices = self._extract_citation_indices(answer_text)
        invalid_indices = [index for index in referenced_indices if index < 1 or index > len(items)]
        valid_indices = [index for index in referenced_indices if 1 <= index <= len(items)]
        uncitable_indices = [
            index for index in valid_indices if not self._evidence_is_citable(items[index - 1])
        ]
        expected_bindings = len(valid_indices) - len(uncitable_indices)
        return {
            "referenced_evidence_indices": referenced_indices,
            "invalid_evidence_indices": invalid_indices,
            "uncitable_evidence_indices": uncitable_indices,
            "expected_bindings": expected_bindings,
            "resolved_bindings": len(citations),
        }

    def _build_claim_support_audit(
        self,
        items: list[EvidenceItem],
        answer_text: str,
    ) -> ClaimSupportAudit:
        claims: list[ClaimSupportRecord] = []
        for claim_number, claim_text in enumerate(self._split_claims(answer_text), start=1):
            claim_tokens = self._support_tokens(CITATION_MARKER_RE.sub(" ", claim_text))
            if len(claim_tokens) < 3:
                continue
            referenced = self._extract_citation_indices(claim_text)
            valid = [index for index in referenced if 1 <= index <= len(items)]
            citable = [
                index
                for index in valid
                if self._evidence_is_citable(items[index - 1])
            ]
            support_by_evidence: dict[str, float] = {}
            for index in citable:
                evidence = items[index - 1]
                evidence_tokens = self._support_tokens(f"{evidence.title} {evidence.snippet}")
                overlap = len(claim_tokens & evidence_tokens)
                recall = overlap / max(len(claim_tokens), 1)
                precision = overlap / max(len(evidence_tokens), 1)
                f1 = 0.0
                if recall + precision > 0:
                    f1 = (2 * recall * precision) / (recall + precision)
                # Claim recall matters more than evidence precision because a source
                # span normally contains context beyond one answer claim.
                support_by_evidence[str(index)] = round((recall * 0.75) + (f1 * 0.25), 3)
            support_score = max(support_by_evidence.values(), default=0.0)
            claims.append(
                {
                    "claim": claim_number,
                    "text": claim_text[:500],
                    "referenced_evidence_indices": referenced,
                    "valid_evidence_indices": valid,
                    "citable_evidence_indices": citable,
                    "support_by_evidence": support_by_evidence,
                    "support_score": round(support_score, 3),
                    "supported": bool(citable and support_score >= 0.18),
                }
            )

        claim_count = len(claims)
        cited_claims = sum(bool(claim["citable_evidence_indices"]) for claim in claims)
        supported_claims = sum(bool(claim["supported"]) for claim in claims)
        mean_support = (
            sum(float(claim["support_score"]) for claim in claims) / claim_count
            if claim_count
            else 0.0
        )
        return {
            "claim_count": claim_count,
            "cited_claims": cited_claims,
            "supported_claims": supported_claims,
            "citation_coverage": round(cited_claims / claim_count, 3) if claim_count else 0.0,
            "support_coverage": round(supported_claims / claim_count, 3) if claim_count else 0.0,
            "mean_lexical_support": round(mean_support, 3),
            "claims": claims,
        }

    @staticmethod
    def _split_claims(answer_text: str) -> list[str]:
        claims: list[str] = []
        for raw_line in answer_text.splitlines():
            line = re.sub(r"^\s*(?:#{1,6}\s+|[-*+]\s+|\d+[.)]\s+)", "", raw_line).strip()
            if not line:
                continue
            claims.extend(segment.strip() for segment in CLAIM_SPLIT_RE.split(line) if segment.strip())
        return claims

    @staticmethod
    def _support_tokens(text: str) -> set[str]:
        return {
            token
            for token in TOKEN_RE.findall(text.lower())
            if len(token) > 2 and token not in SUPPORT_STOPWORDS and not token.isdigit()
        }

    @staticmethod
    def _extract_citation_indices(text: str) -> list[int]:
        indices = {
            int(value.strip())
            for group in CITATION_MARKER_RE.findall(text)
            for value in group.split(",")
        }
        return sorted(indices)

    def _evidence_is_citable(self, item: EvidenceItem) -> bool:
        if not item.citation_candidate or not item.document_id or item.source_type == "graph_edge":
            return False
        source_text = str(item.metadata.get("source_text") or item.snippet)
        start, end = self._locate_source_span(source_text, item.snippet)
        has_text_anchor = start is not None and end is not None
        has_visual_anchor = bool(item.page_number is not None and self._extract_page_asset_path(item))
        return has_text_anchor or has_visual_anchor


    def _finalize_text(
        self,
        draft_text: str,
        citations: list[Citation],
        route_mode: str,
        plan_type: str,
        query_language: str,
    ) -> str:
        text = draft_text.strip()
        if not text:
            if self._settings.strict_mode_enabled:
                raise StrictModeViolationError(
                    message="strict mode cannot finalize an empty answer",
                    code="EMPTY_FINAL_ANSWER",
                )
            if query_language.lower().startswith("es"):
                return "No pude producir una respuesta fundamentada con la evidencia disponible."
            return "I could not produce a grounded answer."

        if query_language.lower().startswith("es"):
            text = re.sub(r"^\s*the evidence supports\s*:\s*", "Evidencia principal: ", text, flags=re.IGNORECASE)
            text = re.sub(
                r"^\s*i could not find grounded evidence for this query\.?\s*$",
                "No encontre evidencia suficiente para esta consulta.",
                text,
                flags=re.IGNORECASE,
            )
            text = re.sub(
                r"^\s*i could not produce a grounded answer\.?\s*$",
                "No pude producir una respuesta fundamentada con la evidencia disponible.",
                text,
                flags=re.IGNORECASE,
            )

        if plan_type == "visual_grounded_synthesis" and route_mode == "visual":
            return text
        return text

    def _enforce_strict_answer(
        self,
        answer_text: str,
        citations: list[Citation],
        verification: VerificationResult,
        route_mode: str,
    ) -> None:
        if not self._settings.strict_mode_enabled:
            return
        if not answer_text.strip():
            raise StrictModeViolationError("strict mode requires non-empty answer text", code="EMPTY_ANSWER")
        if not citations:
            raise StrictModeViolationError("strict mode requires at least one citation", code="MISSING_CITATIONS")
        unresolved = [citation.id for citation in citations if not self._citation_is_resolved(citation)]
        if unresolved:
            raise StrictModeViolationError(
                "strict mode requires citations to resolve to a real span, node, or visual page",
                code="UNRESOLVED_CITATION_BINDING",
            )
        if route_mode == "visual" and self._settings.visual_required:
            has_visual_citation = any(
                citation.page_number is not None and citation.page_asset_path
                for citation in citations
            )
            if not has_visual_citation:
                raise StrictModeViolationError(
                    "strict visual mode requires at least one resolved visual citation with page asset path",
                    code="MISSING_VISUAL_CITATION",
                )
        if verification.grounding_score < float(self._settings.min_grounding_score):
            raise StrictModeViolationError(
                message=(
                    "strict mode requires grounding_score >= "
                    f"{self._settings.min_grounding_score}, got {verification.grounding_score}"
                ),
                code="LOW_GROUNDING_SCORE",
            )

    async def _verify(
        self,
        search_result: SearchResult,
        answer_text: str,
        plan_type: str,
        citations: list[Citation],
    ) -> VerificationResult:
        issues: list[str] = []
        if not answer_text.strip():
            return VerificationResult(verdict=AnswerVerdict.UNVERIFIED, grounding_score=0.0, issues=["empty_answer"])

        evidence_items = search_result.evidence_pack.items
        contradictions = search_result.evidence_pack.contradictions
        answer_tokens = [token for token in TOKEN_RE.findall(answer_text.lower()) if len(token) > 2]
        evidence_text = " ".join(item.snippet for item in evidence_items).lower()
        overlap = sum(1 for token in answer_tokens if token in evidence_text)
        coverage = overlap / max(len(answer_tokens), 1)
        claim_audit = self._build_claim_support_audit(evidence_items, answer_text)
        claim_count = int(claim_audit["claim_count"])
        cited_claims = int(claim_audit["cited_claims"])
        supported_claims = int(claim_audit["supported_claims"])
        citation_coverage = float(claim_audit["citation_coverage"])
        support_coverage = float(claim_audit["support_coverage"])
        mean_support = float(claim_audit["mean_lexical_support"])
        floor = float(self._settings.grounding_floor)
        grounding_score = min(
            1.0,
            floor
            + (coverage * 0.20)
            + (citation_coverage * 0.35)
            + (support_coverage * 0.25)
            + (mean_support * 0.20),
        )
        unverified_threshold = float(self._settings.min_grounding_score)
        logger.info(
            f"Verification details: overlap={overlap} | answer_tokens={len(answer_tokens)} | "
            f"coverage={coverage:.3f} | cited_claims={cited_claims}/{claim_count} | "
            f"supported_claims={supported_claims}/{claim_count} | mean_support={mean_support:.3f} | "
            f"pre-LLM grounding_score={grounding_score:.3f}"
        )

        if claim_count and cited_claims < claim_count:
            issues.append("uncited_claims")
        if cited_claims and supported_claims < cited_claims:
            issues.append("weak_claim_support")

        citation_audit = self._build_citation_audit(evidence_items, answer_text, citations)
        if citation_audit["invalid_evidence_indices"]:
            issues.append("invalid_citation_markers")
        if citation_audit["uncitable_evidence_indices"]:
            issues.append("uncitable_evidence_references")
        resolved_bindings = citation_audit["resolved_bindings"]
        expected_bindings = citation_audit["expected_bindings"]
        if (
            isinstance(resolved_bindings, int)
            and isinstance(expected_bindings, int)
            and resolved_bindings < expected_bindings
        ):
            issues.append("unresolved_citation_markers")
        expected_language = search_result.query.language.split("-", 1)[0].lower()
        detected_answer_language = QueryRoutingPolicy.detect_language(answer_text)
        if expected_language == "es" and detected_answer_language == "en":
            issues.append("wrong_output_language")

        if not citations:
            issues.append("missing_citations")
        elif any(not self._citation_is_resolved(citation) for citation in citations):
            issues.append("unresolved_citation_binding")
        if contradictions and plan_type != "argument_synthesis":
            issues.append("unresolved_contradiction")
        blocking_issues = {
            "missing_citations",
            "unresolved_citation_binding",
            "unresolved_citation_markers",
            "invalid_citation_markers",
            "wrong_output_language",
        }
        if grounding_score < unverified_threshold or any(issue in blocking_issues for issue in issues):
            verdict = AnswerVerdict.UNVERIFIED
        elif issues and "unresolved_contradiction" in issues:
            verdict = AnswerVerdict.CONFLICTING
        elif grounding_score < 0.7:
            verdict = AnswerVerdict.PARTIALLY_VERIFIED
        else:
            verdict = AnswerVerdict.VERIFIED
        llm_verification = await self._verify_with_llm(search_result, answer_text)
        if llm_verification is not None:
            issues = sorted(set([*issues, *llm_verification.issues]) - {"none"})
            verdict_rank = {
                AnswerVerdict.UNVERIFIED: 0,
                AnswerVerdict.CONFLICTING: 1,
                AnswerVerdict.PARTIALLY_VERIFIED: 2,
                AnswerVerdict.VERIFIED: 3,
            }
            if verdict_rank[llm_verification.verdict] < verdict_rank[verdict]:
                verdict = llm_verification.verdict
            if llm_verification.grounding_score > 0:
                grounding_score = min(grounding_score, llm_verification.grounding_score)

        if "wrong_output_language" in issues:
            verdict = AnswerVerdict.UNVERIFIED
            grounding_score = min(grounding_score, max(0.0, unverified_threshold - 0.01))
        elif any(issue in issues for issue in {"uncitable_evidence_references", "invalid_citation_markers"}):
            if verdict == AnswerVerdict.VERIFIED:
                verdict = AnswerVerdict.PARTIALLY_VERIFIED
            grounding_score = min(grounding_score, 0.69)
        elif any(issue in issues for issue in {"uncited_claims", "weak_claim_support"}):
            if verdict == AnswerVerdict.VERIFIED:
                verdict = AnswerVerdict.PARTIALLY_VERIFIED
            grounding_score = min(grounding_score, 0.74)
        logger.info(
            f"Verification finished: verdict={verdict} | final grounding_score={grounding_score:.3f} | "
            f"issues={issues} | LLM verification={'none' if llm_verification is None else llm_verification}"
        )
        return VerificationResult(verdict=verdict, grounding_score=round(grounding_score, 3), issues=issues)

    def _build_generator(self, backend: str) -> LLMGateway:
        settings = self._settings
        if backend == "llamacpp":
            return LlamaCppAdapter(url=settings.llm_url, required=settings.llm_required)
        return OllamaAdapter(url=settings.llm_url, model=settings.llm_model, required=settings.llm_required)

    async def _verify_with_llm(self, search_result: SearchResult, answer_text: str) -> VerificationResult | None:
        template = self._load_prompt("verification")
        prompt = (
            template.replace("{{QUERY}}", search_result.query.text)
            .replace("{{ANSWER}}", answer_text)
            .replace("{{EVIDENCE}}", self._format_evidence(search_result.evidence_pack.items))
        )
        prompt += (
            "\nTreat each [n] marker as a reference only to evidence item [n]. "
            "A marker pointing outside the list, to an item without a document, or to a graph edge "
            "cannot verify a documentary claim. Report wrong_output_language when the answer "
            f"is not in {search_result.query.language}.\n"
        )
        try:
            result = await self._generator.generate(prompt, max_tokens=256, temperature=0.0)
        except Exception:
            return None

        text: str
        if isinstance(result, str):
            text = result
        elif hasattr(result, "text"):
            text = result.text
        else:
            return None

        if not text or not text.strip():
            return None

        lowered = text.lower()
        verdict = AnswerVerdict.PARTIALLY_VERIFIED
        if "conflicting" in lowered:
            verdict = AnswerVerdict.CONFLICTING
        elif "unverified" in lowered:
            verdict = AnswerVerdict.UNVERIFIED
        elif "verified" in lowered and "partially" not in lowered:
            verdict = AnswerVerdict.VERIFIED

        score_match = re.search(r"grounding[_\s-]*score\s*:\s*([0-9]*\.?[0-9]+)", lowered)
        grounding_score = float(score_match.group(1)) if score_match else 0.0
        issues_line = next((line for line in text.splitlines() if line.lower().startswith("issues:")), "")
        issues = [part.strip() for part in issues_line.split(":", 1)[1].split(",") if part.strip()] if issues_line else []
        return VerificationResult(verdict=verdict, grounding_score=grounding_score, issues=issues)

    @staticmethod
    def _locate_source_span(source_text: str, snippet: str) -> tuple[int | None, int | None]:
        normalized_source = " ".join(source_text.split())
        normalized_snippet = " ".join(snippet.split())
        if not normalized_source or not normalized_snippet:
            return None, None
        start = normalized_source.lower().find(normalized_snippet.lower())
        if start >= 0:
            return start, start + len(normalized_snippet)
        prefix = normalized_snippet[: min(len(normalized_snippet), 80)]
        start = normalized_source.lower().find(prefix.lower())
        if start >= 0:
            return start, start + len(prefix)
        return None, None

    @staticmethod
    def _citation_is_resolved(citation: Citation) -> bool:
        has_span = citation.char_start is not None and citation.char_end is not None
        has_text_anchor = has_span
        has_visual_anchor = bool(citation.page_number is not None and citation.page_asset_path)
        return bool(citation.document_id and (has_text_anchor or has_visual_anchor))

    @staticmethod
    def _extract_node_id(item: EvidenceItem) -> str | None:
        if item.metadata.get("node_id"):
            return str(item.metadata["node_id"])
        node_ids = item.metadata.get("node_ids")
        if isinstance(node_ids, list) and node_ids:
            return str(node_ids[0])
        return None

    @staticmethod
    def _extract_bbox(item: EvidenceItem) -> dict[str, object] | None:
        bbox = item.metadata.get("bbox")
        return bbox if isinstance(bbox, dict) else None

    @staticmethod
    def _extract_heading_path(item: EvidenceItem) -> list[str]:
        heading_path = item.metadata.get("heading_path")
        if isinstance(heading_path, list):
            return [str(part) for part in heading_path]
        return []

    @staticmethod
    def _extract_page_asset_path(item: EvidenceItem) -> str | None:
        value = item.metadata.get("image_path") or item.metadata.get("page_asset_path")
        return str(value) if value else None


def normalize_citation_answer_ids(answer_id: str, citations: list[Citation]) -> list[Citation]:
    for citation in citations:
        citation.answer_id = answer_id
    return citations
