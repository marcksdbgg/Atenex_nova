# AGENTS.md — Atenex Nova

> **Ultima actualizacion:** 2026-04-06
> **Estado actual:** Fases 0-9 implementadas en el repo y validadas con tests/build.
> **Fuente de verdad del producto:** `docs/baseline.md` + `docs/plan.md` + codigo actual.

---

## 1. Que es Atenex Nova

Atenex Nova es una plataforma local de memoria documental y RAG. No es un chatbot con vectores; es un sistema de memoria con varios motores de acceso que ingiere documentos locales, construye memoria estructurada y responde con grounding, citas a spans concretos, routing por tipo de pregunta y soporte para documentos complejos.

El diseno real del repo sigue el estilo **Modular Monolith + Local Engines** con arquitectura hexagonal y capas claras:

- `presentation`
- `application`
- `domain`
- `infrastructure`
- `workers`
- `evaluation`
- `shared`

---

## 2. Entorno y arranque

| Elemento | Valor |
| --- | --- |
| SO objetivo | Windows 11 |
| Shell | PowerShell |
| Ruta del repo | `G:\Atenex\Atenex_nova` |
| Python | 3.11+ (recomendado 3.12) |
| Node.js | 20 LTS+ |
| Docker | Docker Desktop para Qdrant y PostgreSQL |

### Procesos que componen Atenex

- `atenex-api` -> FastAPI
- `atenex-worker` -> runner de jobs
- `atenex-ui` -> Vite + React
- `qdrant` -> vector DB local/self-hosted
- `postgres` -> base relacional de produccion
- `llm-runtime` -> llama.cpp o Ollama

### Como levantar todo

1. Levantar servicios locales.

```powershell
Set-Location G:\Atenex\Atenex_nova
docker compose up -d qdrant
docker compose --profile prod up -d postgres
```

2. Levantar backend.

```powershell
Set-Location G:\Atenex\Atenex_nova\backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
uvicorn atenex_nova.main:app --reload --port 8000
```

3. Levantar worker.

```powershell
Set-Location G:\Atenex\Atenex_nova\backend
.venv\Scripts\python.exe -m atenex_nova.workers.main
```

4. Levantar frontend.

```powershell
Set-Location G:\Atenex\Atenex_nova\frontend
npm install
npm run dev
```

Si `5173` ya esta ocupado, Vite puede caer a `5174`. El backend ya permite por defecto `5173` y `5174` en CORS para `localhost` y `127.0.0.1`.

### Variables de entorno clave

Las settings viven en `backend/atenex_nova/shared/config/settings.py` y usan prefijo `ATENEX_`.

- `ATENEX_DATABASE_URL` -> por defecto SQLite local
- `ATENEX_QDRANT_URL` -> por defecto `http://localhost:6333`
- `ATENEX_LLM_BACKEND` -> `ollama` o `llamacpp`
- `ATENEX_LLM_URL` -> por defecto `http://localhost:11434`
- `ATENEX_LLM_MODEL` -> por defecto `gemma4:e4b`
- `ATENEX_EMBEDDING_MODEL` -> por defecto `google/embeddinggemma-300m`
- `ATENEX_EMBEDDING_PROFILE` -> `lite` / `standard` / `max`
- `ATENEX_BLOB_STORE_PATH` -> por defecto `storage/uploads`

---

## 3. Estructura real del repo

```text
Atenex_nova/
├── AGENTS.md
├── README.md
├── docker-compose.yml
├── docs/
│   ├── baseline.md
│   └── plan.md
├── backend/
│   ├── pyproject.toml
│   ├── atenex_nova/
│   │   ├── main.py
│   │   ├── dependencies.py
│   │   ├── application/
│   │   ├── domain/
│   │   ├── infrastructure/
│   │   ├── presentation/
│   │   ├── evaluation/
│   │   ├── shared/
│   │   └── workers/
│   └── tests/
└── frontend/
	├── package.json
	├── src/
	│   ├── App.tsx
	│   ├── components/
	│   ├── pages/
	│   ├── services/
	│   ├── styles/
	│   └── types/
	└── README.md
```

Nota: `frontend/README.md` es el template de Vite y no debe tomarse como documentacion operativa del producto.

---

## 4. Donde se almacena cada cosa

### Documentos fuente / PDFs / uploads

Los archivos subidos se guardan en el blob store local:

- ruta base: `backend/storage/uploads`
- estructura: `backend/storage/uploads/{collection_id}/{document_id}/{filename}`

La clase que lo implementa es `backend/atenex_nova/infrastructure/files/blob_store.py` y el upload entra por `POST /collections/{collection_id}/documents`.

### Chunks

Los chunks viven en la base relacional, en la tabla `retrieval_chunks`.

- campo de texto: `text`
- resumen: `summary`
- nodos origen: `node_ids_json`
- referencia vectorial: `embedding_ref`
- referencia sparse: `sparse_ref`

### Propositions

Las proposiciones viven en la tabla `propositions`.

- texto atomico: `text`
- origen: `source_chunk_id`
- referencia vectorial: `embedding_ref`

### Summaries

Los resuenos jerarquicos viven en la tabla `summary_nodes`.

- `scope_type`: `section`, `document`, `collection`
- `scope_id`: id del alcance
- `embedding_ref`: referencia vectorial

### Citas y respuestas

Las respuestas y sus citas se guardan en:

- `answers`
- `citations`

### Jobs

La cola interna de trabajos usa la tabla `jobs` con estados `pending`, `running`, `succeeded`, `failed`, `cancelled`.

### Evaluaciones

Los runs y casos de evaluacion viven en:

- `evaluation_runs`
- `evaluation_cases`

### Visual pages

La cache visual se guarda en disco, dentro de:

- `backend/storage/visual_pages/{collection_id}.json`
- `backend/storage/visual_pages/{collection_id}/{page_id}.png`

Si no puede renderizar PNG, el adaptador cae a un `.txt` de respaldo.

### Vectores en Qdrant

Los vectores no se guardan en archivos locales como fuente primaria; se indexan en Qdrant y los ids quedan referenciados en SQL.

Colecciones Qdrant usadas hoy:

- `collection_{collection_id}` -> chunks
- `collection_{collection_id}_propositions` -> proposiciones
- `collection_{collection_id}_summaries` -> summaries
- `pages_visual` -> paginas visuales

Persistencia de Qdrant:

- volumen Docker `qdrant_storage`
- montado en `/qdrant/storage`

---

## 5. Como funciona la ingesta

### Flujo principal

1. `POST /collections/{collection_id}/documents`
2. `BlobStore.store(...)` escribe el archivo en disco
3. Se crea `Document` con `source_path` apuntando al archivo local
4. Se encola `parse_document`
5. El worker parsea, normaliza y segmenta
6. Se crean chunks en `retrieval_chunks`
7. Se embeben e indexan en Qdrant
8. Se encolan fases de memoria enriquecida
9. Se crean proposiciones, summaries y edges
10. Se genera el cache visual si aplica

### Jobs registrados en el worker

El worker en `backend/atenex_nova/workers/main.py` registra:

- `parse_document`
- `normalize_document`
- `segment_document`
- `embed_chunks` / `embed_document`
- `rebuild_collection`
- `extract_propositions`
- `generate_summaries`
- `embed_propositions`
- `embed_summaries`
- `build_graph`
- `index_visual_pages`

### Document lifecycle

Los estados del documento se van marcando de forma explicita en el pipeline:

- `registered`
- `parsed`
- `normalized`
- `segmented`
- `embedded`
- `indexed`
- `ready`
- `failed`

---

## 6. Busqueda hibrida y BM25

La busqueda hibrida esta implementada en `backend/atenex_nova/application/orchestrators/retrieval_orchestrator.py`.

### BM25 / sparse

El encoder local esta en `backend/atenex_nova/infrastructure/embeddings/bm25_encoder.py`.

- tokeniza con regex local
- calcula BM25 sobre textos pequenos del corpus local
- se usa para chunks, propositions, summaries y fallback visual

### Dense

Se usa `EmbeddingGemmaAdapter` con dimension 384 por defecto en el perfil standard.

### Fusion real

En la recuperacion actual:

- chunks -> `0.6 dense + 0.4 BM25`
- propositions -> `0.65 dense + 0.35 BM25`
- summaries -> score lexical con sesgo fijo
- visual -> Qdrant primero, fallback local dense + BM25

### Routing y boosts

El router clasifica la consulta en:

- `exact`
- `factual_local`
- `multi_hop`
- `global`
- `argumentative`
- `visual`

El ranking aplica boosts por tipo de resultado y por modo.

### Multi-hop

Cuando el modo es `multi_hop`, se expanden edges desde `relation_edges` mediante `GraphStore`.

---

## 7. Query, answer y exports

### Query intelligence

Los endpoints reales estan en `backend/atenex_nova/presentation/api/routers/queries.py`:

- `POST /queries/search`
- `POST /queries/answer`

### Answer service

`backend/atenex_nova/application/services/answer_service.py` persiste respuestas y citas y expone exportaciones:

- Markdown: `GET /answers/{id}/export/markdown`
- PDF: `GET /answers/{id}/export/pdf`

### Verificacion

La respuesta final se persiste con:

- plan de respuesta
- grounding score
- verdict
- citas
- evidence pack

### UI

La UI actual incluye:

- Dashboard
- Collections
- Query Workspace
- Evaluation
- Jobs

Las rutas estan en `frontend/src/App.tsx` y la navegacion en `frontend/src/components/Sidebar.tsx`.

---

## 8. Ruta visual

La ruta visual vive en `backend/atenex_nova/infrastructure/visual/colpali_adapter.py`.

### Que hace realmente

- renderiza paginas visuales a `backend/storage/visual_pages`
- indexa paginas en Qdrant en la coleccion `pages_visual`
- usa BM25 local como fallback si Qdrant no responde
- el worker `index_visual_pages` agrupa nodos por pagina y genera payloads

### En consulta

El orchestrator agrega hits visuales cuando el modo es `visual`.

---

## 9. Evaluacion y hardening

### Evaluacion

La evaluacion esta implementada en:

- `backend/atenex_nova/evaluation/models.py`
- `backend/atenex_nova/evaluation/datasets/manager.py`
- `backend/atenex_nova/evaluation/scorers/retrieval_scorer.py`
- `backend/atenex_nova/evaluation/scorers/answer_scorer.py`
- `backend/atenex_nova/evaluation/regression/comparator.py`
- `backend/atenex_nova/application/services/evaluation_service.py`
- `backend/atenex_nova/presentation/api/routers/evaluation.py`

### Dataset por defecto

Existe el dataset `baseline` en `backend/atenex_nova/evaluation/datasets/baseline.json`.

### Hardening operativo

Existe el rebuild de coleccion:

- `POST /collections/{collection_id}/rebuild`
- servicio: `backend/atenex_nova/application/services/rebuild_service.py`
- job handler: `RebuildCollectionJobHandler`

Ese rebuild limpia chunks/propositions/summaries/edges, borra el cache visual y re-encola segmentacion para reconstruccion.

---

## 10. Configuracion y almacenamiento por defecto

### Backend

La app FastAPI arranca en `backend/atenex_nova/main.py` y en el lifespan crea tablas automaticamente con `create_all_tables()`.

Por defecto usa SQLite local:

- `backend/atenex_nova.db`

### Produccion local

Si se activa Postgres con Docker Compose, la base relacional usa:

- DB: `atenex_nova`
- usuario: `atenex`
- password: `atenex_dev_password`

### Qdrant

Qdrant expone:

- REST en `6333`
- gRPC en `6334`

### Frontend

El frontend toma `VITE_API_URL` y, si no existe, apunta a `http://localhost:8000`.

---

## 11. Verificacion local

Comandos que se usan para validar el repo:

```powershell
Set-Location G:\Atenex\Atenex_nova\backend
.\.venv\Scripts\python.exe -m pytest tests -q

Set-Location G:\Atenex\Atenex_nova\frontend
npm run build
```

### Resultado de la ultima validacion ejecutada

- Backend: 22 tests aprobados
- Frontend: build de produccion exitoso

---

## 12. Estado frente a baseline.md y plan.md

### Implementado y funcional en el repo

- carga de documentos locales
- blob store de uploads
- segmentacion en chunks
- BM25 local
- retrieval hibrido dense+sparse
- routing por modo de pregunta
- proposiciones, summaries y grafo relacional
- answer generation con citas
- export Markdown/PDF
- ruta visual con cache local y Qdrant
- evaluation runs y reports
- rebuild de coleccion
- UI con Query, Collections, Evaluation y Jobs

### Diferencias o piezas opcionales respecto al diseno teorico

- no hay DesktopShell ni CLI dedicados
- no hay un motor externo de graph database; el grafo vive en la capa relacional
- ColPali se implementa como adaptador local con cache y fallback, no como stack pesado separado
- el runtime generativo es externo (`llama.cpp` o `Ollama`) y debe estar levantado aparte si se quiere generar con LLM real
- las migraciones formales existen como dependencia/idea del stack, pero el arranque actual usa creacion automatica de tablas en desarrollo

---

## 13. Reglas para trabajar en este repo

1. No mezclar dominio con infraestructura.
2. No llamar adapters directamente desde routers; usar servicios de aplicacion.
3. Mantener las dependencias por inyeccion.
4. Usar rutas absolutas desde `atenex_nova.*`.
5. Mantener `storage/uploads` y `storage/visual_pages` como almacenamiento local de artefactos.
6. Si se toca retrieval, revisar `retrieval_orchestrator.py`, `bm25_encoder.py`, `embedding_adapter.py` y `colpali_adapter.py` juntos.
7. Si se toca jobs, revisar `workers/main.py` y `workers/runner.py`.
8. Si se toca UI, revisar `frontend/src/App.tsx`, `frontend/src/pages/Pages.tsx` y `frontend/src/services/api.ts`.

---

## 14. Archivos de referencia que hay que leer primero

- `docs/plan.md`
- `docs/baseline.md`
- `README.md`
- `docker-compose.yml`
- `backend/atenex_nova/main.py`
- `backend/atenex_nova/workers/main.py`
- `backend/atenex_nova/application/orchestrators/retrieval_orchestrator.py`
- `backend/atenex_nova/infrastructure/embeddings/bm25_encoder.py`
- `backend/atenex_nova/infrastructure/visual/colpali_adapter.py`
- `frontend/src/pages/Pages.tsx`

---

## 15. Recordatorio de prompts y docs

- Los prompts deben versionarse en `prompts/`.
- La documentacion de arquitectura vive en `docs/plan.md`.
- La propuesta baseline y rationale inicial viven en `docs/baseline.md`.
- Este archivo es la referencia operativa para agentes y editores.
