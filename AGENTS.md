# Atenex Nova Workspace Instructions

## Source of Truth
- Use [docs/baseline.md](docs/baseline.md) for the product contract and rationale.
- Use [docs/final-gap-inventory.md](docs/final-gap-inventory.md) as the canonical inventory of the real remaining gap against the baseline.
- Use [docs/plan_restante.md](docs/plan_restante.md) only as historical context; if it differs from the final gap inventory, the inventory prevails.
- Use [README.md](README.md) for quick start and runtime commands.
- Do not duplicate those docs here; link to them instead.
- [frontend/README.md](frontend/README.md) is the Vite template and is not operationally authoritative.

## Documentation To Read First
- For backend or architecture work, read [docs/baseline.md](docs/baseline.md) and [docs/final-gap-inventory.md](docs/final-gap-inventory.md) before editing code.
- Use [docs/plan_restante.md](docs/plan_restante.md) only if historical context is needed.
- For backend implementation details, also read [docs/architecture-backend.md](docs/architecture-backend.md) and [docs/jobs-and-workers.md](docs/jobs-and-workers.md).
- For product framing or tradeoff context, read [docs/baseline.md](docs/baseline.md).
- For frontend structure and API contracts, also read [docs/architecture-frontend.md](docs/architecture-frontend.md) and [docs/api-endpoints.md](docs/api-endpoints.md).
- For setup, run commands, and local services, read [README.md](README.md).
- For UI work, check [design-system/atenex-nova/MASTER.md](design-system/atenex-nova/MASTER.md) first and then any page override under [design-system/atenex-nova/pages/](design-system/atenex-nova/pages/).
- Keep in mind that `frontend/README.md` is only the scaffold template.

## Code Style
- Preserve the modular monolith + hexagonal layering: `presentation` -> `application` -> `domain` -> `infrastructure` -> `workers` -> `evaluation` -> `shared`.
- Use absolute imports from `atenex_nova.*`.
- Keep changes small and local; prefer existing patterns over introducing new abstractions.
- Do not let routers call infrastructure directly; go through application services and orchestrators.

## Build and Test
- Backend install: `pip install -e ".[dev]"` from `backend/`.
- If your task touches parsing/embeddings/visual retrieval, install ML deps too: `pip install -e ".[all]"`.
- Backend tests: `pytest tests -q`.
- Backend quality checks: `ruff check .` and `mypy`.
- Run API: `uvicorn atenex_nova.main:app --reload --port 8000`.
- Run worker: `python -m atenex_nova.workers.main`.
- Frontend dev: `npm run dev`.
- Frontend checks: `npm run build` (includes `tsc -b`) and `npm run lint`.

## Architecture and Entry Points
- API entry point: [backend/atenex_nova/main.py](backend/atenex_nova/main.py).
- Dependency wiring: [backend/atenex_nova/dependencies.py](backend/atenex_nova/dependencies.py).
- Worker entry point: [backend/atenex_nova/workers/main.py](backend/atenex_nova/workers/main.py).
- Retrieval changes usually touch [backend/atenex_nova/application/orchestrators/retrieval_orchestrator.py](backend/atenex_nova/application/orchestrators/retrieval_orchestrator.py), [backend/atenex_nova/infrastructure/embeddings/bm25_encoder.py](backend/atenex_nova/infrastructure/embeddings/bm25_encoder.py), and the embedding/visual adapters together.
- Frontend routes live in [frontend/src/App.tsx](frontend/src/App.tsx) and page implementations in [frontend/src/pages/Pages.tsx](frontend/src/pages/Pages.tsx).

## Conventions and Pitfalls
- Store uploads in `backend/storage/uploads/{collection_id}/{document_id}/{filename}` and visual page cache in `backend/storage/visual_pages/`.
- Local services: Qdrant runs on `6333/6334`; PostgreSQL runs on `5432` only when started with `docker compose --profile prod up -d`; default LLM runtime is Ollama on `11434` with `gemma4:e4b` (llama.cpp on `8080` is optional alternative).
- The backend CORS setup already allows localhost and 127.0.0.1 on ports 5173 and 5174.
- When changing jobs, review [backend/atenex_nova/workers/main.py](backend/atenex_nova/workers/main.py) and [backend/atenex_nova/workers/runner.py](backend/atenex_nova/workers/runner.py) together.
- For frontend API behavior and fallback rules, check [frontend/src/services/api.ts](frontend/src/services/api.ts).
- Update [docs/final-gap-inventory.md](docs/final-gap-inventory.md) or [docs/baseline.md](docs/baseline.md) if a change affects product behavior, architecture, or the declared remaining gap.
