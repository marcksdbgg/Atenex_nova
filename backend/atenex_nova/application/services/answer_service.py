"""Application service for answer generation and retrieval."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

from sqlalchemy.ext.asyncio import AsyncSession

from atenex_nova.application.orchestrators.answer_orchestrator import (
    AnswerBundle,
    AnswerOrchestrator,
    normalize_citation_answer_ids,
)
from atenex_nova.application.services.query_service import QueryService
from atenex_nova.domain.entities.answer import Answer
from atenex_nova.domain.entities.citation import Citation
from atenex_nova.infrastructure.db.repositories.sql_answer_repo import SqlAnswerRepository
from atenex_nova.infrastructure.db.repositories.sql_citation_repo import SqlCitationRepository
from atenex_nova.infrastructure.db.repositories.sql_query_repo import SqlQueryRepository
from atenex_nova.shared.observability.pipeline_audit import PipelineAuditService


@dataclass(slots=True)
class AnswerDetail:
    answer: Answer
    citations: list[Citation]
    evidence_items: list
    query_id: str
    collection_id: str
    query_text: str
    normalized_query: str
    language: str
    intent: str
    route_mode: str


class AnswerService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._query_service = QueryService(session)
        self._answer_repo = SqlAnswerRepository(session)
        self._citation_repo = SqlCitationRepository(session)
        self._query_repo = SqlQueryRepository(session)
        self._orchestrator = AnswerOrchestrator()
        self._audit = PipelineAuditService(session=session)

    async def answer(self, collection_id: str, query: str, mode: str = "auto", generation_profile: str = "standard") -> AnswerBundle:
        search_result = await self._query_service.search_only(collection_id=collection_id, query=query, mode=mode)
        async with self._audit.step(
            run_id=search_result.query.id,
            entity_type="query",
            entity_id=search_result.query.id,
            pipeline="answering",
            stage="compose_answer",
            context={"query": query, "mode": mode, "generation_profile": generation_profile, "collection_id": collection_id},
        ) as audit:
            audit.metrics(
                evidence_items=len(search_result.evidence_pack.items),
                evidence_budget=search_result.evidence_pack.token_budget,
                evidence_tokens=search_result.evidence_pack.estimated_tokens,
                evidence_budget_utilization=search_result.evidence_pack.budget_utilization,
                route_mode=search_result.query.route_mode,
                intent=search_result.query.intent,
            )
            bundle = await self._orchestrator.compose(search_result, generation_profile=generation_profile)
            citations = normalize_citation_answer_ids(bundle.answer.id, bundle.citations)
            await self._answer_repo.create(bundle.answer)
            if citations:
                await self._citation_repo.create_many(citations)
            await self._session.commit()
            audit.metrics(
                answer_id=bundle.answer.id,
                citations=len(citations),
                grounding_score=bundle.answer.grounding_score,
                verdict=bundle.answer.verdict,
            )
            bundle.citations = citations
            return bundle

    async def get_answer(self, answer_id: str) -> AnswerDetail | None:
        answer = await self._answer_repo.get_by_id(answer_id)
        if answer is None:
            return None
        citations = await self._citation_repo.list_by_answer(answer_id)
        query = await self._query_repo.get_by_id(answer.query_id)
        if query is None:
            return AnswerDetail(
                answer=answer,
                citations=citations,
                evidence_items=[],
                query_id=answer.query_id,
                collection_id="",
                query_text="",
                normalized_query="",
                language="auto",
                intent="factual",
                route_mode="factual_local",
            )
        search_result = await self._query_service.search_only(collection_id=query.collection_id, query=query.text, mode=query.route_mode or "auto")
        return AnswerDetail(
            answer=answer,
            citations=citations,
            evidence_items=search_result.evidence_pack.items,
            query_id=query.id,
            collection_id=query.collection_id,
            query_text=query.text,
            normalized_query=query.normalized_text,
            language=query.language,
            intent=query.intent,
            route_mode=query.route_mode,
        )

    def export_markdown(self, detail: AnswerDetail) -> str:
        lines = [
            f"# Answer {detail.answer.id}",
            "",
            f"**Question:** {detail.query_text}",
            f"**Plan:** {detail.answer.plan_type}",
            f"**Verdict:** {detail.answer.verdict}",
            f"**Grounding score:** {detail.answer.grounding_score:.3f}",
            "",
            detail.answer.text,
            "",
            "## Citations",
        ]
        if detail.citations:
            for index, citation in enumerate(detail.citations, start=1):
                location = f"page {citation.page_number}" if citation.page_number is not None else "document citation"
                lines.append(f"{index}. {location}: {citation.snippet}")
        else:
            lines.append("No citations available.")
        return "\n".join(lines)

    def export_pdf(self, detail: AnswerDetail) -> bytes:
        try:
            from reportlab.lib.pagesizes import A4  # type: ignore[import-not-found]
            from reportlab.pdfgen import canvas  # type: ignore[import-not-found]
        except Exception:
            return self.export_markdown(detail).encode("utf-8")

        buffer = BytesIO()
        pdf = canvas.Canvas(buffer, pagesize=A4)
        _width, height = A4
        y = height - 48
        pdf.setTitle(f"Answer {detail.answer.id}")

        def write_line(text: str, indent: int = 0) -> None:
            nonlocal y
            pdf.drawString(48 + indent, y, text[:120])
            y -= 16
            if y < 64:
                pdf.showPage()
                y = height - 48

        write_line(f"Answer {detail.answer.id}")
        write_line(f"Question: {detail.query_text}")
        write_line(f"Plan: {detail.answer.plan_type}")
        write_line(f"Verdict: {detail.answer.verdict}")
        write_line(f"Grounding score: {detail.answer.grounding_score:.3f}")
        write_line("")
        for paragraph in detail.answer.text.splitlines() or [detail.answer.text]:
            write_line(paragraph)
        write_line("")
        write_line("Citations:")
        if detail.citations:
            for index, citation in enumerate(detail.citations, start=1):
                location = f"page {citation.page_number}" if citation.page_number is not None else "citation"
                write_line(f"{index}. {location} - {citation.snippet}", indent=16)
        else:
            write_line("No citations available.", indent=16)

        pdf.save()
        return buffer.getvalue()
