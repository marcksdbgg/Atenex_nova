"""Answer orchestration, verification and citation binding."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from atenex_nova.application.orchestrators.retrieval_orchestrator import SearchResult
from atenex_nova.application.policies.answer_planning_policy import AnswerPlanningPolicy
from atenex_nova.domain.entities.answer import Answer
from atenex_nova.domain.entities.citation import Citation
from atenex_nova.domain.entities.evidence_item import EvidenceItem
from atenex_nova.domain.value_objects.identifiers import AnswerVerdict, new_id
from atenex_nova.infrastructure.llm.llm_gateway import LlamaCppAdapter, LLMGateway, OllamaAdapter
from atenex_nova.shared.config.settings import get_settings
from atenex_nova.shared.exceptions.base import ServiceUnavailableError, StrictModeViolationError

TOKEN_RE = re.compile(r"[\w\-]+", re.UNICODE)
PROMPT_FILES = {
    "direct_answer": "DIRECT_ANSWER_PROMPT.md",
    "hierarchical_synthesis": "HIERARCHICAL_MAP_PROMPT.md",
    "global_synthesis": "GLOBAL_SYNTHESIS_PROMPT.md",
    "argument_synthesis": "ARGUMENT_SYNTHESIS_PROMPT.md",
    "visual_grounded_synthesis": "VISUAL_GROUNDED_PROMPT.md",
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

    async def compose(self, search_result: SearchResult, generation_profile: str = "standard") -> AnswerBundle:
        plan_type = self._planner.choose_plan(search_result.evidence_pack)
        prompt = self._build_prompt(search_result, plan_type, generation_profile)
        draft_text = await self._generate(prompt, plan_type)
        citations = self._bind_citations(search_result.evidence_pack.items, draft_text)
        answer_text = self._finalize_text(
            draft_text,
            citations,
            search_result.evidence_pack.route_mode,
            plan_type,
            search_result.query.language,
        )
        verification = self._verify(answer_text, search_result.evidence_pack.items, search_result.evidence_pack.contradictions, plan_type, citations)
        self._enforce_strict_answer(answer_text, citations, verification)
        answer = Answer(
            id=new_id(),
            query_id=search_result.query.id,
            plan_type=plan_type,
            text=answer_text,
            grounding_score=verification.grounding_score,
            verdict=verification.verdict.value,
        )
        return AnswerBundle(
            query_id=search_result.query.id,
            collection_id=search_result.query.collection_id,
            query_text=search_result.query.text,
            normalized_query=search_result.query.normalized_text,
            query_language=search_result.query.language,
            query_intent=search_result.query.intent,
            route_mode=search_result.query.route_mode,
            plan_type=plan_type,
            answer=answer,
            citations=citations,
            evidence_items=search_result.evidence_pack.items,
            prompt=prompt,
            draft_text=draft_text,
            verification=verification,
        )

    async def _generate(self, prompt: str, plan_type: str) -> str:
        max_tokens = 1024 if plan_type in {"direct_answer", "visual_grounded_synthesis"} else 1536
        temperature = 0.15 if plan_type == "direct_answer" else 0.25
        text = await self._generator.generate(
            prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            stop=["\n\n###", "\n<END>"] if plan_type != "visual_grounded_synthesis" else ["\n\n###"],
        )
        if text.strip():
            return text.strip()
        raise ServiceUnavailableError(
            service="llm",
            message="LLM returned empty draft text; non-LLM fallback answers are disabled",
        )

    def _build_prompt(self, search_result: SearchResult, plan_type: str, generation_profile: str) -> str:
        template = self._load_prompt(plan_type)
        evidence_block = self._format_evidence(search_result.evidence_pack.items)
        uncertainty_policy = (
            "If evidence is weak or contradictory, say so explicitly and prefer uncertainty over invention."
        )
        replacements = {
            "{{QUERY}}": search_result.query.text,
            "{{NORMALIZED_QUERY}}": search_result.query.normalized_text,
            "{{PLAN}}": plan_type,
            "{{ROUTE_MODE}}": search_result.query.route_mode,
            "{{LANGUAGE}}": search_result.query.language,
            "{{GENERATION_PROFILE}}": generation_profile,
            "{{EVIDENCE}}": evidence_block,
            "{{UNCERTAINTY_POLICY}}": uncertainty_policy,
        }
        for key, value in replacements.items():
            template = template.replace(key, value)
        return template

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
            start = draft_text.find(marker)
            citations.append(
                Citation(
                    id=new_id(),
                    answer_id="",
                    document_id=item.document_id or "",
                    page_number=item.page_number,
                    node_id=item.metadata.get("node_id") if item.metadata else None,
                    char_start=start,
                    char_end=start + len(marker),
                    snippet=item.snippet[:240],
                )
            )
        if not citations:
            for item in items[:3]:
                citations.append(
                    Citation(
                        id=new_id(),
                        answer_id="",
                        document_id=item.document_id or "",
                        page_number=item.page_number,
                        node_id=item.metadata.get("node_id") if item.metadata else None,
                        char_start=None,
                        char_end=None,
                        snippet=item.snippet[:240],
                    )
                )
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
                "No encontré evidencia suficiente para esta consulta.",
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
    ) -> None:
        if not self._settings.strict_mode_enabled:
            return
        if not answer_text.strip():
            raise StrictModeViolationError("strict mode requires non-empty answer text", code="EMPTY_ANSWER")
        if not citations:
            raise StrictModeViolationError("strict mode requires at least one citation", code="MISSING_CITATIONS")
        if verification.grounding_score < float(self._settings.min_grounding_score):
            raise StrictModeViolationError(
                message=(
                    "strict mode requires grounding_score >= "
                    f"{self._settings.min_grounding_score}, got {verification.grounding_score}"
                ),
                code="LOW_GROUNDING_SCORE",
            )

    def _verify(
        self,
        answer_text: str,
        evidence_items: list[EvidenceItem],
        contradictions: list[EvidenceItem],
        plan_type: str,
        citations: list[Citation],
    ) -> VerificationResult:
        issues: list[str] = []
        if not answer_text.strip():
            return VerificationResult(verdict=AnswerVerdict.UNVERIFIED, grounding_score=0.0, issues=["empty_answer"])

        answer_tokens = [token for token in TOKEN_RE.findall(answer_text.lower()) if len(token) > 2]
        evidence_text = " ".join(item.snippet for item in evidence_items).lower()
        overlap = sum(1 for token in answer_tokens if token in evidence_text)
        coverage = overlap / max(len(answer_tokens), 1)
        citation_score = min(len(citations), 5) / 5.0
        grounding_score = min(1.0, 0.35 + (coverage * 0.45) + (citation_score * 0.2))

        if not citations:
            issues.append("missing_citations")
        if contradictions and plan_type != "argument_synthesis":
            issues.append("unresolved_contradiction")
        if grounding_score < 0.35:
            verdict = AnswerVerdict.UNVERIFIED
        elif issues and "unresolved_contradiction" in issues:
            verdict = AnswerVerdict.CONFLICTING
        elif grounding_score < 0.7:
            verdict = AnswerVerdict.PARTIALLY_VERIFIED
        else:
            verdict = AnswerVerdict.VERIFIED
        return VerificationResult(verdict=verdict, grounding_score=round(grounding_score, 3), issues=issues)

    def _build_generator(self, backend: str) -> LLMGateway:
        settings = self._settings
        if backend == "llamacpp":
            return LlamaCppAdapter(url=settings.llm_url, required=settings.llm_required)
        return OllamaAdapter(url=settings.llm_url, model=settings.llm_model, required=settings.llm_required)


def normalize_citation_answer_ids(answer_id: str, citations: list[Citation]) -> list[Citation]:
    for citation in citations:
        citation.answer_id = answer_id
    return citations
