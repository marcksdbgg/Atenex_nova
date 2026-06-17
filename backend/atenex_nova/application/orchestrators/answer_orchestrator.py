"""Answer orchestration, verification and citation binding."""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from atenex_nova.application.orchestrators.retrieval_orchestrator import SearchResult
from atenex_nova.application.policies.answer_planning_policy import AnswerPlanningPolicy
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
        gen_res = await self._generate(prompt, plan_type)
        draft_text = gen_res.text
        input_token_count = gen_res.prompt_tokens
        output_token_count = gen_res.completion_tokens
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
            repair_prompt = self._build_repair_prompt(prompt, verification.issues)
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
                if self._is_better_attempt(verification, citations, repaired_verification, repaired_citations):
                    prompt = repair_prompt
                    draft_text = repaired_draft
                    input_token_count = repaired_gen.prompt_tokens
                    output_token_count = repaired_gen.completion_tokens
                    citations = repaired_citations
                    answer_text = repaired_answer
                    verification = repaired_verification
                    verification.issues = sorted(
                        set([*verification.issues, "regenerated_after_failed_verification"]),
                    )
            except ServiceUnavailableError:
                pass

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
                "prompt_trace": self._build_prompt_trace(
                    search_result=search_result,
                    plan_type=plan_type,
                    generation_profile=generation_profile,
                    prompt=prompt,
                ),
            },
            full_prompt=prompt,
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
    def _build_repair_prompt(prompt: str, issues: list[str]) -> str:
        issue_text = ", ".join(issues) if issues else "low grounding"
        return (
            f"{prompt}\n\n"
            "### Verification Repair\n"
            f"The previous draft had these problems: {issue_text}.\n"
            "Regenerate the answer with only grounded claims, explicit inline citations like [1], [2], and clear uncertainty if evidence is insufficient.\n"
            "Do not add claims without support in the evidence block.\n"
        )

    async def _generate(self, prompt: str, plan_type: str) -> LLMGenerationResult:
        max_tokens = 1024 if plan_type in {"direct_answer", "visual_grounded_synthesis"} else 1536
        temperature = 0.15 if plan_type == "direct_answer" else 0.25
        gen_res = await self._generator.generate(
            prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            stop=["\n[User]", "\n[Assistant]", "\n<END>"],
        )

        if isinstance(gen_res, str):
            text = gen_res
            prompt_tokens = max(1, len(prompt) // 4)
            completion_tokens = max(1, len(text) // 4)
            gen_res = LLMGenerationResult(
                text=text,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )

        if gen_res.text.strip():
            return gen_res
        raise ServiceUnavailableError(
            service="llm",
            message="LLM returned empty draft text; non-LLM fallback answers are disabled",
        )

    def _build_prompt(
        self,
        search_result: SearchResult,
        plan_type: str,
        generation_profile: str,
        chat_history: list[Any] | None = None,
    ) -> str:
        template = self._load_prompt(plan_type)
        evidence_block = self._format_evidence(search_result.evidence_pack.items)
        reduce_instructions = self._load_prompt("hierarchical_reduce") if plan_type == "hierarchical_synthesis" else ""
        uncertainty_policy = (
            "If evidence is weak or contradictory, say so explicitly and prefer uncertainty over invention."
        )
        replacements = {
            "{{QUERY}}": search_result.query.text,
            "{{NORMALIZED_QUERY}}": search_result.query.normalized_text,
            "{{PLAN}}": plan_type,
            "{{ROUTE_MODE}}": search_result.query.route_mode,
            "{{ROUTE_REASON}}": search_result.route_reason,
            "{{LANGUAGE}}": search_result.query.language,
            "{{GENERATION_PROFILE}}": generation_profile,
            "{{EVIDENCE}}": evidence_block,
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
        }
        if self._settings.store_prompts:
            trace["prompt"] = prompt
        return trace

    @staticmethod
    def _serialize_evidence_item(item: EvidenceItem) -> dict[str, object]:
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
            "metadata": item.metadata,
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
        for index, item in enumerate(items[:5], start=1):
            marker = f"[{index}]"
            if marker not in draft_text:
                continue
            if not item.document_id:
                continue
            source_text = str(item.metadata.get("source_text") or item.snippet)
            start, end = self._locate_source_span(source_text, item.snippet)
            citation = Citation(
                id=new_id(),
                answer_id="",
                document_id=item.document_id,
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
        if citations and not any(marker in text for marker in ("[1]", "[2]", "[3]")):
            suffix = " ".join(f"[{index}]" for index in range(1, min(len(citations), 3) + 1))
            text = f"{text} {suffix}".strip()
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
        citation_score = min(len(citations), 5) / 5.0
        floor = float(self._settings.grounding_floor)
        grounding_score = min(1.0, floor + (coverage * 0.55) + (citation_score * 0.45))
        unverified_threshold = float(self._settings.min_grounding_score)
        logger.info(
            f"Verification details: overlap={overlap} | answer_tokens={len(answer_tokens)} | "
            f"coverage={coverage:.3f} | citation_score={citation_score:.3f} | "
            f"pre-LLM grounding_score={grounding_score:.3f}"
        )

        if not citations:
            issues.append("missing_citations")
        elif any(not self._citation_is_resolved(citation) for citation in citations):
            issues.append("unresolved_citation_binding")
        if contradictions and plan_type != "argument_synthesis":
            issues.append("unresolved_contradiction")
        if grounding_score < unverified_threshold:
            verdict = AnswerVerdict.UNVERIFIED
        elif issues and "unresolved_contradiction" in issues:
            verdict = AnswerVerdict.CONFLICTING
        elif grounding_score < 0.7:
            verdict = AnswerVerdict.PARTIALLY_VERIFIED
        else:
            verdict = AnswerVerdict.VERIFIED
        llm_verification = await self._verify_with_llm(search_result, answer_text)
        if llm_verification is not None:
            deterministic_issues = list(issues)
            issues = sorted(set([*issues, *llm_verification.issues]) - {"none"})
            if deterministic_issues:
                grounding_score = min(grounding_score, llm_verification.grounding_score or grounding_score)
                if llm_verification.verdict == AnswerVerdict.UNVERIFIED:
                    verdict = AnswerVerdict.UNVERIFIED
                elif llm_verification.verdict == AnswerVerdict.CONFLICTING:
                    verdict = AnswerVerdict.CONFLICTING
            else:
                verdict = llm_verification.verdict
                grounding_score = max(grounding_score, llm_verification.grounding_score)
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
