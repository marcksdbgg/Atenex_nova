# Atenex Nova Workspace Instructions

## Source of Truth
- Use [docs/baseline.md](docs/baseline.md) for the product contract and rationale.
- Use [docs/auditoria-completa.md](docs/auditoria-completa.md) as the canonical technical audit (claims-vs-implementation, contrastive) and remaining-gap reference against the baseline.

- Use [README.md](README.md) for the live repository snapshot, quick start, and current verification status.
- Do not duplicate those docs here; link to them instead.
- [frontend/README.md](frontend/README.md) is the Vite scaffold template and is not operationally authoritative.

## Current Verified Snapshot
- OpenAPI/docs contract test: 1 passed in the current checkout.
- Backend unit, integration, and E2E tests: **96 passed, 3 skipped** (2026-06-16, Qdrant+Ollama live; `backend/.venv312/Scripts/python.exe -m pytest tests -q`).
- Frontend build: successful (green).
- Frontend lint: successful (green).
- Backend `ruff`: clean (0 issues, green).
- Backend `mypy`: clean (0 errors, green).
- The current workspace uses **two venvs** on Windows:
  - `backend/.venv312/` — **canonical GPU venv** (Python 3.12, torch+cu128, RTX 4060 CUDA 12.8). Use `backend/.venv312/Scripts/python.exe` for all runtime and ML commands.
  - `backend/.venv/` — legacy CPU-only venv (Python 3.14, torch+cpu). Use only as fallback if `.venv312` is unavailable.
- GPU: RTX 4060 8 GB VRAM, driver 595.97, CUDA runtime 13.2 (cu128 wheels are compatible). Ollama LLM also runs on this GPU.
- The canonical technical audit is [docs/auditoria-completa.md](docs/auditoria-completa.md); treat it as a contrastive audit ledger, not a live test log.

## Documentation To Read First
- For backend or architecture work, read [docs/baseline.md](docs/baseline.md) and [docs/auditoria-completa.md](docs/auditoria-completa.md) before editing code.

- For backend implementation details, also read [docs/architecture-backend.md](docs/architecture-backend.md) and [docs/jobs-and-workers.md](docs/jobs-and-workers.md).
- For product framing or tradeoff context, read [docs/baseline.md](docs/baseline.md).
- For frontend structure and API contracts, also read [docs/architecture-frontend.md](docs/architecture-frontend.md) and [docs/api-endpoints.md](docs/api-endpoints.md).
- For setup, run commands, and local services, read [README.md](README.md).
- For vector quantization and TurboQuant/VecQuant integration design, read [docs/turboquant-integration.md](docs/turboquant-integration.md).
- For UI work, check [design-system/atenex-nova/MASTER.md](design-system/atenex-nova/MASTER.md) first and then any page override under [design-system/atenex-nova/pages/](design-system/atenex-nova/pages/).

## Architecture and Entry Points
- Preserve the modular monolith + hexagonal layering: `presentation` -> `application` -> `domain` -> `infrastructure` -> `workers` -> `evaluation` -> `shared`.
- Use absolute imports from `atenex_nova.*`.
- API entry point: [backend/atenex_nova/main.py](backend/atenex_nova/main.py).
- Dependency wiring: [backend/atenex_nova/dependencies.py](backend/atenex_nova/dependencies.py).
- Worker entry point: [backend/atenex_nova/workers/main.py](backend/atenex_nova/workers/main.py).
- Worker dispatcher: [backend/atenex_nova/workers/runner.py](backend/atenex_nova/workers/runner.py).
- Retrieval changes usually touch [backend/atenex_nova/application/orchestrators/retrieval_orchestrator.py](backend/atenex_nova/application/orchestrators/retrieval_orchestrator.py), [backend/atenex_nova/infrastructure/embeddings/bm25_encoder.py](backend/atenex_nova/infrastructure/embeddings/bm25_encoder.py), and the embedding / visual adapters together.
- Frontend routes live in [frontend/src/App.tsx](frontend/src/App.tsx) and page implementations in [frontend/src/pages/Pages.tsx](frontend/src/pages/Pages.tsx).

## Implementation Notes
- Current backend flow is a modular monolith with FastAPI routers over application services and worker-driven ingestion jobs.
- Current retrieval is hybrid: dense via TurboQuant IP estimator (`PurePyTurboQuantCandidateIndex` or optional turbovec), local sparse/BM25, reranking, and page-text visual retrieval (`VisualPageRetriever`, not ColPali VL).
- Current query UX is chat-first and includes history, evidence, citations, document drill-down, and page viewers.
- Storage paths remain: uploads under `backend/storage/uploads/{collection_id}/{document_id}/{filename}`, visual page cache under `backend/storage/visual_pages/`, and local turbovec candidate indexes under `backend/storage/turbovec/`.
- Qdrant collections are namespaced per corpus for chunks, propositions, summaries, and visual pages.
- If a change affects product behavior, architecture, or the declared remaining gap, update [README.md](README.md) and [docs/auditoria-completa.md](docs/auditoria-completa.md) together.

## Build and Test
- Backend install: `pip install -e ".[dev]"` from `backend/`.
- If the task touches parsing, embeddings, or visual retrieval, install ML deps too: `pip install -e ".[all]"`.
- Backend tests: `backend/.venv312/Scripts/python.exe -m pytest tests -q` on Windows (use `.venv312` for GPU support).
- Backend quality checks: `backend/.venv312/Scripts/python.exe -m ruff check .` and `backend/.venv312/Scripts/python.exe -m mypy atenex_nova` on Windows.
- Run API: `uvicorn atenex_nova.main:app --reload --port 8000`.
- Run worker: `python -m atenex_nova.workers.main`.
- Frontend dev: `npm run dev`.
- Frontend checks: `npm run build` (includes `tsc -b`) and `npm run lint`.

## Conventions and Pitfalls
- Do not let routers call infrastructure directly; go through application services and orchestrators.
- When changing jobs, review [backend/atenex_nova/workers/main.py](backend/atenex_nova/workers/main.py) and [backend/atenex_nova/workers/runner.py](backend/atenex_nova/workers/runner.py) together.
- For frontend API behavior and fallback rules, check [frontend/src/services/api.ts](frontend/src/services/api.ts).
- Local services: Qdrant runs on `6333/6334`; PostgreSQL runs on `5432` only when started with `docker compose --profile prod up -d`; default LLM runtime is Ollama on `11434` with `gemma4:12b` (llama.cpp on `8080` is an optional alternative). Embeddings are also local/offline-first via Ollama (`embeddinggemma`, `ATENEX_EMBEDDING_BACKEND=ollama` by default) — no Hugging Face download or login is required; run `ollama pull embeddinggemma` once.
- The backend CORS setup already allows localhost and 127.0.0.1 on ports 5173 and 5174.
- Keep changes small and local; prefer existing patterns over introducing new abstractions.
